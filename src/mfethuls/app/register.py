"""Register raw data that the registry does not describe yet (the "Register new data" dialog).

When the app may write the registry (``backend.writes_registry``), the new rows are
appended to the registry file. Otherwise the registry is kept elsewhere (e.g. on
OneDrive) and the dialog offers the rows as a download to add there.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from mfethuls.discovery import (
    REGISTRY_COLUMNS,
    NewData,
    discover_unregistered,
    chosen_rows,
    filter_new_data,
    overlapping_folders,
    sync_folder_ticks,
    tree_rows,
    validate_proposed,
)
from mfethuls.experiments import Registry, append_rows
from mfethuls.registry_validator import _load_instrument_config
from mfethuls.settings import get_settings

_HELPER_COLUMNS = ["include", "_folder", "_modified", "_kind", "_data", "_whole"]
_TREE = "register_tree"


def instrument_options() -> List[str]:
    return [entry["name"] for entry in _load_instrument_config()]


def registry_rows(edited: pd.DataFrame) -> pd.DataFrame:
    """The ticked rows, without the dialog's helper columns, with empty text as missing."""
    rows = edited[edited["include"].fillna(False).astype(bool)] if "include" in edited else edited
    rows = rows.drop(columns=[c for c in _HELPER_COLUMNS if c in rows.columns])
    return rows.replace({"": None}).reset_index(drop=True)


def status_table(rows: pd.DataFrame, results: List[Dict[str, Any]]) -> pd.DataFrame:
    table = []
    for name, result in zip(rows["name"], results):
        problems = [e["message"] for e in result["errors"]] + [w["message"] for w in result["warnings"]]
        icon = "✗" if result["errors"] else ("⚠" if result["warnings"] else "✓")
        table.append({"": icon, "Name": name, "Problems": " · ".join(problems) or "Ready"})
    return pd.DataFrame(table)


def csv_bytes(rows: pd.DataFrame) -> bytes:
    return rows.to_csv(index=False).encode("utf-8")


def xlsx_bytes(rows: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    rows.to_excel(buffer, index=False)
    return buffer.getvalue()


def _not_proposed(items: List[NewData], data_root: str) -> List[str]:
    notes = [item.issue for item in items if item.issue]
    for item in items:
        notes.extend(item.run_issues.values())
    return sorted(set(notes))


# "Modified in the last" choices, in days (None = all).
_AGE_CHOICES = {"7 days": 7, "30 days": 30, "3 months": 91, "All": None}
_DEFAULT_AGE = "30 days"


def _since(choice: str) -> Optional[datetime]:
    days = _AGE_CHOICES[choice]
    return None if days is None else datetime.now() - timedelta(days=days)


def _filter_controls(items: List[NewData]) -> tuple[List[NewData], str]:
    """Age, instrument and name filters above the editor; returns the matching items and a key for them."""

    # Start with recent data, or with everything when nothing is that recent.
    has_recent = bool(filter_new_data(items, modified_since=_since(_DEFAULT_AGE)))
    default_age = _DEFAULT_AGE if has_recent else "All"
    age_col, folder_col, search_col = st.columns([1, 2, 2])
    age = age_col.selectbox("Modified in the last", list(_AGE_CHOICES), index=list(_AGE_CHOICES).index(default_age))
    folders = folder_col.multiselect(
        "Instruments", sorted({item.folder_name for item in items}), placeholder="All instruments"
    )
    text = search_col.text_input("Search", placeholder="File or folder name")

    shown = filter_new_data(items, modified_since=_since(age), folders=set(folders) or None, text=text)
    note = f"Showing **{len(shown)}** of {len(items)} new items."
    if not has_recent and age == "All":
        note += f" Nothing changed in the last {_DEFAULT_AGE}, so all are shown."
    st.caption(note + " Changing the filters clears ticks and edits.")
    return shown, f"{age}|{','.join(sorted(folders))}|{text.strip().casefold()}"


# -- the folder tree being edited --------------------------------------------------
#
# Ticking a folder ticks its files, which the editor cannot do by itself. The table is kept
# in the session (``tree``); the editor shows ``base`` and its edits are applied to ``base``
# again on every change. Only a folder's tick redraws the editor (new key), to show its
# files ticked: ticking a file or typing a sample ID leaves it as it is, so it stays quick.


def _show(state: Dict[str, Any]) -> None:
    state.update(base=state["tree"].copy(), version=state["version"] + 1)


def _tree_state(proposals: pd.DataFrame, filters_key: str) -> Dict[str, Any]:
    """The table being edited; started again when the filters or the data found change."""
    found = proposals["_folder"].astype(str) + "/" + proposals["raw_data_filename"].astype(str)
    signature = f"{filters_key}|{'|'.join(found)}"
    state = st.session_state.get(_TREE)
    if state is None or state["signature"] != signature:
        tree = proposals.copy()
        tree.insert(0, "include", False)  # nothing is registered unless ticked
        state = {"signature": signature, "tree": tree, "version": state["version"] if state else 0}
        _show(state)
        st.session_state[_TREE] = state
    return state


def _edited(editor_key: str) -> None:
    state = st.session_state[_TREE]
    base = state["base"]
    tree = base.copy()
    for position, change in st.session_state[editor_key]["edited_rows"].items():
        for column, value in change.items():
            tree.at[base.index[int(position)], column] = value
    folders = tree["_kind"] == "folder"
    redraw = not tree.loc[folders, "include"].eq(True).equals(base.loc[folders, "include"].eq(True))
    state["tree"] = sync_folder_ticks(base, tree)
    if redraw:
        _show(state)


@st.dialog("Register new data", width="large")
def register_dialog(registry_path: str, data_root: str, *, writes_registry: bool, on_saved=None) -> None:
    """Propose registry rows for unregistered raw data, validate them live, then save or download."""

    registry = Registry.load(registry_path)
    _unclaimed_note(data_root, writes=writes_registry)
    items = discover_unregistered(registry, data_root)
    if not items:
        if unclaimed(data_root):
            st.caption("Once an instrument reads a folder, its files are proposed here.")
        else:
            st.success("Everything in the data folder is already in the registry.")
        return

    items, filters_key = _filter_controls(items)
    if not items:
        st.info("No new data matches these filters.")
        return

    proposals = tree_rows(items, registry, data_root)
    if proposals.empty:
        st.info("Nothing can be registered as found; see below.")
    else:
        state = _tree_state(proposals, filters_key)
        st.markdown("Tick what to register, then fill in the sample and anything else you know.\n"
                    "- A **file** is one experiment.\n"
                    "- Ticking a **📁 folder** ticks all the files under it, each its own experiment "
                    "(runs R001, R002, …); untick the ones you don't want.\n"
                    "- A folder marked **one experiment** is registered whole, all its files together, "
                    "e.g. a titration or a time series.")
        extra = [c for c in proposals.columns if c not in REGISTRY_COLUMNS and c not in _HELPER_COLUMNS]
        editor_key = f"register-editor-{state['version']}"
        st.data_editor(
            state["base"],
            key=editor_key,
            on_change=_edited,
            args=(editor_key,),
            hide_index=True,
            width="stretch",
            disabled=["_data", "_modified"],
            column_order=["include", "_data", *[c for c in REGISTRY_COLUMNS if c != "raw_data_filename"],
                          *extra, "_modified"],
            column_config={
                "include": st.column_config.CheckboxColumn("Register"),
                "_data": st.column_config.TextColumn("data", width="large", help="Found in the data folder."),
                "name": st.column_config.TextColumn("name", required=True, help="Unique experiment name."),
                "instrument_name": st.column_config.SelectboxColumn("instrument_name", options=instrument_options(), required=True),
                "sample_id": st.column_config.TextColumn("sample_id", help="S followed by 3–6 digits, e.g. S001."),
                "run_id": st.column_config.TextColumn("run_id", help="R followed by 3–6 digits, e.g. R001."),
                "_modified": st.column_config.DatetimeColumn("modified", format="YYYY-MM-DD HH:mm"),
            },
        )

        chosen = chosen_rows(state["tree"])
        rows = registry_rows(chosen)
        both = overlapping_folders(chosen)
        for folder in both:
            st.error(f"**{folder}** is ticked as one experiment and file by file: untick the folder or its files.",
                     icon=":material/error:")
        results = validate_proposed(registry, rows, data_root)
        if results:
            st.dataframe(status_table(rows, results), hide_index=True, width="stretch")
        else:
            st.caption("Nothing ticked yet.")
        ready = bool(results) and not both and not any(result["errors"] for result in results)

        if not writes_registry:
            st.info(
                "The registry is kept on OneDrive. Download these rows, add them to the registry there, "
                "then press **Sync from OneDrive**."
            )
            left, right = st.columns(2)
            left.download_button("Download rows (.csv)", data=csv_bytes(rows), file_name="new_registry_rows.csv",
                                 mime="text/csv", disabled=not ready, width="stretch")
            right.download_button("Download rows (.xlsx)", data=xlsx_bytes(rows), file_name="new_registry_rows.xlsx",
                                  disabled=not ready, width="stretch")
        else:
            left, right = st.columns(2)
            save = left.button("Save to registry", disabled=not ready, width="stretch")
            save_and_ingest = right.button("Save & ingest", type="primary", disabled=not ready, width="stretch")
            if save or save_and_ingest:
                try:
                    append_rows(registry_path, rows)
                except (PermissionError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    st.session_state.pop(_TREE, None)
                    if on_saved is not None:
                        on_saved(list(rows["name"]), ingest=save_and_ingest)
                    st.rerun()

    notes = _not_proposed(items, data_root)
    if notes:
        with st.expander(f"Not proposed ({len(notes)})"):
            for note in notes:
                st.caption(note)

    skipped = sorted(f"{item.folder_name}/{path}" for item in items for path in item.ignored)
    if skipped:
        with st.expander(f"Files that will not be read ({len(skipped)})"):
            st.caption("These files sit next to the data but no instrument here reads them (e.g. plots). "
                       "Ingest skips them; they stay where they are.")
            for path in skipped:
                st.caption(path)


@st.cache_data(show_spinner=False, ttl=30)
def unclaimed(data_root: str) -> list:
    """:func:`~mfethuls.discovery.unclaimed_folders`, cached: the dialogs ask on every rerun, and
    walking a large folder on a synced drive is slow. Cleared with the registry caches."""
    from mfethuls.discovery import unclaimed_folders

    return unclaimed_folders(data_root)


def _unclaimed_note(data_root: str, *, writes: bool = True) -> None:
    """Folders of data no instrument reads, each with a way to choose a known instrument or add one."""
    from mfethuls.app.instruments import UNCLAIMED, _link_result, link_folder_controls, request_dialog

    _link_result(UNCLAIMED)
    for folder in unclaimed(data_root):
        with st.container(border=True):
            text_col, button_col = st.columns([3, 1], vertical_alignment="center")
            hint = (f" Its name suggests **{folder.suggested}**: check it below." if folder.suggested else
                    " If mfethuls knows the instrument, choose it below; otherwise add it.")
            text_col.markdown(f"**{folder.folder_name}** holds {folder.count_label} file(s) that no instrument "
                              f"reads yet.{hint}")
            if button_col.button("New instrument", key=f"unclaimed-{folder.folder_name}", width="stretch",
                                 help="Teach mfethuls an instrument it does not know, from one of these files."):
                request_dialog(folder.folder_name)
            link_folder_controls(folder.folder_name, folder.suggested, f"unclaimed-{folder.folder_name}",
                                 writes=writes)


def _modified(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False, ttl=600)
def _registry_frame(path: str, modified: float) -> pd.DataFrame:
    return Registry.load(path).frame


@st.cache_data(show_spinner=False, ttl=60)
def _count_new_data(registry_path: str, data_root: str, modified: float) -> int:
    return sum(1 for item in discover_unregistered(Registry.load(registry_path), data_root) if not item.issue)


def registry_frame(path: str) -> pd.DataFrame:
    """The registry table at ``path``; cached until the file changes."""
    return _registry_frame(path, _modified(path))


def count_new_data(registry_path: str, data_root: str) -> int:
    """How many items under ``data_root`` the registry does not describe yet.

    Cached until the registry changes, and for at most a minute, so new raw files show up.
    """
    return _count_new_data(registry_path, data_root, _modified(registry_path))


def clear_registry_caches() -> None:
    _registry_frame.clear()
    _count_new_data.clear()
    unclaimed.clear()


def new_data_prompt(backend, registry_path: str) -> None:
    """Sidebar note about unregistered raw data, opening the "Register new data" dialog."""
    data_root = get_settings().data_root
    if not data_root or not registry_path or not os.path.exists(registry_path):
        return
    message = st.session_state.pop("register_message", None)
    if message:
        st.success(message)
    try:
        count = count_new_data(registry_path, data_root)
        folders = [folder.folder_name for folder in unclaimed(data_root)]
    except Exception as exc:
        st.caption(f"Could not scan the data folder: {exc}")
        return
    if count:
        st.info(f"**{count}** new data item{'s' if count != 1 else ''} found in the data folder.")
    if folders:
        # Without this, data in a folder named unlike its instrument ("DMA data") would never show up.
        st.info(f"No instrument reads the folder{'s' if len(folders) != 1 else ''} "
                f"{', '.join(f'**{name}**' for name in folders)} yet: open **Review & register** to choose one.")
    # The next step when there is new data, so it stands out then.
    if st.button("Review & register", icon=":material/playlist_add:", disabled=not (count or folders),
                 type="primary" if count or folders else "secondary", width="stretch"):
        register_dialog(
            registry_path, data_root, writes_registry=backend.writes_registry,
            on_saved=lambda names, ingest: _after_register(backend, registry_path, names, ingest),
        )
    if st.button("Scan the data folder again", icon=":material/refresh:", type="tertiary", width="stretch",
                 help="Look for raw files added since the app started"):
        _count_new_data.clear()
        unclaimed.clear()
        st.rerun()


def _after_register(backend, registry_path: str, names: list[str], ingest: bool) -> None:
    """Refresh after rows were added to the registry, and ingest them if asked."""
    from mfethuls.app.welcome import mark_done

    mark_done("register")
    clear_registry_caches()
    message = f"Added {len(names)} experiment{'s' if len(names) != 1 else ''} to the registry."
    if ingest:
        with st.spinner(f"Ingesting {len(names)} experiment(s)…"):
            results = backend.ingest(names, registry_path, refresh=True)
        failed = [name for name, result in results if result.get("status") == "error"]
        message += f" Ingested {len(names) - len(failed)}." + (f" Failed: {', '.join(failed)}." if failed else "")
        backend.clear_caches()
        if not failed:
            # Done: the data is next. Ingest closes and Datasets opens; the result is a toast.
            st.session_state["ingest_message"] = message
            st.session_state["just_ingested"] = True
            return
    st.session_state["register_message"] = message
