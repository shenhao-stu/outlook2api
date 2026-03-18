"""JWT authentication helpers and FastAPI dependency."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Optional

from fastapi import HTTPException, Request

from outlook2api.config import get_config


def make_jwt(address: str, password: str, secret: str) -> str:
    """Simple HMAC-signed token. Uses \\x01 separator to support passwords with colons."""
    sep = "\x01"
    payload = f"{address}{sep}{password}{sep}{int(time.time())}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode().rstrip("=")


def verify_token(token: str, secret: str) -> Optional[tuple[str, str]]:
    """Verify token signature and return (address, password) or None."""
    try:
        padded = token + "=" * (4 - len(token) % 4)
        raw = base64.urlsafe_b64decode(padded).decode()
        parts = raw.split("|")
        if len(parts) != 2:
            return None
        payload, sig = parts
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        sep = "\x01"
        if sep not in payload:
            return None
        addr, rest = payload.split(sep, 1)
        pwd, _ = rest.rsplit(sep, 1)
        return (addr, pwd) if addr and pwd else None
    except Exception:
        return None


def get_current_user(request: Request) -> tuple[str, str]:
    """FastAPI dependency: extract and verify Bearer token, return (address, password)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = auth[7:].strip()
    secret = get_config().get("jwt_secret", "change-me-in-production")
    creds = verify_token(token, secret)
    if not creds:
        raise HTTPException(status_code=401, detail="Invalid token")
    return creds
