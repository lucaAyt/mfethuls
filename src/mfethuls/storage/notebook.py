"""Convenience helpers for notebook usage."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from .metadata import PostgresMetadataBackend


def list_datasets(db_url: str, limit: int = 100, filters: Optional[Dict[str, Any]] = None) -> "pd.DataFrame":
    if not db_url:
        return pd.DataFrame()
    backend = PostgresMetadataBackend(db_url)
    rows = backend.list_datasets(limit=limit, filters=filters)
    return pd.DataFrame(rows)


def get_dataset(db_url: str, dataset_id: int) -> Optional["pd.Series"]:
    if not db_url:
        return None
    backend = PostgresMetadataBackend(db_url)
    row = backend.get_dataset_by_id(dataset_id)
    if row is None:
        return None
    return pd.Series(row)
