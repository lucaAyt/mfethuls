"""Instruments in the app: the list in ⚙ Settings and the "Add instrument" dialog.

An experimentalist adds an instrument from one of its files. By default a chatbot
drafts the instrument definition: the dialog gives a ready prompt (the format's
rules, mfethuls' own reading of the file and its first lines) and takes the answer
back. Alternatively mfethuls fills in its own guesses
(:mod:`mfethuls.instruments.detect`). Either way the result lands in the same plain
form (the instrument, how the file is read, what each column is), checked against
the file with a table, a plot and warnings, before it is saved next to the data
(``.mfethuls/instruments``), where everyone using that data folder gets it.

When the app may not write to the data folder (``backend.writes_definitions``
false, e.g. a team server whose data folder is synced from OneDrive), the
definition and its sample file are offered as downloads instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from mfethuls.instruments.configured import (
    builtin_names,
    definition_statuses,
    definition_text,
    instrument_entries,
    lab_dir,
    link_folder,
    prepare_definition,
    remove_definition,
    save_definition,
)
from mfethuls.instruments.definition import (
    COLUMN_OPS,
    DATA_ENDS,
    DELIMITERS,
    DERIVED_OPS,
    TIME_UNITS,
    VALUE_TYPES,
    WORKBOOK_EXTENSIONS,
    DefinitionError,
    definition_json,
    parse_definition,
)
from mfethuls.instruments.detect import ENCODINGS, _canonical_unit, detect, guess_column
from mfethuls.instruments.units import QUANTITIES, conversion, range_warnings
from mfethuls.schema_normalization import missing_required
from mfethuls.settings import get_settings

# Session-state key that asks the page to open the dialog on its next run
# (a dialog cannot open another one, e.g. from ⚙ Settings).
OPEN_REQUEST = "add_instrument_request"
_MESSAGE = "add_instrument_message"
_REMOVING = "remove_instrument"
# What the last folder link did, shown where it was made: (key, message, ok).
LINKED = "link_folder_result"

CHATBOT = "Ask a chatbot"
MANUAL = "Fill in myself"
_ID_COLUMNS = {"experiment_id", "sample_id", "run_id", "name", "source_file"}
_NEW_TYPE = "(a new type)"
_NEW_FOLDER = "(a new folder)"
_IDENTITY_KEYS = ("'name'", "'type'", "'model'", "'folder_name'", "'data_layout'", "'spec_version'")


# -- helpers without Streamlit (tested directly) -------------------------------

def quantity_options(extra: Tuple[str, ...] = ()) -> List[str]:
    return [""] + sorted(set(QUANTITIES) | {e for e in extra if e})


def unit_options(extra: Tuple[str, ...] = ()) -> List[str]:
    units = {unit for q in QUANTITIES.values() for unit in q.unit_names() if unit} | {e for e in extra if e}
    return [""] + sorted(units, key=str.casefold)


def _sources(mapping: Dict[str, Any]) -> List[str]:
    source = mapping.get("source")
    return [source] if isinstance(source, str) else [s for s in (source or []) if isinstance(s, str)]


def _matching(column: str, seed_columns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The seed mapping that names ``column`` (exactly, else ignoring case and spaces)."""
    for loose in (False, True):
        for mapping in seed_columns:
            if not isinstance(mapping, dict):
                continue
            for source in _sources(mapping):
                if source == column or (loose and source.strip().casefold() == column.strip().casefold()):
                    return mapping
    return None


def mapping_rows(file_columns: List[str], seed_columns: Optional[List[Dict[str, Any]]] = None) -> pd.DataFrame:
    """One row per file column: its quantity and unit from ``seed_columns``, else mfethuls' guess.

    With seed columns (a pasted definition), columns the seed does not map stay
    empty; without, every column gets mfethuls' guess.
    """
    rows = []
    taken: set = set()
    for column in file_columns:
        if seed_columns is not None:
            mapping = _matching(column, seed_columns) or {}
            quantity = str(mapping.get("quantity") or "")
            unit = str(mapping.get("unit") or "")
            if quantity in QUANTITIES and unit:
                unit = _canonical_unit(quantity, unit) or unit
            rows.append({"source": column, "quantity": quantity, "unit": unit,
                         "name": str(mapping.get("column") or "")})
            continue
        guess = guess_column(column, taken)
        if guess.quantity:
            taken.add(guess.quantity)
        rows.append({"source": column, "quantity": guess.quantity or "", "unit": guess.unit or "", "name": ""})
    return pd.DataFrame(rows, columns=["source", "quantity", "unit", "name"])


def columns_from_rows(frame: pd.DataFrame, seed_columns: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The definition's ``columns`` from the edited table.

    A row with a quantity is a quantity mapping; a row with only a name is a plain
    column. Alternative source names of a seed mapping are kept, and seed mappings
    for columns not in this file are kept unchanged (other exports may have them).
    """
    seed_columns = [m for m in (seed_columns or []) if isinstance(m, dict)]
    out: List[Dict[str, Any]] = []
    used: List[int] = []
    for row in frame.to_dict("records"):
        source = str(row["source"])
        seed = _matching(source, seed_columns)
        if seed is not None:
            used.append(id(seed))
        sources: Any = _sources(seed) if seed is not None and len(_sources(seed)) > 1 else source
        quantity = str(row.get("quantity") or "").strip()
        name = str(row.get("name") or "").strip()
        if quantity:
            item: Dict[str, Any] = {"source": sources, "quantity": quantity}
            unit = row.get("unit")
            if isinstance(unit, str) and unit.strip():
                item["unit"] = unit.strip()
            out.append(item)
        elif name:
            out.append({"source": sources, "column": name})
    out += [m for m in seed_columns if id(m) not in used]
    return out


def _conversion_text(factor: float, offset: float) -> str:
    if factor == 1.0 and offset == 0.0:
        return "unchanged"
    parts = [f"× {factor:.6g}"] if factor != 1.0 else []
    if offset:
        parts.append(f"{'+' if offset > 0 else '−'} {abs(offset):.6g}")
    return " ".join(parts)


def mapping_summary(columns: List[Dict[str, Any]], file_columns: List[str], instrument_type: str) -> pd.DataFrame:
    """What happens to each file column: kept as it is, or stored as a quantity (and how converted)."""
    rows = []
    for column in file_columns:
        mapping = _matching(column, columns)
        if mapping is None:
            rows.append({"column in the file": column, "is": "—", "stored as": column, "values": "kept as they are"})
        elif mapping.get("column"):
            rows.append({"column in the file": column, "is": "—", "stored as": mapping["column"],
                         "values": "kept as they are"})
        elif mapping.get("quantity") in QUANTITIES:
            quantity = QUANTITIES[mapping["quantity"]]
            stored, unit = quantity.target(instrument_type, mapping.get("unit"))
            try:
                text = _conversion_text(*conversion(quantity, mapping.get("unit"), instrument_type))
            except ValueError as exc:
                text = str(exc)
            source_unit = mapping.get("unit") or unit
            rows.append({"column in the file": column, "is": quantity.label, "stored as": stored,
                         "values": f"{source_unit or '(no unit)'} → {unit or '(no unit)'}: {text}"})
    return pd.DataFrame(rows, columns=["column in the file", "is", "stored as", "values"])


def derived_rows(seed: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for step in seed.get("derived") or []:
        if isinstance(step, dict):
            number = step.get("factor", step.get("value"))
            rows.append({"op": str(step.get("op", "")), "column": str(step.get("column", "")),
                         "into": str(step.get("into", "")),
                         "number": float(number) if isinstance(number, (int, float)) else None,
                         "amount": step.get("amount", step.get("by")), "unit": step.get("unit")})
    return pd.DataFrame(rows, columns=["op", "column", "into", "number", "amount", "unit"]).astype(
        {"op": "object", "column": "object", "into": "object", "number": "float64", "amount": "object",
         "unit": "object"})


def derived_from_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    out = []
    for row in frame.to_dict("records"):
        op = str(row.get("op") or "").strip()
        if not op or op == "None":
            continue
        step: Dict[str, Any] = {"op": op, "column": str(row.get("column") or "").strip(),
                                "into": str(row.get("into") or "").strip()}
        number = row.get("number")
        if op in ("scale", "offset") and number is not None and not pd.isna(number):
            step["factor" if op == "scale" else "value"] = float(number)
        if op == "add_time":
            step["amount"] = _cell(row.get("amount"))
            step["unit"] = _cell(row.get("unit")) or "ms"
        if op in COLUMN_OPS:
            step["by"] = _cell(row.get("amount"))
        out.append(step)
    return out


def _cell(value: Any) -> str:
    """An editor cell as text ('' when empty)."""
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()


# Where a value in "Values from the file name and header" comes from.
_VALUE_SOURCES = {"from_file_name": "file name", "from_sheet_name": "sheet name", "from_header": "header"}
_CAPTURED_COLUMNS = ["from", "column", "pattern", "type", "timezone", "values"]


def values_text(values: Dict[str, str]) -> str:
    """A ``values`` table as one editable line: ``ri=^RID; uv=^(VWD|DAD)``."""
    return "; ".join(f"{stored}={pattern}" for stored, pattern in values.items())


def values_from_text(text: str) -> Dict[str, str]:
    """The inverse of :func:`values_text`."""
    out: Dict[str, str] = {}
    for part in text.split(";"):
        stored, _, pattern = part.partition("=")
        if stored.strip():
            out[stored.strip()] = pattern.strip()
    return out


def captured_rows(seed: Dict[str, Any]) -> pd.DataFrame:
    """``from_file_name``, ``from_sheet_name`` and ``from_header`` entries as rows of one table."""
    rows = []
    for key, source in _VALUE_SOURCES.items():
        for item in seed.get(key) or []:
            if isinstance(item, dict):
                values = item.get("values") if isinstance(item.get("values"), dict) else {}
                rows.append({"from": source, "column": str(item.get("column") or ""),
                             "pattern": str(item.get("pattern") or ""), "type": str(item.get("type") or "text"),
                             "timezone": str(item.get("timezone") or ""), "values": values_text(values)})
    return pd.DataFrame(rows, columns=_CAPTURED_COLUMNS).astype(object)


def captured_from_rows(frame: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    """The table back as ``{"from_file_name": [...], "from_sheet_name": [...], "from_header": [...]}``
    (empty lists left out)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    keys = {source: key for key, source in _VALUE_SOURCES.items()}
    for row in frame.to_dict("records"):
        column, pattern = _cell(row.get("column")), _cell(row.get("pattern"))
        if not column and not pattern:
            continue
        item: Dict[str, Any] = {"column": column, "pattern": pattern}
        if _cell(row.get("type")) not in ("", "text"):
            item["type"] = _cell(row.get("type"))
        if _cell(row.get("timezone")):
            item["timezone"] = _cell(row.get("timezone"))
        if _cell(row.get("values")):
            item["values"] = values_from_text(_cell(row.get("values")))
        out.setdefault(keys.get(_cell(row.get("from")), "from_file_name"), []).append(item)
    return out


def route_problems(problems: List[str]) -> Dict[str, List[str]]:
    """Problems by the form section they belong to: instrument, file, columns, extras, other."""
    routed: Dict[str, List[str]] = {"instrument": [], "file": [], "columns": [], "extras": [], "other": []}
    for problem in problems:
        head = re.sub(r"^format \d+: ", "", problem).split(":")[0]
        if problem.startswith(("derived", "'plot'", "from_file_name", "from_sheet_name", "from_header", "'from_")) \
                or "filled twice" in problem:
            routed["extras"].append(problem)
        elif "'file" in problem or "file:" in problem:
            routed["file"].append(problem)
        elif "column" in head or problem.startswith("'columns'"):
            routed["columns"].append(problem)
        elif problem.startswith(_IDENTITY_KEYS):
            routed["instrument"].append(problem)
        else:
            routed["other"].append(problem)
    return routed


def layouts(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The seed's file layouts as ``{label, file, columns}`` (one when it has no ``formats``)."""
    formats = seed.get("formats")
    if isinstance(formats, list) and formats:
        return [{"label": str(f.get("label") or f"layout {i + 1}"),
                 "file": f.get("file") if isinstance(f.get("file"), dict) else {},
                 "columns": f.get("columns") if isinstance(f.get("columns"), list) else []}
                for i, f in enumerate(formats) if isinstance(f, dict)]
    return [{"label": "", "file": seed.get("file") if isinstance(seed.get("file"), dict) else {},
             "columns": seed.get("columns") if isinstance(seed.get("columns"), list) else []}]


def layout_for(seed_layouts: List[Dict[str, Any]], sample: Path) -> int:
    """The layout whose file endings (and ``contains`` text) match ``sample``."""
    suffix = sample.suffix.casefold()
    try:
        with sample.open(encoding="latin-1") as handle:
            head = "".join(line for _, line in zip(range(50), handle))
    except OSError:
        head = ""
    for i, layout in enumerate(seed_layouts):
        extensions = layout["file"].get("extensions") or []
        extensions = [extensions] if isinstance(extensions, str) else extensions
        endings = {str(e).casefold() if str(e).startswith(".") else f".{str(e).casefold()}" for e in extensions}
        if suffix in endings and (not layout["file"].get("contains") or layout["file"]["contains"] in head):
            return i
    return 0


def seed_from_detection(detection, folder: Optional[str] = None) -> Dict[str, Any]:
    return detection.definition(name="", type=detection.type_guess or "", model="", folder_name=folder or "",
                                data_layout="file")


def known_types() -> List[str]:
    from mfethuls.schema_normalization import _get_schema_file_path

    folder = Path(_get_schema_file_path("x")).parent
    return sorted({p.stem for p in folder.glob("*.json")} | {e["type"] for e in instrument_entries()})


def required_columns(instrument_type: str) -> List[Any]:
    """The type's required columns; an entry that is a list means "one of these"."""
    from mfethuls.schema_normalization import _load_instrument_schema

    return list(_load_instrument_schema(instrument_type).get("required_columns", []))


def clash(data: Dict[str, Any]) -> Optional[str]:
    """Why ``data`` cannot be added next to the current instruments, or None."""
    name = str(data.get("name", "")).casefold()
    for entry in instrument_entries():
        if entry["name"] != name and (entry["type"], entry["model"]) == (data.get("type"), data.get("model")):
            return (f"The instrument {entry['name']!r} already has type {entry['type']!r} and model "
                    f"{entry['model']!r}. Give this one another model, e.g. the instrument's make or room.")
    return None


def usage(name: str, registry_frame: Optional[pd.DataFrame], datasets: List[Dict[str, Any]]) -> Tuple[int, int]:
    """(registry rows, ingested datasets) that use the instrument ``name``."""
    rows = 0
    if registry_frame is not None and "instrument_name" in registry_frame:
        rows = int((registry_frame["instrument_name"].astype(str).str.strip().str.casefold() == name).sum())
    ingested = sum(1 for d in datasets if str(d.get("instrument_name", "")).casefold() == name)
    return rows, ingested


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf8")).hexdigest()[:10]


# -- Streamlit: opening the dialog, the Settings section ------------------------

def request_dialog(folder: Optional[str] = None, *, edit: Optional[str] = None) -> None:
    """Open the "Add instrument" dialog on the next run (e.g. from inside another dialog), or with
    ``edit`` (a lab definition's path) the "Edit instrument" dialog."""
    st.session_state[OPEN_REQUEST] = {"folder": folder, "edit": edit}
    st.rerun()


def open_requested_dialog(backend) -> None:
    """Called by the page each run: opens the dialog when it was asked for."""
    message = st.session_state.pop(_MESSAGE, None)
    if message:
        st.toast(message, icon=":material/check_circle:")
    request = st.session_state.pop(OPEN_REQUEST, None)
    if request is not None and request.get("edit"):
        edit_instrument_dialog(backend, request["edit"])
    elif request is not None:
        add_instrument_dialog(backend, folder=request.get("folder"))


def _read_by(entry: Dict[str, Any]) -> str:
    from mfethuls.instruments.definition import BUILTIN_DIR

    source = entry.get("definition")
    if source is None:
        return "built-in code"
    # Built-in definitions are loaded from their files too: the path tells them apart.
    builtin = source == "built-in" or Path(source).resolve().parent == BUILTIN_DIR.resolve()
    return "built-in definition" if builtin else "lab definition"


def render_instruments_section(backend, registry_path: str = "") -> None:
    """⚙ Settings → Instruments: what mfethuls can read; add or remove the lab's instruments."""
    st.caption("The instruments mfethuls can read. Add one from a file it exports. The lab's instruments are "
               "saved in the data folder (`.mfethuls/instruments`), so everyone using it gets them.")
    entries = sorted(instrument_entries(), key=lambda e: e["name"])
    st.dataframe(pd.DataFrame([{"instrument": e["name"], "type": e["type"], "model": e["model"],
                                "folder": _folder_text(e), "read by": _read_by(e)} for e in entries]),
                 hide_index=True, width="stretch")
    statuses = definition_statuses()
    for status in statuses:
        name = Path(status.source).name
        for problem in status.problems:
            st.error(f"`{name}` is not used: {_plain(problem)}")
        for warning in status.warnings:
            st.warning(f"`{name}`: {_plain(warning)}")

    data_root = get_settings().data_root
    if st.button("Add instrument", icon=":material/add_circle:", width="stretch", type="primary",
                 disabled=not data_root, help=None if data_root else "Choose the data folder first."):
        request_dialog()

    if data_root:
        st.markdown("**Change an instrument's folder**")
        change_folder_controls(backend, registry_path)

    if statuses:
        st.markdown("**The lab's instruments**")
        for status in statuses:
            _remove_row(backend, status, registry_path)


def _folder_text(entry: Dict[str, Any]) -> str:
    default = entry.get("default_folder")
    return f"{entry['folder_name']} (instead of {default})" if default else entry["folder_name"]


def group_label(folder: str, entries: List[Dict[str, Any]]) -> str:
    """``DSC (dsc_default, dsc_mettler_toledo_v0, +2)``: an instrument folder and who reads it."""
    names = [e["name"] for e in entries]
    shown = ", ".join(names[:2]) + (f", +{len(names) - 2}" if len(names) > 2 else "")
    return f"{folder} ({shown})"


def _link(names: List[str], folder: str, key: str) -> None:
    """Button callback: link the instruments to ``folder`` and say how it went."""
    from mfethuls.app.register import clear_registry_caches

    try:
        link_folder(names, folder)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        st.session_state[LINKED] = (key, _plain(exc), False)
        return
    clear_registry_caches()
    st.session_state[LINKED] = (key, f"{_plain(', '.join(names))} now read{'s' if len(names) == 1 else ''} the "
                                     f"folder **{_plain(folder)}**.", True)


def _link_result(key: str) -> None:
    """The message of a folder link made by the controls with ``key`` (Markdown, already escaped)."""
    result = st.session_state.get(LINKED)
    if result and result[0] == key:
        st.session_state.pop(LINKED)
        (st.success if result[2] else st.error)(result[1])


UNCLAIMED = "unclaimed"


def link_folder_controls(folder: str, suggested: Optional[str], key: str, *, writes: bool) -> None:
    """For a folder no instrument reads: choose the known instrument whose data it holds.

    The outcome is shown by ``_link_result(UNCLAIMED)``: once linked, the folder is no longer listed.
    """
    from mfethuls.discovery import instrument_groups

    groups = instrument_groups()
    options = list(groups)
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    chosen = left.selectbox(
        f"Instrument for **{_plain(folder)}**", options, key=f"{key}-group",
        index=options.index(suggested) if suggested in options else None,
        placeholder="Choose the instrument whose files these are", format_func=lambda f: group_label(f, groups[f]),
        help="mfethuls then reads this folder for that instrument, instead of its usual folder.")
    right.button("Use this folder", key=f"{key}-link", width="stretch", disabled=chosen is None or not writes,
                 help=None if writes else "This app does not change the data folder.",
                 on_click=_link, args=([e["name"] for e in groups.get(chosen, [])], folder, UNCLAIMED))


def change_folder_controls(backend, registry_path: str = "") -> None:
    """⚙ Settings → Instruments: point an instrument (and the others sharing its folder) at another folder."""
    from mfethuls.discovery import instrument_folders, instrument_groups

    key = "change-folder"
    _link_result(key)
    groups = instrument_groups()
    c1, c2 = st.columns(2)
    current = c1.selectbox("Instrument", list(groups), key=f"{key}-group", format_func=lambda f: group_label(f, groups[f]))
    names = [e["name"] for e in groups[current]]
    folders = [entry.name for entry in instrument_folders()]
    options = folders + [_NEW_FOLDER]
    target = c2.selectbox("Reads the folder", options, key=f"{key}-{current}",
                          index=options.index(current) if current in options else len(options) - 1)
    if target == _NEW_FOLDER:
        target = c2.text_input("New folder name", value=current, key=f"{key}-{current}-new")
    target = (target or "").strip()
    if target and target != current and target not in folders:
        st.caption(f"There is no folder **{_plain(target)}** in the data folder yet: create it and put the "
                   "instrument's files in it.")
    if registry_path and os.path.exists(registry_path) and target != current:
        from mfethuls.app.register import registry_frame

        try:
            frame = registry_frame(registry_path)
            rows = sum(usage(name, frame, [])[0] for name in names)
        except Exception:  # noqa: BLE001 - the count is a courtesy
            rows = 0
        if rows:
            st.caption(f"{rows} registry row(s) use {'these instruments' if len(names) > 1 else names[0]}: "
                       f"their raw data is then looked for in **{_plain(target)}**.")
    st.button("Change folder", key=f"{key}-apply", width="stretch",
              disabled=not target or target == current or not backend.writes_definitions,
              help=None if backend.writes_definitions else "This app does not change the data folder.",
              on_click=_link, args=(names, target, key))


def _set_removing(source: Optional[str]) -> None:
    if source is None:
        st.session_state.pop(_REMOVING, None)
    else:
        st.session_state[_REMOVING] = source


def _remove_row(backend, status, registry_path: str) -> None:
    path = Path(status.source)
    label = status.name or path.stem
    left, edit, right = st.columns([3, 1, 1], vertical_alignment="center")
    left.markdown(f"`{label}` · {_plain(path.name)}" +("" if status.active else " *(not used)*"))
    if st.session_state.get(_REMOVING) != status.source:
        if edit.button("Edit", key=f"edit-{path.name}", icon=":material/edit:", width="stretch",
                       help="Change how its files are read: header, columns, values. Checked before saving."):
            request_dialog(edit=status.source)
        right.button("Remove", key=f"remove-{path.name}", icon=":material/delete:", width="stretch",
                     on_click=_set_removing, args=(status.source,))
        return

    frame = None
    if registry_path and os.path.exists(registry_path):
        try:
            from mfethuls.app.register import registry_frame

            frame = registry_frame(registry_path)
        except Exception:  # noqa: BLE001 - the counts are a courtesy
            frame = None
    try:
        datasets = backend.list_datasets()
    except Exception:  # noqa: BLE001
        datasets = []
    rows, ingested = usage(label, frame, datasets)
    lines = [f"Used by **{rows}** registry row(s) and **{ingested}** ingested experiment(s). Their data stays; "
             "the registry rows can't be ingested again until an instrument reads them."]
    if label in builtin_names():
        lines.append(f"mfethuls' built-in `{label}` reads its files again afterwards; **Clean up** then offers "
                     "to read them again.")
    lines.append("The files are moved to `.mfethuls/instruments/removed/`, not deleted: move them back to undo.")
    st.warning("  \n".join(lines), icon=":material/warning:")
    if not backend.writes_definitions:
        st.info(f"This app does not change the data folder. On OneDrive, move `{path.name}` and its sample file "
                "out of the data folder's `.mfethuls/instruments` folder, then sync.")
        st.button("Close", key=f"remove-close-{path.name}", on_click=_set_removing, args=(None,))
        return
    confirm, cancel = st.columns(2)
    if confirm.button(f"Remove {label}", key=f"remove-yes-{path.name}", type="primary", width="stretch"):
        try:
            remove_definition(path)
        except Exception as exc:  # noqa: BLE001
            st.error(_plain(exc))
            return
        from mfethuls.app.register import clear_registry_caches

        clear_registry_caches()
        st.session_state.pop(_REMOVING, None)
        st.session_state["reconcile_message"] = f"Removed the instrument {label}."
        st.rerun()
    cancel.button("Cancel", key=f"remove-no-{path.name}", width="stretch", on_click=_set_removing, args=(None,))


# -- Streamlit: the dialog --------------------------------------------------------

def _stats(folder: Path, files: List[str]) -> List[Tuple[str, int, float]]:
    stats = []
    for name in files:
        try:
            stat = (folder / name).stat()
        except OSError:
            continue
        stats.append((name, stat.st_size, stat.st_mtime))
    return stats


def _ending(name: str) -> str:
    return Path(name).suffix.casefold()


def build_file(folder: Path, files: List[str]) -> Optional[str]:
    """The file to build the definition from: the largest of the folder's most common file type
    (so a plot or a note next to the data is not picked)."""
    stats = _stats(folder, files)
    if not stats:
        return None
    counts = Counter(_ending(name) for name, *_ in stats)
    common = max(counts, key=lambda ending: (counts[ending], ending))
    return max((s for s in stats if _ending(s[0]) == common), key=lambda s: (s[1], s[0]))[0]


def files_to_check(folder: Path, files: List[str], chosen: str, count: int = 6) -> List[str]:
    """Other files of ``chosen``'s type to check the definition against: the largest, the newest,
    then others spread over the folder in name order."""
    stats = _stats(folder, [f for f in files if f != chosen and _ending(f) == _ending(chosen)])
    picks: List[str] = []
    for key in (lambda s: s[1], lambda s: s[2]):
        if stats:
            name = max(stats, key=key)[0]
            if name not in picks:
                picks.append(name)
    rest = sorted(name for name, *_ in stats if name not in picks)
    wanted = max(count - len(picks), 0)
    if rest and wanted:
        step = len(rest) / min(wanted, len(rest))
        picks.extend(rest[int(i * step)] for i in range(min(wanted, len(rest))))
    return picks[:count]


def _sample_picker(folder: Optional[str], key: str) -> Tuple[Optional[Path], List[Path]]:
    """The file to build the definition from, and other files of its type to check it against.

    The files come from a folder in the data folder: the instrument needs one anyway, and
    its other files show whether the definition reads them all.
    """
    from mfethuls.app.register import unclaimed
    from mfethuls.discovery import folder_files, instrument_folders

    data_root = get_settings().data_root
    st.markdown("**1. The folder with the instrument's files**")
    entries = instrument_folders(data_root)
    if not entries:
        st.info("Put a few files exported by the instrument in a folder in your data folder (e.g. `TGA`), "
                "then come back here.", icon=":material/create_new_folder:")
        return None, []
    new = [f.folder_name for f in unclaimed(data_root)]
    names = new + [e.name for e in entries if e.name not in new]
    left, right = st.columns([1, 2])
    chosen = left.selectbox("Folder", names, index=names.index(folder) if folder in names else 0,
                            key=f"{key}-folder",
                            format_func=lambda n: f"{n} (no instrument reads it yet)" if n in new else n,
                            help="The folder in your data folder that holds this instrument's files.")
    base = Path(data_root) / chosen
    files, _, _ = folder_files(str(base))
    if not files:
        right.info("This folder is empty: put a few files from the instrument in it.", icon=":material/folder:")
        return None, []
    default = build_file(base, files)
    file = right.selectbox("Build from", files, index=files.index(default) if default in files else 0,
                           key=f"{key}-file-{chosen}",
                           help="To start with, the largest file of the type the folder holds most of.")
    others = files_to_check(base, files, file)
    if others:
        st.caption(f"mfethuls also checks that it reads {len(others)} other `{_ending(file) or 'no ending'}` "
                   f"file{'s' if len(others) != 1 else ''} in this folder.")
    else:
        st.caption("Put a few more files from the instrument in this folder: mfethuls then checks that it "
                   "reads them all.")
    return base / file, [base / name for name in others]


def _show(slot, problems: List[str]) -> None:
    for problem in problems:
        slot.warning(_plain(problem), icon=":material/edit_note:")


# Characters Streamlit's Markdown gives a meaning (links, images, formatting, LaTeX).
_MARKDOWN = re.compile(r"([\\`*_\[\]()<>!#|~$])")


def _plain(text: Any) -> str:
    """``text`` as it is, for Streamlit's Markdown.

    Messages quote definitions and files, which come from chatbots and other people:
    a link or an image in them (which the browser would load) is shown as text.
    """
    return _MARKDOWN.sub(r"\\\1", str(text))


def _identity_section(seed: Dict[str, Any], key: str, sample: Path, folder: Optional[str], name: str
                      ) -> Dict[str, Any]:
    from mfethuls.discovery import instrument_folders

    data_root = get_settings().data_root
    folders = [entry.name for entry in instrument_folders(data_root)]
    in_data = bool(data_root) and sample.resolve().is_relative_to(Path(data_root).resolve())
    default_folder = str(seed.get("folder_name") or folder or (sample.parent.name if in_data else ""))

    c1, c2 = st.columns(2)
    options = folders + [_NEW_FOLDER]
    chosen = c1.selectbox("Its data folder", options, key=f"{key}-folder-choice",
                          index=options.index(default_folder) if default_folder in folders else len(options) - 1,
                          help="The folder in the data folder where this instrument's files are kept.")
    if chosen == _NEW_FOLDER:
        chosen = c1.text_input("New folder name", value=default_folder, key=f"{key}-folder-new")
    if not (chosen or "").strip():
        st.warning("Choose the folder that holds this instrument's files, so mfethuls finds them. "
                   "It can be changed later under ⚙ Settings → Instruments.", icon=":material/folder:")
    elif chosen.strip() not in folders:
        st.info(f"There is no folder **{_plain(chosen.strip())}** in the data folder yet: create it and put "
                "the instrument's files in it.", icon=":material/folder:")

    c1, c2, c3 = st.columns(3)
    types = known_types() + [_NEW_TYPE]
    seed_type = str(seed.get("type") or "").casefold()
    type_ = c1.selectbox("Measurement type", types, key=f"{key}-type",
                         index=types.index(seed_type) if seed_type in types else len(types) - 1,
                         help="A known type gets mfethuls' plots and checks for it.")
    if type_ == _NEW_TYPE:
        type_ = c1.text_input("New type", value=seed_type, key=f"{key}-type-new", placeholder="e.g. photometry")
    model = c2.text_input("Model", value=str(seed.get("model") or ""), key=f"{key}-model",
                          placeholder="e.g. netzsch_tg209",
                          help="Make, model or software version; tells it apart from other instruments of this type.")
    choices = ["file", "folder"]
    layout = c3.selectbox("One experiment is", choices, key=f"{key}-layout",
                          index=choices.index(seed.get("data_layout")) if seed.get("data_layout") in choices else 0,
                          format_func=lambda v: "one file" if v == "file" else "one folder of files")
    name_choices = ["file", "folder", "sheet"]
    name_from = st.selectbox("Each file's curve is named after", name_choices, key=f"{key}-name-from",
                             index=name_choices.index(seed["name_from"]) if seed.get("name_from") in name_choices else 0,
                             format_func=lambda v: {"file": "the file", "folder": "its folder",
                                                    "sheet": "its sheet (workbooks with one test per sheet)"}[v])
    description = st.text_input("Notes (optional)", value=str(seed.get("description") or ""), key=f"{key}-notes",
                                placeholder="e.g. Netzsch TG 209 F1 in room 2.14, Proteus 8 text export")
    identity = {"spec_version": 1, "name": name.strip().casefold(), "type": (type_ or "").strip().casefold(),
                "model": model.strip(), "folder_name": (chosen or "").strip(), "data_layout": layout}
    if name_from != "file":
        identity["name_from"] = name_from
    if description.strip():
        identity["description"] = description.strip()
    return identity


def _choice(options: List[str], value: Any, fallback: str) -> Tuple[List[str], int]:
    """``options`` (plus ``value`` when it is not one of them) and the index of ``value``."""
    value = fallback if value in (None, "") else value
    options = options + ([value] if value not in options else [])
    return options, options.index(value)


def _reading_section(seed_file: Dict[str, Any], key: str, sample: Path) -> Dict[str, Any]:
    """The ``file`` settings, starting from the seed, in plain words."""
    header = seed_file.get("header") if isinstance(seed_file.get("header"), dict) else {}
    extensions = seed_file.get("extensions") or [sample.suffix.casefold() or ".txt"]
    extensions = [extensions] if isinstance(extensions, str) else list(extensions)
    book = sample.suffix.casefold() in WORKBOOK_EXTENSIONS
    c1, c2, c3 = st.columns(3)
    endings = c1.text_input("File endings", ", ".join(map(str, extensions)), key=f"{key}-ext",
                            help="Separate several with commas, e.g. .txt, .csv")
    if book:
        # A workbook holds cells, not text: no encoding, separator or decimal mark to choose.
        sheet_seed = seed_file.get("sheet")
        sheet = c2.text_input("Sheet with the table (optional)", "" if sheet_seed is None else str(sheet_seed),
                              key=f"{key}-sheet",
                              help="Its name or number (1 = first, -1 = last). Empty: the first sheet with "
                                   "the header text below. Use a number when sheets are named after the sample.")
        encoding = delimiter = decimal = None
        c1, c2, c3 = st.columns(3)
    else:
        sheet = ""
        options, index = _choice(["auto"] + [e for e in ENCODINGS if e != "utf-8-sig"],
                                 seed_file.get("encoding"), "utf-8")
        encoding = c2.selectbox("Text encoding", options, index=index, key=f"{key}-enc",
                                help="auto: UTF-8, else Windows cp1252 (a safe choice); utf-8 for most files; "
                                     "cp1252 for many Windows instrument programs (°, µ).")
        options, index = _choice(list(DELIMITERS), seed_file.get("delimiter"), "comma")
        delimiter = c3.selectbox("Columns separated by", options, index=index, key=f"{key}-delim",
                                 format_func=lambda v: {"whitespace": "spaces / tabs"}.get(v, v))
        c1, c2, c3 = st.columns(3)
        options, index = _choice([".", ","], seed_file.get("decimal"), ".")
        decimal = c1.selectbox("Decimal mark", options, index=index, key=f"{key}-dec",
                               format_func=lambda v: {".": "point (1.5)", ",": "comma (1,5)"}.get(v, v))
    rows_seed = header.get("rows", 1) if header.get("rows", 1) in (0, 1, 2) else 1
    rows = c2.selectbox("Header lines", [0, 1, 2], index=rows_seed, key=f"{key}-rows",
                        format_func=lambda n: {0: "none", 1: "column names", 2: "names, then units"}[n])
    skip_seed = header.get("skip_lines", 0)
    skip = c3.number_input("Lines to skip first", min_value=0, step=1, key=f"{key}-skip",
                           value=int(skip_seed) if isinstance(skip_seed, int) and skip_seed >= 0 else 0,
                           help="Counted from the top, or from the line below when that is set.")
    c1, c2 = st.columns(2)
    starts_at = c1.text_input("The table starts at the line containing", str(header.get("starts_at") or ""),
                              key=f"{key}-starts",
                              help="Text on the line with the column names. Leave empty to count lines from the top.")
    contains = c2.text_input("Only files containing (optional)", str(seed_file.get("contains") or ""),
                             key=f"{key}-contains",
                             help="Text near the top that tells this layout apart from others with the same ending.")
    seed_end = seed_file.get("data_ends") or "end_of_file"
    ends_options = list(DATA_ENDS) + ["text marker"]
    c1, c2 = st.columns(2)
    ends = c1.selectbox("The data ends at", ends_options, key=f"{key}-ends",
                        index=ends_options.index(seed_end if seed_end in DATA_ENDS else "text marker"),
                        format_func=lambda v: {"end_of_file": "the end of the file",
                                               "first_non_numeric_row": "the first line that is not numbers",
                                               "text marker": "a line containing…"}[v])
    marker = c2.text_input("End text", "" if seed_end in DATA_ENDS else str(seed_end), key=f"{key}-marker",
                           disabled=ends != "text marker")
    c1, c2 = st.columns(2)
    comment = c1.text_input("Comment lines start with (optional)", str(seed_file.get("comment") or ""),
                            key=f"{key}-comment")
    names_from = c2.text_input(
        "Column names are listed above the table, in lines like (optional)",
        str(header.get("names_from") or ""), key=f"{key}-names-from", disabled=rows != 0,
        help="For files that list their columns one per line above the table, e.g. 'Sig1<tab>Time (min)': "
             "a regular expression whose group (…) is the name, e.g. ^Sig\\d+\\t(.+)$. "
             "Needs Header lines: none.")
    blocks_seed = seed_file.get("blocks") if isinstance(seed_file.get("blocks"), dict) else {}
    c1, c2, c3 = st.columns(3)
    blocks_at = c1.text_input(
        "Several tables, each starting at a line containing (optional)", str(blocks_seed.get("starts_at") or ""),
        key=f"{key}-blocks-at",
        help="For files with one table per interval or step, each with its own header lines, e.g. "
             "'Interval and data points:'. The settings above then apply to each table.")
    blocks_column = c2.text_input("Each row's table goes in the column", str(blocks_seed.get("column") or "block"),
                                  key=f"{key}-blocks-column", disabled=not blocks_at.strip())
    blocks_label = c3.text_input(
        "Table label (optional)", str(blocks_seed.get("label") or ""), key=f"{key}-blocks-label",
        disabled=not blocks_at.strip(),
        help="A regular expression whose group (…) on the table's first line is its label, e.g. "
             "^Interval and data points:\\s*(\\d+). Empty: the tables are numbered 1, 2, …")
    segment_lines = st.checkbox(
        "Text lines inside the table label the rows below them (segments)", key=f"{key}-segments",
        value=seed_file.get("segment_lines") is True,
        help="E.g. '2) DSC 8500 Temperature Scan' between rows of numbers: each row gets its segment "
             "in a 'segment' column, instead of the table ending there.")
    settings: Dict[str, Any] = {"extensions": [e.strip() for e in endings.split(",") if e.strip()]}
    if not book:
        settings.update(encoding=encoding, delimiter=delimiter, decimal=decimal)
    settings["header"] = {"rows": rows}
    sheet = sheet.strip()
    if sheet:
        settings["sheet"] = int(sheet) if re.fullmatch(r"-?\d+", sheet) else sheet
    if starts_at.strip():
        settings["header"]["starts_at"] = starts_at.strip()
    if skip:
        settings["header"]["skip_lines"] = int(skip)
    if rows == 0 and names_from.strip():
        settings["header"]["names_from"] = names_from.strip()
    if ends == "text marker" and marker.strip():
        settings["data_ends"] = marker.strip()
    elif ends == "first_non_numeric_row":
        settings["data_ends"] = ends
    if contains.strip():
        settings["contains"] = contains.strip()
    if comment.strip():
        settings["comment"] = comment.strip()
    if segment_lines:
        settings["segment_lines"] = True
    if blocks_at.strip():
        settings["blocks"] = {"starts_at": blocks_at.strip(), "column": blocks_column.strip() or "block"}
        if blocks_label.strip():
            settings["blocks"]["label"] = blocks_label.strip()
    # Settings the form does not show (e.g. duplicate_rows) are kept as they were.
    settings.update({k: v for k, v in seed_file.items() if k not in _FILE_FORM_KEYS})
    return settings


def _file_columns(settings: Dict[str, Any], sample: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    """Column names of ``sample`` read with ``settings``, or why it cannot be read."""
    from mfethuls.parsers.tabular import read_table

    try:
        fmt = parse_definition({"name": "x", "type": "x", "model": "x", "folder_name": "x", "file": settings,
                                "columns": [{"source": "x", "column": "x"}]}).formats[0].file
        return [str(c) for c in read_table(sample, fmt).columns], None
    except DefinitionError as exc:
        return None, "; ".join(p.removeprefix("file: ") for p in exc.problems)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        return None, str(exc)


def _columns_section(seed_columns: Optional[List[Dict[str, Any]]], file_columns: List[str], key: str
                     ) -> List[Dict[str, Any]]:
    st.caption("For each column: what it measures and the unit **in the file**; mfethuls converts it to the "
               "standard unit. Leave it empty if you don't know: the column is kept under its own name. "
               "A *plain name* stores a column that measures nothing (e.g. a detector) under a simple name.")
    rows = mapping_rows(file_columns, seed_columns)
    edited = st.data_editor(
        rows, key=f"{key}-columns-{_digest(file_columns)}", hide_index=True, width="stretch",
        disabled=["source"],
        column_config={
            "source": st.column_config.TextColumn("column in the file"),
            "quantity": st.column_config.SelectboxColumn("measures", options=quantity_options(tuple(rows["quantity"]))),
            "unit": st.column_config.SelectboxColumn("unit in the file", options=unit_options(tuple(rows["unit"])),
                                                     help="Empty: the quantity's standard unit."),
            "name": st.column_config.TextColumn("plain name", help="Only for columns that measure no quantity."),
        },
    )
    return columns_from_rows(edited, seed_columns)


def _extras_section(seed: Dict[str, Any], stored: List[str], new_type: bool, key: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    seed_derived = derived_rows(seed)
    seed_values = captured_rows(seed)
    st.markdown("**Values from the file name and header**")
    st.caption("Fill a column from the file name or from a line above the table: the part of the text in "
               "brackets (…) of the pattern. **values** turns codes into words, e.g. `ri=^RID; uv=^VWD`. "
               "**datetime**: give the time zone of local times (e.g. Europe/Zurich); stored in UTC.")
    edited_values = st.data_editor(
        seed_values, key=f"{key}-values", hide_index=True, width="stretch", num_rows="dynamic",
        column_config={
            "from": st.column_config.SelectboxColumn("taken from", options=list(_VALUE_SOURCES.values()),
                                                     required=True, default="file name"),
            "column": st.column_config.TextColumn("new column"),
            "pattern": st.column_config.TextColumn("pattern", help="Regular expression; its (…) group is kept."),
            "type": st.column_config.SelectboxColumn("stored as", options=list(VALUE_TYPES), default="text"),
            "timezone": st.column_config.TextColumn("time zone", help="datetime only, e.g. Europe/Zurich."),
            "values": st.column_config.TextColumn("values (optional)",
                                                  help="word=pattern; word=pattern, e.g. ri=^RID; uv=^VWD"),
        },
    )
    out.update(captured_from_rows(edited_values))
    st.markdown("**Extra columns and plot**")
    st.caption("Columns computed from stored ones, always into a new column (the data itself never changes): "
               "**normalize_pct** scales to 0–100 %, **pct_of_initial** gives % of the first value (TGA: "
               "100 % = initial mass), **scale** multiplies by the number, **offset** adds it, **multiply** / "
               "**divide** by another column (e.g. heat flow ÷ sample mass), **add_time** adds the time in "
               "another column (e.g. milliseconds from the file name) to a date-time.")
    edited = st.data_editor(
        seed_derived, key=f"{key}-derived", hide_index=True, width="stretch", num_rows="dynamic",
        column_config={
            "op": st.column_config.SelectboxColumn("operation", options=list(DERIVED_OPS)),
            "column": st.column_config.SelectboxColumn(
                "of the column", options=sorted(set(stored) | set(seed_derived["column"].dropna().astype(str)))),
            "into": st.column_config.TextColumn("new column"),
            "number": st.column_config.NumberColumn("number", help="scale: the factor; offset: what is added."),
            "amount": st.column_config.TextColumn(
                "other column", help="add_time: the column with the time to add; multiply / divide: the column "
                                     "to multiply or divide by (e.g. sample_mass_mg)."),
            "unit": st.column_config.SelectboxColumn("its unit", options=list(TIME_UNITS),
                                                     help="add_time only."),
        },
    )
    derived = derived_from_rows(edited)
    if derived:
        out["derived"] = derived
    plot = seed.get("plot") if isinstance(seed.get("plot"), dict) else {}
    candidates = stored + [d["into"] for d in derived if d.get("into")]
    if new_type and len(candidates) >= 2:
        c1, c2 = st.columns(2)
        x = c1.selectbox("Plot: x axis", candidates, key=f"{key}-plot-x",
                         index=candidates.index(plot["x"]) if plot.get("x") in candidates else 0)
        ys = [c for c in candidates if c != x]
        y = c2.selectbox("Plot: y axis", ys, key=f"{key}-plot-y",
                         index=ys.index(plot["y"]) if plot.get("y") in ys else 0)
        out["plot"] = {"x": x, "y": y}
    elif new_type:
        st.caption("Say what at least two columns measure to choose what to plot.")
    return out


def text_rows_message(file_name: str, info: Dict[str, Any]) -> str:
    """Warning for rows with text in number columns (see :func:`~mfethuls.parsers.tabular.text_in_numbers`)."""
    columns = info["columns"]
    shown = ", ".join(columns[:3]) + (f" and {len(columns) - 3} more" if len(columns) > 3 else "")
    return (f"{file_name}: {info['rows']} row(s) have text where numbers are expected (in {shown}), from line "
            f"{info['first_line']}: {info['first_text']!r}. If that is not data, set *The data ends at* to "
            "the first line that is not numbers, or to a line containing that text.")


def check_file(definition, path: Path) -> Dict[str, Any]:
    """Read ``path`` with ``definition``: rows, warnings, or the error. For the files-checked table."""
    from mfethuls.parsers.tabular import TabularParser, select_format, text_in_numbers

    try:
        data = TabularParser(definition).parse({"f": [str(path)]}, instrument_type=definition.type).data
        fmt = definition.formats[select_format(definition, path)]
        info = text_in_numbers(path, fmt.file)
    except Exception as exc:  # noqa: BLE001 - reported per file
        return {"file": path.name, "rows": None, "warnings": [], "error": str(exc)}
    warnings = [text_rows_message(path.name, info)] if info else []
    warnings += [f"{path.name}: {w}" for w in range_warnings(data, definition.type)]
    return {"file": path.name, "rows": len(data), "warnings": warnings, "error": None}


def _check_others(definition, others: List[Path]) -> Tuple[List[str], List[str]]:
    """The other files checked: one line when all read cleanly, else a table; returns (problems, warnings)."""
    if not others:
        return [], []
    results = [check_file(definition, path) for path in others]
    if not any(r["error"] or r["warnings"] for r in results):
        st.caption(f":material/check_circle: Also reads the {len(results)} other file{'s' if len(results) != 1 else ''} "
                   f"checked cleanly: {', '.join(r['file'] for r in results)}.")
        return [], []
    st.markdown("**The other files checked**")
    st.dataframe(pd.DataFrame([{
        "file": r["file"], "rows": r["rows"],
        "result": f"✗ {r['error']}" if r["error"] else (f"⚠ {len(r['warnings'])} warning(s)" if r["warnings"]
                                                          else "✓ reads cleanly"),
    } for r in results]), hide_index=True, width="stretch")
    problems = [f"{r['file']} cannot be read: {r['error']}" for r in results if r["error"]]
    warnings = [w for r in results for w in r["warnings"]]
    for problem in problems:
        st.error(_plain(problem), icon=":material/error:")
    for warning in warnings:
        st.warning(_plain(warning), icon=":material/warning:")
    return problems, warnings


def _check_section(data: Dict[str, Any], sample: Path, file_columns: List[str], slots: Dict[str, Any],
                   layout_columns: List[Dict[str, Any]], others: Optional[List[Path]] = None, stored_tab=None
                   ) -> Tuple[bool, List[str]]:
    """Validate and parse ``sample`` (and ``others``): the outcome here, each problem in its section
    of **Adjust details**, and the stored table in ``stored_tab``.

    Returns (ok, problems or warnings).
    """
    from mfethuls.parsers.tabular import TabularParser, select_format, text_in_numbers

    try:
        definition = parse_definition(data)
    except DefinitionError as exc:
        routed = route_problems(exc.problems)
        # A problem with the name is shown under it, at the top.
        routed["name"] = [p for p in routed["instrument"] if p.startswith("'name'")]
        routed["instrument"] = [p for p in routed["instrument"] if not p.startswith("'name'")]
        for section, problems in routed.items():
            _show(slots[section], problems)
        places = [_TABS[section] for section in _TABS if routed[section]]
        where = f": see **Adjust details** below ({', '.join(places)})" if places else ""
        st.warning(f"{len(exc.problems)} problem(s) to fix{where}.", icon=":material/edit_note:")
        return False, list(exc.problems)
    problem = clash(data)
    if problem:
        _show(slots["instrument"], [problem])
        st.warning("1 problem to fix: see **Adjust details** below (Instrument).", icon=":material/edit_note:")
        return False, [problem]

    with stored_tab if stored_tab is not None else st.container():
        st.markdown("**What will be stored**")
        st.dataframe(mapping_summary(layout_columns, file_columns, definition.type), hide_index=True,
                     width="stretch")
    try:
        dataset = TabularParser(definition).parse({"sample": [str(sample)]}, instrument_type=definition.type)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        message = f"The file cannot be read this way: {exc}"
        st.error(_plain(message))
        return False, [message]
    frame = dataset.data.drop(columns=[c for c in _ID_COLUMNS if c in dataset.data.columns])
    warnings = range_warnings(frame, definition.type)
    info = text_in_numbers(sample, definition.formats[select_format(definition, sample)].file)
    if info:
        warnings.insert(0, text_rows_message(sample.name, info))
    missing = missing_required(required_columns(definition.type), frame.columns)
    if missing:
        warnings.append(f"{definition.type} data needs {', '.join(missing)}: say which column measures "
                        f"{'it' if len(missing) == 1 else 'them'} for mfethuls' {definition.type} plots and checks.")
    for warning in warnings:
        st.warning(_plain(warning), icon=":material/warning:")
    shown = ", ".join(f"`{c}`" for c in frame.columns[:6]) + (f" and {len(frame.columns) - 6} more"
                                                              if len(frame.columns) > 6 else "")
    st.caption(f"Read **{len(frame)}** rows and **{len(frame.columns)}** columns from {_plain(sample.name)} "
               f"as **{_plain(definition.type)}**: {shown}.")
    with stored_tab if stored_tab is not None else st.container():
        st.dataframe(frame.head(200), hide_index=True, width="stretch", height=200)
        for parts in dataset.metadata.get("file_text", {}).values():
            kept = {k: v for k, v in parts.items() if k != "format"}
            if kept:
                st.markdown("**Text around the table** (kept with the data)")
                for part, lines in kept.items():
                    st.caption(f"**{part}**")
                    if isinstance(lines, dict):  # values taken from the text, e.g. the sample mass
                        lines = [f"{name}: {value}" for name, value in lines.items()]
                    st.code("\n".join(lines[:40]) + ("\n…" if len(lines) > 40 else ""), language=None)
    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    plot = definition.plot or {}
    mapped = [m.column or QUANTITIES[m.quantity].target(definition.type, m.unit)[0]
              for fmt in definition.formats for m in fmt.columns]
    mapped = [c for c in dict.fromkeys(mapped) if c in numeric]
    x = plot.get("x") if plot.get("x") in numeric else (mapped[0] if mapped else (numeric[0] if numeric else None))
    y = plot.get("y") if plot.get("y") in numeric else next((c for c in mapped + numeric if c != x), None)
    if x and y:
        import plotly.graph_objects as go

        fig = go.Figure(go.Scattergl(x=frame[x], y=frame[y], mode="lines"))
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), xaxis_title=x, yaxis_title=y)
        st.plotly_chart(fig, width="stretch")
    other_problems, other_warnings = _check_others(definition, others or [])
    if other_problems:
        return False, other_problems + warnings + other_warnings
    return True, warnings + other_warnings


def _save_controls(backend, data: Dict[str, Any], sample: Path, key: str, *,
                   editing: Optional[str] = None) -> None:
    name = data.get("name", "")
    # Compared as save_definition writes it: "TGA" replaces tga.json and the built-in tga.
    stored_name = str(name).strip().casefold()
    folder = lab_dir()
    existing = folder / f"{stored_name}.json" if folder else None
    if editing is not None and stored_name == str(editing).strip().casefold():
        allowed = True  # changing it is the point
    elif existing is not None and existing.exists():
        allowed = st.checkbox(f"Replace the lab's existing instrument {name!r}", key=f"{key}-replace")
    elif stored_name in builtin_names():
        allowed = st.checkbox(f"Replace mfethuls' built-in instrument {name!r} for everyone using this data "
                              "folder", key=f"{key}-replace-builtin")
    else:
        allowed = True
    try:
        prepared = prepare_definition(data, sample)
    except Exception as exc:  # noqa: BLE001
        st.error(_plain(exc))
        return
    left, right = st.columns(2)
    left.download_button("Download definition (.json)", data=definition_text(prepared).encode("utf8"),
                         file_name=f"{name}.json", mime="application/json", width="stretch")
    if not backend.writes_definitions:
        right.download_button("Download its sample file", data=sample.read_bytes(),
                              file_name=prepared["check"]["sample"], width="stretch")
        st.info("This app does not write to the data folder. Put both files in the data folder's "
                "`.mfethuls/instruments` folder (e.g. on OneDrive), then sync.")
        return
    if right.button("Save changes" if editing else "Save instrument", type="primary", disabled=not allowed,
                    width="stretch", key=f"{key}-save"):
        try:
            path = save_definition(data, sample, overwrite=True)
        except Exception as exc:  # noqa: BLE001
            st.error(_plain(exc))
            return
        from mfethuls.app.register import clear_registry_caches

        clear_registry_caches()
        if editing:
            st.session_state[_MESSAGE] = (f"Saved the changes to {name}. Data already ingested is read again "
                                          "when you ingest it, or under ⚙ Settings → Clean up (Read again).")
        else:
            st.session_state[_MESSAGE] = f"Added the instrument {name} ({path.name}). Its data can now be registered."
        st.rerun()


# The file settings the form shows (see _reading_section); others are kept from the seed.
_FILE_FORM_KEYS = {"extensions", "encoding", "delimiter", "decimal", "header", "sheet", "data_ends", "contains",
                   "comment", "segment_lines", "blocks"}
# The definition's keys the form fills in (see definition_form); others (tables, ...) are kept from the seed.
_FORM_KEYS = {"spec_version", "name", "type", "model", "folder_name", "data_layout", "name_from", "description",
              "file", "columns", "formats", "from_file_name", "from_sheet_name", "from_header", "derived", "plot",
              "characterizer",
              "check"}

# The tabs of "Adjust details", by the section problems are routed to (see route_problems).
_TABS = {"instrument": "Instrument", "file": "Reading the file", "columns": "Columns", "extras": "Values and plot"}


def needs_fixing(seed: Dict[str, Any]) -> bool:
    """Whether ``seed`` has problems besides its name: then **Adjust details** opens by itself."""
    try:
        parse_definition(seed)
    except DefinitionError as exc:
        return any(not p.startswith("'name'") for p in exc.problems)
    except Exception:  # noqa: BLE001
        return True
    return clash(seed) is not None


def definition_form(backend, seed: Dict[str, Any], sample: Path, key: str, *, folder: Optional[str] = None,
                    origin: str = "", guess_columns: bool = False, others: Optional[List[Path]] = None,
                    editing: Optional[str] = None) -> None:
    """The form every route ends in: the outcome, the name and Save, with everything else that was
    filled in under **Adjust details**; checked against ``sample`` (and ``others``).

    ``seed`` is a definition (possibly incomplete or wrong) that fills the form.
    With ``guess_columns``, columns the seed leaves empty get mfethuls' guesses. ``editing`` is
    the name of the lab instrument being changed: its name stays (registry rows use it).
    """
    seed_layouts = layouts(seed)
    index = layout_for(seed_layouts, sample)
    layout = seed_layouts[index]

    name_help = ("What the registry's instrument_name column says for this instrument: lower case letters, "
                 "digits, _ and -.")
    if editing:
        name_help += " Registry rows use it, so it stays when editing; to rename, add the instrument again."
    name = st.text_input("Name", value=str(seed.get("name") or ""), key=f"{key}-name", placeholder="e.g. tga_netzsch",
                         disabled=editing is not None, help=name_help)
    slots = {"name": st.container()}
    result = st.container()

    with st.expander(":material/tune: Adjust details", expanded=editing is not None or needs_fixing(seed)):
        if editing:
            st.caption("How this instrument's files are read: change what is wrong, and check the result above.")
        else:
            st.caption("Everything the chatbot or mfethuls filled in. Most files need nothing here: change only "
                       "what is wrong.")
        tabs = st.tabs([*_TABS.values(), "Stored data", "Definition (JSON)"])
        with tabs[0]:
            identity = _identity_section(seed, key, sample, folder, name)
            slots["instrument"] = st.container()
        with tabs[1]:
            if len(seed_layouts) > 1:
                rest = ", ".join(lay["label"] for i, lay in enumerate(seed_layouts) if i != index)
                st.caption(f"This instrument has several file layouts. Editing **{layout['label']}** (it matches "
                           f"{sample.name}); the others are kept unchanged: {rest}.")
            settings = _reading_section(layout["file"], key, sample)
            slots["file"] = st.container()
        file_columns, reason = _file_columns(settings, sample)
        if file_columns is None:
            slots["file"].error(f"The file cannot be read with these settings: {reason}", icon=":material/error:")
            result.warning("The file cannot be read this way: see **Adjust details** below (Reading the file).",
                           icon=":material/edit_note:")
            return
        with tabs[2]:
            columns = _columns_section(None if guess_columns else layout["columns"], file_columns, key)
            slots["columns"] = st.container()

        type_ = identity["type"]
        stored = [QUANTITIES[c["quantity"]].target(type_, c.get("unit"))[0] if c.get("quantity") in QUANTITIES
                  else c.get("column")
                  for c in columns]
        stored = [c for c in dict.fromkeys(stored) if isinstance(c, str) and c]
        with tabs[3]:
            extras = _extras_section(seed, stored, bool(type_) and type_ not in known_types(), key)
            slots["extras"] = st.container()
        stored_tab, json_tab = tabs[4], tabs[5]

    data: Dict[str, Any] = dict(identity)
    if origin and not data.get("description"):
        data["description"] = f"{origin} ({date.today().isoformat()})"
    if len(seed_layouts) > 1:
        data["formats"] = [
            {"label": lay["label"], "file": settings if i == index else lay["file"],
             "columns": columns if i == index else lay["columns"]}
            for i, lay in enumerate(seed_layouts)
        ]
    else:
        data["file"] = settings
        data["columns"] = columns
    data.update(extras)
    if isinstance(seed.get("characterizer"), dict):
        data["characterizer"] = seed["characterizer"]
    # What the form does not show (a results table, ...) is kept as the seed has it.
    data.update({k: v for k, v in seed.items() if k not in _FORM_KEYS})
    with json_tab:
        st.code(definition_text(data), language="json")

    with result:
        slots["other"] = st.container()
        if not columns:
            st.info("Say what at least one column measures: see **Adjust details** below (Columns).")
            return
        ok, problems = _check_section(data, sample, file_columns, slots, columns, others, stored_tab)
        if problems:
            from mfethuls.instruments.spec import problems_prompt

            title = "Copy the problems for the chatbot" if not ok else "Copy the warnings for the chatbot"
            with st.expander(f":material/chat: {title}", expanded=bool(origin) and not ok):
                st.caption("Paste this into the chatbot, then paste its corrected answer in step 3; or fix "
                           "the details below.")
                st.code(problems_prompt(problems, data), language="markdown", height=200)
        if ok:
            _save_controls(backend, data, sample, key, editing=editing)


def _chatbot_flow(backend, sample: Path, others: List[Path], folder: Optional[str], key: str) -> None:
    from mfethuls.instruments.detect import file_outline
    from mfethuls.instruments.spec import spec_card

    st.markdown("**2. Copy this prompt into a chatbot** (e.g. Gemini or Claude)")
    what = ("the first 40 and last 15 rows of every sheet" if sample.suffix.casefold() in WORKBOOK_EXTENSIONS
            else "the first 40 and last 15 lines")
    st.warning(f"The prompt contains {what} of **{sample.name}**. Only send it if your data "
               "may be shared with that service (unpublished results, your institution's rules). Of the other "
               "files, only their shape (line counts, where text and numbers are) goes in.",
               icon=":material/privacy_tip:")
    hints = st.text_input("What you know about the instrument (optional, goes into the prompt)", key=f"{key}-hints",
                          placeholder="e.g. Netzsch TG 209; files go in the TGA folder; use the sample temperature")
    encoding = "utf-8"
    summary = ""
    try:
        detection = detect(sample)
        encoding = detection.file.get("encoding", "utf-8")
        summary = detection.summary()
    except Exception:  # noqa: BLE001 - the chatbot reads the file itself
        pass
    other_files = {}
    for path in others[:2]:
        try:
            other_files[path.name] = file_outline(path)
        except Exception:  # noqa: BLE001 - checked again below
            continue
    folder_hint = f"Its data folder is {folder!r}." if folder else ""
    prompt_hints = "\n".join(h for h in (hints.strip(), folder_hint, summary) if h)
    try:
        prompt = spec_card(sample, encoding=encoding, hints=prompt_hints, other_files=other_files)
    except ValueError as exc:  # a binary file mfethuls cannot read
        st.error(_plain(exc))
        return
    st.code(prompt, language="markdown", height=200)
    st.caption("Copy it with the button at the top right of the box.")

    st.markdown("**3. Paste the chatbot's answer here, then press Read the answer**")
    text = st.text_area("The chatbot's answer", key=f"{key}-answer", height=150, label_visibility="collapsed",
                        placeholder="Paste the JSON the chatbot wrote (or a definition a colleague sent you).")
    # The box takes its text when it loses focus, so pressing the button is enough.
    st.button("Read the answer", type="primary", icon=":material/arrow_downward:", key=f"{key}-read")
    if not text.strip():
        return
    start, end = text.find("{"), text.rfind("}")
    try:
        seed = definition_json(text[start:end + 1] if start >= 0 and end > start else text)
    except DefinitionError as exc:
        st.error(f"The answer is not a definition: {_plain(exc.problems[0])}. Ask the chatbot to reply with "
                 "the JSON only.")
        return
    if not isinstance(seed, dict):
        st.error("The answer must be one JSON object { ... }.")
        return
    st.success("Read below. If the plot looks right, press **Save instrument**; if not, change it under "
               "**Adjust details**, or paste another answer.", icon=":material/arrow_downward:")
    definition_form(backend, seed, sample, f"{key}-{_digest(seed)}", folder=folder, others=others,
                    origin="Drafted with a chatbot and checked in mfethuls")


def _manual_flow(backend, sample: Path, others: List[Path], folder: Optional[str], key: str) -> None:
    try:
        detection = detect(sample)
    except Exception as exc:  # noqa: BLE001
        st.error(f"mfethuls could not find a table in {_plain(sample.name)}: {_plain(exc)}. Try **{CHATBOT}**.")
        return
    st.markdown("**2. Check mfethuls' guesses**")
    for note in detection.notes:
        st.caption(note)
    with st.expander("The whole file, part by part"):
        st.code("\n".join(detection.outline), language=None)
    definition_form(backend, seed_from_detection(detection, folder), sample, f"{key}-auto", folder=folder,
                    others=others, guess_columns=True)


def saved_sample(path: Path, seed: Dict[str, Any]) -> Optional[Path]:
    """The copy of the file a lab definition was made from, saved next to it, if it is still there."""
    check = seed.get("check") if isinstance(seed.get("check"), dict) else {}
    sample = path.parent / str(check.get("sample") or "")
    return sample if check.get("sample") and sample.is_file() else None


def _folder_others(folder: Optional[str], sample: Path) -> List[Path]:
    """Files in the instrument's folder to check an edited definition against, like Add instrument's."""
    from mfethuls.discovery import folder_files

    data_root = get_settings().data_root
    if not (data_root and folder) or not (Path(data_root) / folder).is_dir():
        return []
    base = Path(data_root) / folder
    files, _, _ = folder_files(str(base))
    return [base / name for name in files_to_check(base, files, sample.name)]


@st.dialog("Edit instrument", width="large")
def edit_instrument_dialog(backend, source: str) -> None:
    """A lab instrument's saved definition in the form, checked against the file it was made from."""
    path = Path(source)
    try:
        seed = definition_json(path.read_text(encoding="utf8"), str(path))
    except Exception as exc:  # noqa: BLE001
        st.error(f"{path.name} cannot be opened: {_plain(exc)}")
        return
    if not isinstance(seed, dict):
        st.error(f"{path.name} is not an instrument definition.")
        return
    name = str(seed.get("name") or path.stem)
    folder = seed.get("folder_name") if isinstance(seed.get("folder_name"), str) else None
    sample = saved_sample(path, seed)
    if sample is None:
        st.info("The file this instrument was made from is not next to it any more: choose one of its files.")
        sample, others = _sample_picker(folder, f"edit-{path.stem}")
        if sample is None:
            return
    else:
        others = _folder_others(folder, sample)
        st.caption(f"Checked against **{sample.name}**, the file it was made from"
                   + (f", and {len(others)} other file(s) in `{folder}`." if others else "."))
    definition_form(backend, seed, sample, f"edit-{path.stem}-{_digest(seed)}", folder=folder, others=others,
                    editing=name)


@st.dialog("Add instrument", width="large")
def add_instrument_dialog(backend, *, folder: Optional[str] = None) -> None:
    """From a file the instrument exports to a saved instrument definition."""
    mode = st.segmented_control("How", [CHATBOT, MANUAL], default=CHATBOT, key="add-instrument-mode",
                                label_visibility="collapsed")
    sample, others = _sample_picker(folder, "add-instrument")
    if sample is None:
        st.info("Choose a file the instrument exported.")
        return
    key = "add-instrument-" + _digest(str(sample))
    if mode == MANUAL:
        _manual_flow(backend, sample, others, folder, key)
    else:
        _chatbot_flow(backend, sample, others, folder, key)
