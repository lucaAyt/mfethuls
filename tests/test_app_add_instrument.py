"""Adding and removing instruments in the app: chatbot route (default), own guesses, plain form, Remove."""

import re
import json

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from mfethuls.app.instruments import (  # noqa: E402
    columns_from_rows,
    derived_from_rows,
    derived_rows,
    layout_for,
    layouts,
    mapping_rows,
    mapping_summary,
    route_problems,
    usage,
)
from mfethuls.instruments.configured import remove_definition, save_definition  # noqa: E402

DIALOG = """
import streamlit as st
from mfethuls.app.backend import LocalBackend
from mfethuls.app.instruments import add_instrument_dialog

class Backend(LocalBackend):
    writes_registry = {writes}

add_instrument_dialog(Backend(), folder="Photometer")
"""

SETTINGS = """
import streamlit as st
from mfethuls.app.backend import LocalBackend
from mfethuls.app.instruments import render_instruments_section

class Backend(LocalBackend):
    def list_datasets(self):
        return [{{"instrument_name": "photometer"}}]

render_instruments_section(Backend(), {registry!r})
"""

ANSWER = {
    "name": "photometer", "type": "absorbance_kinetics", "model": "lab_built", "folder_name": "Photometer",
    "file": {"extensions": [".dat"], "delimiter": "semicolon", "decimal": ",", "header": {"starts_at": "Time"}},
    "columns": [{"source": "Time (min)", "quantity": "time", "unit": "min"},
                {"source": "A600", "quantity": "absorbance"}],
    "plot": {"x": "time_s", "y": "absorbance_a_u"},
}


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "Photometer").mkdir(parents=True)
    (root / "Photometer" / "kin1.dat").write_text(
        "Photometer v2\nSample: LUB900\nTime (min);A600;Lamp\n0,0;0,10;on\n1,0;0,20;on\n2,0;0,30;on\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH_TO_DATA", str(root))
    yield root
    from mfethuls.instruments.configured import instrument_definitions

    instrument_definitions(data_root="")  # unregister the lab parsers again


def _run(script):
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    return at


def _by_key(widgets, suffix):
    return next(w for w in widgets if w.key and w.key.endswith(suffix))


def _shown(markdown: str) -> str:
    """A message as the user sees it: without the escapes that keep its text from being Markdown."""
    return re.sub(r"\\(.)", r"\1", markdown)


def _paste(at, answer):
    _by_key(at.text_area, "-answer").input(answer).run()
    assert not at.exception, at.exception
    return at


def _saved(data_root, name="photometer"):
    return json.loads((data_root / ".mfethuls" / "instruments" / f"{name}.json").read_text(encoding="utf8"))


def _click(at, label):
    [b for b in at.button if b.label == label][0].click().run()
    assert not at.exception, at.exception


# --- the chatbot route ------------------------------------------------------------

def test_chatbot_is_the_default_and_its_prompt_holds_the_file_and_mfethuls_reading(data_root):
    at = _run(DIALOG.format(writes=True))
    assert at.segmented_control(key="add-instrument-mode").value == "Ask a chatbot"
    prompt = at.code[0].value
    assert "Write an mfethuls *instrument definition*" in prompt
    assert "Time (min);A600;Lamp" in prompt  # the file's head
    assert "mfethuls' own reading of the file" in prompt and "decimal comma" in prompt
    assert "Its data folder is 'Photometer'." in prompt
    assert any("first 40 and last 15 lines of **kin1.dat**" in _shown(w.value) for w in at.warning)


def test_chatbot_answer_fills_the_form_and_is_saved(data_root):
    at = _run(DIALOG.format(writes=True))
    _paste(at, "Here is the definition:\n```json\n" + json.dumps(ANSWER) + "\n```\nHope this helps!")

    assert _by_key(at.text_input, "-name").value == "photometer"
    assert _by_key(at.text_input, "-model").value == "lab_built"
    assert _by_key(at.selectbox, "-delim").value == "semicolon"
    summary = next(d.value for d in at.dataframe if "column in the file" in d.value.columns)
    assert summary.loc[summary["column in the file"] == "Time (min)", "values"].item() == "min → s: × 60"
    assert summary.loc[summary["column in the file"] == "Lamp", "values"].item() == "kept as they are"
    assert any("Read **3** rows" in c.value for c in at.caption)

    _click(at, "Save instrument")
    saved = _saved(data_root)
    assert saved["columns"] == ANSWER["columns"] and saved["plot"] == ANSWER["plot"]
    assert saved["description"].startswith("Drafted with a chatbot and checked in mfethuls")
    assert saved["check"]["rows"] == 3


def test_the_form_changes_what_the_chatbot_wrote(data_root):
    at = _paste(_run(DIALOG.format(writes=True)), json.dumps(ANSWER))
    _by_key(at.text_input, "-model").input("photometer_2").run()
    _by_key(at.text_input, "-notes").input("Built in-house").run()
    _click(at, "Save instrument")
    saved = _saved(data_root)
    assert saved["model"] == "photometer_2" and saved["description"] == "Built in-house"


def test_problems_are_shown_in_their_section_and_offered_to_the_chatbot(data_root):
    wrong = {**ANSWER, "model": "", "columns": [{"source": "A600", "quantity": "absorbanse"}]}
    at = _paste(_run(DIALOG.format(writes=True)), json.dumps(wrong))
    problems = [_shown(e.value) for e in at.warning]  # things to fix, not failures
    assert any("'model' is missing" in e for e in problems)
    assert any("2 problem(s) to fix: see **Adjust details** below (Instrument, Columns)" in e for e in problems)
    assert not [b for b in at.button if b.label == "Save instrument"]
    feedback = next(c.value for c in at.code if c.value.startswith("mfethuls checked"))
    assert feedback.startswith("mfethuls checked your instrument definition")
    assert "'model' is missing" in feedback and '"name": "photometer"' in feedback


def test_unknown_quantities_from_the_chatbot_are_problems(data_root):
    wrong = {**ANSWER, "columns": [{"source": "A600", "quantity": "absorbanse"}]}
    at = _paste(_run(DIALOG.format(writes=True)), json.dumps(wrong))
    assert any("unknown quantity 'absorbanse'" in _shown(e.value) for e in at.warning)


def test_implausible_values_are_warned_about(data_root):
    answer = {**ANSWER, "columns": [{"source": "Time (min)", "quantity": "time", "unit": "min"},
                                    {"source": "A600", "quantity": "mass", "unit": "kg"}]}
    at = _paste(_run(DIALOG.format(writes=True)), json.dumps(answer))
    assert any("Mass (mass_mg) goes from 1e+05 to 3e+05 mg" in _shown(w.value) and "Is the unit in the file right?"
               in _shown(w.value) for w in at.warning), [_shown(w.value) for w in at.warning]
    assert [b for b in at.button if b.label == "Save instrument"]  # a warning, not a refusal


def test_without_write_access_the_files_are_offered_as_downloads(data_root):
    at = _paste(_run(DIALOG.format(writes=False)), json.dumps(ANSWER))
    assert not [b for b in at.button if b.label == "Save instrument"]
    assert any("does not write to the data folder" in i.value for i in at.info)
    assert not (data_root / ".mfethuls").exists()


# --- filling in yourself ----------------------------------------------------------

def test_own_guesses_fill_the_same_form(data_root):
    at = _run(DIALOG.format(writes=True))
    at.segmented_control(key="add-instrument-mode").set_value("Fill in myself").run()
    assert any("decimal comma" in c.value for c in at.caption)
    assert _by_key(at.selectbox, "-folder-choice").value == "Photometer"
    _by_key(at.text_input, "-name").input("photometer").run()
    _by_key(at.text_input, "-type-new").input("absorbance_kinetics").run()
    _by_key(at.text_input, "-model").input("lab_built").run()
    _click(at, "Save instrument")
    saved = _saved(data_root)
    assert saved["columns"] == [{"source": "Time (min)", "quantity": "time", "unit": "min"}]
    assert "description" not in saved


# --- removing ---------------------------------------------------------------------

def test_remove_asks_first_then_moves_the_files_aside(data_root, tmp_path):
    save_definition(ANSWER, data_root / "Photometer" / "kin1.dat")
    registry = tmp_path / "registry.csv"
    pd.DataFrame([{"name": "K1", "instrument_name": "photometer"}, {"name": "K2", "instrument_name": "tga"}]
                 ).to_csv(registry, index=False)
    at = _run(SETTINGS.format(registry=str(registry)))
    _click(at, "Remove")
    warning = " ".join(_shown(w.value) for w in at.warning)
    assert "Used by **1** registry row(s) and **1** ingested experiment(s)" in warning
    assert "removed/" in warning
    assert (data_root / ".mfethuls" / "instruments" / "photometer.json").exists()

    _click(at, "Remove photometer")
    folder = data_root / ".mfethuls" / "instruments"
    assert not (folder / "photometer.json").exists()
    (moved,) = (folder / "removed").iterdir()
    assert sorted(p.name for p in moved.iterdir()) == ["photometer.json", "photometer.sample.dat"]


def test_remove_can_be_cancelled(data_root):
    save_definition(ANSWER, data_root / "Photometer" / "kin1.dat")
    at = _run(SETTINGS.format(registry=""))
    _click(at, "Remove")
    _click(at, "Cancel")
    assert (data_root / ".mfethuls" / "instruments" / "photometer.json").exists()
    assert [b.label for b in at.button if b.label.startswith("Remove")] == ["Remove"]


def test_remove_definition_refuses_files_outside_the_lab_folder(data_root, tmp_path):
    other = tmp_path / "x.json"
    other.write_text("{}", encoding="utf8")
    with pytest.raises(ValueError, match="not one of the lab's instrument definitions"):
        remove_definition(other)


# --- helpers ------------------------------------------------------------------------

def test_form_columns_keep_alternative_names_and_mappings_for_other_exports():
    seed = [{"source": ["Weight [mg]", "Mass [mg]"], "quantity": "mass", "unit": "mg"},
            {"source": "DTG [%/min]", "quantity": "mass_loss_rate", "unit": "%/min"},
            {"source": "Detector", "column": "detector_name"}]
    rows = mapping_rows(["Mass [mg]", "Detector", "Other"], seed)
    assert rows[["quantity", "unit", "name"]].values.tolist() == [
        ["mass", "mg", ""], ["", "", "detector_name"], ["", "", ""]]
    rows.loc[2, ["quantity", "unit"]] = ["temperature", "K"]
    assert columns_from_rows(rows, seed) == [
        {"source": ["Weight [mg]", "Mass [mg]"], "quantity": "mass", "unit": "mg"},
        {"source": "Detector", "column": "detector_name"},
        {"source": "Other", "quantity": "temperature", "unit": "K"},
        {"source": "DTG [%/min]", "quantity": "mass_loss_rate", "unit": "%/min"},  # not in this file: kept
    ]


def test_mapping_summary_spells_out_conversions():
    summary = mapping_summary([{"source": "T", "quantity": "temperature", "unit": "K"},
                               {"source": "m", "quantity": "mass", "unit": "g"}], ["T", "m", "x"], "tga")
    assert summary["values"].tolist() == ["K → °C: − 273.15", "g → mg: × 1000", "kept as they are"]
    assert summary["stored as"].tolist() == ["temperature_C", "mass_mg", "x"]


def test_problems_are_routed_to_form_sections():
    routed = route_problems([
        "'model' is missing", "file: unknown key 'delimeter'", "'file.decimal' must be \".\" or \",\"",
        "column 2 ('A600'): unknown quantity 'x'", "derived 1: 'op' must be one of ...", "format 2: column 1: x",
        "'columns' must list at least one column", "something else",
    ])
    assert routed == {
        "instrument": ["'model' is missing"],
        "file": ["file: unknown key 'delimeter'", "'file.decimal' must be \".\" or \",\""],
        "columns": ["column 2 ('A600'): unknown quantity 'x'", "format 2: column 1: x",
                    "'columns' must list at least one column"],
        "extras": ["derived 1: 'op' must be one of ..."],
        "other": ["something else"],
    }


def test_derived_round_trip():
    seed = {"derived": [{"op": "normalize_pct", "column": "mass_mg", "into": "mass_pct"},
                        {"op": "scale", "column": "mass_mg", "into": "mass_g", "factor": 0.001}]}
    assert derived_from_rows(derived_rows(seed)) == seed["derived"]


def test_the_layout_matching_the_sample_is_edited(tmp_path):
    seed = {"formats": [{"label": "text", "file": {"extensions": [".txt"], "contains": "Version 2"}, "columns": []},
                        {"label": "old text", "file": {"extensions": [".txt"]}, "columns": []},
                        {"label": "csv", "file": {"extensions": ["csv"]}, "columns": []}]}
    old = tmp_path / "a.txt"
    old.write_text("Version 1\n", encoding="utf-8")
    csv = tmp_path / "b.csv"
    csv.write_text("x\n", encoding="utf-8")
    assert [layout_for(layouts(seed), p) for p in (old, csv)] == [1, 2]


def test_usage_counts_rows_and_datasets():
    frame = pd.DataFrame({"instrument_name": ["photometer", " Photometer", "tga"]})
    assert usage("photometer", frame, [{"instrument_name": "photometer"}, {"instrument_name": "tga"}]) == (2, 1)


# --- the end of the file and other files ---------------------------------------------

def _other_files(root):
    folder = root / "Photometer"
    long_run = ["Photometer v2", "Sample: LUB901", "Time (min);A600;Lamp"]
    long_run += [f"{i},0;0,{i % 9 + 1};on" for i in range(30)]
    long_run += ["", "Results", "Max A600;0,9", "Operator;LB"]
    (folder / "kin2.dat").write_text("\n".join(long_run) + "\n", encoding="utf-8")
    (folder / "notes.csv").write_text("not,the,instrument\n", encoding="utf-8")


def test_the_folder_gives_the_file_and_the_others_of_its_type_to_check(data_root):
    _other_files(data_root)
    at = _run(DIALOG.format(writes=True))
    # The largest file of the folder's most common type; the note next to the data is not checked.
    assert _by_key(at.selectbox, "-file-Photometer").value == "kin2.dat"
    assert any("also checks that it reads 1 other `.dat` file" in c.value for c in at.caption)
    assert "Another file of this instrument, `kin1.dat`" in at.code[0].value

    _by_key(at.selectbox, "-file-Photometer").set_value("kin1.dat").run()
    prompt = at.code[0].value
    assert "Another file of this instrument, `kin2.dat`" in prompt
    assert "lines 35–37: text (3 lines)" in prompt and "Max A600" not in prompt  # its shape, not its data

    at = _paste(at, json.dumps(ANSWER))
    table = next(d.value for d in at.dataframe if "result" in d.value.columns)
    assert table.to_dict("records") == [{"file": "kin2.dat", "rows": 33, "result": "⚠ 1 warning(s)"}]
    warning = next(_shown(w.value) for w in at.warning if _shown(w.value).startswith("kin2.dat: 3 row(s) have text"))
    assert "from line 35: 'Results'" in warning and "*The data ends at*" in warning
    assert any(c.value.startswith("mfethuls checked") and "kin2.dat: 3 row(s)" in c.value for c in at.code)
    assert [b for b in at.button if b.label == "Save instrument"]  # warnings don't block

    fixed = {**ANSWER, "file": {**ANSWER["file"], "data_ends": "first_non_numeric_row"}}
    at = _paste(at, json.dumps(fixed))
    assert not [d for d in at.dataframe if "result" in d.value.columns]
    assert any("Also reads the 1 other file checked cleanly: kin2.dat" in c.value for c in at.caption)


def test_an_other_file_that_cannot_be_read_blocks_saving(data_root):
    (data_root / "Photometer" / "broken.dat").write_text("nothing; to read\n", encoding="utf-8")
    at = _paste(_run(DIALOG.format(writes=True)), json.dumps(ANSWER))
    assert any(_shown(e.value).startswith("broken.dat cannot be read") for e in at.error)
    assert not [b for b in at.button if b.label == "Save instrument"]


def test_the_answer_is_read_with_a_button_and_details_open_only_when_needed(data_root):
    at = _run(DIALOG.format(writes=True))
    assert [b for b in at.button if b.label == "Read the answer"]
    at = _paste(at, json.dumps(ANSWER))
    assert not at.expander[0].proto.expanded  # Adjust details: nothing to fix
    wrong = {**ANSWER, "model": ""}
    at = _paste(at, json.dumps(wrong))
    assert next(e for e in at.expander if "Adjust details" in e.label).proto.expanded


def test_without_files_in_the_data_folder_the_user_is_told_where_to_put_them(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("PATH_TO_DATA", str(tmp_path / "data"))
    at = _run(DIALOG.format(writes=True))
    assert any("Put a few files exported by the instrument in a folder" in i.value for i in at.info)


def test_new_format_keys_survive_the_form(data_root):
    """segment_lines, name_from, from_file_name and encoding auto are kept when a definition is edited."""
    folder = data_root / "PE"
    folder.mkdir()
    (folder / "run_005.txt").write_text(
        "Sample: PLA\n1) Isothermal\n\tTime\tUnsubtracted\tProgram\n\t\tHeat Flow\tTemperature\n"
        "\t0.0\t-0.81\t30.0\n\t0.5\t-0.82\t30.0\n2) Scan\n\t1.0\t-0.88\t30.1\n", encoding="cp1252")
    answer = {
        "name": "pe_lab", "type": "dsc", "model": "pe_lab", "folder_name": "PE",
        "file": {"extensions": [".txt"], "encoding": "auto", "delimiter": "tab",
                 "header": {"starts_at": "Unsubtracted", "rows": 2}, "data_ends": "first_non_numeric_row",
                 "segment_lines": True},
        "columns": [{"source": "Time", "quantity": "time", "unit": "min"},
                    {"source": "Program Temperature", "quantity": "temperature", "unit": "°C"},
                    {"source": "Unsubtracted Heat Flow", "quantity": "heat_flow", "unit": "mW"}],
        "name_from": "folder",
        "from_file_name": [{"column": "step", "pattern": "_0*([^_]+)$"}],
    }
    at = _run(DIALOG.format(writes=True).replace('folder="Photometer"', 'folder="PE"'))
    at = _paste(at, json.dumps(answer))
    assert _by_key(at.checkbox, "-segments").value is True
    assert _by_key(at.selectbox, "-name-from").value == "folder"
    _click(at, "Save instrument")
    saved = _saved(data_root, "pe_lab")
    assert saved["file"]["segment_lines"] is True and saved["file"]["encoding"] == "auto"
    assert saved["name_from"] == "folder" and saved["from_file_name"] == answer["from_file_name"]
    assert saved["check"]["rows"] == 3 and "segment" in saved["check"]["columns"]


def test_header_values_names_from_and_add_time_survive_the_form(data_root):
    """from_header, from_file_name values/types, add_time and header.names_from are kept when edited."""
    folder = data_root / "FL"
    folder.mkdir()
    (folder / "s1__0__18-11-09-757.txt").write_text(
        "Date: Sun May 11 18:11:09 CEST 2025\nSig1\tWavelength (nm)\nSig2\tCounts\n"
        ">>>>>Begin Spectral Data<<<<<\n347.5\t11.8\n348.1\t1.8\n", encoding="utf-8")
    answer = {
        "name": "flame_lab", "type": "fluorescence", "model": "flame_lab", "folder_name": "FL",
        "data_layout": "folder", "name_from": "folder",
        "file": {"extensions": [".txt"], "encoding": "auto", "delimiter": "tab",
                 "header": {"starts_at": ">>>>>Begin", "skip_lines": 1, "rows": 0, "names_from": r"^Sig\d+\t(.+)$"}},
        "columns": [{"source": "Wavelength (nm)", "quantity": "wavelength", "unit": "nm"},
                    {"source": "Counts", "quantity": "emission", "unit": "counts"}],
        "from_header": [{"column": "header_time", "pattern": r"^Date:\s*(.+)$", "type": "datetime",
                         "timezone": "Europe/Zurich"}],
        "from_file_name": [{"column": "file_time_ms", "pattern": r"-(\d{1,3})$", "type": "number"},
                           {"column": "spot", "pattern": r"^([a-z]+)\d", "values": {"sample": "^s$"}}],
        "derived": [{"op": "add_time", "column": "header_time", "amount": "file_time_ms", "unit": "ms",
                     "into": "timestamp"}],
    }
    at = _run(DIALOG.format(writes=True).replace('folder="Photometer"', 'folder="FL"'))
    at = _paste(at, json.dumps(answer))
    assert _by_key(at.text_input, "-names-from").value == r"^Sig\d+\t(.+)$"
    _click(at, "Save instrument")
    saved = _saved(data_root, "flame_lab")
    for key in ("from_header", "from_file_name", "derived"):
        assert saved[key] == answer[key], key
    assert saved["file"]["header"]["names_from"] == answer["file"]["header"]["names_from"]
    assert {"timestamp", "header_time", "file_time_ms", "spot", "wavelength_nm"} <= set(saved["check"]["columns"])


def test_values_table_text_round_trip():
    from mfethuls.app.instruments import captured_from_rows, captured_rows, values_from_text, values_text

    values = {"ri": "^(RID|DRI)", "uv": "^VWD"}
    assert values_from_text(values_text(values)) == values
    seed = {"from_file_name": [{"column": "detector_name", "pattern": "_([^_.]+)$", "values": values}],
            "from_header": [{"column": "w", "pattern": "W: (.+)", "type": "number"}]}
    assert captured_from_rows(captured_rows(seed)) == seed


def test_blocks_survive_the_form(data_root):
    folder = data_root / "RH"
    folder.mkdir()
    (folder / "r1.csv").write_text(
        "Project:\tX\nInterval and data points:\t1\t1\nInterval data:\tTime\tG\n\t\t\n\t[s]\t[Pa]\n\t1\t10\n"
        "Interval and data points:\t2\t1\nInterval data:\tTime\tG\n\t\t\n\t[s]\t[Pa]\n\t2\t20\n", encoding="utf-8")
    blocks = {"starts_at": "Interval and data points:", "column": "interval",
              "label": r"^Interval and data points:\s*(\d+)"}
    answer = {"name": "rheo_lab", "type": "rheometer", "model": "rheo_lab", "folder_name": "RH",
              "file": {"extensions": [".csv"], "encoding": "auto", "delimiter": "tab",
                       "header": {"starts_at": "Interval data:", "rows": 2}, "blocks": blocks},
              "columns": [{"source": "Time [s]", "quantity": "time", "unit": "s"}]}
    at = _run(DIALOG.format(writes=True).replace('folder="Photometer"', 'folder="RH"'))
    at = _paste(at, json.dumps(answer))
    assert _by_key(at.text_input, "-blocks-at").value == "Interval and data points:"
    _click(at, "Save instrument")
    saved = _saved(data_root, "rheo_lab")
    assert saved["file"]["blocks"] == blocks
    assert saved["check"]["rows"] == 2 and "interval" in saved["check"]["columns"]


def test_read_by_tells_built_in_definitions_from_lab_ones(tmp_path):
    from mfethuls.app.instruments import _read_by
    from mfethuls.instruments.definition import BUILTIN_DIR

    assert _read_by({"definition": str(BUILTIN_DIR / "tga.json")}) == "built-in definition"
    assert _read_by({"definition": "built-in"}) == "built-in definition"
    assert _read_by({"definition": str(tmp_path / ".mfethuls" / "instruments" / "tga.json")}) == "lab definition"
    assert _read_by({}) == "built-in code"



# --- editing a lab instrument -------------------------------------------------------

EDIT = """
import streamlit as st
from mfethuls.app.backend import LocalBackend
from mfethuls.app.instruments import edit_instrument_dialog

edit_instrument_dialog(LocalBackend(), {path!r})
"""


def test_settings_offer_edit_next_to_remove(data_root):
    save_definition(ANSWER, data_root / "Photometer" / "kin1.dat")
    at = AppTest.from_string(SETTINGS.format(registry=""), default_timeout=60).run()
    [b for b in at.button if b.label == "Edit"][0].click().run()
    request = at.session_state["add_instrument_request"]
    assert request["edit"].endswith("photometer.json")


def test_edit_opens_the_saved_instrument_and_saves_the_changes(data_root):
    path = save_definition({**ANSWER, "file": {**ANSWER["file"], "duplicate_rows": "drop"},
                            "tables": [{"name": "notes", "starts_at": "Sample:"}]},
                           data_root / "Photometer" / "kin1.dat")
    at = _run(EDIT.format(path=str(path)))
    name = _by_key(at.text_input, "-name")
    assert name.value == "photometer" and name.disabled  # registry rows use the name
    assert any("Checked against **photometer.sample.dat**" in c.value for c in at.caption)
    assert any("Read **3** rows" in c.value for c in at.caption)
    assert not [c for c in at.checkbox if c.label.startswith("Replace")]  # editing needs no Replace

    _by_key(at.text_input, "-model").input("lab_built_v2").run()
    _click(at, "Save changes")
    saved = _saved(data_root)
    assert saved["name"] == "photometer" and saved["model"] == "lab_built_v2"
    assert saved["columns"] == ANSWER["columns"] and saved["check"]["rows"] == 3
    # What the form does not show is kept.
    assert saved["file"]["duplicate_rows"] == "drop" and saved["tables"] == [{"name": "notes", "starts_at": "Sample:"}]
    assert sorted(p.name for p in path.parent.iterdir()) == ["photometer.json", "photometer.sample.dat"]


def test_edit_without_its_sample_file_asks_for_one(data_root):
    path = save_definition(ANSWER, data_root / "Photometer" / "kin1.dat")
    (path.parent / "photometer.sample.dat").unlink()
    at = _run(EDIT.format(path=str(path)))
    assert any("not next to it any more" in i.value for i in at.info)
    assert _by_key(at.selectbox, "-folder").value == "Photometer"
    assert any("Read **3** rows" in c.value for c in at.caption)
