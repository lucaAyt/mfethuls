"""Find raw data under PATH_TO_DATA that the registry does not describe yet.

Each instrument has a ``folder_name`` in ``config/instrument_params.json``;
several can share one (the DSC models share ``DSC/``). In an instrument folder:

- each file directly in it is one experiment, named by its stem (``poly1.txt`` and
  ``poly1.csv`` are one experiment);
- each subfolder is proposed once, and can be registered either as **one
  experiment** (``raw_data_filename`` = the folder name, all its files together,
  e.g. a Flame spectra series or a Bruker NMR experiment) or **one experiment per
  file** (each file a run of the same sample: R001, R002, ...). A subfolder that
  holds a single stem (``LUB055/LUB055.txt``) is proposed as that file.

Data files are those the instruments' parsers read (see
``parsers.registry.data_extensions``). Other files next to the data, such as a
plot saved in the experiment folder, are ignored and listed in ``NewData.ignored``.

The instrument's ``data_layout`` (``"folder"`` or ``"file"``) only sets the
default for subfolders; the person registering decides per folder.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Collection, Dict, Iterable, List, Optional

import pandas as pd

from .experiments import Registry, _normalize_optional_str
from .manifest import MANIFEST_FILENAME
from .parsers.registry import data_extensions, get_parser
from .registry_validator import _load_instrument_config
from .settings import get_settings

# Registry columns proposed for new rows, in this order (extra registry columns follow).
REGISTRY_COLUMNS = [
    "name",
    "instrument_name",
    "sample_id",
    "run_id",
    "raw_data_filename",
    "measurement_profile",
    "description",
]
_IGNORED_NAMES = {MANIFEST_FILENAME, ".gitkeep"}


@dataclass
class NewData:
    """Raw data that no registry row describes: a file stem, or a subfolder.

    For a subfolder, ``runs`` maps each unregistered file stem inside it to its
    files, for registering the folder as one experiment per file.
    """

    folder_name: str
    layout: str  # "file" or "folder"
    raw_data_filename: str
    files: List[str]
    modified: datetime
    # Instruments that use this folder.
    instruments: List[str]
    # Instrument to pre-fill: the only one for this kind of data, if there is one.
    suggested: Optional[str] = None
    runs: Dict[str, List[str]] = field(default_factory=dict)
    # For a subfolder registered per file: instrument to pre-fill for its runs.
    suggested_for_runs: Optional[str] = None
    # Runs that cannot be registered per file, with the reason (they are left out of proposals).
    run_issues: Dict[str, str] = field(default_factory=dict)
    # For a subfolder: register it as one experiment per file unless told otherwise.
    split_by_default: bool = False
    # Why it cannot be registered as found (e.g. the same name in two folders).
    issue: Optional[str] = None
    # Files next to the data that no instrument here reads (plots, notes); ingest skips them.
    ignored: List[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Identifies the item across reruns, e.g. ``DSC/poly1``."""
        return f"{self.folder_name}/{self.raw_data_filename}"


def _visible(name: str) -> bool:
    return not name.startswith(".") and name not in _IGNORED_NAMES and not name.lower().endswith(".parquet")


def _modified(paths: Iterable[str]) -> datetime:
    return datetime.fromtimestamp(max(os.path.getmtime(path) for path in paths))


def _walk_files(directory: str) -> List[str]:
    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        found.extend(os.path.join(root, f) for f in sorted(files) if _visible(f))
    return found


def _registered(registry: Registry, instrument_names: set[str]) -> set[str]:
    """Raw data names already used by registry rows of these instruments (or rows without one).

    Rows skipped as invalid still count, so their data is not proposed again.
    """

    frame = registry.frame
    if frame.empty or "name" not in frame:
        return set()
    used = set()
    for rec in frame.to_dict(orient="records"):
        instrument = _normalize_optional_str(rec.get("instrument_name"))
        if instrument is not None and instrument.casefold() not in instrument_names:
            continue
        stem = _normalize_optional_str(rec.get("raw_data_filename")) or _normalize_optional_str(rec.get("name"))
        if stem:
            used.add(stem)
    return used


def _by_stem(paths: Iterable[str], extensions: set[str], registered: set[str]) -> Dict[str, List[str]]:
    stems: Dict[str, List[str]] = defaultdict(list)
    for path in paths:
        name = os.path.basename(path)
        stem, ext = os.path.splitext(name)
        # Registered by stem, or by file name (a run named like its folder, see proposed_rows).
        if _visible(name) and ext.casefold() in extensions and stem not in registered and name not in registered:
            stems[stem].append(path)
    return dict(sorted(stems.items()))


def _scan_group(folder_name: str, entries: list[dict], data_root: str, registered: set[str]) -> List[NewData]:
    folder = os.path.join(data_root, folder_name)
    if not os.path.isdir(folder):
        return []

    file_layout = [e["name"] for e in entries if e["data_layout"] == "file"]
    folder_layout = [e["name"] for e in entries if e["data_layout"] == "folder"]
    every = [e["name"] for e in entries]
    readable = {e["name"]: data_extensions(get_parser(e["type"], e["model"])) for e in entries}
    # Extensions of single-file instruments: what can be a run or a file experiment.
    extensions = set().union(*(readable[name] or set() for name in file_layout))
    # Extensions any instrument here reads (None: one of them reads every file).
    data = None if None in readable.values() else set().union(*readable.values())

    def ignored(paths: Iterable[str]) -> List[str]:
        if data is None:
            return []
        return [os.path.relpath(p, folder) for p in paths if os.path.splitext(p)[1].casefold() not in data]

    def only(names: List[str]) -> Optional[str]:
        return names[0] if len(names) == 1 else (every[0] if len(every) == 1 else None)

    items: List[NewData] = []
    top_files = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, f))]
    for stem, files in _by_stem(top_files, extensions, registered).items():
        others = ignored(f for f in top_files if os.path.splitext(os.path.basename(f))[0] == stem)
        items.append(NewData(folder_name, "file", stem, files, _modified(files), every, suggested=only(file_layout),
                             ignored=others))

    for child in sorted(os.listdir(folder)):
        path = os.path.join(folder, child)
        if not os.path.isdir(path) or child.startswith(".") or child in registered:
            continue
        found = _walk_files(path)
        others = ignored(found)
        files = [f for f in found if os.path.relpath(f, folder) not in others]
        if not files:
            continue  # no data in it, e.g. a folder of plots
        runs = _by_stem(files, extensions, registered)
        every_run = _by_stem(files, extensions, set())
        if every_run and not runs:
            continue  # every file in it is already registered as a run
        if len(every_run) == 1 and list(runs) == list(every_run) and len(runs[next(iter(runs))]) == len(files):
            # A folder around a single experiment (LUB055/LUB055.txt) is just that file.
            (stem,) = runs
            items.append(NewData(folder_name, "file", stem, runs[stem], _modified(files), every,
                                 suggested=only(file_layout), ignored=others))
            continue
        items.append(
            NewData(
                folder_name,
                "folder",
                child,
                files,
                _modified(files),
                every,
                suggested=only(folder_layout),
                runs=runs,
                suggested_for_runs=only(file_layout),
                # Folders of single-file instruments are usually runs; series instruments keep them whole.
                split_by_default=bool(runs) and not folder_layout,
                ignored=others,
            )
        )

    # A stem in more than one directory cannot be found unambiguously at ingest.
    directories: Dict[str, set[str]] = defaultdict(set)
    for item in items:
        stems = {item.raw_data_filename: item.files} if item.layout == "file" else item.runs
        for stem, paths in stems.items():
            directories[stem].update(os.path.dirname(p) for p in paths)
    def ambiguity(stem: str) -> Optional[str]:
        if len(directories[stem]) < 2:
            return None
        places = ", ".join(os.path.relpath(d, data_root) for d in sorted(directories[stem]))
        return f"'{stem}' exists in several folders ({places}); rename one so the experiment is unambiguous."

    for item in items:
        if item.layout == "file":
            item.issue = ambiguity(item.raw_data_filename)
        else:
            item.run_issues = {stem: msg for stem in item.runs if (msg := ambiguity(stem))}
    return items


def discover_unregistered(registry: Registry, data_root: Optional[str] = None) -> List[NewData]:
    """Raw data under ``data_root`` (default ``PATH_TO_DATA``) without a registry row."""

    data_root = data_root or get_settings().data_root
    if not data_root:
        raise ValueError("No data folder to scan. Set PATH_TO_DATA or pass data_root.")

    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in _load_instrument_config():
        groups[entry["folder_name"]].append(entry)

    items: List[NewData] = []
    for folder_name, entries in sorted(groups.items()):
        registered = _registered(registry, {entry["name"].casefold() for entry in entries})
        items.extend(_scan_group(folder_name, entries, data_root, registered))
    return items


def _unique_name(base: str, taken: set[str]) -> str:
    name, counter = base, 2
    while name in taken:
        name, counter = f"{base}_{counter}", counter + 1
    taken.add(name)
    return name


def proposed_rows(
    items: Iterable[NewData],
    registry: Registry,
    *,
    split: Optional[Collection[str]] = None,
) -> pd.DataFrame:
    """Registry rows for ``items`` (those without an ``issue``), pre-filled where the data says enough.

    ``split`` holds the keys of subfolders to register as one experiment per file;
    by default each subfolder follows ``NewData.split_by_default``. Split folders get
    one row per file with ``run_id`` R001, R002, ... in file-name order; runs listed in
    ``NewData.run_issues`` are left out. A run named like its folder (``LUB055/LUB055.txt``)
    gets its file name as ``raw_data_filename``, since the bare name means the whole folder.

    ``name`` is the raw data name, made unique; ``instrument_name`` is pre-filled
    when only one instrument fits that kind of data. Helper columns ``_folder`` and
    ``_modified`` describe the data and are not part of the registry.
    """

    items = [item for item in items if not item.issue]
    if split is None:
        split = {item.key for item in items if item.split_by_default}
    extra = [c for c in registry.frame.columns if c not in REGISTRY_COLUMNS]
    taken = set(registry.frame["name"].dropna().astype(str)) if "name" in registry.frame else set()

    def row(raw_data_filename, instrument, run_id, folder, modified, name=None):
        values = {column: None for column in REGISTRY_COLUMNS + extra}
        values.update(
            name=_unique_name(name or raw_data_filename, taken),
            instrument_name=instrument,
            run_id=run_id,
            raw_data_filename=raw_data_filename,
            _folder=folder,
            _modified=modified,
        )
        return values

    rows = []
    for item in items:
        if item.layout == "folder" and item.key in split and item.runs:
            runs = [(stem, files) for stem, files in item.runs.items() if stem not in item.run_issues]
            for number, (stem, files) in enumerate(runs, start=1):
                raw = os.path.basename(files[0]) if stem == item.raw_data_filename else stem
                rows.append(row(raw, item.suggested_for_runs, f"R{number:03d}", item.key, _modified(files), stem))
        else:
            folder = item.key if item.layout == "folder" else item.folder_name
            rows.append(row(item.raw_data_filename, item.suggested, "R001", folder, item.modified))
    return pd.DataFrame(rows, columns=REGISTRY_COLUMNS + extra + ["_folder", "_modified"])


@lru_cache(maxsize=512)
def _probe_file(instrument_name: str, path: str, modified: float) -> Optional[str]:
    """Read one raw file with the instrument's parser; the problem, or None. ``modified`` keys the cache."""
    from .config.loader import check_parsed
    from .parsers.registry import reads

    entry = next((e for e in _load_instrument_config() if e["name"] == instrument_name), None)
    if entry is None:
        return None  # unknown instruments are reported by the registry checks
    parser = get_parser(entry["type"], entry["model"])
    if not reads(parser, path):
        return f"{os.path.basename(path)} is not a {instrument_name} file type"
    try:
        dataset = parser.parse(
            {"probe": [path]},
            experiment_id="probe",
            instrument_type=entry["type"],
            instrument_model=entry["model"],
            instrument_name=instrument_name,
        )
        check_parsed(dataset, instrument_name)
    except Exception as exc:  # noqa: BLE001 - any failure means "not this instrument's data"
        return str(exc)
    return None


def probe_raw_data(instrument_name: str, raw_data_filename: str, data_root: Optional[str] = None) -> Optional[str]:
    """Whether raw data reads as this instrument's data: the problem, or None.

    Reads only the first data file, so it is quick enough to run while rows are edited.
    Returns None when the files cannot be found (reported elsewhere).
    """
    from .manifest import find_data_files
    from .parsers.registry import reads

    data_root = data_root or get_settings().data_root
    entry = next((e for e in _load_instrument_config() if e["name"] == instrument_name), None)
    if entry is None or not data_root:
        return None
    try:
        _, files = find_data_files(os.path.join(data_root, entry["folder_name"]), raw_data_filename)
    except (FileNotFoundError, ValueError):
        return None
    parser = get_parser(entry["type"], entry["model"])
    data = [f for f in files if reads(parser, f)] or files
    if not data:
        return None
    return _probe_file(instrument_name, data[0], os.path.getmtime(data[0]))


def validate_proposed(registry: Registry, rows: pd.DataFrame, data_root: Optional[str] = None) -> List[dict]:
    """Validation results for new rows, checked together with the existing registry.

    The same checks as a registry preview (``validate_registry_dataframe``), plus three
    that matter for data found on disk: the instrument must be chosen, the raw data
    must be found exactly once (problems the general check only warns about), and it
    must read as the chosen instrument's data (:func:`probe_raw_data`), so files of
    another instrument are not registered and ingested as this one.
    Returns one result per row: ``{"valid", "errors", "warnings", ...}``.
    """

    from .registry_validator import validate_registry_dataframe

    if rows.empty:
        return []
    data_root = data_root or get_settings().data_root
    helper = [c for c in rows.columns if str(c).startswith("_") or c == "include"]
    combined = pd.concat([registry.frame, rows.drop(columns=helper)], ignore_index=True)
    results = validate_registry_dataframe(combined, check_data_paths=True, data_root=data_root)["rows"]
    results = results[len(registry.frame):]

    for result in results:
        if not _normalize_optional_str(result["values"].get("instrument_name")):
            result["errors"].append({"field": "instrument_name", "message": "Choose the instrument."})
        data_problems = [w for w in result["warnings"] if w["field"] == "data_path"]
        result["warnings"] = [w for w in result["warnings"] if w["field"] != "data_path"]
        # Only the "no instrument" registry warning is replaced by the error above.
        result["warnings"] = [w for w in result["warnings"] if "missing instrument_name" not in w["message"]]
        result["errors"].extend(data_problems)
        values = result["values"]
        instrument = _normalize_optional_str(values.get("instrument_name"))
        raw = _normalize_optional_str(values.get("raw_data_filename")) or _normalize_optional_str(values.get("name"))
        if not result["errors"] and instrument and raw:
            problem = probe_raw_data(instrument, raw, data_root)
            if problem:
                result["errors"].append({
                    "field": "instrument_name",
                    "message": f"This does not read as {instrument} data ({problem}). Is the instrument right?",
                })
        result["valid"] = not result["errors"]
    return results


def filter_new_data(
    items: Iterable[NewData],
    *,
    modified_since: Optional[datetime] = None,
    folders: Optional[Collection[str]] = None,
    text: Optional[str] = None,
) -> List[NewData]:
    """The items matching every given filter, newest first.

    - ``modified_since``: items whose newest file is at least this recent
    - ``folders``: instrument folders to keep (``None`` keeps all)
    - ``text``: case-insensitive part of the file or folder name; for a subfolder,
      the names of the files inside it count too
    """

    needle = (text or "").strip().casefold()

    def matches(item: NewData) -> bool:
        if modified_since is not None and item.modified < modified_since:
            return False
        if folders is not None and item.folder_name not in folders:
            return False
        if needle:
            names = [item.raw_data_filename, *item.runs, *(os.path.basename(path) for path in item.files)]
            return any(needle in name.casefold() for name in names)
        return True

    return sorted((item for item in items if matches(item)), key=lambda item: item.modified, reverse=True)
