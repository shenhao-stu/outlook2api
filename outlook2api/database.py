"""SQLAlchemy async database setup and models."""
from __future__ import annotations

import ssl as _ssl
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text, select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from outlook2api.config import get_config


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (no tzinfo) for PostgreSQL compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:16])
    email = Column(String, unique=True, nullable=False, index=True)
    password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    last_used = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0)
    source = Column(String, default="manual")  # manual, ci, import
    notes = Column(Text, default="")

    def to_dict(self, hide_password: bool = False) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "password": "••••••••" if hide_password else self.password,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "usage_count": self.usage_count,
            "source": self.source,
            "notes": self.notes,
        }


_engine = None
_session_factory = None


def _get_db_url() -> str:
    url = get_config()["database_url"]
    # Convert postgres:// to postgresql+asyncpg://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # Strip sslmode from URL — handled via connect_args instead
    if "asyncpg" in url and "sslmode=" in url:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        params.pop("sslmode", None)
        new_query = urlencode(params, doseq=True)
        url = urlunparse(parsed._replace(query=new_query))
    return url


def _needs_ssl() -> bool:
    """Check if the configured database URL requires SSL."""
    url = get_config()["database_url"]
    return "sslmode=require" in url or "ssl=true" in url


async def init_db() -> None:
    global _engine, _session_factory
    url = _get_db_url()
    is_sqlite = "sqlite" in url
    connect_args: dict = {"check_same_thread": False} if is_sqlite else {}
    if not is_sqlite and _needs_ssl():
        connect_args["ssl"] = _ssl.create_default_context()
    # Disable prepared statement cache to avoid stale plan errors after schema changes
    engine_kwargs: dict = {"echo": False, "connect_args": connect_args}
    if not is_sqlite:
        engine_kwargs["pool_pre_ping"] = True
    _engine = create_async_engine(url, **engine_kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with _session_factory() as session:
        yield session


async def get_stats(db: AsyncSession) -> dict:
    total = (await db.execute(select(func.count(Account.id)))).scalar() or 0
    active = (await db.execute(
        select(func.count(Account.id)).where(Account.is_active == True)
    )).scalar() or 0
    return {"total": total, "active": active, "inactive": total - active}
