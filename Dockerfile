FROM python:3.12-slim

WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY outlook2api/ outlook2api/
COPY pyproject.toml .

RUN mkdir -p /tmp/data

# Default to SQLite; override with DATABASE_URL env var for PostgreSQL persistence
ENV DATABASE_URL=sqlite+aiosqlite:////tmp/data/outlook2api.db
ENV OUTLOOK2API_PORT=7860

CMD ["uvicorn", "outlook2api.app:app", "--host", "0.0.0.0", "--port", "7860"]
