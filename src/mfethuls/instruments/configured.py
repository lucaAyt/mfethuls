"""The instruments mfethuls knows, and the readers that read their files.

Three things, each with one job:

- A **measurement type** (``dsc``, ``uv_vis``, ...): what the data is; its schema, quantities and plots.
- A **reader**: how one export format of a type is read (``dsc_mettler_toledo_v1``, ``uv_insitu`` for
  Flame spectra). Built-in definitions (``config/readers/*.json``), code readers
  (``config/code_readers.json``: Bruker NMR), and the lab's definitions next to the data
  (``PATH_TO_DATA/.mfethuls/readers/*.json``, shared with everyone who uses that data folder; one
  with a built-in reader's name replaces it). Readers are never named in the registry.
- An **instrument**: where data comes from as the lab sees it, and what the registry's
  ``instrument_name`` names. Each has one type and **one folder** of the data folder, and each folder
  belongs to one instrument; anything below the folder is the lab's business. mfethuls has one
  instrument per type (``config/instruments.json``: ``dsc`` reads ``DSC``, ...); the lab adds its own
  in ``PATH_TO_DATA/.mfethuls/instruments/*.json`` (``{"name": "dsc_room_b", "type": "dsc",
  "folder_name": "DSC room B"}``). A lab file with a built-in instrument's name replaces it: that is
  how a built-in instrument gets another folder.

Each experiment's files are read by one reader of its instrument's type (or of the readers the
instrument lists): the one that claims their extension, or, when several do, the one that
recognises the first file (:func:`reader_for`). Readers of other types are never tried.

A lab file is skipped (and reported by :func:`lab_statuses`) when it is invalid. Each lab
reader keeps a copy of the file it was made from; whenever the readers are loaded, the copy is
read again and compared with what it gave when the reader was saved, so a change in how
mfethuls reads files is reported instead of silently changing data.
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
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .definition import (
    _NAME_RE,
    MAX_DEFINITION_BYTES,
    DefinitionError,
    InstrumentDefinition,
    builtin_definitions,
    definition_json,
    load_definition,
    parse_definition,
)

logger = logging.getLogger(__name__)

_CONFIG = Path(__file__).resolve().parent.parent / "config"
CODE_READERS_FILE = _CONFIG / "code_readers.json"
INSTRUMENTS_FILE = _CONFIG / "instruments.json"
LAB_READERS = Path(".mfethuls") / "readers"
LAB_INSTRUMENTS = Path(".mfethuls") / "instruments"
SAMPLE_INFIX = ".sample"

# Columns every parser adds; left out of a definition's sample check.
_ID_COLUMNS = {"experiment_id", "sample_id", "run_id", "name", "source_file"}


@dataclass
class DefinitionStatus:
    """How one lab file (a reader or an instrument) was taken in: active or not, and why."""

    source: str
    kind: str = "reader"  # "reader" or "instrument"
    name: Optional[str] = None
    active: bool = False
    problems: List[str] = field(default_factory=list)  # why it is not used
    warnings: List[str] = field(default_factory=list)  # used, but needs a look


@dataclass(frozen=True)
class Reader:
    """One export format of a measurement type: a definition, or a code parser."""

    name: str
    type: str
    model: str
    layout: str = "file"  # "file": one file per experiment; "folder": a folder (series) per experiment
    description: str = ""
    definition: Optional[InstrumentDefinition] = None
    lab: bool = False  # one of the lab's definitions

    @property
    def parser(self):
        return _parser_of(self)

    @property
    def characterizer(self) -> Optional[Dict[str, Any]]:
        return dict(self.definition.characterizer) if self.definition and self.definition.characterizer else None

    def claims(self, path) -> bool:
        """Whether this reader reads files with ``path``'s extension (a code reader may read any)."""
        from mfethuls.parsers.registry import reads

        return reads(self.parser, path)

    def recognises(self, path) -> bool:
        """Whether ``path`` is this reader's format: its extension, and for a definition the text and
        header marker of one of its formats (see :func:`~mfethuls.parsers.tabular.recognised_format`)."""
        return self.recognition(path) is not None

    def recognition(self, path) -> Optional[bool]:
        """How this reader recognises ``path``: True by its content (text or a header marker), False
        by its extension only (a format looking for nothing, or a code reader), None not at all.
        A reader that recognises a file by its content is more specific. The file is read once."""
        if self.definition is None:
            return False if self.claims(path) else None
        from mfethuls.parsers.tabular import recognised_format

        index = recognised_format(self.definition, path)
        if index is None:
            return None
        file = self.definition.formats[index].file
        return bool(file.contains is not None or file.not_contains is not None or file.header_starts_at)


@dataclass(frozen=True)
class Instrument:
    """A source of data: its name (the registry's ``instrument_name``), type and folder."""

    name: str
    type: str
    folder_name: str
    readers: Tuple[str, ...] = ()  # only these readers; empty: every reader of its type
    description: str = ""
    source: Optional[str] = None  # the lab's file; None for a built-in instrument
    default_folder: Optional[str] = None  # a built-in instrument's own folder, when a lab file moved it

    @property
    def builtin(self) -> bool:
        return self.source is None or self.default_folder is not None


_INSTRUMENT_KEYS = {"spec_version", "name", "type", "folder_name", "readers", "description"}


def parse_instrument(data: Any, source: Optional[str] = None) -> Instrument:
    """An :class:`Instrument` from its JSON; ``DefinitionError`` listing what is wrong."""
    from mfethuls.naming import file_name_problem

    if not isinstance(data, dict):
        raise DefinitionError(["the file must contain one JSON object { ... }"], source)
    problems = []
    if "file" in data or "formats" in data or "columns" in data:
        raise DefinitionError(["this is a reader (it says how files are read): put it in .mfethuls/readers"], source)
    unknown = sorted(set(data) - _INSTRUMENT_KEYS)
    if unknown:
        problems.append(f"unknown keys {', '.join(map(repr, unknown))}: an instrument takes only "
                        "name, type, folder_name, readers and description")
    name, type_, folder = (str(data.get(key) or "").strip() for key in ("name", "type", "folder_name"))
    if not _NAME_RE.match(name.casefold() or "-"):
        problems.append("'name' must be lower-case letters, digits, '_' or '-'")
    if not _NAME_RE.match(type_.casefold() or "-"):
        problems.append("'type' must name a measurement type (e.g. dsc, uv_vis)")
    if not folder or file_name_problem(folder):
        problems.append(f"'folder_name' {file_name_problem(folder) or 'is missing'}")
    readers = data.get("readers") or []
    if not (isinstance(readers, list) and all(isinstance(r, str) and r.strip() for r in readers)):
        problems.append("'readers' must list reader names")
        readers = []
    if problems:
        raise DefinitionError(problems, source)
    return Instrument(name=name.casefold(), type=type_.casefold(), folder_name=folder,
                      readers=tuple(r.strip().casefold() for r in readers),
                      description=str(data.get("description") or "")[:500], source=source)


@lru_cache(maxsize=1)
def _code_readers() -> Tuple[Dict[str, Any], ...]:
    return tuple(json.loads(CODE_READERS_FILE.read_text(encoding="utf8"))) if CODE_READERS_FILE.exists() else ()


@lru_cache(maxsize=1)
def _default_instruments() -> Tuple[Instrument, ...]:
    return tuple(parse_instrument(entry) for entry in json.loads(INSTRUMENTS_FILE.read_text(encoding="utf8")))


@lru_cache(maxsize=1)
def _builtin() -> Tuple[InstrumentDefinition, ...]:
    from mfethuls.parsers.tabular import register_definition

    definitions = tuple(builtin_definitions())
    for definition in definitions:
        register_definition(definition)
    return definitions


def _data_root(data_root: Optional[str]) -> Optional[str]:
    if data_root is None:
        from mfethuls.settings import get_settings

        data_root = get_settings().data_root
    return data_root or None


def lab_dir(data_root: Optional[str] = None) -> Optional[Path]:
    """Folder of the lab's readers, or None without a data folder."""
    root = _data_root(data_root)
    return Path(root) / LAB_READERS if root else None


def instruments_dir(data_root: Optional[str] = None) -> Optional[Path]:
    """Folder of the lab's instruments, or None without a data folder."""
    root = _data_root(data_root)
    return Path(root) / LAB_INSTRUMENTS if root else None


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


_lab_cache: Dict[str, Any] = {}  # folder kind -> (folder state, its files)


def _load_files(directory: Optional[Path], kind: str) -> Tuple[list, List[DefinitionStatus]]:
    """The valid files of one lab folder (readers' definitions or instruments) and the status of
    every file; cached until a file in it changes."""
    key = (str(directory), _dir_state(directory))
    cached = _lab_cache.get(kind)
    if cached is not None and cached[0] == key:
        return cached[1]
    found: list = []
    statuses: List[DefinitionStatus] = []
    if directory is not None and directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            status = DefinitionStatus(source=str(path), kind=kind)
            statuses.append(status)
            try:
                if kind == "reader":
                    item = load_definition(path)
                    status.warnings = verify_sample(item)
                else:
                    if path.stat().st_size > MAX_DEFINITION_BYTES:
                        raise DefinitionError(["it is too large to be an instrument"], str(path))
                    item = parse_instrument(definition_json(path.read_text(encoding="utf8"), str(path)), str(path))
            except DefinitionError as exc:
                status.problems = list(exc.problems)
                continue
            except Exception as exc:  # noqa: BLE001 - one broken file must not hide the others
                logger.exception("Could not load %s", path)
                status.problems = [f"it could not be loaded: {exc}"]
                continue
            status.name = item.name
            found.append(item)
    _lab_cache[kind] = (key, (found, statuses))
    return found, statuses


# The app's sessions run in parallel threads (Streamlit): resolving and the reader cache are locked.
_lock = threading.RLock()
# Parsers of definitions, by the definition's fingerprint (its content, name included).
_tabular_parsers: Dict[str, Any] = {}


def _parser_of(reader: Reader):
    """The parser of ``reader``: a code parser, the registered one of a built-in, else one kept per definition."""
    from mfethuls.parsers.registry import _PARSER_REGISTRY
    from mfethuls.parsers.tabular import TabularParser

    definition = reader.definition
    registered = _PARSER_REGISTRY.get((reader.type, reader.model))
    if definition is None:
        if registered is None:
            raise ValueError(f"No parser for {reader.type} {reader.model} (reader {reader.name!r})")
        return registered
    if isinstance(registered, TabularParser) and registered.definition == definition:
        return registered
    with _lock:
        parser = _tabular_parsers.get(definition.fingerprint)
        if parser is None or parser.definition != definition:
            parser = _tabular_parsers[definition.fingerprint] = TabularParser(definition)
        return parser


@dataclass
class _Setup:
    readers: Dict[str, Reader]
    instruments: Dict[str, Instrument]
    statuses: List[DefinitionStatus]


def _resolve(data_root: Optional[str]) -> _Setup:
    """Readers and instruments by name, and the lab files' statuses.

    Inside :func:`~mfethuls.manifest.one_scan_per_folder` (one validation, ingest or clean up)
    they are worked out once: otherwise every lookup reads the settings and the lab's files again.
    """
    from mfethuls.manifest import operation_cache

    cache = operation_cache()
    if cache is None:
        with _lock:
            return _resolve_locked(data_root)
    key = ("instruments", data_root)
    if key not in cache:
        with _lock:
            cache[key] = _resolve_locked(data_root)
    return cache[key]


def _resolve_locked(data_root: Optional[str]) -> _Setup:
    readers: Dict[str, Reader] = {}
    for entry in _code_readers():
        name = str(entry["name"]).casefold()
        readers[name] = Reader(name, entry["type"], entry["model"], entry.get("data_layout", "file"),
                               entry.get("description", ""))
    for definition in _builtin():
        readers[definition.name] = _definition_reader(definition, lab=False)

    lab, reader_statuses = _load_files(lab_dir(data_root), "reader")
    by_source = {status.source: status for status in reader_statuses}
    taken: set = set()
    for definition in lab:
        status = by_source[definition.source]
        status.problems = []
        status.active = definition.name not in taken
        if not status.active:
            status.problems = [f"another file already defines the reader {definition.name!r}"]
            continue
        taken.add(definition.name)
        readers[definition.name] = _definition_reader(definition, lab=True)

    instruments = {instrument.name: instrument for instrument in _default_instruments()}
    files, instrument_statuses = _load_files(instruments_dir(data_root), "instrument")
    by_source = {status.source: status for status in instrument_statuses}
    defaults = dict(instruments)
    overridden = {item.name for item in files if item.name in defaults}
    folders = {i.folder_name.casefold(): i.name for i in defaults.values() if i.name not in overridden}
    seen: set = set()
    for item in files:
        status = by_source[item.source]
        status.problems = _instrument_problems(item, readers, folders, seen)
        status.active = not status.problems
        seen.add(item.name)
        if not status.active:
            default = defaults.get(item.name)
            if default is not None:
                taker = folders.get(default.folder_name.casefold())
                if taker is None:
                    folders[default.folder_name.casefold()] = default.name  # the built-in one stays
                elif taker != default.name:  # its folder went to another lab instrument meanwhile
                    instruments.pop(default.name, None)
                    status.problems.append(f"the built-in {default.name} is not used either: its folder "
                                           f"{default.folder_name} is the folder of {taker}")
            continue
        if item.name in defaults:
            item = _replace(item, default_folder=defaults[item.name].folder_name)
        instruments[item.name] = item
        folders[item.folder_name.casefold()] = item.name
    # A built-in instrument whose type lost every reader (cannot happen with the shipped files).
    instruments = {name: i for name, i in instruments.items() if _readers_of(i, readers)}
    return _Setup(readers, dict(sorted(instruments.items())), reader_statuses + instrument_statuses)


def _replace(instrument: Instrument, **changes) -> Instrument:
    from dataclasses import replace

    return replace(instrument, **changes)


def _definition_reader(definition: InstrumentDefinition, *, lab: bool) -> Reader:
    return Reader(definition.name, definition.type, definition.model, definition.data_layout,
                  definition.description, definition, lab)


def _instrument_problems(item: Instrument, readers: Dict[str, Reader], folders: Dict[str, str],
                         seen: set) -> List[str]:
    """Why a lab instrument cannot be used next to the others; empty when it can."""
    from difflib import get_close_matches

    if item.name in seen:
        return [f"another file already defines the instrument {item.name!r}"]
    types = sorted({r.type for r in readers.values()})
    if item.type not in types:
        close = get_close_matches(item.type, types, n=3, cutoff=0.6)
        return [f"no reader reads {item.type!r} data" + (f" (did you mean {', '.join(close)}?)" if close else "")]
    problems = []
    for name in item.readers:
        reader = readers.get(name)
        if reader is None:
            problems.append(f"'readers' names {name!r}, which is not a reader")
        elif reader.type != item.type:
            problems.append(f"'readers' names {name!r}, which reads {reader.type} data, not {item.type}")
    owner = folders.get(item.folder_name.casefold())
    if owner is not None and owner != item.name:
        problems.append(f"{item.folder_name} is already the folder of the instrument {owner}: "
                        "each folder belongs to one instrument")
    return problems


def _readers_of(instrument: Instrument, readers: Dict[str, Reader]) -> List[Reader]:
    if instrument.readers:
        return [readers[name] for name in instrument.readers if name in readers]
    return sorted((r for r in readers.values() if r.type == instrument.type), key=lambda r: r.name)


# -- looking things up -------------------------------------------------------------


def instruments(data_root: Optional[str] = None) -> List[Instrument]:
    """Every instrument, by name."""
    return list(_resolve(data_root).instruments.values())


def get_instrument(name: str, data_root: Optional[str] = None) -> Instrument:
    """The instrument called ``name`` (case ignored); ``ValueError`` when there is none."""
    found = _resolve(data_root).instruments.get(str(name or "").strip().casefold())
    if found is None:
        raise ValueError(f"Unknown instrument {name!r}")
    return found


def instrument_for_folder(folder_name: str, data_root: Optional[str] = None) -> Optional[Instrument]:
    """The instrument reading ``folder_name`` (case ignored), or None."""
    folder = str(folder_name).casefold()
    return next((i for i in instruments(data_root) if i.folder_name.casefold() == folder), None)


def readers(data_root: Optional[str] = None) -> List[Reader]:
    """Every reader, by name."""
    return sorted(_resolve(data_root).readers.values(), key=lambda r: r.name)


def get_reader(name: str, data_root: Optional[str] = None) -> Optional[Reader]:
    """The reader called ``name``, or None."""
    return _resolve(data_root).readers.get(str(name or "").strip().casefold())


def readers_of(instrument: Instrument | str, data_root: Optional[str] = None) -> List[Reader]:
    """The readers of an instrument: those it lists, else every reader of its type."""
    if isinstance(instrument, str):
        instrument = get_instrument(instrument, data_root)
    return _readers_of(instrument, _resolve(data_root).readers)


def measurement_types(data_root: Optional[str] = None) -> List[str]:
    """Every measurement type some reader reads."""
    return sorted({r.type for r in readers(data_root)})


def recognising_readers(candidates: Iterable[Reader], path) -> List[Reader]:
    """The ``candidates`` that recognise ``path``. A reader that recognises it by its content (its
    header marker or text) wins over one that takes any file of its ending: a Flame file has
    the Flame marker, and a reader without a marker would take it too."""
    found = [(r, r.recognition(path)) for r in candidates if r.claims(path)]
    marked = [r for r, by_content in found if by_content]
    return marked or [r for r, by_content in found if by_content is not None]


def reader_for(instrument: Instrument | str, files: Iterable[str], data_root: Optional[str] = None) -> Reader:
    """The reader of an experiment's ``files``: the instrument's one reader claiming their extension,
    or, when several do, the one that recognises the first file they claim (only then is a file
    opened). ``ValueError`` saying why when none or several do."""
    if isinstance(instrument, str):
        instrument = get_instrument(instrument, data_root)
    files = list(files)
    candidates = readers_of(instrument, data_root)
    claiming = [r for r in candidates if any(r.claims(f) for f in files)]
    if len(claiming) == 1:
        return claiming[0]
    if not claiming:
        endings = ", ".join(sorted({os.path.splitext(f)[1] or "(none)" for f in files})) or "no files"
        raise ValueError(f"no {instrument.type} reader reads these files ({endings})")
    first = next(f for f in files if any(r.claims(f) for r in claiming))
    recognising = recognising_readers(claiming, first)
    if len(recognising) == 1:
        return recognising[0]
    names = ", ".join(r.name for r in (recognising or claiming))
    if not recognising:
        raise ValueError(f"{os.path.basename(first)} is none of the {instrument.type} formats mfethuls reads "
                         f"({names}); add a reader for it")
    raise ValueError(f"{os.path.basename(first)} looks like more than one {instrument.type} format ({names}); "
                     "their readers must tell their files apart")


def lab_statuses(data_root: Optional[str] = None) -> List[DefinitionStatus]:
    """One status per lab file, readers then instruments (problems and warnings to show the user)."""
    return _resolve(data_root).statuses


def reader_definitions(data_root: Optional[str] = None) -> List[InstrumentDefinition]:
    """Every definition in use (built-in and the lab's)."""
    return [r.definition for r in readers(data_root) if r.definition is not None]


def builtin_names() -> set:
    """Names of mfethuls' own readers."""
    return {d.name for d in _builtin()} | {str(e["name"]).casefold() for e in _code_readers()}


# -- changing the lab's files -------------------------------------------------------


def _write_json(path: Path, data: Any) -> None:
    from mfethuls._files import replace_with_retry

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf8") as handle:
        handle.write(definition_text(data))
    replace_with_retry(temp, str(path))


def _check_new(item: Instrument, data_root: Optional[str]) -> None:
    """``ValueError`` when ``item`` could not be used next to the other instruments."""
    setup = _resolve(data_root)
    folders = {i.folder_name.casefold(): i.name for i in setup.instruments.values() if i.name != item.name}
    problems = _instrument_problems(item, setup.readers, folders, set())
    if problems:
        raise ValueError("; ".join(problems))


def add_instrument(name: str, type_: str, folder: str, data_root: Optional[str] = None, *,
                   description: str = "") -> Path:
    """Write the lab's file of a new instrument ``name`` of type ``type_`` reading ``folder``.

    Returns the file; ``ValueError`` with the reason when it could not be used (then nothing is written).
    """
    directory = instruments_dir(data_root)
    if directory is None:
        raise ValueError("No data folder: set the data folder before adding instruments.")
    data = {"spec_version": 1, "name": str(name).strip().casefold(), "type": str(type_).strip().casefold(),
            "folder_name": str(folder).strip()}
    if description:
        data["description"] = description
    path = directory / f"{data['name']}.json"
    try:
        item = parse_instrument(data, str(path))
    except DefinitionError as exc:
        raise ValueError("; ".join(exc.problems)) from None
    if item.name in _resolve(data_root).instruments:
        raise ValueError(f"there is already an instrument called {item.name!r}")
    if path.exists():
        raise ValueError(f"the lab's file {path.name} exists but cannot be used: fix or remove it in Settings first")
    _check_new(item, data_root)
    _write_json(path, data)
    logger.info("Added the instrument %s (%s) reading %s", item.name, item.type, item.folder_name)
    return path


def name_from_folder(folder: str, type_: str, data_root: Optional[str] = None) -> str:
    """A name for a new instrument reading ``folder``: the folder's name as an instrument name
    (``DSC room B`` -> ``dsc_room_b``), or ``<type>_<that>`` when it is taken or empty."""
    import re

    taken = {i.name for i in instruments(data_root)}
    base = re.sub(r"[^a-z0-9_-]+", "_", str(folder).casefold()).strip("_-")
    if base and base not in taken:
        return base
    stem = f"{type_}_{base}" if base else type_
    name, number = stem, 2
    while name in taken:
        name, number = f"{stem}_{number}", number + 1
    return name


def folder_taker(type_: str, data_root: Optional[str] = None) -> Optional[Instrument]:
    """The built-in instrument of ``type_`` when its folder is not in the data folder: a folder of
    that type's data that no instrument reads is then its folder (``DSC data`` for ``dsc``)."""
    root = _data_root(data_root)
    builtin = next((i for i in instruments(data_root) if i.type == type_ and i.builtin), None)
    if builtin is None or not root:
        return None
    present = {entry.name.casefold() for entry in os.scandir(root) if entry.is_dir()} if os.path.isdir(root) else set()
    return builtin if builtin.folder_name.casefold() not in present else None


def assign_folder(folder: str, type_: str, name: Optional[str] = None, data_root: Optional[str] = None) -> str:
    """Give ``folder`` (one no instrument reads) an instrument of type ``type_``; returns its name.

    The type's built-in instrument takes it when that instrument's own folder is not in the data
    folder (:func:`folder_taker`); otherwise a new instrument ``name`` (default: from the folder's
    name) reads it, and the built-in one keeps its folder and data.
    """
    taker = folder_taker(type_, data_root)
    if taker is not None:
        set_folder(taker.name, folder, data_root)
        return taker.name
    name = name or name_from_folder(folder, type_, data_root)
    add_instrument(name, type_, folder, data_root)
    return str(name).strip().casefold()


def set_folder(name: str, folder: str, data_root: Optional[str] = None) -> None:
    """Make the instrument ``name`` read ``folder``: its lab file is changed, or for a built-in
    instrument one is written (removed again when ``folder`` is its own folder).
    ``ValueError`` when the folder is not a plain name or another instrument reads it."""
    from mfethuls.naming import file_name_problem

    folder = str(folder).strip()
    if not folder or (issue := file_name_problem(folder)):
        raise ValueError(f"The folder {folder!r} {issue or 'is empty'}.")
    directory = instruments_dir(data_root)
    if directory is None:
        raise ValueError("No data folder: set the data folder before changing an instrument's folder.")
    instrument = get_instrument(name, data_root)
    _check_new(_replace(instrument, folder_name=folder), data_root)
    default = next((i for i in _default_instruments() if i.name == instrument.name), None)
    path = Path(instrument.source) if instrument.source else directory / f"{instrument.name}.json"
    if not instrument.source and path.exists():  # a lab file for it that cannot be used: never overwrite it
        raise ValueError(f"the lab's file {path.name} exists but cannot be used: fix or remove it in Settings first")
    data = json.loads(path.read_text(encoding="utf8")) if instrument.source else \
        {"spec_version": 1, "name": instrument.name, "type": instrument.type}
    data["folder_name"] = folder
    if default is not None and folder == default.folder_name and set(data) <= {"spec_version", "name", "type",
                                                                               "folder_name"}:
        path.unlink(missing_ok=True)  # back to the built-in instrument as it is
    else:
        _write_json(path, data)
    logger.info("The instrument %s now reads the folder %s", instrument.name, folder)


REMOVED_SUBDIR = "removed"


def remove_definition(source, data_root: Optional[str] = None) -> Path:
    """Move a lab file (a reader with its sample, or an instrument) to ``removed/<date-time>/``
    next to it; returns that folder.

    Nothing is deleted: moving the files back restores it. Data already ingested stays where it is.
    """
    from datetime import datetime

    path = Path(source)
    folders = [d for d in (lab_dir(data_root), instruments_dir(data_root)) if d is not None]
    directory = next((d for d in folders if path.parent.resolve() == d.resolve()), None)
    if directory is None or path.suffix != ".json":
        raise ValueError(f"{path.name} is not one of the lab's readers or instruments")
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
    logger.info("Moved %s to %s", path.name, target)
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
    """Write a lab reader's definition and a copy of its sample file; returns the definition's path.

    The definition is checked and must read ``sample``. Raises
    :class:`~mfethuls.instruments.definition.DefinitionError`,
    :class:`~mfethuls.parsers.ingestion.ParseError` or ``FileExistsError``.
    """
    from mfethuls._files import replace_with_retry

    directory = lab_dir(data_root)
    if directory is None:
        raise ValueError("No data folder: set the data folder before adding readers.")
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
    logger.info("Saved reader definition %s", target)
    return target
