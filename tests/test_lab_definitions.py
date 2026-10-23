"""The lab's readers and instruments: saved next to the data, loaded at run time."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.examples import EXAMPLES_DIR
from mfethuls.instruments.configured import (
    add_instrument,
    assign_folder,
    get_instrument,
    get_reader,
    instruments,
    instruments_dir,
    lab_dir,
    lab_statuses,
    reader_definitions,
    reader_for,
    readers_of,
    save_definition,
    set_folder,
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
    return f"{get_reader(name).definition.fingerprint}@tabular{TabularParser.version}"


def _sample(path: Path, rows: int = 3) -> Path:
    lines = ["Photometer v2", "Sample: LUB900", "Time (min);A600;Lamp"]
    lines += [f"{i},0;0,{i + 1};on" for i in range(rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _instrument_file(name, **data):
    instruments_dir().mkdir(parents=True, exist_ok=True)
    path = instruments_dir() / f"{name}.json"
    path.write_text(json.dumps({"name": name, **data}), encoding="utf8")
    return path


@pytest.fixture(autouse=True)
def restore_parsers():
    yield
    reader_definitions()  # resolve again without a data folder


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "Photometer").mkdir(parents=True)
    monkeypatch.setenv("PATH_TO_DATA", str(root))
    return root


def test_saved_reader_is_listed_and_reads_files(data_root, tmp_path):
    sample = _sample(tmp_path / "upload.dat")
    path = save_definition(PHOTOMETER, sample)

    assert path == lab_dir() / "photometer.json" and lab_dir() == data_root / ".mfethuls" / "readers"
    saved = json.loads(path.read_text(encoding="utf8"))
    assert saved["check"] == {"sample": "photometer.sample.dat", "rows": 3,
                              "columns": ["time_s", "absorbance_a_u", "Lamp"]}
    assert (lab_dir() / "photometer.sample.dat").read_text(encoding="utf-8") == sample.read_text(encoding="utf-8")

    reader = get_reader("photometer")
    assert reader.lab and reader.type == "absorbance_kinetics" and reader.definition.source == str(path)
    parser = get_parser("absorbance_kinetics", "lab_built")
    assert isinstance(parser, TabularParser)
    data = parser.parse({"x": [str(sample)]}, experiment_id="e").data
    assert data["time_s"].tolist() == [0.0, 60.0, 120.0]
    assert data["absorbance_a_u"].tolist() == [0.1, 0.2, 0.3]
    assert [(s.kind, s.active) for s in lab_statuses()] == [("reader", True)]
    # A reader is not an instrument: the registry needs one reading the folder.
    assert "photometer" not in {i.name for i in instruments()}


def test_save_refuses_bad_definitions_samples_and_overwrites(data_root, tmp_path):
    sample = _sample(tmp_path / "upload.dat")
    with pytest.raises(DefinitionError):
        save_definition({**PHOTOMETER, "columns": []}, sample)
    with pytest.raises(DefinitionError, match="'folder_name' belongs to the instrument"):
        save_definition({**PHOTOMETER, "folder_name": "Photometer"}, sample)
    wrong = tmp_path / "wrong.dat"
    wrong.write_text("nothing here\n", encoding="utf-8")
    with pytest.raises(ParseError, match="header text 'Time'"):
        save_definition(PHOTOMETER, wrong)
    save_definition(PHOTOMETER, sample)
    with pytest.raises(FileExistsError):
        save_definition(PHOTOMETER, sample)
    save_definition({**PHOTOMETER, "description": "v2"}, sample, overwrite=True)


def test_without_a_data_folder_only_built_ins_exist(tmp_path):
    assert lab_dir() is None and instruments_dir() is None
    with pytest.raises(ValueError, match="No data folder"):
        save_definition(PHOTOMETER, _sample(tmp_path / "s.dat"))
    with pytest.raises(ValueError, match="No data folder"):
        add_instrument("photometer", "tga", "Photometer")


def test_removing_a_lab_reader_unregisters_its_parser(data_root, tmp_path):
    path = save_definition(PHOTOMETER, _sample(tmp_path / "s.dat"))
    assert get_reader("photometer") is not None
    path.unlink()
    assert get_reader("photometer") is None
    assert ("absorbance_kinetics", "lab_built") not in _PARSER_REGISTRY


def test_lab_reader_overrides_a_builtin_and_is_undone(data_root, tmp_path):
    builtin_parser = get_parser("ftir", "bruker")
    sample = tmp_path / "spec.csv"
    sample.write_text("Created by Instrument,\ncm-1,%T\n4000,88\n3999,87\n", encoding="utf-8")
    override = {
        "name": "ftir", "type": "ftir", "model": "bruker",
        "file": {"extensions": [".csv"], "header": {"skip_lines": 1}},
        "columns": [{"source": "cm-1", "quantity": "wavenumber", "unit": "cm-1"},
                    {"source": "%T", "quantity": "transmittance", "unit": "fraction"}],
    }
    path = save_definition(override, sample)

    lab_parser = get_parser("ftir", "bruker")
    assert lab_parser is not builtin_parser
    data = lab_parser.parse({"x": [str(sample)]}, experiment_id="e").data
    assert data["transmittance_pct"].tolist() == [8800.0, 8700.0]
    assert get_reader("ftir").definition.source == str(path)

    path.unlink()
    assert get_parser("ftir", "bruker") is builtin_parser


def test_invalid_lab_files_are_reported(data_root, tmp_path):
    lab_dir().mkdir(parents=True)
    (lab_dir() / "broken.json").write_text("{ not json", encoding="utf8")
    # A second reader of a type and model: allowed, each reader has its own name.
    (lab_dir() / "tga_v2.json").write_text(json.dumps({**PHOTOMETER, "name": "tga_v2", "type": "tga",
                                                       "model": "tgaX"}), encoding="utf8")
    statuses = {Path(s.source).name: s for s in lab_statuses()}

    assert not statuses["broken.json"].active and "not valid JSON" in statuses["broken.json"].problems[0]
    assert statuses["tga_v2.json"].active and not statuses["tga_v2.json"].problems
    assert [r.name for r in readers_of("tga")] == ["tga", "tga_v2"]
    with pytest.raises(ValueError, match="Several readers are tga tgaX"):
        get_parser("tga", "tgaX")  # ambiguous by type and model: look up by name


def test_a_lab_instrument_is_another_source_of_a_type(data_root):
    _instrument_file("nmr600", type="nmr", folder_name="NMR600")
    _instrument_file("dsc_room_b", type="dsc", folder_name="DSC room B", description="Mettler, room B")

    assert get_instrument("nmr600").folder_name == "NMR600" and get_instrument("nmr").folder_name == "NMR"
    assert [r.name for r in readers_of("nmr600")] == ["nmr"]
    assert [r.name for r in readers_of("dsc_room_b")] == [r.name for r in readers_of("dsc")]
    assert get_instrument("dsc_room_b").description == "Mettler, room B"
    assert {Path(s.source).name: (s.kind, s.active) for s in lab_statuses()} == {
        "nmr600.json": ("instrument", True), "dsc_room_b.json": ("instrument", True)}


def test_a_reader_that_knows_a_file_by_its_marker_wins_over_one_that_takes_any_file(data_root, tmp_path):
    """A lab fluorimeter reader takes any .txt; a Flame file has the Flame marker, so Flame reads it."""
    sample = tmp_path / "scan_emission.txt"
    sample.write_text("".join(f"{300 + i}\t{i * 10}\n" for i in range(5)), encoding="utf-8")
    save_definition({"spec_version": 1, "name": "fluorimeter_txt", "type": "fluorescence", "model": "fluorimeter",
                     "data_layout": "file", "file": {"extensions": [".txt"], "delimiter": "tab", "header": {"rows": 0}},
                     "columns": [{"source": "column_1", "quantity": "wavelength", "unit": "nm"},
                                 {"source": "column_2", "quantity": "emission", "unit": "counts"}]}, sample)
    _instrument_file("fluorimeter", type="fluorescence", folder_name="Fluorimeter")
    flame = sorted((EXAMPLES_DIR / "data" / "Fluorescence" / "poly3").glob("*.txt"))[:2]

    assert reader_for("fluorescence", [str(f) for f in flame]).name == "fluorescence_insitu"
    assert reader_for("fluorimeter", [str(f) for f in flame]).name == "fluorescence_insitu"
    assert reader_for("fluorimeter", [str(sample)]).name == "fluorimeter_txt"


@pytest.mark.parametrize("name, data, problem", [
    ("nmr600", {"type": "nrm", "folder_name": "NMR600"}, "no reader reads 'nrm' data (did you mean nmr?)"),
    ("nmr600", {"type": "nmr", "folder_name": "TGA"}, "TGA is already the folder of the instrument tga"),
    ("nmr600", {"type": "nmr", "folder_name": "tga"}, "already the folder of the instrument tga"),  # case
    ("dsc_b", {"type": "dsc", "folder_name": "B", "readers": ["tga"]}, "'tga', which reads tga data, not dsc"),
    ("dsc_b", {"type": "dsc", "folder_name": "B", "readers": ["dsc_nope"]}, "'dsc_nope', which is not a reader"),
    ("nmr600", {"type": "nmr", "folder_name": "NMR600", "same_as": "nmr"}, "unknown keys 'same_as'"),
    ("nmr600", {"type": "nmr", "folder_name": "a/b"}, "'folder_name'"),
    ("nmr600", {**PHOTOMETER}, "this is a reader"),
])
def test_lab_instrument_problems_are_reported(data_root, name, data, problem):
    _instrument_file(name, **{k: v for k, v in data.items() if k != "name"})
    (status,) = lab_statuses()
    assert status.kind == "instrument" and not status.active and problem in " ".join(status.problems)
    assert name not in {i.name for i in instruments()}


def test_two_lab_instruments_cannot_share_a_folder(data_root):
    _instrument_file("a_first", type="dsc", folder_name="DSC room B")
    _instrument_file("b_second", type="dsc", folder_name="dsc ROOM b")
    statuses = {s.name: s for s in lab_statuses()}
    assert statuses["a_first"].active and not statuses["b_second"].active
    assert "each folder belongs to one instrument" in statuses["b_second"].problems[0]


def test_a_builtin_instrument_is_moved_by_a_lab_file_and_back(data_root):
    set_folder("dsc", "DSC data")
    path = instruments_dir() / "dsc.json"
    assert json.loads(path.read_text(encoding="utf8")) == {"spec_version": 1, "name": "dsc", "type": "dsc",
                                                           "folder_name": "DSC data"}
    moved = get_instrument("dsc")
    assert (moved.folder_name, moved.default_folder, moved.builtin) == ("DSC data", "DSC", True)
    with pytest.raises(ValueError, match="already the folder of the instrument tga"):
        set_folder("dsc", "TGA")

    set_folder("dsc", "DSC")  # its own folder: the lab file goes
    assert not path.exists() and get_instrument("dsc").folder_name == "DSC"


def test_a_broken_override_does_not_bring_back_a_builtin_whose_folder_was_taken(data_root):
    _instrument_file("a_dsc", type="dsc", folder_name="DSC")  # free, since dsc.json moves dsc
    broken = _instrument_file("dsc", type="dsc", folder_name="DSC moved", readers=["typo"])

    assert "dsc" not in {i.name for i in instruments()}  # else two instruments would read DSC/
    assert get_instrument("a_dsc").folder_name == "DSC"
    status = next(s for s in lab_statuses() if s.source == str(broken))
    assert not status.active and any("not used either" in p for p in status.problems)


def test_a_lab_file_that_cannot_be_used_is_never_overwritten(data_root):
    broken = _instrument_file("dsc", type="dsc", folder_name="DSC", readers=["typo"])
    before = broken.read_text(encoding="utf8")
    assert get_instrument("dsc").source is None  # the built-in one is used meanwhile
    with pytest.raises(ValueError, match="exists but cannot be used"):
        set_folder("dsc", "DSC new")
    assert broken.read_text(encoding="utf8") == before


def test_checks_use_the_lab_files_of_the_data_folder_they_are_given(tmp_path, monkeypatch):
    from mfethuls.discovery import probe_raw_data

    other = tmp_path / "other"
    (other / "B").mkdir(parents=True)
    (other / "B" / "notes.txt").write_text("not a DSC export\n", encoding="utf-8")
    (other / ".mfethuls" / "instruments").mkdir(parents=True)
    (other / ".mfethuls" / "instruments" / "dsc_b.json").write_text(
        json.dumps({"name": "dsc_b", "type": "dsc", "folder_name": "B"}), encoding="utf8")
    monkeypatch.setenv("PATH_TO_DATA", str(tmp_path / "settings-data"))
    # Before, the instrument was looked up in the settings' data folder, and the row passed unchecked.
    assert "none of the dsc formats" in probe_raw_data("dsc_b", "notes", data_root=str(other))


def test_a_lab_instrument_moves_in_its_own_file(data_root):
    path = add_instrument("nmr600", "nmr", "NMR600", description="600 MHz")
    set_folder("nmr600", "NMR 600 MHz")
    assert json.loads(path.read_text(encoding="utf8")) == {
        "spec_version": 1, "name": "nmr600", "type": "nmr", "folder_name": "NMR 600 MHz", "description": "600 MHz"}
    with pytest.raises(ValueError, match="already an instrument called 'nmr600'"):
        add_instrument("NMR600", "nmr", "Elsewhere")
    with pytest.raises(ValueError, match="already the folder of the instrument nmr600"):
        add_instrument("nmr800", "nmr", "NMR 600 MHz")


def test_a_folder_goes_to_the_builtin_instrument_when_its_own_folder_is_missing(data_root):
    # No DSC folder: the built-in dsc takes "DSC data" (the first user's layout).
    assert assign_folder("DSC data", "dsc") == "dsc"
    assert get_instrument("dsc").folder_name == "DSC data"
    # TGA has its folder: a second instrument, named after the new folder.
    (data_root / "TGA").mkdir()
    assert assign_folder("TGA room B", "tga") == "tga_room_b"
    assert (get_instrument("tga").folder_name, get_instrument("tga_room_b").folder_name) == ("TGA", "TGA room B")


def test_a_lab_instrument_ingests_its_own_folder(data_root):
    shutil.copytree(EXAMPLES_DIR / "data" / "DSC", data_root / "DSC room B")
    add_instrument("dsc_room_b", "dsc", "DSC room B")
    registry = Registry.from_frame(pd.DataFrame([{"name": "B_dsc_001", "instrument_name": "dsc_room_b",
                                                  "raw_data_filename": "poly1", "sample_id": "S001"}]))
    with open_local_stores() as stores:
        result = ingest_experiment_dataset("B_dsc_001", registry=registry, stores=stores)
        (row,) = stores.catalog.list_registered()
    assert result["status"] == "persisted"
    assert (row["instrument_name"], row["instrument_type"]) == ("dsc_room_b", "dsc")
    assert (row["reader"], row["instrument_model"]) == ("dsc_mettler_toledo_v1", "mettler_toledo_v1")
    assert row["rows"] > 1000


def test_sample_check_reports_a_changed_reading(data_root, tmp_path):
    path = save_definition(PHOTOMETER, _sample(tmp_path / "s.dat"))
    assert lab_statuses()[0].warnings == []

    saved = json.loads(path.read_text(encoding="utf8"))
    saved["columns"][1]["source"] = "A700"  # the absorbance column is no longer found
    path.write_text(json.dumps(saved), encoding="utf8")
    (status,) = lab_statuses()
    assert status.active
    assert status.warnings == [
        "its sample file now gives other columns (missing absorbance_a_u; new A600)"]

    (lab_dir() / saved["check"]["sample"]).unlink()
    assert "is missing" in lab_statuses()[0].warnings[0]


def test_new_measurement_type_ingests_plots_and_is_reread_after_an_edit(tmp_path, monkeypatch):
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    data_root = copy / "data"
    monkeypatch.setenv("PATH_TO_DATA", str(data_root))
    (data_root / "Photometer").mkdir()
    _sample(data_root / "Photometer" / "kin1.dat", rows=5)
    definition_path = save_definition(PHOTOMETER, data_root / "Photometer" / "kin1.dat")
    # A new type has no built-in instrument: the folder gets one of its own.
    assert assign_folder("Photometer", "absorbance_kinetics") == "photometer"

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

    assert rows["LB_kin_001"]["reader_fingerprint"] == _fp("photometer")
    assert rows["LB_tga_001"]["reader_fingerprint"] == _fp("tga")
    assert rows["LB_dsc_001"]["reader_fingerprint"] == _fp("dsc_mettler_toledo_v1")
    assert rows["LB_fluorescence_001"]["reader_fingerprint"] == _fp("fluorescence_insitu")
    assert {name: row["reader"] for name, row in rows.items() if name.endswith("_001")} == {
        "LB_kin_001": "photometer", "LB_tga_001": "tga", "LB_dsc_001": "dsc_mettler_toledo_v1",
        "LB_ftir_001": "ftir", "LB_fluorescence_001": "fluorescence_insitu"}

    from mfethuls.config.loader import load_experiment_dataset

    dataset = load_experiment_dataset("LB_kin_001", registry=registry)
    assert dataset.metadata["file_text"]["kin1.dat"]["preamble"] == ["Photometer v2", "Sample: LUB900"]
    spec = build_dataset_spec(dataset)
    assert spec.panel.traces[0].x.tolist() == [0.0, 60.0, 120.0, 180.0, 240.0]

    # Editing the reader (a new derived column) asks for the data to be read again.
    saved = json.loads(definition_path.read_text(encoding="utf8"))
    saved["derived"] = [{"op": "normalize_pct", "column": "absorbance_a_u", "into": "absorbance_pct"}]
    definition_path.write_text(json.dumps(saved), encoding="utf8")
    with open_local_stores() as stores:
        current = plan(registry, stores)
        assert [(a.kind, a.name) for a in current.actions] == [("reparse", "LB_kin_001")]
        assert current.actions[0].reason == "the reader photometer has changed"
        assert [r["status"] for r in apply(current, registry, stores)] == ["done"]
        assert plan(registry, stores).actions == []
    dataset = load_experiment_dataset("LB_kin_001", registry=registry)
    assert dataset.data["absorbance_pct"].tolist() == pytest.approx([0.0, 25.0, 50.0, 75.0, 100.0])


def test_datasets_stored_without_their_reader_are_read_again(tmp_path, monkeypatch):
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    monkeypatch.setenv("PATH_TO_DATA", str(copy / "data"))
    registry = Registry.from_frame(pd.read_csv(copy / "experiments_registry.csv"))
    with open_local_stores() as stores:
        ingest_experiment_dataset("LB_ftir_001", refresh=True, registry=registry, stores=stores)
        stores.catalog._conn.execute("UPDATE dataset_registry SET reader = NULL")
        actions = [(a.kind, a.name, a.reason) for a in plan(registry, stores).actions if a.name == "LB_ftir_001"]
        assert actions == [("reparse", "LB_ftir_001", "read before mfethuls recorded which reader read the data")]
        stores.catalog._conn.execute("UPDATE dataset_registry SET reader = 'ftir', reader_fingerprint = NULL")
        actions = [(a.kind, a.name, a.reason) for a in plan(registry, stores).actions if a.name == "LB_ftir_001"]
    assert actions == [("reparse", "LB_ftir_001", "ftir is now read by a definition")]


def test_removing_an_override_brings_the_builtin_back(data_root, tmp_path):
    from mfethuls.instruments.configured import remove_definition

    builtin_parser = get_parser("ftir", "bruker")
    sample = tmp_path / "spec.csv"
    sample.write_text("Created by Instrument,\ncm-1,%T\n4000,88\n", encoding="utf-8")
    path = save_definition({"name": "ftir", "type": "ftir", "model": "bruker",
                            "file": {"extensions": [".csv"], "header": {"skip_lines": 1}},
                            "columns": [{"source": "cm-1", "quantity": "wavenumber"}]}, sample)
    assert get_parser("ftir", "bruker") is not builtin_parser
    moved = remove_definition(path)
    assert moved.parent == lab_dir() / "removed"
    assert sorted(p.name for p in moved.iterdir()) == ["ftir.json", "ftir.sample.csv"]
    assert get_parser("ftir", "bruker") is builtin_parser
    assert lab_statuses() == []  # removed/ is not read

    instrument = add_instrument("nmr600", "nmr", "NMR600")
    assert remove_definition(instrument).parent == instruments_dir() / "removed"
    assert "nmr600" not in {i.name for i in instruments()}


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
        assert actions == [("reparse", name, "fluorescence_insitu is now read by a definition")]
        apply(current, registry, stores)
        assert [a for a in plan(registry, stores).actions if a.name == name] == []


def test_read_again_names_both_versions_of_a_code_parser():
    from mfethuls.experiments import Experiment
    from mfethuls.reconcile import _reader_change

    exp = Experiment(name="EXP014", instrument_name="nmr")
    reason = _reader_change([{"reader": "nmr", "reader_fingerprint": "BrukerNMRParser-v5"}], exp)  # a downgrade
    assert reason == "read by another version of mfethuls' nmr reader (BrukerNMRParser-v5 -> BrukerNMRParser-v4)"
    assert _reader_change([{"reader": "nmr", "reader_fingerprint": "BrukerNMRParser-v4"}], exp) is None


def test_a_new_definition_reader_version_offers_read_again(data_root):
    from mfethuls.experiments import Experiment
    from mfethuls.reconcile import _reader_change

    exp = Experiment(name="LB_tga_001", instrument_name="tga")
    current = _fp("tga")
    assert _reader_change([{"reader": "tga", "reader_fingerprint": current}], exp) is None
    older = current.replace(f"@tabular{TabularParser.version}", "@tabular0")
    assert "definition reader (tabular0 -> tabular" in _reader_change([{"reader": "tga", "reader_fingerprint": older}],
                                                                       exp)
    changed = _reader_change([{"reader": "tga", "reader_fingerprint": "0000@tabular1"}], exp)
    assert changed == "the reader tga has changed"
    # A reader that is gone (a lab reader removed) does not read its data again.
    assert _reader_change([{"reader": "tga_gone", "reader_fingerprint": "0000@tabular1"}], exp) is None
