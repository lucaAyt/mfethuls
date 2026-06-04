"""API helpers for storage and parsing."""

from __future__ import annotations

import io
import os
from contextlib import contextmanager
from typing import Iterator, Optional

import pandas as pd
from fastapi import HTTPException

from ..storage import DuckDBQueryBackend


@contextmanager
def duckdb_session(*, read_only: bool = True) -> Iterator[DuckDBQueryBackend]:
    """Open a short-lived DuckDB connection (release file lock when done)."""

    backend = DuckDBQueryBackend(read_only=read_only)
    try:
        yield backend
    finally:
        backend.close()


def get_api_storage_root() -> str:
    root = os.path.join(os.getcwd(), ".mfethuls_registry")
    os.makedirs(root, exist_ok=True)
    return root


def read_tabular_content_bytes(content_bytes: bytes) -> pd.DataFrame:
    """Read a CSV/XLSX payload into a DataFrame."""

    try:
        return pd.read_excel(io.BytesIO(content_bytes))
    except Exception:
        try:
            return pd.read_csv(io.BytesIO(content_bytes))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not parse file: {exc}") from exc
