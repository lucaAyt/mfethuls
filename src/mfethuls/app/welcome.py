"""What the app shows while no experiments are selected, and choosing where the data lives.

- **Landing page** (not set up yet): what mfethuls is and does, with **Get started**
  and **Try the example**.
- **Setup** (Get started, or ⚙ Settings later): the data folder, checked as you type,
  with the expected folder layout. The registry is made for you in the data folder
  (``registry.xlsx``); another one can be chosen once you know what it is for. Saved
  with :func:`mfethuls.settings.save_settings`, so notebooks use the same folders.
- **Progress** (set up, nothing selected): a checklist that ticks off register,
  ingest, select and plot as they are done.
- **Example workspace**: a copy of the bundled examples (:mod:`mfethuls.examples`)
  used for this session only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from mfethuls.app.register import clear_registry_caches, count_new_data, registry_frame
from mfethuls.discovery import REGISTRY_COLUMNS
from mfethuls.examples import DEFAULT_WORKSPACE, create_workspace
from mfethuls.settings import DEFAULT_REGISTRY_NAME, configure, get_settings, save_settings, settings_file

_EXAMPLE_KEY = "example_workspace"
_SETUP_KEY = "show_setup"
_LANDING_KEY = "show_landing"
_PROGRESS_FILE = "progress.json"


# -- state ------------------------------------------------------------------------


def example_folder() -> Optional[str]:
    """The example workspace the app is using, if any."""
    return st.session_state.get(_EXAMPLE_KEY)


def is_set_up() -> bool:
    """Whether the data folder and the registry exist."""
    settings = get_settings()
    return bool(settings.data_root and os.path.isdir(settings.data_root)
                and settings.registry_path and os.path.isfile(settings.registry_path))


def default_registry(data_root: str) -> str:
    return os.path.join(data_root, DEFAULT_REGISTRY_NAME)


def ensure_registry() -> None:
    """Make the data folder's own registry if it is the one in use and does not exist yet."""
    settings = get_settings()
    if not (settings.data_root and os.path.isdir(settings.data_root) and settings.registry_path):
        return
    if settings.registry_path == default_registry(settings.data_root) and not os.path.exists(settings.registry_path):
        _create_registry(settings.registry_path)


def setup_requested() -> bool:
    return bool(st.session_state.get(_SETUP_KEY))


def landing_requested() -> bool:
    return bool(st.session_state.get(_LANDING_KEY))


def show_landing() -> None:
    """The home button: back to the landing page."""
    st.session_state[_LANDING_KEY] = True
    st.session_state.pop(_SETUP_KEY, None)


def _progress_path() -> Path:
    """Where getting-started progress is kept: in the example folder, or next to the saved settings."""
    folder = example_folder()
    return Path(folder) / _PROGRESS_FILE if folder else settings_file().parent / _PROGRESS_FILE


def _load_progress() -> Dict[str, Any]:
    try:
        saved = json.loads(_progress_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"done": [], "dismissed": False}
    return {"done": list(saved.get("done", [])), "dismissed": bool(saved.get("dismissed", False))}


def _save_progress(progress: Dict[str, Any]) -> None:
    path = _progress_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(progress), encoding="utf-8")
    except OSError:
        pass  # progress is a convenience; never fail the app over it


def mark_done(step: str) -> None:
    """Remember that a getting-started step was done ("register", "select", "plot")."""
    progress = _load_progress()
    if step not in progress["done"]:
        progress["done"].append(step)
        _save_progress(progress)


def _done(step: str) -> bool:
    return step in _load_progress()["done"]


def dismiss_guide() -> None:
    progress = _load_progress()
    progress["dismissed"] = True
    _save_progress(progress)


def _forget_state(backend) -> None:
    st.session_state.pop("reconcile_plan", None)
    clear_registry_caches()
    backend.clear_caches()


def enter_example(backend, *, fresh: bool = False) -> None:
    """Copy the examples (once) and point the app at them for this session."""
    workspace = create_workspace(DEFAULT_WORKSPACE, fresh=fresh)
    configure(workspace.settings(get_settings()))
    st.session_state[_EXAMPLE_KEY] = str(workspace.folder)
    st.session_state.pop(_SETUP_KEY, None)
    st.session_state.pop(_LANDING_KEY, None)
    _forget_state(backend)


def leave_example(backend) -> None:
    """Go back to the saved data folder and registry."""
    configure(None)
    st.session_state.pop(_EXAMPLE_KEY, None)
    _forget_state(backend)


# -- landing page -----------------------------------------------------------------

_BENEFITS = [
    (":material/dataset:", "Your data, organised",
     "Every export is read, cleaned and stored in one consistent format across instruments, linked to its "
     "experiment and its raw file. Nothing gets lost, mixed up or overwritten."),
    (":material/science:", "For experimentalists",
     "Register, process and compare experiments without code: overlay runs, samples and instruments, "
     "and export publication-ready figures."),
    (":material/model_training:", "For data science and AI",
     "Harmonised, traceable data from every instrument, ready to query from Python or SQL and to build "
     "features and models on."),
]


def _open_tutorial() -> None:
    from mfethuls.tutorials import MarimoMissing, TUTORIAL_WORKSPACE, open_tutorial

    try:
        open_tutorial()
    except MarimoMissing as exc:
        st.session_state["tutorial_message"] = ("warning", str(exc))
    except Exception as exc:  # noqa: BLE001 - shown on the page
        st.session_state["tutorial_message"] = ("error", f"Could not open the tutorial: {exc}")
    else:
        st.session_state["tutorial_message"] = (
            "info", f"Opening the Python tutorial in a new browser tab (a marimo notebook in `{TUTORIAL_WORKSPACE}`).")


def render_landing(backend) -> None:
    _, middle, _ = st.columns([1, 6, 1])
    with middle:
        st.markdown(
            "<div role='heading' aria-level='1' style='text-align:center;font-size:3.4rem;font-weight:700;"
            "margin:2.5rem 0 0'>mfethuls</div>"
            "<p style='text-align:center;font-size:1.4rem;opacity:0.85;margin:0.3rem 0 1.6rem'>"
            "From scattered instrument files to analysis-ready data.</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align:center;font-size:1.05rem;max-width:46rem;margin:0 auto 2rem'>"
            "mfethuls is a framework that reads, cleans and organises your experimental data, so every "
            "measurement is consistent, traceable and ready to compare. This app is the quickest way to use it: "
            "register experiments, process them and explore the results, no code needed.</p>",
            unsafe_allow_html=True,
        )
        for column, (icon, title, text) in zip(st.columns(3), _BENEFITS):
            with column.container(border=True, height="stretch"):
                st.subheader(icon, anchor=False)  # no link icon: the cards are not links
                st.markdown(f"**{title}**")
                st.markdown(text)  # body text, not a faint caption: this is what the app is for
        st.write("")
        set_up = is_set_up() or bool(example_folder())
        local = getattr(backend, "offers_example", False)
        _, start_col, example_col, python_col, _ = st.columns([1, 2, 2, 2, 1])
        if set_up:
            if start_col.button("Open my data", icon=":material/arrow_forward:", type="primary", width="stretch"):
                st.session_state.pop(_LANDING_KEY, None)
                st.rerun()
        elif start_col.button("Get started", icon=":material/arrow_forward:", type="primary", width="stretch"):
            st.session_state[_SETUP_KEY] = True
            st.session_state.pop(_LANDING_KEY, None)
            st.rerun()
        if local and not example_folder() and example_col.button(
            "Try the example", icon=":material/science:", width="stretch",
            help=f"Explore example DSC, TGA, FTIR and fluorescence data in the app, copied to {DEFAULT_WORKSPACE}.",
        ):
            enter_example(backend)
            st.rerun()
        if local:
            python_col.button(
                "Use it from Python", icon=":material/code:", width="stretch", on_click=_open_tutorial,
                help="Open the tutorial notebook (marimo): load, compare and plot the example data in Python.",
            )
        message = st.session_state.pop("tutorial_message", None)
        if message:
            kind, text = message
            {"info": st.info, "warning": st.warning, "error": st.error}[kind](text)
        st.markdown(
            "<p style='text-align:center;opacity:0.8;font-size:0.95rem;margin-top:1.5rem'>"
            "Your raw files stay where they are; mfethuls builds a clean, reproducible dataset alongside them.</p>",
            unsafe_allow_html=True,
        )


# -- setup --------------------------------------------------------------------------


def render_folder_layout() -> None:
    """The expected layout of the data folder, and the instrument folder names mfethuls knows."""
    st.code(
        "my-lab-data/                   ← data folder\n"
        "├── DSC/                       ← one folder per instrument\n"
        "│   ├── polymerA_run1.txt      ← one file per experiment…\n"
        "│   └── polymerA_run2.txt\n"
        "├── UV_Vis/\n"
        "│   └── titration_A/           ← …or one folder for a series\n"
        "│       ├── spectrum_001.txt\n"
        "│       └── spectrum_002.txt\n"
        "└── TGA/\n"
        "    └── polymerA.txt\n"
        "\n"
        "registry.xlsx                  ← registry: one row per experiment, made for you",
        language=None,
    )
    from mfethuls.instruments.configured import instruments, readers_of

    rows = [
        {
            "Folder": f"{instrument.folder_name}/",
            "Instrument": instrument.name,
            "An experiment is": " or ".join(sorted({
                "a folder of files" if reader.layout == "folder" else "a file" for reader in readers_of(instrument)
            })),
        }
        for instrument in sorted(instruments(), key=lambda i: i.folder_name.casefold())
    ]
    with st.expander("Instrument folder names"):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _check_data_folder(path: str) -> None:
    if not path:
        return
    if not os.path.isdir(path):
        st.warning("This folder does not exist.", icon=":material/folder_off:")
        return
    from mfethuls.instruments.configured import instruments

    known = {instrument.folder_name for instrument in instruments(data_root=path)}
    children = sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)) and not d.startswith("."))
    found = [d for d in children if d in known]
    other = [d for d in children if d not in known and not d.startswith("_")]
    if found:
        st.success(f"Instrument folders found: {', '.join(found)}", icon=":material/folder_open:")
    else:
        st.warning("No instrument folders found yet. Add one folder per instrument, named as below.",
                   icon=":material/folder:")
    if other:
        st.caption(f"Not instrument folders (ignored): {', '.join(other)}")


def _check_registry(path: str) -> bool:
    """Show another registry's state; returns whether an empty one should be created on save."""
    if not path:
        return False
    if os.path.isfile(path):
        try:
            frame = registry_frame(path)
            st.success(f"Registry with {len(frame)} rows.", icon=":material/table:")
        except Exception as exc:
            st.error(f"Cannot read this registry: {exc}", icon=":material/error:")
        return False
    if not path.lower().endswith((".csv", ".xlsx")):
        st.warning("Use a .csv or .xlsx file.", icon=":material/error:")
        return False
    if not os.path.isdir(os.path.dirname(os.path.abspath(path))):
        st.warning("Its folder does not exist.", icon=":material/folder_off:")
        return False
    return st.checkbox("Create an empty registry here", value=True,
                       help="A spreadsheet with the registry columns; rows are added when you register data.")


def _example_registry_downloads(key: str) -> None:
    """The example registry as a download, to see the format or start from it."""
    from mfethuls.app.register import csv_bytes, xlsx_bytes
    from mfethuls.examples import REGISTRY_PATH

    example = pd.read_csv(REGISTRY_PATH)
    text_col, xlsx_col, csv_col = st.columns([2, 1, 1], vertical_alignment="center")
    text_col.caption("See what a registry looks like:")
    xlsx_col.download_button("Example .xlsx", data=xlsx_bytes(example), file_name="example_registry.xlsx",
                             icon=":material/download:", key=f"{key}_example_xlsx", width="stretch")
    csv_col.download_button("Example .csv", data=csv_bytes(example), file_name="example_registry.csv",
                            mime="text/csv", icon=":material/download:", key=f"{key}_example_csv", width="stretch")


def _create_registry(path: str) -> None:
    empty = pd.DataFrame(columns=REGISTRY_COLUMNS)
    if path.lower().endswith(".xlsx"):
        empty.to_excel(path, index=False)
    else:
        empty.to_csv(path, index=False)


def _describe_default_registry(data_root: str) -> None:
    """Where the registry made for you is, and whether it exists yet."""
    if not data_root or not os.path.isdir(data_root):
        return
    path = default_registry(data_root)
    if not os.path.isfile(path):
        st.caption(f":material/table: mfethuls keeps the list of your experiments (the registry) in "
                   f"`{DEFAULT_REGISTRY_NAME}` in this folder. It is made when you save; rows are added "
                   "when you register data.")
        return
    try:
        rows = len(registry_frame(path))
    except Exception as exc:
        st.error(f"Cannot read {DEFAULT_REGISTRY_NAME} in this folder: {exc}", icon=":material/error:")
        return
    st.caption(f":material/table: The list of your experiments (the registry) is `{DEFAULT_REGISTRY_NAME}` "
               f"in this folder: {rows} row{'s' if rows != 1 else ''}.")


_COPY_PATH_TIP = (":material/content_copy: To copy a folder's path: open it in File Explorer, click the "
                  "address bar and copy it (Ctrl+C), or right-click the folder and choose **Copy as path**. "
                  "Then paste it here.")


def path_input(label: str, *, value: str, key: str, **text_input_args) -> str:
    """A text input for a pasted path; the quotes **Copy as path** adds are taken off."""
    return st.text_input(label, value=value, key=key, **text_input_args).strip().strip('"').strip()


def render_setup_form(backend, *, key: str) -> None:
    """The data folder input, checked as it is typed, another registry if wanted, and Save."""
    settings = get_settings()
    if not getattr(backend, "edits_settings", False):
        st.caption("The data folder and registry are set by whoever runs this app.")
        st.markdown(f"Registry: `{os.path.basename(settings.registry_path or '') or 'not set'}`")
        return
    data_root = path_input("Data folder", value=settings.data_root or "", key=f"{key}_data_root",
                           placeholder=r"e.g. C:\Users\you\OneDrive\lab-data",
                           help="The folder that holds one subfolder per instrument.")
    st.caption(_COPY_PATH_TIP)
    _check_data_folder(data_root)
    # A registry other than the data folder's own is shown as it was saved.
    custom = ""
    if settings.registry_path and settings.data_root and settings.registry_path != default_registry(settings.data_root):
        custom = settings.registry_path
    with st.expander(":material/table: Use a different registry", expanded=bool(custom)):
        st.caption("For a registry kept somewhere else, e.g. shared on OneDrive. Leave empty to use "
                   f"`{DEFAULT_REGISTRY_NAME}` in the data folder.")
        registry_path = path_input("Registry (spreadsheet)", value=custom, key=f"{key}_registry",
                                   placeholder=r"e.g. C:\Users\you\OneDrive\experiments.xlsx",
                                   help="CSV or Excel file with one row per experiment.")
        create = _check_registry(registry_path)
        _example_registry_downloads(key)
    if not registry_path:
        _describe_default_registry(data_root)
    with st.expander("Where processed data is stored"):
        storage = path_input("Storage folder (optional)", value=settings.local_storage or "",
                             key=f"{key}_storage",
                             help="Parsed data is stored here. Empty: a _storage folder inside the data folder.")
    ok = bool(data_root and os.path.isdir(data_root)
              and (not registry_path or os.path.isfile(registry_path) or create))
    if st.button("Save", type="primary", icon=":material/save:", disabled=not ok, key=f"{key}_save", width="stretch"):
        if registry_path and create:
            _create_registry(registry_path)
        # Without another registry, the data folder's own is used, made now if it is missing.
        save_settings(data_root=data_root, registry_path=registry_path or None, local_storage=storage or None)
        ensure_registry()
        if example_folder():
            leave_example(backend)
        st.session_state.pop(_SETUP_KEY, None)
        _forget_state(backend)
        st.rerun()
    if example_folder():
        st.caption("Saving switches the app from the example data to these folders.")


def render_setup(backend) -> None:
    """The Get started page."""
    _, middle, _ = st.columns([1, 4, 1])
    with middle:
        st.title("Get started", anchor=False)
        st.markdown("Tell mfethuls where your instruments save their data. "
                    "You can change this any time under **⚙ Settings**.")
        # One column: beside the form, the folder layout was too narrow and cut off.
        render_setup_form(backend, key="setup")
        if st.button("Back", icon=":material/arrow_back:", key="setup_back"):
            st.session_state.pop(_SETUP_KEY, None)
            st.rerun()
        st.markdown("**How to organise the data folder**")
        render_folder_layout()


# -- settings dialog sections -----------------------------------------------------


def render_example_settings(backend) -> None:
    folder = example_folder()
    if folder:
        st.caption(f"The app is using the example data in `{folder}`. Your own data is untouched.")
        leave_col, restart_col = st.columns(2)
        if leave_col.button("Back to my data", icon=":material/logout:", width="stretch"):
            leave_example(backend)
            st.rerun()
        if restart_col.button("Start the example again", icon=":material/restart_alt:", width="stretch",
                              help="Delete the example folder and copy the examples afresh."):
            enter_example(backend, fresh=True)
            st.rerun()
    else:
        st.caption(f"Explore example DSC, TGA, FTIR and fluorescence data, copied to `{DEFAULT_WORKSPACE}`.")
        if st.button("Try the example", icon=":material/science:", width="stretch"):
            enter_example(backend)
            st.rerun()


def render_loading_settings() -> None:
    """How many rows to load per experiment (kept in session state while the dialog is closed)."""
    load_all = st.toggle("Load all rows", value=st.session_state.get("load_all_rows", True),
                         help="Plots and SVG exports use every data point. Turn off to load fewer rows "
                              "per experiment when browsing very large datasets.")
    st.session_state["load_all_rows"] = load_all
    if not load_all:
        st.session_state["row_limit"] = int(st.number_input(
            "Rows per experiment", min_value=10, step=500, value=st.session_state.get("row_limit", 5000)))


def row_limit() -> Optional[int]:
    """Rows to load per experiment; ``None`` loads all (the default)."""
    return None if st.session_state.get("load_all_rows", True) else st.session_state.get("row_limit", 5000)


# -- progress -----------------------------------------------------------------------


def _registry_names(registry_path: str) -> List[str]:
    frame = registry_frame(registry_path)
    if "name" not in frame or "instrument_name" not in frame:
        return []
    return frame.loc[frame["instrument_name"].notna(), "name"].dropna().astype(str).tolist()


def guide_steps(datasets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The getting-started steps: ``{"title", "done", "hint"}`` each.

    With the example, registering and ingesting are done when every example is; with
    your own data, when it was done at least once (a data folder usually holds files
    you never mean to register). Selecting, plotting and cleaning up are remembered on
    disk, so the list survives restarts.
    """
    settings = get_settings()
    example = bool(example_folder())
    new: Optional[int] = None
    registered: List[str] = []
    try:
        new = count_new_data(settings.registry_path, settings.data_root)
        registered = _registry_names(settings.registry_path)
    except Exception:
        pass
    ingested = {d.get("experiment_name") for d in datasets}
    missing = [name for name in registered if name not in ingested]

    if example:
        registered_done = new == 0
        register_hint = (f"**{new}** example items are not in the registry yet. Open **Ingest** → **Review & "
                         "register**, tick the FTIR and fluorescence rows and press **Save to registry**."
                         if new else "All example data is registered.")
        ingested_done = bool(registered) and not missing
    else:
        registered_done = bool(registered) or _done("register")
        register_hint = ("New raw data that is not in the registry yet shows up under **Ingest** → **Review & register**: "
                         "rows are proposed from the files and checked as you edit them.")
        if new:
            items = "item in the data folder is" if new == 1 else "items in the data folder are"
            register_hint = f"**{new}** {items} not in the registry. " + register_hint
        ingested_done = bool(datasets)
    ingest_hint = "Open **Ingest**, tick the experiments (or **Select all**) and press **Ingest**: raw files are read and stored."
    if missing:
        ingest_hint = f"**{len(missing)}** registered experiments are not ingested yet. " + ingest_hint

    return [
        {"title": "Choose your data folder", "done": True,
         "hint": "Change it any time under **⚙ Settings**."},
        {"title": "Register new data", "done": registered_done, "hint": register_hint},
        {"title": "Ingest", "done": ingested_done, "hint": ingest_hint},
        {"title": "Select experiments", "done": _done("select"),
         "hint": "Pick one or more experiments under **Datasets** in the sidebar; the page then shows their data."},
        {"title": "Plot and export", "done": _done("plot"),
         "hint": "Open the **Plot** section: the built-in plot for each instrument, or a line or scatter plot with "
                 "**Colour by** and **Style by**. Set axis limits and export a vector SVG or interactive HTML."},
    ]


def _render_step(number: int, step: Dict[str, Any], *, compact: bool = False) -> None:
    icon = ":material/check_circle:" if step["done"] else ":material/radio_button_unchecked:"
    colour = "green" if step["done"] else "gray"
    text = f":{colour}[{icon}] **{number}. {step['title']}**"
    st.markdown(text if compact and step["done"] else f"{text}  \n{step['hint']}")


def _render_steps(steps: List[Dict[str, Any]], *, compact: bool = False) -> None:
    done = sum(step["done"] for step in steps)
    st.progress(done / len(steps), text=f"{done} of {len(steps)} steps done")
    for number, step in enumerate(steps, start=1):
        _render_step(number, step, compact=compact)


def render_progress(backend, datasets: List[Dict[str, Any]]) -> None:
    """Set up, nothing selected: where the user is in the workflow."""
    example = example_folder()
    steps = guide_steps(datasets)

    if example:
        text_col, button_col = st.columns([4, 1], vertical_alignment="center")
        text_col.success(
            "You are exploring the **example data**: the DSC and TGA experiments are registered, the FTIR "
            "and fluorescence files are waiting to be registered. Follow the steps below.",
            icon=":material/science:",
        )
        if button_col.button("Back to my data", icon=":material/logout:", width="stretch"):
            leave_example(backend)
            st.rerun()

    if all(step["done"] for step in steps[:3]) and datasets and not example:
        st.info("Select one or more experiments under **Datasets** in the sidebar to look at them.",
                icon=":material/arrow_back:")
        with st.expander("Getting started"):
            _render_steps(steps)
        return
    st.subheader("Getting started", anchor=False)
    _render_steps(steps)


def render_guide_tracker(datasets: List[Dict[str, Any]]) -> None:
    """The getting-started progress in the sidebar, so it stays in view while exploring."""
    if not (is_set_up() or example_folder()) or _load_progress()["dismissed"]:
        return
    steps = guide_steps(datasets)
    done = sum(step["done"] for step in steps)
    with st.container(border=True):
        if done == len(steps):
            if not st.session_state.get("guide_celebrated"):
                st.session_state["guide_celebrated"] = True
                st.toast("Getting started complete. You know your way around mfethuls!", icon=":material/celebration:")
            st.markdown(":green[:material/celebration:] **Getting started complete**")
            st.caption("You have been through every step.")
            st.button("Dismiss", icon=":material/close:", on_click=dismiss_guide, width="stretch",
                      help="Hide this box. The checklist stays on the home page.")
            return
        upcoming = next(number for number, step in enumerate(steps, start=1) if not step["done"])
        st.progress(done / len(steps), text=f"Getting started: {done} of {len(steps)}")
        st.caption(f"Next: **{upcoming}. {steps[upcoming - 1]['title']}**")
        with st.popover("Guide", icon=":material/checklist:", width="stretch"):
            _render_steps(steps, compact=True)
            st.caption(steps[upcoming - 1]["hint"])
