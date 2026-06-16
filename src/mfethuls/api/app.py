"""FastAPI application wiring for mfethuls."""

from __future__ import annotations

from fastapi import FastAPI, Security

from .auth import verify_token
from .routes import router

app = FastAPI(title="mfethuls-mvp-api")

# All routes in the router require a valid bearer token.
# /health is registered directly on app so container health checks skip auth.
app.include_router(router, dependencies=[Security(verify_token)])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
