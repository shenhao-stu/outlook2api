"""Admin API routes — account management, bulk import, stats."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from outlook2api.config import get_config
from outlook2api.database import Account, get_db, get_stats

admin_router = APIRouter(prefix="/admin/api", tags=["admin"])


def _verify_admin(request: Request) -> None:
    """Check admin password from cookie or Authorization header."""
    cfg = get_config()
    expected = cfg["admin_password"]
    # Cookie auth
    token = request.cookies.get("admin_token", "")
    if token and token == hashlib.sha256(expected.encode()).hexdigest():
        return
    # Header auth
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:].strip() == expected:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


class LoginRequest(BaseModel):
    password: str


class AccountUpdate(BaseModel):
    is_active: bool | None = None
    notes: str | None = None


class BulkImportRequest(BaseModel):
    accounts: list[dict]
    source: str = "import"


@admin_router.post("/login")
async def admin_login(body: LoginRequest):
    cfg = get_config()
    if body.password != cfg["admin_password"]:
        raise HTTPException(status_code=401, detail="Invalid password")
    token = hashlib.sha256(cfg["admin_password"].encode()).hexdigest()
    return {"token": token}


@admin_router.get("/stats")
async def admin_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    stats = await get_stats(db)
    # Recent accounts (last 7 days)
    week_ago = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    from datetime import timedelta
    week_ago = week_ago - timedelta(days=7)
    recent = (await db.execute(
        select(func.count(Account.id)).where(Account.created_at >= week_ago)
    )).scalar() or 0
    stats["recent_7d"] = recent
    return stats


@admin_router.get("/accounts")
async def list_accounts(
    request: Request,
    page: int = 1,
    limit: int = 50,
    search: str = "",
    active: str = "",
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    q = select(Account)
    count_q = select(func.count(Account.id))
    if search:
        q = q.where(Account.email.ilike(f"%{search}%"))
        count_q = count_q.where(Account.email.ilike(f"%{search}%"))
    if active == "true":
        q = q.where(Account.is_active == True)
        count_q = count_q.where(Account.is_active == True)
    elif active == "false":
        q = q.where(Account.is_active == False)
        count_q = count_q.where(Account.is_active == False)
    total = (await db.execute(count_q)).scalar() or 0
    q = q.order_by(Account.created_at.desc()).offset((page - 1) * limit).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return {
        "accounts": [a.to_dict(hide_password=True) for a in rows],
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
    }


@admin_router.post("/accounts")
async def create_account(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    body = await request.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "").strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    existing = (await db.execute(select(Account).where(Account.email == email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Account already exists")
    account = Account(email=email, password=password, source="manual")
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account.to_dict()


@admin_router.post("/accounts/bulk")
async def bulk_import(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    body = await request.json()
    accounts_data = body.get("accounts", [])
    source = body.get("source", "import")
    imported = 0
    skipped = 0
    for item in accounts_data:
        email = ""
        password = ""
        if isinstance(item, dict):
            email = item.get("email", "").strip().lower()
            password = item.get("password", "").strip()
        elif isinstance(item, str) and ":" in item:
            parts = item.split(":", 1)
            email = parts[0].strip().lower()
            password = parts[1].strip()
        if not email or not password:
            skipped += 1
            continue
        existing = (await db.execute(select(Account).where(Account.email == email))).scalar_one_or_none()
        if existing:
            skipped += 1
            continue
        db.add(Account(email=email, password=password, source=source))
        imported += 1
    await db.commit()
    return {"imported": imported, "skipped": skipped, "total": len(accounts_data)}


@admin_router.post("/accounts/upload")
async def upload_accounts(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    content = (await file.read()).decode("utf-8", errors="replace")
    accounts_data = []
    for line in content.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            accounts_data.append(line)
    # Reuse bulk import logic
    imported = 0
    skipped = 0
    for item in accounts_data:
        parts = item.split(":", 1)
        email = parts[0].strip().lower()
        password = parts[1].strip()
        if not email or not password:
            skipped += 1
            continue
        existing = (await db.execute(select(Account).where(Account.email == email))).scalar_one_or_none()
        if existing:
            skipped += 1
            continue
        db.add(Account(email=email, password=password, source="upload"))
        imported += 1
    await db.commit()
    return {"imported": imported, "skipped": skipped, "total": len(accounts_data)}


@admin_router.patch("/accounts/{account_id}")
async def update_account(
    account_id: str,
    body: AccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    account = (await db.execute(select(Account).where(Account.id == account_id))).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if body.is_active is not None:
        account.is_active = body.is_active
    if body.notes is not None:
        account.notes = body.notes
    await db.commit()
    return account.to_dict()


@admin_router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    account = (await db.execute(select(Account).where(Account.id == account_id))).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(account)
    await db.commit()
    return {"status": "deleted"}


@admin_router.delete("/accounts")
async def delete_all_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    await db.execute(delete(Account))
    await db.commit()
    return {"status": "all deleted"}


@admin_router.get("/accounts/{account_id}/password")
async def get_account_password(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _verify_admin(request)
    account = (await db.execute(select(Account).where(Account.id == account_id))).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"password": account.password}


@admin_router.get("/export")
async def export_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Export all active accounts as email:password text."""
    _verify_admin(request)
    rows = (await db.execute(
        select(Account).where(Account.is_active == True).order_by(Account.created_at.desc())
    )).scalars().all()
    lines = [f"{a.email}:{a.password}" for a in rows]
    return {"count": len(lines), "data": "\n".join(lines)}
