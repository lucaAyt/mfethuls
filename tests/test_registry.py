"""The Registry object, and the registry as owner of descriptive fields."""

import logging
import shutil
from pathlib import Path

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.config.loader import apply_registry_fields, ingest_experiment_dataset, load_experiment_dataset
from mfethuls.dataset import Dataset
from mfethuls.experiments import Experiment
from mfethuls.storage.duckdb_backend import DuckDBQueryBackend

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def test_from_frame_keeps_valid_rows_and_records_problems():
    registry = Registry.from_frame(
        pd.DataFrame(
            [
                {"name": "ok", "instrument_name": "dsc", "sample_id": "S001"},
                {"name": "bad_instrument", "instrument_name": "no_such_instrument"},
                {"name": "placeholder", "instrument_name": None},
                {"name": None, "instrument_name": "dsc"},
            ]
        )
    )

    assert registry.names == ["ok", "placeholder"]
    assert "ok" in registry and "bad_instrument" not in registry
    assert len(registry) == 2 and len(registry.frame) == 4
    problems = {problem.name: problem for problem in registry.problems}
    assert problems["bad_instrument"].skipped
    assert problems[None].skipped
    assert not problems["placeholder"].skipped and problems["placeholder"].warnings
    assert "ok" not in problems


def test_get_unknown_name_explains_why():
    registry = Registry.from_frame(pd.DataFrame([{"name": "bad", "instrument_name": "nope"}]), path="/lab/reg.csv")

    with pytest.raises(KeyError, match=r"reg\.csv.*Registry\.problems"):
        registry.get("bad")


def test_for_samples_keeps_registry_order():
    registry = Registry.from_frame(
        pd.DataFrame(
            [
                {"name": "a", "instrument_name": "dsc", "sample_id": "S001"},
                {"name": "b", "instrument_name": "dsc", "sample_id": "S002"},
                {"name": "c", "instrument_name": "dsc", "sample_id": "S001"},
            ]
        )
    )

    assert [exp.name for exp in registry.for_samples(["S001"])] == ["a", "c"]


def test_load_requires_name_and_instrument_columns(tmp_path):
    path = tmp_path / "registry.csv"
    pd.DataFrame([{"name": "a"}]).to_csv(path, index=False)

    with pytest.raises(ValueError, match="instrument_name"):
        Registry.load(str(path))


def test_apply_registry_fields_overrides_stored_snapshot():
    stored = Dataset(
        data=pd.DataFrame({"temperature_C": [1.0, 2.0], "sample_id": ["S001", "S001"], "run_id": ["R001", "R001"]}),
        metadata={"sample_id": "S001", "description": "old text", "operator": "AB", "schema_version": "1.1"},
    )
    exp = Experiment(name="exp", instrument_name="dsc", experiment_id="abc", sample_id="S002", run_id="R003",
                     metadata={"description": "new text", "operator": "CD"})

    apply_registry_fields(stored, exp)

    assert stored.metadata["description"] == "new text"
    assert stored.metadata["operator"] == "CD"
    assert stored.metadata["schema_version"] == "1.1"  # parse-time facts are kept
    assert stored.data["sample_id"].tolist() == ["S002", "S002"]
    assert stored.data["run_id"].tolist() == ["R003", "R003"]


@pytest.fixture
def examples(tmp_path, monkeypatch):
    """A temporary copy of examples/ with storage under tmp_path."""
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    monkeypatch.setenv("PATH_TO_DATA", str(copy / "data"))
    monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", str(tmp_path / "storage"))
    return copy / "experiments_registry.csv"


def _edited_registry(path: Path, name: str, **changes) -> Registry:
    frame = pd.read_csv(path)
    for column, value in changes.items():
        frame[column] = frame[column].astype(object) if column in frame else None
        frame.loc[frame["name"] == name, column] = value
    return Registry.from_frame(frame, path=str(path))


def test_cached_load_uses_current_registry_description(examples):
    registry = Registry.load(str(examples))
    first = load_experiment_dataset("LB_dsc_001", refresh=True, registry=registry)
    assert first.metadata["description"] == "DSC run - polymer 1"

    edited = _edited_registry(examples, "LB_dsc_001", description="Corrected description", batch="B7")
    cached = load_experiment_dataset("LB_dsc_001", registry=edited)

    assert cached.experiment_id == first.experiment_id  # served from storage, not re-parsed
    assert cached.metadata["description"] == "Corrected description"
    assert cached.metadata["batch"] == "B7"


def test_corrected_sample_id_replaces_catalog_entry(examples, tmp_path, caplog):
    with DuckDBQueryBackend(db_path=str(tmp_path / "catalog.duckdb")) as backend:
        ingest_experiment_dataset("LB_dsc_001", refresh=True, query_backend=backend,
                                  registry=Registry.load(str(examples)))
        (old,) = backend.list_registered()

        with caplog.at_level(logging.WARNING, logger="mfethuls.storage.duckdb_backend"):
            ingest_experiment_dataset("LB_dsc_001", query_backend=backend,
                                      registry=_edited_registry(examples, "LB_dsc_001", sample_id="S009"))
        rows = backend.list_registered()
        old_view_exists = backend.query(
            "SELECT count(*) AS n FROM duckdb_views() WHERE view_name = ?", [old["table_name"]]
        )["n"][0]

    assert [row["table_name"] for row in rows] == ["LB_dsc_001_S009_R001"]
    assert rows[0]["experiment_id"] == old["experiment_id"]
    assert rows[0]["sample_id"] == "S009"
    assert old_view_exists == 0
    assert Path(old["storage_path"]).exists()  # user data is not deleted
    assert old["table_name"] in caplog.text and "can be deleted" in caplog.text


def test_renamed_experiment_keeps_its_id_and_replaces_catalog_entry(examples, tmp_path):
    with DuckDBQueryBackend(db_path=str(tmp_path / "catalog.duckdb")) as backend:
        ingest_experiment_dataset("LB_dsc_001", refresh=True, query_backend=backend,
                                  registry=Registry.load(str(examples)))
        (old,) = backend.list_registered()

        frame = pd.read_csv(examples)
        frame.loc[frame["name"] == "LB_dsc_001", "name"] = "LB_dsc_renamed"
        renamed = Registry.from_frame(frame, path=str(examples))
        ingest_experiment_dataset("LB_dsc_renamed", query_backend=backend, registry=renamed)
        rows = backend.list_registered()

    assert [row["experiment_name"] for row in rows] == ["LB_dsc_renamed"]
    assert rows[0]["experiment_id"] == old["experiment_id"]


def test_malformed_sample_id_skips_the_row_instead_of_failing():
    registry = Registry.from_frame(
        pd.DataFrame(
            [
                {"name": "ok", "instrument_name": "tga", "sample_id": "S001"},
                {"name": "typo", "instrument_name": "tga", "sample_id": "S1"},
            ]
        )
    )

    assert registry.names == ["ok"]
    (problem,) = registry.problems
    assert problem.name == "typo" and problem.skipped
    assert "Invalid sample_id" in problem.errors[0]
