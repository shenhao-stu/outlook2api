"""Outlook2API FastAPI application — mail.tm-compatible Hydra API for Outlook accounts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from outlook2api.config import get_config
from outlook2api.database import init_db, _get_db_url
from outlook2api.routes import router
from outlook2api.admin_routes import admin_router

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Outlook2API", description="Mail.tm-compatible API for Outlook accounts", lifespan=lifespan)
    app.include_router(router, tags=["mail"])
    app.include_router(admin_router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_file = STATIC_DIR / "index.html"
        if html_file.exists():
            return HTMLResponse(html_file.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Outlook2API</h1><p><a href='/docs'>API Docs</a> | <a href='/admin'>Admin</a></p>")

    @app.get("/health")
    async def health():
        url = _get_db_url()
        db_type = "postgresql" if "postgresql" in url else "sqlite"
        host = url.split("@")[1].split("/")[0] if "@" in url else "local"
        return {"status": "ok", "db_type": db_type, "db_host": host}

    @app.get("/admin", response_class=HTMLResponse)
    @app.get("/admin/{path:path}", response_class=HTMLResponse)
    async def admin_page(request: Request, path: str = ""):
        html_file = STATIC_DIR / "admin.html"
        if html_file.exists():
            return HTMLResponse(html_file.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Admin panel not found</h1>")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    cfg = get_config()
    uvicorn.run("outlook2api.app:app", host=cfg["host"], port=cfg["port"], reload=True)
