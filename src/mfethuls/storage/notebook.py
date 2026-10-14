"""Convenience helpers for notebook usage: what is in the DuckDB catalog."""

from __future__ import annotations

from typing import Optional

import pandas as pd


def list_datasets(limit: int = 100) -> pd.DataFrame:
    """Ingested datasets from the DuckDB catalog: experiment, instrument, sample, run, profile and row count."""

    from .duckdb_backend import DuckDBQueryBackend

    with DuckDBQueryBackend(read_only=True) as qb:
        return pd.DataFrame(qb.list_registered()[:limit])


def get_dataset(experiment_name: str) -> Optional["pd.Series"]:
    """The catalog row of one experiment, by name; ``None`` if it was not ingested."""

    from .duckdb_backend import DuckDBQueryBackend

    with DuckDBQueryBackend(read_only=True) as qb:
        rows = [row for row in qb.list_registered() if row["experiment_name"] == experiment_name]
    return pd.Series(rows[0]) if rows else None
