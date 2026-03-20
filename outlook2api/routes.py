"""Mail.tm-compatible Hydra API routes for Outlook accounts."""

from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outlook2api.auth import make_jwt, get_current_user
from outlook2api.config import get_config
from outlook2api.database import Account, get_db
from outlook2api.outlook_imap import fetch_messages_imap, validate_login

router = APIRouter()

OUTLOOK_DOMAINS = [
    {"id": "/domains/outlook.com", "domain": "outlook.com", "isActive": True, "isVerified": True},
    {"id": "/domains/hotmail.com", "domain": "hotmail.com", "isActive": True, "isVerified": True},
    {"id": "/domains/live.com", "domain": "live.com", "isActive": True, "isVerified": True},
]


class AccountCreate(BaseModel):
    address: str
    password: str


class TokenRequest(BaseModel):
    address: str
    password: str


@router.get("/domains")
def get_domains():
    return {"hydra:member": OUTLOOK_DOMAINS, "hydra:totalItems": len(OUTLOOK_DOMAINS)}


@router.post("/accounts")
async def create_account(body: AccountCreate, db: AsyncSession = Depends(get_db)):
    address = body.address.strip().lower()
    password = body.password
    if not address or "@" not in address:
        raise HTTPException(status_code=400, detail="Invalid address")
    domain = address.split("@")[1].lower()
    allowed = {d["domain"] for d in OUTLOOK_DOMAINS}
    if domain not in allowed:
        raise HTTPException(status_code=400, detail=f"Domain {domain} not supported")
    if not validate_login(address, password):
        raise HTTPException(status_code=401, detail="Invalid credentials or IMAP disabled")
    # Add to database if not exists
    existing = (await db.execute(select(Account).where(Account.email == address))).scalar_one_or_none()
    if not existing:
        db.add(Account(email=address, password=password, source="api"))
        await db.commit()
    return {"id": f"/accounts/{secrets.token_hex(8)}", "address": address, "createdAt": time.time()}


@router.post("/token")
async def get_token(body: TokenRequest, db: AsyncSession = Depends(get_db)):
    address = body.address.strip().lower()
    password = body.password
    # Check database first
    account = (await db.execute(select(Account).where(Account.email == address))).scalar_one_or_none()
    if account:
        if account.password != password:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    else:
        # Not in database — validate via IMAP and add
        if not validate_login(address, password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        db.add(Account(email=address, password=password, source="api"))
        await db.commit()
    secret = get_config().get("jwt_secret", "change-me-in-production")
    token = make_jwt(address, password, secret)
    return {"token": token, "id": address}


@router.get("/me")
async def get_me(user: tuple[str, str] = Depends(get_current_user)):
    return {"id": user[0], "address": user[0], "quota": 0}


@router.get("/messages")
async def list_messages(
    page: int = 1,
    limit: int = 20,
    user: tuple[str, str] = Depends(get_current_user),
):
    address, password = user
    msgs = fetch_messages_imap(address, password, limit=limit)
    return {"hydra:member": msgs, "hydra:totalItems": len(msgs)}


@router.get("/messages/{msg_id}")
async def get_message(
    msg_id: str,
    user: tuple[str, str] = Depends(get_current_user),
):
    address, password = user
    msgs = fetch_messages_imap(address, password, limit=50)
    for m in msgs:
        if str(m.get("id")) == str(msg_id):
            return m
    raise HTTPException(status_code=404, detail="Message not found")


@router.get("/messages/{msg_id}/code")
async def get_message_code(
    msg_id: str,
    user: tuple[str, str] = Depends(get_current_user),
):
    """Extract verification code from a specific message."""
    address, password = user
    msgs = fetch_messages_imap(address, password, limit=50)
    for m in msgs:
        if str(m.get("id")) == str(msg_id):
            code = m.get("verification_code", "")
            if not code:
                raise HTTPException(status_code=404, detail="No verification code found in message")
            return {"code": code, "message_id": msg_id, "subject": m.get("subject", "")}
    raise HTTPException(status_code=404, detail="Message not found")


@router.delete("/accounts/me")
async def delete_account(
    db: AsyncSession = Depends(get_db),
    user: tuple[str, str] = Depends(get_current_user),
):
    account = (await db.execute(select(Account).where(Account.email == user[0]))).scalar_one_or_none()
    if account:
        await db.delete(account)
        await db.commit()
    return {"status": "deleted"}
