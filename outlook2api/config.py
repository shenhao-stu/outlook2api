"""Configuration for outlook2api."""
from __future__ import annotations

import os


def get_config() -> dict:
    return {
        "host": os.environ.get("OUTLOOK2API_HOST", "0.0.0.0"),
        "port": int(os.environ.get("OUTLOOK2API_PORT", "8001")),
        "accounts_file": os.environ.get(
            "OUTLOOK2API_ACCOUNTS_FILE",
            os.path.join(os.path.dirname(__file__), "..", "data", "outlook_accounts.json"),
        ),
        "jwt_secret": os.environ.get("OUTLOOK2API_JWT_SECRET", "change-me-in-production"),
        "admin_password": os.environ.get("ADMIN_PASSWORD", "bk@3fd3E"),
        "database_url": os.environ.get(
            "DATABASE_URL",
            "sqlite+aiosqlite:///./data/outlook2api.db",
        ),
        "smtp_host": os.environ.get("OUTLOOK_SMTP_HOST", "smtp-mail.outlook.com"),
        "smtp_port": int(os.environ.get("OUTLOOK_SMTP_PORT", "587")),
    }
