from __future__ import annotations

from unittest.mock import patch
from pathlib import Path

import pytest
import pandas as pd

from mfethuls.worker import process_job


def _job_snapshot(tmp_path: Path, names: list[str]) -> str:
    """The filtered registry snapshot /ingest stores for a job."""
    path = tmp_path / "job_registry.parquet"
    pd.DataFrame([{"name": name, "instrument_name": "dsc"} for name in names]).to_parquet(path)
    return str(path)


@patch("mfethuls.worker.update_job")
@patch("mfethuls.worker.get_job")
def test_process_job_ingests_only_the_jobs_registry_snapshot(mock_get_job, mock_update_job, tmp_path, monkeypatch):
    # The full registry has more experiments than were selected for the job.
    full_registry = tmp_path / "full.csv"
    pd.DataFrame([{"name": n, "instrument_name": "dsc"} for n in ("exp_a", "exp_b", "exp_c")]).to_csv(
        full_registry, index=False
    )
    monkeypatch.setenv("PATH_TO_REGISTRY", str(full_registry))
    mock_get_job.return_value = {
        "job_id": "job1",
        "job_registry_storage_path": _job_snapshot(tmp_path, ["exp_b"]),
        "storage_mode": "local",
    }

    with patch("mfethuls.worker._process_job_ingest", return_value={"job_id": "job1"}) as mock_ingest:
        process_job("job1")

    mock_ingest.assert_called_once()
    kwargs = mock_ingest.call_args.kwargs
    assert kwargs["experiment_names"] == ["exp_b"]
    assert kwargs["registry"].names == ["exp_b"]


@patch("mfethuls.worker.update_job")
@patch("mfethuls.worker.get_job")
def test_process_job_marks_failed_when_ingest_raises(mock_get_job, mock_update_job, tmp_path):
    mock_get_job.return_value = {
        "job_id": "job1",
        "job_registry_storage_path": _job_snapshot(tmp_path, ["exp_a"]),
        "storage_mode": "local",
    }

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
