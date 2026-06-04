from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mfethuls.worker import process_job


@patch("mfethuls.worker.update_job")
@patch("mfethuls.worker.get_job")
@patch("mfethuls.worker.load_experiment_registry")
@patch("mfethuls.worker.DuckDBQueryBackend")
def test_process_job_closes_duckdb_on_success(
    mock_backend_cls,
    mock_load_registry,
    mock_get_job,
    mock_update_job,
):
    mock_backend = MagicMock()
    mock_backend_cls.return_value = mock_backend
    mock_get_job.return_value = {
        "job_id": "job1",
        "registry_storage_path": "/tmp/registry.parquet",
        "storage_mode": "local",
    }
    mock_load_registry.return_value = __import__("pandas").DataFrame(
        [{"name": "exp_a", "experiment_id": "EXP001", "instrument_name": "dsc"}]
    )

    with patch("mfethuls.worker._process_job_ingest", return_value={"job_id": "job1"}):
        process_job("job1")

    mock_backend.close.assert_called_once()


@patch("mfethuls.worker.update_job")
@patch("mfethuls.worker.get_job")
@patch("mfethuls.worker.load_experiment_registry")
@patch("mfethuls.worker.DuckDBQueryBackend")
def test_process_job_closes_duckdb_when_ingest_raises(
    mock_backend_cls,
    mock_load_registry,
    mock_get_job,
    mock_update_job,
):
    mock_backend = MagicMock()
    mock_backend_cls.return_value = mock_backend
    mock_get_job.return_value = {
        "job_id": "job1",
        "registry_storage_path": "/tmp/registry.parquet",
        "storage_mode": "local",
    }
    mock_load_registry.return_value = __import__("pandas").DataFrame(
        [{"name": "exp_a", "experiment_id": "EXP001", "instrument_name": "dsc"}]
    )

    with patch("mfethuls.worker._process_job_ingest", side_effect=RuntimeError("boom")):
        process_job("job1")

    mock_backend.close.assert_called_once()


def test_duckdb_backend_context_manager_closes():
    pytest.importorskip("duckdb")
    from mfethuls.storage.duckdb_backend import DuckDBQueryBackend

    with DuckDBQueryBackend(db_path=":memory:") as backend:
        assert backend._conn is not None
    assert backend._conn is None
