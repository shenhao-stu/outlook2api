---
title: Outlook2API
emoji: 📧
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
---

# Outlook2API

Mail.tm-compatible REST API for Outlook/Hotmail/Live accounts with admin panel and batch account registration.

## Features

- **Mail API** — Mail.tm-compatible Hydra API endpoints (domains, accounts, token, messages)
- **Admin Panel** — Web UI for account management, bulk import/export, webmail with compose/reply, stats dashboard
- **Batch Registration** — Automated Outlook account creation via GitHub Actions
- **CI Auto-Import** — Registered accounts automatically imported to admin panel
- **Verification Code Extraction** — `GET /messages/{id}/code` extracts OTP from emails

## Quick Start

```bash
# Install dependencies
pip install -r requirements-api.txt

# Start the API server
python -m outlook2api.app

# Open http://localhost:8001 for homepage
# Open http://localhost:8001/admin for admin panel (default password: bk@3fd3E)
```

### Docker

```bash
cp .env.example .env
docker compose up -d outlook2api
```

## API Endpoints

### Mail API (Mail.tm-compatible)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/domains` | No | List supported email domains |
| POST | `/accounts` | No | Register account (validates IMAP) |
| POST | `/token` | No | Get JWT bearer token |
| GET | `/me` | Bearer | Current user info |
| GET | `/messages` | Bearer | List inbox messages |
| GET | `/messages/{id}` | Bearer | Get single message |
| GET | `/messages/{id}/code` | Bearer | Extract verification code |
| DELETE | `/accounts/me` | Bearer | Delete account |

### Admin API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/api/login` | Login (returns token) |
| GET | `/admin/api/stats` | Dashboard statistics |
| GET | `/admin/api/accounts` | List accounts (search, filter, paginate) |
| POST | `/admin/api/accounts` | Add single account |
| POST | `/admin/api/accounts/bulk` | Bulk import (`["email:pass",...]`) |
| POST | `/admin/api/accounts/upload` | File upload (email:password per line) |
| PATCH | `/admin/api/accounts/{id}` | Toggle active / update notes |
| DELETE | `/admin/api/accounts/{id}` | Delete account |
| GET | `/admin/api/accounts/{id}/password` | Reveal password |
| GET | `/admin/api/accounts/{id}/messages` | Fetch messages via IMAP |
| POST | `/admin/api/accounts/{id}/send` | Send email via SMTP |
| GET | `/admin/api/export` | Export all active accounts |

## CI Auto-Import

GitHub Actions automatically imports registered accounts to the admin panel.

**Required secrets:**
- `CAPTCHA_CLIENT_KEY` — YesCaptcha/CapSolver API key
- `PROXY_URL` — HTTP/SOCKS5 proxy
- `OUTLOOK2API_URL` — Admin panel URL (e.g., `https://ohmyapi-outlook2api.hf.space`)
- `ADMIN_PASSWORD` — Admin panel password

```bash
# Trigger registration + auto-import
gh workflow run register-outlook.yml -f count=5 -f threads=1
```

## Environment Variables

| Name | Default | Description |
|------|---------|-------------|
| `OUTLOOK2API_JWT_SECRET` | `change-me-in-production` | JWT signing secret |
| `ADMIN_PASSWORD` | `bk@3fd3E` | Admin panel password |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/outlook2api.db` | Database URL |
| `OUTLOOK2API_HOST` | `0.0.0.0` | API bind host |
| `OUTLOOK2API_PORT` | `8001` | API bind port |
| `OUTLOOK_SMTP_HOST` | `smtp-mail.outlook.com` | SMTP server host |
| `OUTLOOK_SMTP_PORT` | `587` | SMTP server port |

## HuggingFace Deployment

Deployed at: **https://ohmyapi-outlook2api.hf.space**

## Project Structure

```
outlook2api/
├── outlook2api/               # FastAPI mail API + admin
│   ├── app.py                 # Application entry point
│   ├── routes.py              # Mail.tm-compatible API routes
│   ├── admin_routes.py        # Admin API routes
│   ├── database.py            # SQLAlchemy models (Account)
│   ├── auth.py                # JWT auth helpers
│   ├── config.py              # Environment config
│   ├── outlook_imap.py        # IMAP client
│   ├── outlook_smtp.py        # SMTP client (send email)
│   ├── store.py               # Legacy JSON file store
│   └── static/                # Frontend
│       ├── index.html         # Homepage
│       └── admin.html         # Admin panel
├── register/                  # Batch registration
│   ├── outlook_register.py    # DrissionPage registrar
│   └── captcha.py             # FunCaptcha cloud solver
├── .github/workflows/
│   └── register-outlook.yml   # CI: register + auto-import
├── Dockerfile.api
├── Dockerfile.register
├── docker-compose.yml
├── requirements-api.txt
└── requirements-register.txt
```
