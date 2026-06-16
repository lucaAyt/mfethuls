from __future__ import annotations

from unittest.mock import patch
from pathlib import Path

import pytest
import pandas as pd

from mfethuls.worker import process_job


@patch("mfethuls.worker.update_job")
@patch("mfethuls.worker.get_job")
@patch("mfethuls.worker.load_experiment_registry")
@patch("mfethuls.worker.clear_experiment_registry")
def test_process_job_calls_ingest_on_success(
    mock_clear_registry,
    mock_load_registry,
    mock_get_job,
    mock_update_job,
):
    mock_get_job.return_value = {
        "job_id": "job1",
        "job_registry_storage_path": "/tmp/registry.parquet",
        "storage_mode": "local",
    }
    mock_load_registry.return_value = pd.DataFrame(
        [{"name": "exp_a", "experiment_id": "EXP001", "instrument_name": "dsc"}]
    )

    with patch("mfethuls.worker._process_job_ingest", return_value={"job_id": "job1"}) as mock_ingest:
        process_job("job1")

    mock_clear_registry.assert_called_once()
    mock_ingest.assert_called_once()


@patch("mfethuls.worker.update_job")
@patch("mfethuls.worker.get_job")
@patch("mfethuls.worker.load_experiment_registry")
@patch("mfethuls.worker.clear_experiment_registry")
def test_process_job_marks_failed_when_ingest_raises(
    mock_clear_registry,
    mock_load_registry,
    mock_get_job,
    mock_update_job,
):
    mock_get_job.return_value = {
        "job_id": "job1",
        "job_registry_storage_path": "/tmp/registry.parquet",
        "storage_mode": "local",
    }
    mock_load_registry.return_value = pd.DataFrame(
        [{"name": "exp_a", "experiment_id": "EXP001", "instrument_name": "dsc"}]
    )

    with patch("mfethuls.worker._process_job_ingest", side_effect=RuntimeError("boom")):
        process_job("job1")

    mock_update_job.assert_called_with("job1", status="failed", message="ingest failed: boom")


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
