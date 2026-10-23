"""Review & register in the app: folders start closed, so a folder of many files is one row."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import mfethuls.app.welcome as welcome  # noqa: E402
import mfethuls.examples as examples  # noqa: E402

APP = str(Path(welcome.__file__).with_name("streamlit_app.py"))


@pytest.fixture
def lab(tmp_path):
    from mfethuls.settings import configure, save_settings

    data = tmp_path / "lab-data"
    sample = (examples.DATA_DIR / "DSC" / "poly2.txt").read_bytes()
    (data / "DSC" / "batch").mkdir(parents=True)
    (data / "DSC" / "poly2.txt").write_bytes(sample)
    for i in range(1, 4):
        (data / "DSC" / "batch" / f"run{i}.txt").write_bytes(sample)
    registry = tmp_path / "experiments.csv"
    registry.write_text("name,instrument_name,sample_id,run_id,raw_data_filename\n", encoding="utf-8")
    save_settings(data_root=str(data), registry_path=str(registry))
    yield data
    configure(None)


def test_a_folder_of_files_is_one_closed_row(lab):
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception, at.exception
    [b for b in at.button if b.label == "Review & register"][0].click().run()
    assert not at.exception, at.exception

    state = at.session_state["register_tree"]
    shown = state["base"]
    assert shown["_kind"].tolist() == ["folder", "file"]
    assert shown["_data"].tolist()[0] == "▸ \U0001f4c1 DSC/batch/  \xb7  3 files"

    # Ticking the folder ticks its three files out of sight; Open shows them.
    from mfethuls.app import register

    key = f"register-editor-{state['version']}"
    session = {"register_tree": state, key: {"edited_rows": {0: {"include": True, "_open": True}}}}
    with patch.object(register.st, "session_state", session):  # as the editor's callback sees it
        register._edited(key)
    shown = state["base"]
    assert shown["_kind"].tolist() == ["folder", "run", "run", "run", "file"]
    assert shown["include"].tolist() == [True, True, True, True, False]
    assert shown["_data"].tolist()[0].endswith("3 of 3 ticked")


def test_rows_that_can_be_registered_are_saved_without_those_that_cannot(lab, tmp_path):
    from mfethuls import Registry
    from mfethuls.app import register

    (lab / "DSC" / "notes.txt").write_text("not a DSC export\n", encoding="utf-8")
    at = AppTest.from_file(APP, default_timeout=120).run()
    [b for b in at.button if b.label == "Review & register"][0].click().run()
    state = at.session_state["register_tree"]
    files = state["base"]["_kind"] == "file"
    key = f"register-editor-{state['version']}"
    ticks = {position: {"include": True} for position, is_file in enumerate(files) if is_file}  # notes and poly2
    with patch.object(register.st, "session_state", {"register_tree": state, key: {"edited_rows": ticks}}):
        register._edited(key)

    [b for b in at.button if b.label == "Review & register"][0].click().run()  # the dialog again, with the ticks
    assert not at.exception, at.exception
    assert not [b for b in at.sidebar.button if b.label == "Save to registry"]  # in its own window
    assert any("1 of the 2 ticked rows is left out: it can't be registered (✗ above). The other 1 will be saved."
               in w.value for w in at.warning)
    assert [b.disabled for b in at.button if b.label in ("Save to registry", "Save & ingest")] == [False, False]

    # What Save writes. (AppTest shows a dialog only on the run that opened it, so its Save is not clicked here.)
    tree = at.session_state["register_tree"]["tree"]
    rows = register.registry_rows(register.chosen_rows(tree))
    results = register.validate_proposed(Registry.load(str(tmp_path / "experiments.csv")), rows, str(lab))
    assert register.registrable(rows, results)["raw_data_filename"].tolist() == ["poly2"]  # notes is left out


@pytest.mark.parametrize("own_folder", [True, False])
def test_a_folder_no_instrument_reads_gets_one_of_its_type(tmp_path, own_folder):
    """A second instrument when the type's built-in one has its folder; else this folder becomes that one's."""
    from mfethuls.settings import configure, save_settings

    data = tmp_path / "lab-data"
    series = data / "inSitu_UV" / "switch_A"
    series.mkdir(parents=True)
    for path in sorted((examples.DATA_DIR / "Fluorescence" / "poly3").glob("*.txt"))[:3]:
        (series / path.name).write_bytes(path.read_bytes())
    if own_folder:
        (data / "UV_Vis").mkdir()
    registry = tmp_path / "experiments.csv"
    registry.write_text("name,instrument_name,sample_id,run_id,raw_data_filename\n", encoding="utf-8")
    save_settings(data_root=str(data), registry_path=str(registry))
    try:
        at = AppTest.from_file(APP, default_timeout=120).run()
        [b for b in at.button if b.label == "Review & register"][0].click().run()
        assert not at.exception, at.exception

        choice = next(s for s in at.selectbox if s.label.startswith("Measurement type of"))
        # Flame spectra read as UV-Vis or fluorescence; the folder's name says UV.
        assert choice.value == "uv_vis" and {"tga (tga)", "uv_vis (uv_insitu, uv_vis)"} <= set(choice.options)
        names = [t for t in at.text_input if t.label == "Name of the new instrument"]
        assert [t.value for t in names] == (["insitu_uv"] if own_folder else [])
        [b for b in at.button if b.label == "Use this folder"][0].click().run()
        assert not at.exception, at.exception

        file = json.loads((data / ".mfethuls" / "instruments" / ("insitu_uv.json" if own_folder else "uv_vis.json"))
                          .read_text(encoding="utf8"))
        assert file == {"spec_version": 1, "name": "insitu_uv" if own_folder else "uv_vis", "type": "uv_vis",
                        "folder_name": "inSitu_UV"}
        # AppTest reruns the whole page, which closes the dialog; the folder is now read.
        assert any("**1** new data item found" in i.value for i in at.sidebar.info)
    finally:
        configure(None)
