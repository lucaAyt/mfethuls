"""Register raw data that the registry does not describe yet (the "Register new data" dialog).

When the app may write the registry (``backend.writes_registry``), the new rows are
appended to the registry file. Otherwise the registry is kept elsewhere (e.g. on
OneDrive) and the dialog offers the rows as a download to add there.
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

import mfethuls.config
from mfethuls.discovery import (
    REGISTRY_COLUMNS,
    NewData,
    discover_unregistered,
    filter_new_data,
    proposed_rows,
    validate_proposed,
)
from mfethuls.experiments import Registry, append_rows
from mfethuls.registry_validator import _load_instrument_config
from mfethuls.settings import get_settings

_SCHEMA_DIR = os.path.join(os.path.dirname(mfethuls.config.__file__), "schemas")
_HELPER_COLUMNS = ["include", "_folder", "_modified"]


def instrument_options() -> List[str]:
    return [entry["name"] for entry in _load_instrument_config()]


def profile_options() -> List[str]:
    """Measurement profiles of the instruments that need one (DMA, rheometer)."""
    profiles: List[str] = []
    for instrument_type in ("dma", "rheometer"):
        with open(os.path.join(_SCHEMA_DIR, f"{instrument_type}.json"), encoding="utf8") as handle:
            profiles.extend(json.load(handle).get("profiles", {}))
    return sorted(set(profiles))


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
    note = f"Showing **{len(shown)}** of {len(items)} new items, newest first."
    if not has_recent and age == "All":
        note += f" Nothing changed in the last {_DEFAULT_AGE}, so all are shown."
    st.caption(note + " Changing the filters clears ticks and edits.")
    return shown, f"{age}|{','.join(sorted(folders))}|{text.strip().casefold()}"


@st.dialog("Register new data", width="large")
def register_dialog(registry_path: str, data_root: str, *, writes_registry: bool, on_saved=None) -> None:
    """Propose registry rows for unregistered raw data, validate them live, then save or download."""

    registry = Registry.load(registry_path)
    _unclaimed_note(data_root)
    items = discover_unregistered(registry, data_root)
    if not items:
        st.success("Everything in the data folder is already in the registry.")
        return

    items, filters_key = _filter_controls(items)
    if not items:
        st.info("No new data matches these filters.")
        return

    folders = [item for item in items if item.layout == "folder" and item.runs and not item.issue]
    split: List[str] = []
    if folders:
        split = st.multiselect(
            "Folders to register as one experiment per file",
            options=[item.key for item in folders],
            default=[item.key for item in folders if item.split_by_default],
            format_func=lambda key: f"{key} ({len(next(i for i in folders if i.key == key).runs)} files)",
            help=(
                "Selected: each file in the folder is its own experiment (runs R001, R002, ...). "
                "Not selected: the whole folder is one experiment, e.g. a titration or time series."
            ),
        )

    proposals = proposed_rows(items, registry, split=set(split))
    if proposals.empty:
        st.info("Nothing can be registered as found; see below.")
    else:
        # Nothing is registered unless ticked: registering is a deliberate choice per row.
        proposals.insert(0, "include", False)
        st.caption("Tick **Register** for the rows to add, and fill in the sample and anything else you know.")
        edited = st.data_editor(
            proposals,
            key=f"register-editor-{filters_key}-{'|'.join(sorted(split))}",
            hide_index=True,
            width="stretch",
            disabled=["raw_data_filename", "_folder", "_modified"],
            column_order=["include", *REGISTRY_COLUMNS, *[c for c in proposals.columns if c not in REGISTRY_COLUMNS and c not in _HELPER_COLUMNS], "_folder", "_modified"],
            column_config={
                "include": st.column_config.CheckboxColumn("Register", width="small"),
                "name": st.column_config.TextColumn("name", required=True, help="Unique experiment name."),
                "instrument_name": st.column_config.SelectboxColumn("instrument_name", options=instrument_options(), required=True),
                "sample_id": st.column_config.TextColumn("sample_id", help="S followed by 3–6 digits, e.g. S001."),
                "run_id": st.column_config.TextColumn("run_id", help="R followed by 3–6 digits, e.g. R001."),
                "measurement_profile": st.column_config.SelectboxColumn(
                    "measurement_profile", options=profile_options(), help="Needed for DMA and rheometer data."
                ),
                "raw_data_filename": st.column_config.TextColumn("raw data", help="File stem or folder name found on disk."),
                "_folder": st.column_config.TextColumn("folder"),
                "_modified": st.column_config.DatetimeColumn("modified", format="YYYY-MM-DD HH:mm"),
            },
        )

        rows = registry_rows(edited)
        results = validate_proposed(registry, rows, data_root)
        if results:
            st.dataframe(status_table(rows, results), hide_index=True, width="stretch")
        else:
            st.caption("No rows ticked yet.")
        ready = bool(results) and not any(result["errors"] for result in results)

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


def _unclaimed_note(data_root: str) -> None:
    """Folders of data no instrument reads, each with a way to add the instrument."""
    from mfethuls.app.instruments import request_dialog

    for folder in unclaimed(data_root):
        text_col, button_col = st.columns([3, 1], vertical_alignment="center")
        text_col.info(f"**{folder.folder_name}** holds {folder.count_label} file(s) that no instrument reads.",
                      icon=":material/help:")
        if button_col.button("Add instrument", key=f"unclaimed-{folder.folder_name}", width="stretch"):
            request_dialog(folder.folder_name)


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
    except Exception as exc:
        st.caption(f"Could not scan the data folder: {exc}")
        return
    if count:
        st.info(f"**{count}** new data item{'s' if count != 1 else ''} found in the data folder.")
    open_col, rescan_col = st.columns([3, 1], vertical_alignment="bottom")
    if open_col.button("Review & register", icon=":material/playlist_add:", disabled=not count, width="stretch"):
        register_dialog(
            registry_path, data_root, writes_registry=backend.writes_registry,
            on_saved=lambda names, ingest: _after_register(backend, registry_path, names, ingest),
        )
    if rescan_col.button("", icon=":material/refresh:", help="Scan the data folder again", width="stretch"):
        _count_new_data.clear()
        st.rerun()


def _after_register(backend, registry_path: str, names: list[str], ingest: bool) -> None:
    """Refresh after rows were added to the registry, and ingest them if asked."""
    from mfethuls.app.welcome import mark_done

    mark_done("register")
    clear_registry_caches()
    message = f"Added {len(names)} experiment{'s' if len(names) != 1 else ''} to the registry."
    if ingest:
        with st.spinner(f"Ingesting {len(names)} experiment(s)…"):
            results = backend.ingest(names, registry_path)
        failed = [name for name, result in results if result.get("status") == "error"]
        message += f" Ingested {len(names) - len(failed)}." + (f" Failed: {', '.join(failed)}." if failed else "")
        backend.clear_caches()
    st.session_state["register_message"] = message
