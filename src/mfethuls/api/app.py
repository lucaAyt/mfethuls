"""FastAPI application wiring for mfethuls."""

from __future__ import annotations

from fastapi import FastAPI

from .routes import router

app = FastAPI(title="mfethuls-mvp-api")
app.include_router(router)
