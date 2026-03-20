"""Admin API routes — account management, bulk import, stats, mailbox."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from outlook2api.config import get_config
from outlook2api.database import Account, get_db, get_stats
from outlook2api.outlook_imap import fetch_messages_imap, list_folders, delete_messages_imap
from outlook2api.outlook_smtp import send_email

admin_router = APIRouter(prefix="/admin/api", tags=["admin"])


def _verify_admin(request: Request) -> None:
    """Check admin password from cookie or Authorization header."""
    cfg = get_config()
    expected = cfg["admin_password"]
    expected_hash = hashlib.sha256(expected.encode()).hexdigest()
    # Cookie auth
    token = request.cookies.get("admin_token", "")
    if token and token == expected_hash:
        return
    # Header auth: accept both raw password and hashed token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        bearer = auth[7:].strip()
        if bearer == expected or bearer == expected_hash:
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


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body_text: str = ""
    body_html: str = ""
    cc: str = ""
    in_reply_to: str = ""
    references: str = ""


class DeleteMessagesRequest(BaseModel):
    message_ids: list[str]
    folder: str = "INBOX"


@admin_router.post("/login")
async def admin_login(body: LoginRequest):
    cfg = get_config()
    if body.password != cfg["admin_password"]:
        raise HTTPException(status_code=401, detail="Invalid password")
    token = hashlib.sha256(cfg["admin_password"].encode()).hexdigest()
    return {"token": token}


@admin_router.get("/public-stats")
async def public_stats(db: AsyncSession = Depends(get_db)):
    """Public stats (no auth) — total and active account counts."""
    stats = await get_stats(db)
    return {"total": stats.get("total", 0), "active": stats.get("active", 0)}


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
    try:
        existing = (await db.execute(select(Account).where(Account.email == email))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Account already exists")
        account = Account(email=email, password=password, source="manual")
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


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
    """Export all active accounts as email:password text file."""
    _verify_admin(request)
    rows = (await db.execute(
        select(Account).where(Account.is_active == True).order_by(Account.created_at.desc())
    )).scalars().all()
    lines = [f"{a.email}:{a.password}" for a in rows]
    content = "\n".join(lines)
    return PlainTextResponse(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=accounts_export.txt"},
    )


@admin_router.get("/accounts/{account_id}/messages")
async def get_account_messages(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = 30,
    folder: str = "INBOX",
    search: str = "",
):
    """Fetch messages from an account's mailbox via IMAP."""
    _verify_admin(request)
    account = (await db.execute(select(Account).where(Account.id == account_id))).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        messages = await asyncio.to_thread(
            fetch_messages_imap, account.email, account.password, folder, limit, search=search
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IMAP error: {e}")
    return {"email": account.email, "messages": messages, "folder": folder}


@admin_router.get("/accounts/{account_id}/folders")
async def get_account_folders(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List IMAP folders for an account."""
    _verify_admin(request)
    account = (await db.execute(select(Account).where(Account.id == account_id))).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        folders = await asyncio.to_thread(list_folders, account.email, account.password)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IMAP error: {e}")
    return {"email": account.email, "folders": folders}


@admin_router.post("/accounts/{account_id}/messages/delete")
async def delete_account_messages(
    account_id: str,
    body: DeleteMessagesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete messages from an account's mailbox."""
    _verify_admin(request)
    account = (await db.execute(select(Account).where(Account.id == account_id))).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        result = await asyncio.to_thread(
            delete_messages_imap, account.email, account.password, body.message_ids, body.folder
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IMAP error: {e}")
    return result


@admin_router.post("/accounts/{account_id}/send")
async def send_account_email(
    account_id: str,
    body: SendEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send an email from an account via SMTP."""
    _verify_admin(request)
    account = (await db.execute(select(Account).where(Account.id == account_id))).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        result = await asyncio.to_thread(
            send_email,
            from_addr=account.email,
            password=account.password,
            to_addr=body.to,
            subject=body.subject,
            body_text=body.body_text,
            body_html=body.body_html,
            cc=body.cc,
            in_reply_to=body.in_reply_to,
            references=body.references,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result
