"""Instrument definitions owned by the lab: saved next to the data, loaded at run time."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.examples import EXAMPLES_DIR
from mfethuls.instruments.configured import (
    definition_for,
    definition_statuses,
    instrument_definitions,
    instrument_entries,
    lab_dir,
    save_definition,
)
from mfethuls.instruments.definition import DefinitionError
from mfethuls.parsers.ingestion import ParseError
from mfethuls.parsers.registry import _PARSER_REGISTRY, get_parser
from mfethuls.parsers.tabular import TabularParser
from mfethuls.plotting.core import build_dataset_spec
from mfethuls.reconcile import apply, plan
from mfethuls.stores import open_local_stores

PHOTOMETER = {
    "spec_version": 1,
    "name": "photometer",
    "type": "absorbance_kinetics",
    "model": "lab_built",
    "folder_name": "Photometer",
    "data_layout": "file",
    "file": {"extensions": [".dat"], "delimiter": "semicolon", "decimal": ",",
             "header": {"starts_at": "Time"}},
    "columns": [
        {"source": "Time (min)", "quantity": "time", "unit": "min"},
        {"source": "A600", "quantity": "absorbance", "unit": "a.u."},
    ],
    "plot": {"x": "time_s", "y": "absorbance_a_u"},
}


def _fp(name: str) -> str:
    """The reader_fingerprint stored for data read by the definition ``name``."""
    return f"{definition_for(name).fingerprint}@tabular{TabularParser.version}"


def _sample(path: Path, rows: int = 3) -> Path:
    lines = ["Photometer v2", "Sample: LUB900", "Time (min);A600;Lamp"]
    lines += [f"{i},0;0,{i + 1};on" for i in range(rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def restore_parsers():
    yield
    instrument_definitions()  # without a data folder: lab parsers are unregistered again


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "Photometer").mkdir(parents=True)
    monkeypatch.setenv("PATH_TO_DATA", str(root))
    return root


def test_saved_definition_is_listed_and_reads_files(data_root, tmp_path):
    sample = _sample(tmp_path / "upload.dat")
    path = save_definition(PHOTOMETER, sample)

    assert path == lab_dir() / "photometer.json"
    saved = json.loads(path.read_text(encoding="utf8"))
    assert saved["check"] == {"sample": "photometer.sample.dat", "rows": 3,
                              "columns": ["time_s", "absorbance_a_u", "Lamp"]}
    assert (lab_dir() / "photometer.sample.dat").read_text(encoding="utf-8") == sample.read_text(encoding="utf-8")

    entry = next(e for e in instrument_entries() if e["name"] == "photometer")
    assert entry["folder_name"] == "Photometer" and entry["definition"] == str(path)
    parser = get_parser("absorbance_kinetics", "lab_built")
    assert isinstance(parser, TabularParser)
    data = parser.parse({"x": [str(sample)]}, experiment_id="e").data
    assert data["time_s"].tolist() == [0.0, 60.0, 120.0]
    assert data["absorbance_a_u"].tolist() == [0.1, 0.2, 0.3]
    assert [s.active for s in definition_statuses()] == [True]


def test_save_refuses_bad_definitions_samples_and_overwrites(data_root, tmp_path):
    sample = _sample(tmp_path / "upload.dat")
    with pytest.raises(DefinitionError):
        save_definition({**PHOTOMETER, "columns": []}, sample)
    wrong = tmp_path / "wrong.dat"
    wrong.write_text("nothing here\n", encoding="utf-8")
    with pytest.raises(ParseError, match="header text 'Time'"):
        save_definition(PHOTOMETER, wrong)
    save_definition(PHOTOMETER, sample)
    with pytest.raises(FileExistsError):
        save_definition(PHOTOMETER, sample)
    save_definition({**PHOTOMETER, "description": "v2"}, sample, overwrite=True)


def test_without_a_data_folder_only_built_ins_exist(tmp_path):
    assert lab_dir() is None
    with pytest.raises(ValueError, match="No data folder"):
        save_definition(PHOTOMETER, _sample(tmp_path / "s.dat"))


def test_removing_a_lab_definition_unregisters_its_parser(data_root, tmp_path):
    path = save_definition(PHOTOMETER, _sample(tmp_path / "s.dat"))
    assert definition_for("photometer") is not None
    path.unlink()
    assert definition_for("photometer") is None
    assert ("absorbance_kinetics", "lab_built") not in _PARSER_REGISTRY


def test_lab_definition_overrides_a_builtin_and_is_undone(data_root, tmp_path):
    builtin_parser = get_parser("ftir", "bruker")
    sample = tmp_path / "spec.csv"
    sample.write_text("Created by Instrument,\ncm-1,%T\n4000,88\n3999,87\n", encoding="utf-8")
    override = {
        "name": "ftir", "type": "ftir", "model": "bruker", "folder_name": "FTIR",
        "file": {"extensions": [".csv"], "header": {"skip_lines": 1}},
        "columns": [{"source": "cm-1", "quantity": "wavenumber", "unit": "cm-1"},
                    {"source": "%T", "quantity": "transmittance", "unit": "fraction"}],
    }
    path = save_definition(override, sample)

    lab_parser = get_parser("ftir", "bruker")
    assert lab_parser is not builtin_parser
    data = lab_parser.parse({"x": [str(sample)]}, experiment_id="e").data
    assert data["transmittance_pct"].tolist() == [8800.0, 8700.0]
    assert definition_for("ftir").source == str(path)

    path.unlink()
    assert get_parser("ftir", "bruker") is builtin_parser


def test_conflicting_and_invalid_lab_files_are_reported_not_used(data_root, tmp_path):
    folder = lab_dir()
    folder.mkdir(parents=True)
    (folder / "broken.json").write_text("{ not json", encoding="utf8")
    (folder / "clash.json").write_text(json.dumps({**PHOTOMETER, "name": "clash", "type": "tga",
                                                   "model": "tgaX"}), encoding="utf8")
    statuses = {Path(s.source).name: s for s in definition_statuses()}

    assert not statuses["broken.json"].active and "not valid JSON" in statuses["broken.json"].problems[0]
    assert not statuses["clash.json"].active
    assert "already read by the instrument 'tga'" in statuses["clash.json"].problems[0]
    assert "clash" not in {e["name"] for e in instrument_entries()}
    assert get_parser("tga", "tgaX").definition.name == "tga"


def test_sample_check_reports_a_changed_reading(data_root, tmp_path):
    path = save_definition(PHOTOMETER, _sample(tmp_path / "s.dat"))
    assert definition_statuses()[0].warnings == []

    saved = json.loads(path.read_text(encoding="utf8"))
    saved["columns"][1]["source"] = "A700"  # the absorbance column is no longer found
    path.write_text(json.dumps(saved), encoding="utf8")
    (status,) = definition_statuses()
    assert status.active
    assert status.warnings == [
        "its sample file now gives other columns (missing absorbance_a_u; new A600)"]

    (lab_dir() / saved["check"]["sample"]).unlink()
    assert "is missing" in definition_statuses()[0].warnings[0]


def test_new_measurement_type_ingests_plots_and_is_reread_after_an_edit(tmp_path, monkeypatch):
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    data_root = copy / "data"
    monkeypatch.setenv("PATH_TO_DATA", str(data_root))
    (data_root / "Photometer").mkdir()
    _sample(data_root / "Photometer" / "kin1.dat", rows=5)
    definition_path = save_definition(PHOTOMETER, data_root / "Photometer" / "kin1.dat")

    frame = pd.read_csv(copy / "experiments_registry.csv")
    frame = pd.concat([frame, pd.DataFrame([{"name": "LB_kin_001", "instrument_name": "photometer",
                                             "sample_id": "S009", "run_id": "R001",
                                             "raw_data_filename": "kin1"}])], ignore_index=True)
    registry = Registry.from_frame(frame)
    with open_local_stores() as stores:
        for name in registry.names:
            result = ingest_experiment_dataset(name, refresh=True, registry=registry, stores=stores)
            assert result["status"] in {"registered", "persisted"}, (name, result)
        rows = {row["experiment_name"]: row for row in stores.catalog.list_registered()}
        assert plan(registry, stores).actions == []

    fingerprint = _fp("photometer")
    assert rows["LB_kin_001"]["reader_fingerprint"] == fingerprint
    assert rows["LB_tga_001"]["reader_fingerprint"] == _fp("tga")
    assert rows["LB_dsc_001"]["reader_fingerprint"] == _fp("dsc_mettler_toledo_v1")
    assert rows["LB_fluorescence_001"]["reader_fingerprint"] == _fp("fluorescence_insitu")

    from mfethuls.config.loader import load_experiment_dataset

    dataset = load_experiment_dataset("LB_kin_001", registry=registry)
    assert dataset.metadata["file_text"]["kin1.dat"]["preamble"] == ["Photometer v2", "Sample: LUB900"]
    spec = build_dataset_spec(dataset)
    assert spec.panel.traces[0].x.tolist() == [0.0, 60.0, 120.0, 180.0, 240.0]

    # Editing the definition (a new derived column) asks for the data to be read again.
    saved = json.loads(definition_path.read_text(encoding="utf8"))
    saved["derived"] = [{"op": "normalize_pct", "column": "absorbance_a_u", "into": "absorbance_pct"}]
    definition_path.write_text(json.dumps(saved), encoding="utf8")
    with open_local_stores() as stores:
        current = plan(registry, stores)
        assert [(a.kind, a.name) for a in current.actions] == [("reparse", "LB_kin_001")]
        assert "has changed" in current.actions[0].reason
        assert [r["status"] for r in apply(current, registry, stores)] == ["done"]
        assert plan(registry, stores).actions == []
    dataset = load_experiment_dataset("LB_kin_001", registry=registry)
    assert dataset.data["absorbance_pct"].tolist() == pytest.approx([0.0, 25.0, 50.0, 75.0, 100.0])


def test_datasets_ingested_before_the_migration_are_read_again(tmp_path, monkeypatch):
    """Catalog rows without a fingerprint, for an instrument now read by a definition."""
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    monkeypatch.setenv("PATH_TO_DATA", str(copy / "data"))
    registry = Registry.from_frame(pd.read_csv(copy / "experiments_registry.csv"))
    with open_local_stores() as stores:
        ingest_experiment_dataset("LB_ftir_001", refresh=True, registry=registry, stores=stores)
        stores.catalog._conn.execute("UPDATE dataset_registry SET reader_fingerprint = NULL")
        actions = [(a.kind, a.name, a.reason) for a in plan(registry, stores).actions if a.name == "LB_ftir_001"]
    assert actions == [("reparse", "LB_ftir_001", "ftir is now read by an instrument definition")]


def test_removing_an_override_brings_the_builtin_back(data_root, tmp_path):
    from mfethuls.instruments.configured import remove_definition

    builtin_parser = get_parser("ftir", "bruker")
    sample = tmp_path / "spec.csv"
    sample.write_text("Created by Instrument,\ncm-1,%T\n4000,88\n", encoding="utf-8")
    path = save_definition({"name": "ftir", "type": "ftir", "model": "bruker", "folder_name": "FTIR",
                            "file": {"extensions": [".csv"], "header": {"skip_lines": 1}},
                            "columns": [{"source": "cm-1", "quantity": "wavenumber"}]}, sample)
    assert get_parser("ftir", "bruker") is not builtin_parser
    moved = remove_definition(path)
    assert moved.parent == lab_dir() / "removed"
    assert sorted(p.name for p in moved.iterdir()) == ["ftir.json", "ftir.sample.csv"]
    assert get_parser("ftir", "bruker") is builtin_parser
    assert definition_statuses() == []  # removed/ is not read


def test_data_read_by_a_code_parser_is_read_again_by_its_definition(tmp_path, monkeypatch):
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    monkeypatch.setenv("PATH_TO_DATA", str(copy / "data"))
    registry = Registry.from_frame(pd.read_csv(copy / "experiments_registry.csv"))
    name = "LB_fluorescence_001"
    with open_local_stores() as stores:
        ingest_experiment_dataset(name, refresh=True, registry=registry, stores=stores)
        stores.catalog._conn.execute(
            "UPDATE dataset_registry SET reader_fingerprint = 'FlameOceanOpticsParser-v1'")
        current = plan(registry, stores)
        actions = [(a.kind, a.name, a.reason) for a in current.actions if a.name == name]
        assert actions == [("reparse", name,
                            "fluorescence_insitu is now read by an instrument definition")]
        apply(current, registry, stores)
        assert [a for a in plan(registry, stores).actions if a.name == name] == []



def test_read_again_names_both_versions_of_a_code_parser():
    from mfethuls.experiments import Experiment
    from mfethuls.reconcile import _reader_change

    exp = Experiment(name="EXP014", instrument_name="nmr")
    reason = _reader_change([{"reader_fingerprint": "BrukerNMRParser-v5"}], exp)  # e.g. after a downgrade
    assert reason == "read by another version of mfethuls' nmr reader (BrukerNMRParser-v5 -> BrukerNMRParser-v4)"
    assert _reader_change([{"reader_fingerprint": "BrukerNMRParser-v4"}], exp) is None


def test_a_new_definition_reader_version_offers_read_again(data_root):
    from mfethuls.experiments import Experiment
    from mfethuls.reconcile import _reader_change

    exp = Experiment(name="LB_tga_001", instrument_name="tga")
    current = _fp("tga")
    assert _reader_change([{"reader_fingerprint": current}], exp) is None
    older = current.replace(f"@tabular{TabularParser.version}", "@tabular0")
    assert "definition reader (tabular0 -> tabular" in _reader_change([{"reader_fingerprint": older}], exp)
    changed = _reader_change([{"reader_fingerprint": "0000@tabular1"}], exp)
    assert "instrument definition of tga has changed" in changed
