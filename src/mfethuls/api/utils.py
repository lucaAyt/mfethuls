"""API helpers for storage and parsing."""

from __future__ import annotations

import io
import os
from typing import Optional

import pandas as pd
from fastapi import HTTPException

from ..storage import DuckDBQueryBackend

_QUERY_BACKEND: DuckDBQueryBackend | None = None


def get_query_backend() -> DuckDBQueryBackend:
    global _QUERY_BACKEND
    if _QUERY_BACKEND is None:
        _QUERY_BACKEND = DuckDBQueryBackend()
    return _QUERY_BACKEND


def get_api_storage_root() -> str:
    root = os.path.join(os.getcwd(), ".mfethuls_registry")
    os.makedirs(root, exist_ok=True)
    return root


def read_tabular_content(content_bytes: bytes) -> pd.DataFrame:
    """Read a CSV/XLSX payload into a DataFrame."""

    try:
        return pd.read_excel(io.BytesIO(content_bytes))
    except Exception:
        try:
            return pd.read_csv(io.BytesIO(content_bytes))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not parse file: {exc}") from exc
