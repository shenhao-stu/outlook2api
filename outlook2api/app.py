"""Outlook2API FastAPI application — mail.tm-compatible Hydra API for Outlook accounts."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from outlook2api.config import get_config
from outlook2api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Outlook2API", description="Mail.tm-compatible API for Outlook accounts", lifespan=lifespan)
    app.include_router(router, tags=["mail"])
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    cfg = get_config()
    uvicorn.run("outlook2api.app:app", host=cfg["host"], port=cfg["port"], reload=True)
