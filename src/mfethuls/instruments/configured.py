"""The instruments mfethuls knows: code parsers plus instrument definitions.

Three sources, later ones winning for the same instrument ``name``:

1. ``config/instrument_params.json``: instruments read by code parsers (DSC, NMR, ...).
2. Built-in definitions, ``config/instruments/*.json``.
3. The lab's definitions next to the data, ``PATH_TO_DATA/.mfethuls/instruments/*.json``,
   shared with everyone who uses that data folder.

Each instrument reads one folder of the data folder (``folder_name``). The lab can
give a built-in instrument another folder (``DMA data`` instead of ``DMA``): the
links are kept in ``PATH_TO_DATA/.mfethuls/folders.json`` (see :func:`link_folder`);
a lab definition's folder is changed in its own file.

A lab definition is skipped (and reported by :func:`definition_statuses`) when it
is invalid or when its type and model are already read by another instrument.
Each lab definition keeps a copy of the file it was made from; whenever the
definitions are loaded, the copy is read again and compared with what it gave
when the definition was saved, so a change in how mfethuls reads files is
reported instead of silently changing data.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .definition import DefinitionError, InstrumentDefinition, builtin_definitions, load_definition, parse_definition

logger = logging.getLogger(__name__)

PARAMS_FILE = Path(__file__).resolve().parent.parent / "config" / "instrument_params.json"
LAB_SUBDIR = Path(".mfethuls") / "instruments"
FOLDERS_FILE = Path(".mfethuls") / "folders.json"
SAMPLE_INFIX = ".sample"

# Columns every parser adds; left out of a definition's sample check.
_ID_COLUMNS = {"experiment_id", "sample_id", "run_id", "name", "source_file"}


@dataclass
class DefinitionStatus:
    """How one definition file was taken in: active or not, and why."""

    source: str
    name: Optional[str] = None
    active: bool = False
    problems: List[str] = field(default_factory=list)  # why it is not used
    warnings: List[str] = field(default_factory=list)  # used, but needs a look


def _listed_instruments() -> List[Dict[str, Any]]:
    return [dict(entry) for entry in _read_params()]


@lru_cache(maxsize=1)
def _read_params() -> Tuple[Dict[str, Any], ...]:
    if not PARAMS_FILE.exists():
        return ()
    return tuple(json.loads(PARAMS_FILE.read_text(encoding="utf8")))


@lru_cache(maxsize=1)
def _builtin() -> Tuple[InstrumentDefinition, ...]:
    from mfethuls.parsers.tabular import register_definition

    definitions = tuple(builtin_definitions())
    for definition in definitions:
        register_definition(definition)
    return definitions


def lab_dir(data_root: Optional[str] = None) -> Optional[Path]:
    """Folder of the lab's definitions, or None without a data folder."""
    if data_root is None:
        from mfethuls.settings import get_settings

        data_root = get_settings().data_root
    return Path(data_root) / LAB_SUBDIR if data_root else None


def sample_path(definition: InstrumentDefinition) -> Optional[Path]:
    """The stored sample file of a lab definition."""
    if not (definition.check and definition.source):
        return None
    directory = Path(definition.source).parent
    path = directory / definition.check["sample"]
    # parse_definition only accepts a plain file name; never read a file outside the lab's folder.
    return path if path.resolve().parent == directory.resolve() else None


def sample_summary(definition: InstrumentDefinition, path) -> Dict[str, Any]:
    """What ``definition`` reads from ``path``: row count and column names."""
    from mfethuls.parsers.tabular import TabularParser

    data = TabularParser(definition).parse({"sample": [str(path)]}, instrument_type=definition.type).data
    return {"rows": int(len(data)), "columns": [c for c in data.columns if c not in _ID_COLUMNS]}


def verify_sample(definition: InstrumentDefinition) -> List[str]:
    """Warnings when the stored sample no longer reads as when the definition was saved."""
    path = sample_path(definition)
    if path is None:
        return []
    if not path.exists():
        return [f"its sample file {path.name} is missing, so changes in how it reads files cannot be noticed"]
    try:
        now = sample_summary(definition, path)
    except Exception as exc:  # noqa: BLE001 - reported to the user
        return [f"its sample file {path.name} can no longer be read: {exc}"]
    warnings = []
    saved_rows, saved_columns = definition.check.get("rows"), definition.check.get("columns")
    if saved_rows is not None and now["rows"] != saved_rows:
        warnings.append(f"its sample file now gives {now['rows']} rows instead of {saved_rows}")
    if isinstance(saved_columns, list) and now["columns"] != saved_columns:
        missing = [c for c in saved_columns if c not in now["columns"]]
        added = [c for c in now["columns"] if c not in saved_columns]
        detail = "; ".join(filter(None, [
            f"missing {', '.join(missing)}" if missing else "",
            f"new {', '.join(added)}" if added else "",
            "" if missing or added else "order changed",
        ]))
        warnings.append(f"its sample file now gives other columns ({detail})")
    return warnings


def _dir_state(directory: Optional[Path]) -> Tuple:
    if directory is None or not directory.is_dir():
        return ()
    state = []
    for path in sorted(directory.iterdir()):
        try:
            stat = path.stat()
        except OSError:
            continue
        state.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(state)


_lab_cache: Dict[str, Any] = {"key": None, "value": ([], [])}


def _load_lab(directory: Optional[Path]) -> Tuple[List[InstrumentDefinition], List[DefinitionStatus]]:
    """Valid lab definitions and the status of every file; cached until a file changes."""
    key = (str(directory), _dir_state(directory))
    if _lab_cache["key"] == key:
        return _lab_cache["value"]
    definitions: List[InstrumentDefinition] = []
    statuses: List[DefinitionStatus] = []
    if directory is not None and directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            status = DefinitionStatus(source=str(path))
            statuses.append(status)
            try:
                definition = load_definition(path)
            except DefinitionError as exc:
                status.problems = list(exc.problems)
                continue
            except Exception as exc:  # noqa: BLE001 - one broken file must not hide the other instruments
                logger.exception("Could not load the instrument definition %s", path)
                status.problems = [f"it could not be loaded: {exc}"]
                continue
            status.name = definition.name
            status.warnings = verify_sample(definition)
            definitions.append(definition)
    _lab_cache.update(key=key, value=(definitions, statuses))
    return definitions, statuses


# Registry entries a lab definition took over, restored when it goes away.
_displaced: Dict[Tuple[str, str], Any] = {}
_lab_keys: set = set()
# The parser registry is shared by the app's sessions, which Streamlit runs in parallel threads.
_lock = threading.RLock()


def _activate(definitions: List[InstrumentDefinition]) -> None:
    from mfethuls.parsers.registry import _PARSER_REGISTRY
    from mfethuls.parsers.tabular import register_definition

    wanted = {(d.type, d.model): d for d in definitions}
    for key in list(_lab_keys - set(wanted)):
        if key in _displaced:
            _PARSER_REGISTRY[key] = _displaced.pop(key)
        else:
            _PARSER_REGISTRY.pop(key, None)
        _lab_keys.discard(key)
    for key, definition in wanted.items():
        if key not in _lab_keys and key in _PARSER_REGISTRY:
            _displaced[key] = _PARSER_REGISTRY[key]
        register_definition(definition)
        _lab_keys.add(key)


def _resolve(data_root: Optional[str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, InstrumentDefinition],
                                                List[DefinitionStatus]]:
    """Instrument entries by name, definitions in use by name, and lab file statuses."""
    with _lock:
        return _resolve_locked(data_root)


def _resolve_locked(data_root: Optional[str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, InstrumentDefinition],
                                                       List[DefinitionStatus]]:
    entries: Dict[str, Dict[str, Any]] = {}
    for entry in _listed_instruments():
        entries[str(entry.get("name", "")).strip().casefold()] = entry
    used: Dict[str, InstrumentDefinition] = {}
    for definition in _builtin():
        entries[definition.name] = definition.instrument_entry()
        used[definition.name] = definition
    for name, folder in folder_links(data_root).items():
        if name in entries:
            entries[name]["default_folder"] = entries[name]["folder_name"]
            entries[name]["folder_name"] = folder

    lab, statuses = _load_lab(lab_dir(data_root))
    by_source = {status.source: status for status in statuses}
    active: List[InstrumentDefinition] = []
    for definition in lab:
        status = by_source[definition.source]
        status.problems = []
        others = {(e["type"], e["model"]): name for name, e in entries.items() if name != definition.name}
        taken = others.get((definition.type, definition.model))
        if taken is not None:
            status.problems = [f"type {definition.type!r} and model {definition.model!r} are already read by "
                               f"the instrument {taken!r}; give this one another model"]
            status.active = False
            continue
        if any(d.name == definition.name for d in active):
            status.problems = [f"another file already defines the instrument {definition.name!r}"]
            status.active = False
            continue
        status.active = True
        entries[definition.name] = definition.instrument_entry()
        used[definition.name] = definition
        active.append(definition)
    _activate(active)
    return entries, used, statuses


def instrument_entries(data_root: Optional[str] = None) -> List[Dict[str, Any]]:
    """One entry per instrument: type, model, name, folder_name, data_layout, ..."""
    return list(_resolve(data_root)[0].values())


def instrument_definitions(data_root: Optional[str] = None) -> List[InstrumentDefinition]:
    """Every instrument definition in use (built-in and the lab's), each with its parser registered."""
    return list(_resolve(data_root)[1].values())


def definition_for(instrument_name: str, data_root: Optional[str] = None) -> Optional[InstrumentDefinition]:
    """The definition that reads ``instrument_name``, or None for a code parser."""
    return _resolve(data_root)[1].get(str(instrument_name).strip().casefold())


def definition_statuses(data_root: Optional[str] = None) -> List[DefinitionStatus]:
    """One status per lab definition file (problems and warnings to show the user)."""
    return _resolve(data_root)[2]


def builtin_names() -> set:
    return {d.name for d in _builtin()} | {str(e.get("name", "")).casefold() for e in _listed_instruments()}


def folders_file(data_root: Optional[str] = None) -> Optional[Path]:
    """The lab's folder links, or None without a data folder."""
    directory = lab_dir(data_root)
    return directory.parent.parent / FOLDERS_FILE if directory else None


_links_cache: Dict[str, Any] = {"key": None, "value": {}}


def folder_links(data_root: Optional[str] = None) -> Dict[str, str]:
    """Built-in instruments the lab gave another folder: instrument name -> folder name.

    Entries that are not a plain folder name are left out (and logged).
    """
    from mfethuls.naming import file_name_problem

    path = folders_file(data_root)
    try:
        stat = path.stat() if path else None
    except OSError:
        stat = None
    key = (str(path), stat.st_mtime_ns, stat.st_size) if stat else None
    if key is None:
        return {}
    if _links_cache["key"] == key:
        return dict(_links_cache["value"])
    try:
        raw = json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read the folder links %s: %s", path, exc)
        raw = {}
    links = {}
    for name, folder in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(folder, str) or file_name_problem(folder):
            logger.warning("Folder link %r -> %r in %s is not a plain folder name; ignored", name, folder, path)
            continue
        links[str(name).strip().casefold()] = folder
    _links_cache.update(key=key, value=links)
    return dict(links)


def _write_json(path: Path, data: Any) -> None:
    from mfethuls._files import replace_with_retry

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf8") as handle:
        handle.write(definition_text(data))
    replace_with_retry(temp, str(path))


def link_folder(names, folder: str, data_root: Optional[str] = None) -> None:
    """Make the instruments ``names`` read the folder ``folder`` of the data folder.

    A built-in instrument gets a link in ``.mfethuls/folders.json`` (removed again when
    ``folder`` is its own folder); a lab definition's file is changed. One folder holds
    one kind of measurement: a folder another type of instrument reads is refused
    (``ValueError``), as is a name that is not a plain folder name.
    """
    from mfethuls.naming import file_name_problem

    folder = str(folder).strip()
    if not folder or (issue := file_name_problem(folder)):
        raise ValueError(f"The folder {folder!r} {issue or 'is empty'}.")
    if lab_dir(data_root) is None:
        raise ValueError("No data folder: set the data folder before linking instruments.")
    entries, used, _ = _resolve(data_root)
    names = [str(n).strip().casefold() for n in names]
    unknown = [n for n in names if n not in entries]
    if unknown:
        raise ValueError(f"Unknown instrument(s): {', '.join(unknown)}")
    types = {entries[n]["type"] for n in names}
    for name, entry in entries.items():
        if name not in names and entry["folder_name"].casefold() == folder.casefold() and entry["type"] not in types:
            raise ValueError(f"{entry['folder_name']} is already the folder of {name} ({entry['type']} data). "
                             "Keep one kind of measurement per folder.")

    links = folder_links(data_root)
    lab = lab_dir(data_root).resolve()
    for name in names:
        definition = used.get(name)
        if definition is not None and definition.source and Path(definition.source).resolve().parent == lab:
            data = json.loads(Path(definition.source).read_text(encoding="utf8"))
            data["folder_name"] = folder
            _write_json(Path(definition.source), data)
        elif folder == entries[name].get("default_folder", entries[name]["folder_name"]):
            links.pop(name, None)
        else:
            links[name] = folder
    path = folders_file(data_root)
    if links or path.exists():
        _write_json(path, dict(sorted(links.items())))
    logger.info("Linked %s to the folder %s", ", ".join(names), folder)


REMOVED_SUBDIR = "removed"


def remove_definition(source, data_root: Optional[str] = None) -> Path:
    """Move a lab definition file (and its sample) to ``removed/<date-time>/``; returns that folder.

    Nothing is deleted: moving the files back restores the instrument. Data already
    ingested with it stays where it is.
    """
    from datetime import datetime

    directory = lab_dir(data_root)
    path = Path(source)
    if directory is None or path.parent.resolve() != directory.resolve() or path.suffix != ".json":
        raise ValueError(f"{path.name} is not one of the lab's instrument definitions")
    if not path.exists():
        raise FileNotFoundError(f"{path.name} no longer exists")
    files = [path]
    try:
        sample = json.loads(path.read_text(encoding="utf8")).get("check", {}).get("sample")
    except (ValueError, AttributeError):
        sample = None
    if isinstance(sample, str) and (directory / sample).exists() and (directory / sample).parent == directory:
        files.append(directory / sample)
    target = directory / REMOVED_SUBDIR / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target.mkdir(parents=True, exist_ok=True)
    for file in files:
        shutil.move(str(file), str(target / file.name))
    logger.info("Moved instrument definition %s to %s", path.name, target)
    return target


def definition_text(data: Dict[str, Any]) -> str:
    """A definition as it is written to disk."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def prepare_definition(data: Dict[str, Any], sample) -> Dict[str, Any]:
    """``data`` with its ``check`` filled from ``sample`` (raises if either is wrong).

    The ``check`` names the sample copy saved next to the definition and records
    what the definition reads from it.
    """
    from mfethuls.parsers.ingestion import ParseError

    data = {k: v for k, v in data.items() if k != "check"}
    definition = parse_definition(data)
    summary = sample_summary(definition, sample)
    if summary["rows"] == 0:
        raise ParseError(f"{Path(sample).name}: no data rows found")
    sample_name = f"{definition.name}{SAMPLE_INFIX}{Path(sample).suffix.casefold()}"
    return {**data, "check": {"sample": sample_name, **summary}}


def save_definition(
    data: Dict[str, Any],
    sample,
    *,
    data_root: Optional[str] = None,
    overwrite: bool = False,
) -> Path:
    """Write a lab definition and a copy of its sample file; returns the definition's path.

    The definition is checked and must read ``sample``. Raises
    :class:`~mfethuls.instruments.definition.DefinitionError`,
    :class:`~mfethuls.parsers.ingestion.ParseError` or ``FileExistsError``.
    """
    from mfethuls._files import replace_with_retry

    directory = lab_dir(data_root)
    if directory is None:
        raise ValueError("No data folder: set the data folder before adding instruments.")
    data = prepare_definition(data, sample)
    target = directory / f"{data['name'].strip().casefold()}.json"
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target.name} already exists in {directory}")
    directory.mkdir(parents=True, exist_ok=True)

    sample_target = directory / data["check"]["sample"]
    if Path(sample).resolve() != sample_target.resolve():
        shutil.copyfile(sample, sample_target)
    fd, temp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf8") as handle:
        handle.write(definition_text(data))
    replace_with_retry(temp, str(target))
    logger.info("Saved instrument definition %s", target)
    return target
