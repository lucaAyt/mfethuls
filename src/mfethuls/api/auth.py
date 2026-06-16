"""Bearer token authentication dependency."""

from __future__ import annotations

import os

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    api_key = os.environ.get("MFETHULS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MFETHULS_API_KEY environment variable is not set. "
            "The API cannot start without an API key configured."
        )
    if credentials is None or credentials.credentials != api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
