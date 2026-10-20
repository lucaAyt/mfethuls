"""The app for a new user: landing page, Get started (folders saved), and the example workspace."""

import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import mfethuls.app.welcome as welcome  # noqa: E402
import mfethuls.examples as examples  # noqa: E402

APP = str(Path(welcome.__file__).with_name("streamlit_app.py"))


@pytest.fixture
def new_user(tmp_path, monkeypatch):
    """No paths configured; the example workspace goes under tmp_path."""
    monkeypatch.setattr(examples, "DEFAULT_WORKSPACE", tmp_path / "mfethuls-example")
    monkeypatch.setattr(welcome, "DEFAULT_WORKSPACE", tmp_path / "mfethuls-example")
    yield tmp_path
    from mfethuls.settings import configure

    configure(None)  # leave no example settings behind for other tests


def _app():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception, at.exception
    return at


def _click(at, label):
    [b for b in at.button if b.label == label][0].click().run()
    assert not at.exception, at.exception


def test_landing_then_get_started_saves_the_folders(new_user):
    at = _app()
    assert {"Get started", "Try the example"} <= {b.label for b in at.button}

    _click(at, "Get started")
    lab = new_user / "lab-data"
    (lab / "DSC").mkdir(parents=True)
    [t for t in at.text_input if t.label == "Data folder"][0].input(str(lab)).run()
    [t for t in at.text_input if t.label == "Registry (spreadsheet)"][0].input(str(new_user / "experiments.csv")).run()
    assert any("DSC" in s.value for s in at.success)
    _click(at, "Save")

    saved = json.loads((new_user / "settings.json").read_text())  # MFETHULS_SETTINGS_FILE (conftest)
    assert saved["data_root"] == str(lab) and saved["registry_path"] == str(new_user / "experiments.csv")
    assert (new_user / "experiments.csv").read_text().startswith("name,instrument_name")
    assert [h.value for h in at.subheader] == ["Getting started"]
    assert not any(b.label == "Get started" for b in at.button)  # set up: no landing page any more


def test_get_started_with_only_a_data_folder_makes_the_registry_there(new_user):
    at = _app()
    _click(at, "Get started")
    lab = new_user / "lab-data"
    (lab / "DSC").mkdir(parents=True)
    [t for t in at.text_input if t.label == "Data folder"][0].input(str(lab)).run()
    assert any("registry.xlsx" in c.value and "made when you save" in c.value for c in at.caption)
    _click(at, "Save")

    saved = json.loads((new_user / "settings.json").read_text())
    assert saved["data_root"] == str(lab) and "registry_path" not in saved  # it follows the data folder
    import pandas as pd

    assert list(pd.read_excel(lab / "registry.xlsx").columns)[:2] == ["name", "instrument_name"]
    assert [h.value for h in at.subheader] == ["Getting started"]

    # A registry deleted by hand is made again when the app starts.
    (lab / "registry.xlsx").unlink()
    at = _app()
    assert (lab / "registry.xlsx").is_file()


def test_example_walkthrough_and_back(new_user):
    at = _app()
    _click(at, "Try the example")
    assert (new_user / "mfethuls-example" / "experiments_registry.csv").is_file()
    assert any("example items are not in the registry" in m.value for m in at.markdown)

    _click(at, "Back to my data")
    assert any(b.label == "Get started" for b in at.button)  # nothing saved: back to the landing page


def _steps_done(at):
    return [p.proto.text for p in at.get("progress") if "steps done" in p.proto.text][-1]


def test_checklist_ticks_off_and_home_returns_to_the_landing_page(new_user):
    import pandas as pd

    from mfethuls.experiments import append_rows

    at = _app()
    _click(at, "Try the example")
    assert _steps_done(at) == "1 of 5 steps done"

    # Registering shows up without any refresh: the registry file changed.
    append_rows(str(new_user / "mfethuls-example" / "experiments_registry.csv"), pd.DataFrame([
        {"name": "poly1", "instrument_name": "ftir", "raw_data_filename": "poly1"},
        {"name": "poly2", "instrument_name": "ftir", "raw_data_filename": "poly2"},
        {"name": "poly3", "instrument_name": "fluorescence_insitu", "raw_data_filename": "poly3"},
    ]))
    at.run()
    assert _steps_done(at) == "2 of 5 steps done"

    [c for c in at.checkbox if c.label == "Select all"][0].check().run()
    _click(at, "Ingest")
    picker = [m for m in at.multiselect if m.label == "Select experiments to plot"][0]
    picker.select("LB_dsc_001").run()
    # Axis limits open inline, above the chart, and stay applied when closed.
    [t for t in at.toggle if t.label == "Axis limits"][0].set_value(True).run()
    [n for n in at.number_input if n.label == "X min"][0].set_value(50.0).run()
    [t for t in at.toggle if t.label == "Axis limits"][0].set_value(False).run()
    assert any("Axis limits: X 50" in c.value for c in at.caption)
    [m for m in at.multiselect if m.label == "Select experiments to plot"][0].unselect("LB_dsc_001").run()
    assert _steps_done(at) == "5 of 5 steps done"  # registered, ingested, selected, plotted

    [b for b in at.button if b.label == "Home"][0].click().run()
    assert {b.label for b in at.button} >= {"Open my data"}
    _click(at, "Open my data")
    assert _steps_done(at) == "5 of 5 steps done"


def test_landing_opens_the_python_tutorial(new_user, monkeypatch):
    import mfethuls.tutorials as tutorials

    started = []
    monkeypatch.setattr(tutorials, "TUTORIAL_WORKSPACE", new_user / "mfethuls-tutorial")
    monkeypatch.setattr(tutorials.subprocess, "Popen", lambda args, cwd: started.append(args))
    monkeypatch.setattr(tutorials.importlib.util, "find_spec", lambda name: object())  # as if marimo is installed

    at = _app()
    _click(at, "Use it from Python")
    assert started and started[0][-1] == str(new_user / "mfethuls-tutorial" / "local_tutorial.py")
    assert any("Python tutorial" in i.value for i in at.info)


def _tracker(at):
    done = [m.value for m in at.sidebar.markdown if "Getting started complete" in m.value]
    return [p.proto.text for p in at.sidebar.get("progress") if p.proto.text.startswith("Getting started")] or done


def test_progress_on_own_data_is_kept_across_restarts(new_user):
    import shutil

    import pandas as pd

    from mfethuls.settings import save_settings

    lab = new_user / "lab-data"
    (lab / "DSC").mkdir(parents=True)
    shutil.copyfile(examples.DATA_DIR / "DSC" / "poly1.txt", lab / "DSC" / "poly1.txt")
    (lab / "DSC" / "old_run.txt").write_text("never registered", encoding="utf-8")  # leftovers don't block step 2
    registry = new_user / "experiments.csv"
    pd.DataFrame([{"name": "LB_dsc_001", "instrument_name": "dsc_mettler_toledo_v1", "sample_id": "S001",
                   "raw_data_filename": "poly1"}]).to_csv(registry, index=False)
    save_settings(data_root=str(lab), registry_path=str(registry))

    at = _app()

    assert _tracker(at) == ["Getting started: 2 of 5"]  # set up, and something is registered
    [c for c in at.checkbox if c.label == "Select all"][0].check().run()
    _click(at, "Ingest")
    [m for m in at.multiselect if m.label == "Select experiments to plot"][0].select("LB_dsc_001").run()
    # Ingested, selected and plotted: every step done, in view while plotting.
    assert _tracker(at) == [":green[:material/celebration:] **Getting started complete**"]

    restarted = _app()  # a new session: nothing in memory
    assert _tracker(restarted) == [":green[:material/celebration:] **Getting started complete**"]
    assert _steps_done(restarted) == "5 of 5 steps done"


def test_a_backend_serving_other_people_offers_nothing_that_changes_the_host(new_user):
    """edits_settings / offers_example False (the team server): no folder form, example or tutorial."""
    script = (
        "from mfethuls.app.backend import LocalBackend\n"
        "from mfethuls.app.page import run\n"
        "class Shared(LocalBackend):\n"
        "    edits_settings = False\n"
        "    offers_example = False\n"
        "run(Shared())\n"
    )
    at = AppTest.from_string(script, default_timeout=120).run()
    assert not at.exception, at.exception
    labels = {b.label for b in at.button}
    assert "Try the example" not in labels and "Use it from Python" not in labels
    _click(at, "Get started")
    assert not any(t.label == "Data folder" for t in at.text_input)
    assert any("set by whoever runs this app" in c.value for c in at.caption)


def _set_up(new_user, folder: str):
    """Saved folders and an empty registry; a DSC export in ``folder`` of the data folder."""
    from mfethuls.settings import save_settings

    lab = new_user / "lab-data"
    (lab / folder).mkdir(parents=True)
    (lab / folder / "poly 2.txt").write_bytes((examples.DATA_DIR / "DSC" / "poly2.txt").read_bytes())
    registry = new_user / "experiments.csv"
    registry.write_text("name,instrument_name,sample_id,run_id,raw_data_filename\n", encoding="utf-8")
    save_settings(data_root=str(lab), registry_path=str(registry))
    return lab


def test_a_folder_named_unlike_its_instrument_is_offered(new_user):
    # A first user's "DSC data" folder: nothing new for any instrument, yet it must not go unnoticed.
    _set_up(new_user, "DSC data")
    at = _app()

    assert any("No instrument reads the folder **DSC data**" in i.value for i in at.sidebar.info)
    _click(at, "Review & register")
    choice = next(s for s in at.selectbox if s.label.startswith("Instrument for"))
    assert choice.value == "DSC"  # suggested by the folder's name
    _click(at, "Use this folder")

    # AppTest reruns the whole page, which closes the dialog (the app reruns only the dialog).
    assert any("**1** new data item found" in i.value for i in at.sidebar.info)
    assert not any("No instrument reads" in i.value for i in at.sidebar.info)
    _click(at, "Review & register")
    assert any("now read the folder **DSC data**" in s.value for s in at.success)


def test_the_accent_colour_is_saved(new_user):
    from mfethuls.app.appearance import ACCENTS, DEFAULT_ACCENT, saved_accent, theme_args

    assert saved_accent() == DEFAULT_ACCENT
    # Light and dark set separately, so Streamlit keeps its Light / Dark choice; no Deploy button.
    assert theme_args()[:3] == [f"--theme.light.primaryColor={ACCENTS[DEFAULT_ACCENT]}",
                                f"--theme.dark.primaryColor={ACCENTS[DEFAULT_ACCENT]}",
                                "--client.toolbarMode=viewer"]
    assert "--theme.baseFontSize=17" in theme_args()
    _set_up(new_user, "DSC")
    at = _app()
    next(b for b in at.button if b.label == "Settings").click().run()
    next(r for r in at.radio if r.label == "Accent colour").set_value("Blue").run()

    assert saved_accent() == "Blue"
    from streamlit import config

    assert config.get_option("theme.light.primaryColor") == config.get_option("theme.dark.primaryColor") == ACCENTS["Blue"]
    assert config.get_option("theme.primaryColor") is None


def test_a_path_copied_with_quotes_is_taken_as_it_is_meant(new_user):
    # File Explorer's "Copy as path" puts the path in quotes.
    at = _app()
    _click(at, "Get started")
    lab = new_user / "lab data"
    (lab / "DSC").mkdir(parents=True)
    assert any("Copy as path" in c.value for c in at.caption)
    [t for t in at.text_input if t.label == "Data folder"][0].input(f'"{lab}"').run()
    _click(at, "Save")

    assert json.loads((new_user / "settings.json").read_text())["data_root"] == str(lab)


def test_experiments_are_narrowed_by_instrument_and_the_plot_filtered(new_user):
    at = _app()
    _click(at, "Try the example")
    [c for c in at.checkbox if c.label == "Select all"][0].check().run()
    _click(at, "Ingest")
    picker = [m for m in at.multiselect if m.label == "Select experiments to plot"][0]
    every = list(picker.options)
    instruments = next(p for p in at.pills if p.label == "Instrument")
    dsc = next(o for o in instruments.options if "dsc" in o)
    instruments.set_value([dsc]).run()
    picker = [m for m in at.multiselect if m.label == "Select experiments to plot"][0]
    assert 0 < len(picker.options) < len(every)
    picker.select(picker.options[0].split(" · ")[0]).run()  # options are shown with sample and run
    chosen = [m for m in at.multiselect if m.label == "Select experiments to plot"][0].value
    # Showing another instrument's experiments keeps the DSC one chosen.
    other = next(o for o in instruments.options if o != dsc)
    next(p for p in at.pills if p.label == "Instrument").set_value([other]).run()
    assert [m for m in at.multiselect if m.label == "Select experiments to plot"][0].value == chosen
    assert not at.exception

    # The plot's Filter: DSC segments offered first, and a line under the chart while it is on.
    assert any(p.proto.popover.label == "Filter by profile" for p in at.get("popover"))
    column = next(w for w in at.selectbox if w.key == "plot_filter-column")
    assert column.options[1] == "profile"
    column.set_value("profile").run()
    values = next(w for w in at.multiselect if w.key == "plot_filter-values-profile")
    values.select(values.options[1]).run()
    assert any("Showing **" in c.value and "profile is" in c.value.casefold() for c in at.caption)
    assert any(p.proto.popover.label == f"Filter: {values.options[1]}" for p in at.get("popover"))
    _click(at, "Clear")
    assert not any("Showing **" in c.value for c in at.caption)


def test_filter_columns_are_those_with_few_values():
    import pandas as pd

    from mfethuls.app.page import apply_conditions, filter_columns

    data = pd.DataFrame({"_experiment": ["a", "a", "b", "b"],
                         "profile": ["Heating_1", "Cooling_1", "Heating_1", "Cooling_1"],
                         "temperature_C": [1.0, 2.0, 3.0, 4.0], "only": ["x"] * 4, "cycle": [1, 2, 2, 3],
                         "sample_id": ["S1", "S1", "S2", "S2"]})
    # Fewest values first; floats, single values and the experiment's own columns left out.
    assert filter_columns(data) == ["profile", "cycle"]
    kept = apply_conditions(data, {"profile": ["Cooling_1"], "cycle": ["2"]})
    assert kept["temperature_C"].tolist() == [2.0]
