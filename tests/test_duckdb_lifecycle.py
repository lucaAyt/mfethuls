from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def test_duckdb_backend_context_manager_closes():
    pytest.importorskip("duckdb")
    from mfethuls.storage.duckdb_backend import DuckDBQueryBackend

    with DuckDBQueryBackend(db_path=":memory:") as backend:
        assert backend._conn is not None
    assert backend._conn is None


def test_duckdb_backend_persists_parquet_view(tmp_path: Path):
    pytest.importorskip("duckdb")
    from mfethuls.storage.duckdb_backend import DuckDBQueryBackend

    parquet_path = tmp_path / "experiment.parquet"
    pd.DataFrame({"x": [1, 2], "y": [3, 4]}).to_parquet(parquet_path, index=False)

    db_path = tmp_path / "catalog.duckdb"
    with DuckDBQueryBackend(db_path=str(db_path), read_only=False) as backend:
        backend.register_parquet(str(parquet_path), table_name="experiment_data")

    with DuckDBQueryBackend(db_path=str(db_path), read_only=True) as backend:
        frame = backend.query('SELECT * FROM experiment_data ORDER BY x')

    assert frame.to_dict(orient="records") == [{"x": 1, "y": 3}, {"x": 2, "y": 4}]
