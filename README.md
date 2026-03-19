# Outlook2API

Mail.tm-compatible REST API for Outlook/Hotmail/Live accounts with admin panel, batch registration, and CI auto-import.

## Features

- Mail.tm-compatible Hydra API (drop-in replacement for Outlook accounts)
- Admin panel with account management, bulk import, and API docs
- Batch account registration via GitHub Actions (DrissionPage + YesCaptcha)
- CI auto-import: registered accounts automatically pushed to admin database
- SQLite/PostgreSQL backend
- HuggingFace Spaces deployment

## Quick Start

```bash
pip install -r requirements-api.txt
python -m outlook2api.app
# Open http://localhost:8001 (homepage) or http://localhost:8001/admin (admin panel)
# Default admin password: admin
```

## Admin Panel

Access at `/admin`. Features:
- Dashboard with account stats
- Account management (search, filter, toggle, delete)
- Bulk import (text, file upload, CI API)
- Full API documentation with curl examples

## API Endpoints

### Mail API (mail.tm-compatible)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/domains` | No | List supported domains |
| POST | `/accounts` | No | Register account (IMAP validation) |
| POST | `/token` | No | Get JWT token |
| GET | `/me` | Bearer | Current user info |
| GET | `/messages` | Bearer | List messages |
| GET | `/messages/{id}` | Bearer | Get message |
| GET | `/messages/{id}/code` | Bearer | Extract verification code |
| DELETE | `/accounts/me` | Bearer | Delete account |

### Admin API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/api/login` | Login (returns token) |
| GET | `/admin/api/stats` | Dashboard stats |
| GET | `/admin/api/accounts` | List accounts (paginated) |
| POST | `/admin/api/accounts` | Add single account |
| POST | `/admin/api/accounts/bulk` | Bulk import |
| POST | `/admin/api/accounts/upload` | File upload import |
| PATCH | `/admin/api/accounts/{id}` | Update account |
| DELETE | `/admin/api/accounts/{id}` | Delete account |
| GET | `/admin/api/export` | Export all accounts |

## CI Auto-Import

GitHub Actions workflow registers accounts and auto-imports to admin panel.

Required secrets:
- `CAPTCHA_CLIENT_KEY` — YesCaptcha API key
- `PROXY_URL` — Residential proxy
- `OUTLOOK2API_URL` — Admin panel URL (e.g. `https://ohmyapi-outlook2api.hf.space`)
- `ADMIN_PASSWORD` — Admin password

```bash
gh workflow run register-outlook.yml --repo shenhao-stu/outlook2api -f count=5
```

## Environment Variables

| Name | Default | Description |
|------|---------|-------------|
| `ADMIN_PASSWORD` | `admin` | Admin panel password |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/outlook2api.db` | Database URL |
| `OUTLOOK2API_JWT_SECRET` | `change-me-in-production` | JWT secret |
| `OUTLOOK2API_PORT` | `8001` | API port |

## Deployment

Live at: **https://ohmyapi-outlook2api.hf.space**

## Project Structure

```
outlook2api/
├── outlook2api/
│   ├── app.py              # FastAPI entry point
│   ├── database.py         # SQLAlchemy models + async DB
│   ├── admin_routes.py     # Admin API (CRUD, import, export)
│   ├── routes.py           # Mail.tm-compatible API
│   ├── auth.py             # JWT authentication
│   ├── config.py           # Configuration
│   ├── outlook_imap.py     # IMAP client
│   ├── store.py            # Legacy JSON store
│   └── static/             # Frontend (index.html, admin.html)
├── register/
│   ├── outlook_register.py # Batch registrar
│   └── captcha.py          # FunCaptcha solver
├── .github/workflows/
│   └── register-outlook.yml # CI with auto-import
├── Dockerfile.api
├── Dockerfile.register
├── docker-compose.yml
├── requirements-api.txt
└── requirements-register.txt
```
