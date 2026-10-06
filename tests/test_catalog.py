"""The DuckDB dataset catalog: full records on ingest, migration and backfill of older databases."""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest

from mfethuls import experiments as experiments_module
from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.experiments import Experiment, load_experiment_registry
from mfethuls.storage.catalog import CATALOG_FIELDS, CatalogRecord
from mfethuls.storage.duckdb_backend import DuckDBQueryBackend

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def _parquet(path: Path, rows: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"temperature_C": range(rows), "heat_flow_mW": [0.1] * rows}).to_parquet(path)
    return path


def _old_catalog(db_path: Path, storage_path: Path) -> None:
    """A dataset_registry as written before the catalog had full records."""
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "CREATE TABLE dataset_registry (table_name TEXT PRIMARY KEY, storage_path TEXT NOT NULL, "
        "experiment_name TEXT, raw_data_filename TEXT, registered_at TIMESTAMP DEFAULT now())"
    )
    conn.execute(
        "INSERT INTO dataset_registry (table_name, storage_path, experiment_name, raw_data_filename) "
        "VALUES ('LB_dsc_001_S001_R001', ?, 'LB_dsc_001', 'poly1')",
        [str(storage_path)],
    )
    conn.close()


def _sidecar(storage_path: Path) -> None:
    storage_path.with_suffix(".metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": "abc123",
                "instrument_name": "dsc_mettler_toledo",
                "instrument_type": "dsc",
                "instrument_model": "mettler_toledo",
                "sample_id": "S001",
                "run_id": "R001",
                "measurement_profile": None,
            }
        ),
        encoding="utf8",
    )


def test_record_from_experiment_and_dataset_metadata():
    exp = Experiment(name="LB_dsc_001", instrument_name="dsc_mettler_toledo", experiment_id="abc123",
                     raw_data_filename="poly1", sample_id="S001", run_id="R001")

    record = CatalogRecord.build(exp, "/store/abc123_S001_R001.parquet",
                                 dataset_metadata={"instrument_type": "dsc", "instrument_model": "mettler_toledo"},
                                 rows=42)

    assert record.table_name == "LB_dsc_001_S001_R001"
    assert record.fields() == {
        "experiment_id": "abc123", "experiment_name": "LB_dsc_001", "raw_data_filename": "poly1",
        "instrument_name": "dsc_mettler_toledo", "instrument_type": "dsc", "instrument_model": "mettler_toledo",
        "sample_id": "S001", "run_id": "R001", "measurement_profile": None, "rows": 42,
    }


def test_register_writes_and_updates_full_record(tmp_path):
    storage_path = _parquet(tmp_path / "a.parquet")
    record = CatalogRecord(table_name="LB_dsc_001", storage_path=str(storage_path), experiment_id="abc123",
                           instrument_type="dsc", sample_id="S001", rows=3)

    with DuckDBQueryBackend(db_path=str(tmp_path / "c.duckdb")) as backend:
        backend.register_parquet(str(storage_path), record=record)
        backend.register_parquet(str(storage_path), record=CatalogRecord(**{**record.__dict__, "sample_id": "S002"}))
        rows = backend.list_registered()

    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"table_name", "storage_path", "registered_at", *CATALOG_FIELDS}
    assert (row["experiment_id"], row["instrument_type"], row["sample_id"], row["rows"]) == ("abc123", "dsc", "S002", 3)


@pytest.mark.parametrize("read_only", [False, True])
def test_old_database_is_migrated_and_backfilled_from_sidecars(tmp_path, read_only):
    storage_path = _parquet(tmp_path / "store" / "abc123_S001_R001.parquet", rows=5)
    _sidecar(storage_path)
    db_path = tmp_path / "old.duckdb"
    _old_catalog(db_path, storage_path)

    with DuckDBQueryBackend(db_path=str(db_path), read_only=read_only) as backend:
        (row,) = backend.list_registered()

    assert row["experiment_name"] == "LB_dsc_001"
    assert (row["experiment_id"], row["instrument_type"], row["instrument_model"]) == ("abc123", "dsc", "mettler_toledo")
    assert (row["sample_id"], row["run_id"], row["rows"]) == ("S001", "R001", 5)


def test_backfill_skips_rows_without_sidecar(tmp_path):
    storage_path = _parquet(tmp_path / "store" / "x.parquet")
    db_path = tmp_path / "old.duckdb"
    _old_catalog(db_path, storage_path)

    with DuckDBQueryBackend(db_path=str(db_path)) as backend:
        assert backend.backfill_catalog() == 0
        (row,) = backend.list_registered()

    assert row["experiment_id"] is None
    assert row["experiment_name"] == "LB_dsc_001"


def test_ingest_registers_full_catalog_row(tmp_path, monkeypatch):
    examples = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, examples)
    monkeypatch.setenv("PATH_TO_DATA", str(examples / "data"))
    monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", str(tmp_path / "storage"))
    monkeypatch.setattr(experiments_module, "_EXPERIMENT_REGISTRY", {})
    load_experiment_registry(str(examples / "experiments_registry.csv"))

    with DuckDBQueryBackend(db_path=str(tmp_path / "catalog.duckdb")) as backend:
        result = ingest_experiment_dataset("LB_dsc_001", refresh=True, query_backend=backend)
        (row,) = backend.list_registered()
        view_rows = backend.query(f'SELECT count(*) AS n FROM "{row["table_name"]}"')["n"][0]

    assert result["status"] == "persisted"
    assert result["catalog_record"].table_name == row["table_name"]
    assert row["experiment_name"] == "LB_dsc_001"
    assert row["experiment_id"]
    assert (row["instrument_name"], row["instrument_type"]) == ("dsc_mettler_toledo", "dsc")
    assert (row["sample_id"], row["run_id"]) == ("S001", "R001")
    assert row["rows"] == view_rows > 0


@patch("mfethuls.worker.get_job")
@patch("mfethuls.worker.update_job")
def test_worker_batch_registers_catalog_records(mock_update_job, mock_get_job, tmp_path, monkeypatch):
    from mfethuls.worker import _process_job_ingest

    storage_path = _parquet(tmp_path / "store" / "abc123_S001_R001.parquet")
    monkeypatch.setenv("MFETHULS_DUCKDB_PATH", str(tmp_path / "catalog.duckdb"))
    exp = Experiment(name="LB_dsc_001", instrument_name="dsc_mettler_toledo", experiment_id="abc123", sample_id="S001")
    record = CatalogRecord.build(exp, str(storage_path), dataset_metadata={"instrument_type": "dsc"}, rows=3)

    with patch("mfethuls.worker.get_experiment", return_value=exp), patch(
        "mfethuls.worker.ingest_experiment_dataset",
        return_value={"status": "persisted", "storage_path": str(storage_path), "catalog_record": record},
    ):
        _process_job_ingest(job_id="job1", experiment_names=["LB_dsc_001"], job_registry_path="unused",
                            storage_mode="local", cloud_provider=None, db_url=None)

    with DuckDBQueryBackend(db_path=str(tmp_path / "catalog.duckdb"), read_only=True) as backend:
        (row,) = backend.list_registered()
    assert (row["table_name"], row["instrument_type"], row["rows"]) == ("LB_dsc_001_S001_R001", "dsc", 3)
