"""Convenience helpers for notebook usage."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd


def list_datasets(
    db_url: Optional[str] = None,
    limit: int = 100,
    filters: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """List ingested datasets.

    With no arguments uses DuckDB (local mode). Pass a Postgres URL for
    service mode to get richer metadata (instrument, sample, run info).

    Examples:
        list_datasets()                                          # local
        list_datasets("postgresql://user:pass@host/mfethuls")   # service
    """
    if db_url:
        from .metadata import PostgresMetadataBackend
        backend = PostgresMetadataBackend(db_url)
        rows = backend.list_datasets(limit=limit, filters=filters)
        return pd.DataFrame(rows)

    # Local mode — read from DuckDB dataset_registry
    from .config import _get_duckdb_path
    from .duckdb_backend import DuckDBQueryBackend
    db_path = _get_duckdb_path()
    with DuckDBQueryBackend(db_path=db_path, read_only=True) as qb:
        return qb.query(
            "SELECT experiment_name, table_name, storage_path, raw_data_filename, registered_at "
            "FROM dataset_registry ORDER BY registered_at DESC LIMIT ?",
            [limit],
        )


def get_dataset(
    experiment_name: str,
    db_url: Optional[str] = None,
) -> Optional["pd.Series"]:
    """Get metadata for a single experiment by name.

    With no db_url uses DuckDB (local mode). Pass a Postgres URL for
    service mode to get full metadata.

    Examples:
        get_dataset("CL_dsc_001")
        get_dataset("CL_dsc_001", "postgresql://user:pass@host/mfethuls")
    """
    if db_url:
        from .metadata import PostgresMetadataBackend
        row = PostgresMetadataBackend(db_url).get_dataset_by_name(experiment_name)
        return pd.Series(row) if row is not None else None

    # Local mode — read from DuckDB dataset_registry
    from .config import _get_duckdb_path
    from .duckdb_backend import DuckDBQueryBackend
    db_path = _get_duckdb_path()
    with DuckDBQueryBackend(db_path=db_path, read_only=True) as qb:
        df = qb.query(
            "SELECT experiment_name, table_name, storage_path, raw_data_filename, registered_at "
            "FROM dataset_registry WHERE experiment_name = ? LIMIT 1",
            [experiment_name],
        )
    return pd.Series(df.iloc[0]) if not df.empty else None
