# Outlook2API

Mail.tm-compatible REST API for Outlook/Hotmail/Live accounts + batch account registration with cloud FunCaptcha solver.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  outlook2api (FastAPI)         — always-on mail API     │
│  Port 8001 (local) / 7860 (HuggingFace Space)          │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  register (DrissionPage + YesCaptcha)                   │
│  Batch Outlook account creation via signup.live.com     │
│  Runs on-demand: CLI / Docker / GitHub Actions          │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env with your JWT secret

# Start the mail API
docker compose up -d outlook2api

# Run batch registration (on-demand)
docker compose run --rm register --count 5
```

### Local

```bash
# Mail API
pip install -r requirements-api.txt
python -m outlook2api.app

# Registration
pip install -r requirements-register.txt
CAPTCHA_CLIENT_KEY=your-key python -m register.outlook_register --count 5
```

## API Endpoints

Base URL: `http://localhost:8001` (local) or `https://ohmyapi-outlook2api.hf.space` (HuggingFace)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/domains` | No | List supported email domains |
| POST | `/accounts` | No | Register account (validates IMAP login) |
| POST | `/token` | No | Get JWT bearer token |
| GET | `/me` | Bearer | Current user info |
| GET | `/messages` | Bearer | List inbox messages |
| GET | `/messages/{id}` | Bearer | Get single message |
| GET | `/messages/{id}/code` | Bearer | Extract verification code from message |
| DELETE | `/accounts/me` | Bearer | Delete account from store |
| GET | `/docs` | No | Swagger UI |

### Usage Example

```bash
# 1. Register an account
curl -X POST http://localhost:8001/accounts \
  -H 'Content-Type: application/json' \
  -d '{"address": "user@outlook.com", "password": "YourPassword123"}'

# 2. Get token
TOKEN=$(curl -s -X POST http://localhost:8001/token \
  -H 'Content-Type: application/json' \
  -d '{"address": "user@outlook.com", "password": "YourPassword123"}' | jq -r .token)

# 3. List messages
curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/messages

# 4. Extract verification code from a message
curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/messages/42/code
# Response: {"code": "123456", "message_id": "42", "subject": "Your verification code"}
```

## Batch Registration

Automates Outlook account creation via `signup.live.com` using DrissionPage (Chrome automation) and cloud FunCaptcha solving (YesCaptcha/CapSolver).

### Flow

```
signup.live.com → enter email/password/name/birthdate
  → FunCaptcha loads in iframe
  → detect iframe, extract pk= parameter
  → solve via cloud API (FunCaptchaTaskProxyless)
  → inject token, complete registration
  → save email:password to output/
```

### CLI Options

```bash
python -m register.outlook_register \
  --count 10 \          # Number of accounts
  --threads 2 \         # Concurrent threads
  --proxy "http://user:pass@host:port"  # Optional proxy
```

### GitHub Actions

The workflow runs on schedule (`0 4 * * *` UTC) or manually via `workflow_dispatch`.

Required secrets:
- `CAPTCHA_CLIENT_KEY` — YesCaptcha/CapSolver API key

Optional secrets:
- `PROXY_URL` — HTTP/SOCKS5 proxy

Trigger manually:
```bash
gh workflow run register-outlook.yml \
  --repo shenhao-stu/outlook2api \
  -f count=5 -f threads=1
```

## Environment Variables

| Name | Default | Description |
|------|---------|-------------|
| `OUTLOOK2API_JWT_SECRET` | `change-me-in-production` | JWT signing secret |
| `OUTLOOK2API_HOST` | `0.0.0.0` | API bind host |
| `OUTLOOK2API_PORT` | `8001` | API bind port |
| `OUTLOOK2API_ACCOUNTS_FILE` | `data/outlook_accounts.json` | Account store path |
| `CAPTCHA_CLIENT_KEY` | — | YesCaptcha/CapSolver API key |
| `CAPTCHA_CLOUD_URL` | `https://api.yescaptcha.com` | Cloud solver endpoint |
| `FUNCAPTCHA_PUBLIC_KEY` | `B7D8911C-5CC8-A9A3-35B0-554ACEE604DA` | Microsoft FunCaptcha public key |
| `PROXY_URL` | — | HTTP/SOCKS5 proxy for registration |

## HuggingFace Deployment

The API is deployed at: **https://ohmyapi-outlook2api.hf.space**

The HF Space uses a Docker SDK that clones this repo at build time and runs `uvicorn outlook2api.app:app` on port 7860.

Space secrets:
- `OUTLOOK2API_JWT_SECRET` — set in Space Settings → Variables and secrets

## Project Structure

```
outlook2api/
├── outlook2api/           # FastAPI mail API
│   ├── app.py             # Application entry point
│   ├── auth.py            # JWT auth helpers + FastAPI dependency
│   ├── config.py          # Environment-based configuration
│   ├── routes.py          # All API routes
│   ├── outlook_imap.py    # IMAP client + code extraction
│   └── store.py           # JSON file account store
├── register/              # Batch registration module
│   ├── outlook_register.py  # DrissionPage-based registrar
│   └── captcha.py           # FunCaptchaService (cloud solver)
├── .github/workflows/
│   └── register-outlook.yml  # CI workflow
├── Dockerfile.api           # API container
├── Dockerfile.register      # Registration container (with Chrome + Xvfb)
├── docker-compose.yml
├── requirements-api.txt
├── requirements-register.txt
└── pyproject.toml
```
