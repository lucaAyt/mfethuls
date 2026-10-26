"""Find raw data under PATH_TO_DATA that the registry does not describe yet.

Each instrument reads one folder of the data folder, and each folder belongs to one
instrument (see :mod:`mfethuls.instruments.configured`). Folders no instrument reads are
:func:`unclaimed_folders`, with the measurement type their name suggests. In an instrument folder:

- each file directly in it is one experiment, named by its stem (``poly1.txt`` and
  ``poly1.csv`` are one experiment);
- each subfolder is proposed once, and can be registered either as **one
  experiment** (``raw_data_filename`` = the folder name, all its files together,
  e.g. a Flame spectra series or a Bruker NMR experiment) or **one experiment per
  file** (each file a run of the same sample: R001, R002, ...). A subfolder that
  holds a single stem (``LUB055/LUB055.txt``) is proposed as that file.

Data files are those the instrument's readers read (see
``parsers.registry.data_extensions``). Other files next to the data, such as a
plot saved in the experiment folder, are ignored and listed in ``NewData.ignored``.

The readers' ``data_layout`` (``"folder"`` for a series, or ``"file"``) only sets the
default for subfolders; the person registering decides per folder.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Collection, Dict, Iterable, List, Optional

import pandas as pd

from .experiments import Registry, _normalize_optional_str
from .manifest import MANIFEST_FILENAME, one_scan_per_folder
from .naming import stem_key
from .instruments.configured import Instrument, get_instrument, instruments, reader_for, readers, readers_of
from .parsers.registry import data_extensions
from .settings import get_settings

# Registry columns proposed for new rows, in this order (extra registry columns follow).
REGISTRY_COLUMNS = [
    "name",
    "instrument_name",
    "sample_id",
    "run_id",
    "raw_data_filename",
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
    # The instrument whose folder it is in (a list for display: always one).
    instruments: List[str]
    # Instrument to pre-fill: the folder's instrument when one of its readers reads this kind of item.
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
    # For a subfolder: when each run's files were last changed (by stem), read during the scan.
    run_modified: Dict[str, datetime] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Identifies the item across reruns, e.g. ``DSC/poly1``."""
        return f"{self.folder_name}/{self.raw_data_filename}"


def _visible(name: str) -> bool:
    return not name.startswith(".") and name not in _IGNORED_NAMES and not name.lower().endswith(".parquet")


def _modified(paths: Iterable[str], mtimes: Optional[Dict[str, float]] = None) -> datetime:
    """When the newest of ``paths`` was changed; from ``mtimes`` (read with the listing) where it has them."""
    mtimes = mtimes or {}
    return datetime.fromtimestamp(max(mtimes[p] if p in mtimes else os.path.getmtime(p) for p in paths))


def _walk_files(directory: str, mtimes: Optional[Dict[str, float]] = None) -> List[str]:
    """Visible files under ``directory`` in ``os.walk`` order (sorted, hidden folders skipped).

    One ``os.scandir`` per folder; their modification times go into ``mtimes``. On Windows the
    listing already holds them, so no file is opened or stat'ed again (65,000 files on OneDrive
    took 7 s that way).
    """
    found: List[str] = []
    with os.scandir(directory) as listing:
        entries = sorted(listing, key=lambda e: e.name)
    dirs = []
    for entry in entries:
        if entry.is_dir():
            # Like os.walk: a link to a folder is not followed.
            if not entry.name.startswith(".") and not entry.is_symlink():
                dirs.append(entry.path)
        elif _visible(entry.name):
            found.append(entry.path)
            if mtimes is not None:
                mtimes[entry.path] = entry.stat().st_mtime
    for path in dirs:
        found.extend(_walk_files(path, mtimes))
    return found


def _registered(registry: Registry, instrument_names: set[str]) -> set[str]:
    """Raw data names (as :func:`~mfethuls.manifest.stem_key`) already used by registry rows of these
    instruments (or rows without one).

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
            used.add(stem_key(stem))
    return used


def _by_stem(paths: Iterable[str], extensions: set[str], registered: set[str]) -> Dict[str, List[str]]:
    stems: Dict[str, List[str]] = defaultdict(list)
    for path in paths:
        name = os.path.basename(path)
        stem, ext = os.path.splitext(name)
        # Registered by stem, or by file name (a run named like its folder, see proposed_rows).
        if (_visible(name) and ext.casefold() in extensions and stem_key(stem) not in registered
                and stem_key(name) not in registered):
            stems[stem].append(path)
    return dict(sorted(stems.items()))


def _scan_instrument(instrument: Instrument, data_root: str, registered: set[str]) -> List[NewData]:
    folder_name = instrument.folder_name
    folder = os.path.join(data_root, folder_name)
    if not os.path.isdir(folder):
        return []

    found_readers = readers_of(instrument, data_root)
    readable = {r.name: data_extensions(r.parser) for r in found_readers}
    file_layout = [r.name for r in found_readers if r.layout == "file"]
    folder_layout = [r.name for r in found_readers if r.layout == "folder"]
    every = [instrument.name]
    # Extensions of single-file readers: what can be a run or a file experiment.
    extensions = set().union(*(readable[name] or set() for name in file_layout))
    # Extensions any reader here reads (None: one of them reads every file).
    data = None if None in readable.values() else set().union(*readable.values())

    # Every path below starts with ``folder`` and a separator: cut it off instead of os.path.relpath.
    cut = len(os.path.join(folder, ""))

    def ignored(paths: Iterable[str]) -> List[str]:
        if data is None:
            return []
        return [p[cut:] for p in paths if os.path.splitext(p)[1].casefold() not in data]

    items: List[NewData] = []
    mtimes: Dict[str, float] = {}
    with os.scandir(folder) as listing:
        entries = sorted(listing, key=lambda e: e.name)
    top_files = [e.path for e in entries if e.is_file()]
    mtimes.update((e.path, e.stat().st_mtime) for e in entries if e.is_file())
    for stem, files in _by_stem(top_files, extensions, registered).items():
        others = ignored(f for f in top_files if os.path.splitext(os.path.basename(f))[0] == stem)
        items.append(NewData(folder_name, "file", stem, files, _modified(files, mtimes), every,
                             suggested=instrument.name, ignored=others))

    for entry in entries:
        child, path = entry.name, entry.path
        if not entry.is_dir() or child.startswith(".") or stem_key(child) in registered:
            continue
        found = _walk_files(path, mtimes)
        others = ignored(found)
        skipped = set(others)
        files = [f for f in found if f[cut:] not in skipped]
        if not files:
            continue  # no data in it, e.g. a folder of plots
        runs = _by_stem(files, extensions, registered)
        every_run = _by_stem(files, extensions, set())
        if every_run and not runs:
            continue  # every file in it is already registered as a run
        if len(every_run) == 1 and list(runs) == list(every_run) and len(runs[next(iter(runs))]) == len(files):
            # A folder around a single experiment (LUB055/LUB055.txt) is just that file.
            (stem,) = runs
            items.append(NewData(folder_name, "file", stem, runs[stem], _modified(files, mtimes), every,
                                 suggested=instrument.name, ignored=others))
            continue
        items.append(
            NewData(
                folder_name,
                "folder",
                child,
                files,
                _modified(files, mtimes),
                every,
                suggested=instrument.name,
                runs=runs,
                suggested_for_runs=instrument.name,
                # Folders of single-file instruments are usually runs; series instruments keep them whole.
                split_by_default=bool(runs) and not folder_layout,
                ignored=others,
                run_modified={stem: _modified(paths, mtimes) for stem, paths in runs.items()},
            )
        )

    # A stem in more than one directory, or written in two cases, cannot be found unambiguously at ingest.
    directories: Dict[str, set[str]] = defaultdict(set)
    spellings: Dict[str, set[str]] = defaultdict(set)
    for item in items:
        stems = {item.raw_data_filename: item.files} if item.layout == "file" else item.runs
        for stem, paths in stems.items():
            directories[stem_key(stem)].update(os.path.dirname(p) for p in paths)
            spellings[stem_key(stem)].add(stem)

    def ambiguity(stem: str) -> Optional[str]:
        key = stem_key(stem)
        if len(spellings[key]) > 1:
            return (f"{' and '.join(map(repr, sorted(spellings[key])))} differ only in case; rename one so the "
                    "experiment is unambiguous.")
        if len(directories[key]) < 2:
            return None
        places = ", ".join(os.path.relpath(d, data_root) for d in sorted(directories[key]))
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

    items: List[NewData] = []
    for instrument in sorted(instruments(data_root), key=lambda i: i.folder_name):
        items.extend(_scan_instrument(instrument, data_root, _registered(registry, {instrument.name})))
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
                modified = item.run_modified.get(stem) or _modified(files)
                rows.append(row(raw, item.suggested_for_runs, f"R{number:03d}", item.key, modified, stem))
        else:
            folder = item.key if item.layout == "folder" else item.folder_name
            rows.append(row(item.raw_data_filename, item.suggested, "R001", folder, item.modified))
    return pd.DataFrame(rows, columns=REGISTRY_COLUMNS + extra + ["_folder", "_modified"])



def _files_label(paths: List[str], base: str) -> str:
    return ", ".join(os.path.relpath(path, base).replace(os.sep, "/") for path in sorted(paths))


def tree_rows(items: Iterable[NewData], registry: Registry, data_root: str) -> pd.DataFrame:
    """Every way to register ``items`` (those without an ``issue``), laid out as a folder tree.

    Each file experiment is a row; each subfolder is a row followed by a row per file in it,
    which registers that file as its own experiment (run R001, R002, ... in file-name order).
    Newest first: items by when they last changed (then by path), a subfolder's files too.

    Columns are those of :func:`proposed_rows` plus ``_kind`` (``"file"``, ``"folder"`` or
    ``"run"``), ``_data``, the path shown, ``_open``: whether a subfolder's files are shown (False
    at first; None on other rows, see :func:`visible_rows`), and ``_whole``: whether a subfolder's row registers it
    as one experiment (all its files together, e.g. a titration or time series: the default for
    series instruments, and for a folder without files to register one by one). Otherwise the
    subfolder's row only ticks its files (see :func:`sync_folder_ticks`). A subfolder's row and
    the rows of its files share ``_folder``.
    """

    items = sorted((item for item in items if not item.issue), key=lambda item: item.key.casefold())
    items.sort(key=lambda item: item.modified, reverse=True)  # stable: same time stays in path order
    whole = proposed_rows(items, registry, split=set())
    folders = [item for item in items if item.layout == "folder"]
    per_file = proposed_rows(folders, registry, split={item.key for item in folders})
    parts = []
    for position, item in enumerate(items):
        if item.layout == "file":
            label = f"{item.folder_name}/{_files_label(item.files, os.path.join(data_root, item.folder_name))}"
            parts.append(whole.iloc[[position]].assign(_kind="file", _data=label, _whole=False, _open=None))
            continue
        count = len(item.files)
        runs = [files for stem, files in item.runs.items() if stem not in item.run_issues]
        one = not (item.split_by_default and runs)
        label = f"📁 {item.key}/  ·  {count} file{'s' if count != 1 else ''}" + ("  ·  one experiment" if one else "")
        parts.append(whole.iloc[[position]].assign(_kind="folder", _data=label, _whole=one, _open=False))
        if runs:
            base = os.path.join(data_root, item.folder_name, item.raw_data_filename)
            labels = [f"\u2003\u2003└ {_files_label(files, base)}" for files in runs]
            files = per_file[per_file["_folder"] == item.key].assign(_kind="run", _data=labels, _whole=False,
                                                                     _open=None)
            parts.append(files.sort_values("_modified", ascending=False, kind="stable"))
    columns = list(whole.columns) + ["_kind", "_data", "_whole", "_open"]
    if not parts:
        return pd.DataFrame(columns=columns)
    tree = pd.concat(parts, ignore_index=True)[columns]
    tree["_open"] = tree["_open"].astype(object).where(tree["_kind"] == "folder", None)
    return tree


def visible_rows(tree: pd.DataFrame) -> pd.DataFrame:
    """The rows of a :func:`tree_rows` table to show: files, subfolders, and the files of the
    subfolders that are open (``_open``). Index labels are kept, to apply edits to ``tree``.

    A subfolder's ``_data`` gets ▸ (closed) or ▾ (open) and how many of its files are ticked,
    so ticks are not out of sight while it is closed.
    """

    folders = tree["_kind"] == "folder"
    opened = set(tree.loc[folders & tree["_open"].eq(True), "_folder"])
    shown = tree[(tree["_kind"] != "run") | tree["_folder"].isin(opened)].copy()
    runs = tree[tree["_kind"] == "run"]
    for index in shown.index[shown["_kind"] == "folder"]:
        folder = shown.at[index, "_folder"]
        files = runs[runs["_folder"] == folder]
        if files.empty:
            continue
        label = f"{'▾' if folder in opened else '▸'} {shown.at[index, '_data']}"
        ticked = int(_ticks(files).sum())
        if ticked:
            label += f"  ·  {ticked} of {len(files)} ticked"
        shown.at[index, "_data"] = label
    return shown


def _ticks(tree: pd.DataFrame) -> pd.Series:
    return tree["include"].fillna(False).astype(bool)


# Columns each experiment has its own value of: not filled in from a folder's row.
_OWN_VALUES = {"include", "name", "run_id", "raw_data_filename"}


def _blank(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or (isinstance(value, str) and not value.strip())


def _same(a, b) -> bool:
    return (_blank(a) and _blank(b)) or a == b


def sync_folder_ticks(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """``after`` (a :func:`tree_rows` table with an ``include`` column, edited from ``before``) with
    what was changed on subfolders that only tick their files carried over to those files:

    - ticking or unticking such a folder does the same to its files, which can then be ticked
      or unticked one by one;
    - a value typed in the folder's row (e.g. ``sample_id`` or ``instrument_name``) fills in its
      files that were empty or had the folder's previous value; their own values are kept.

    ``_open`` stays None on rows that are not subfolders."""

    tree = after.copy()
    tree["include"] = _ticks(tree)
    if "_open" in tree:
        tree["_open"] = tree["_open"].astype(object).where(tree["_kind"] == "folder", None)
    changed = tree["include"] != _ticks(before)
    selectors = (tree["_kind"] == "folder") & ~tree["_whole"].fillna(False).astype(bool)
    runs = tree["_kind"] == "run"
    for index in tree.index[selectors & changed]:
        tree.loc[runs & (tree["_folder"] == tree.at[index, "_folder"]), "include"] = tree.at[index, "include"]
    filled = [c for c in tree.columns if not str(c).startswith("_") and c not in _OWN_VALUES]
    for index in tree.index[selectors]:
        files = tree.index[runs & (tree["_folder"] == tree.at[index, "_folder"])]
        for column in filled:
            old, new = before.at[index, column], tree.at[index, column]
            if _same(old, new):
                continue
            for file in files:
                if _same(tree.at[file, column], old):
                    tree.at[file, column] = new
    return tree


def chosen_rows(tree: pd.DataFrame) -> pd.DataFrame:
    """The ticked rows of a :func:`tree_rows` table that are experiments: files, and subfolders
    registered whole (a folder that only ticks its files is not one)."""

    whole = tree["_whole"].fillna(False).astype(bool)
    return tree[_ticks(tree) & ((tree["_kind"] != "folder") | whole)]


def overlapping_folders(rows: pd.DataFrame) -> List[str]:
    """Subfolders among ``rows`` (from :func:`chosen_rows`) chosen both whole and file by file."""

    if rows.empty or "_kind" not in rows:
        return []
    whole = set(rows.loc[rows["_kind"] == "folder", "_folder"])
    split = set(rows.loc[rows["_kind"] == "run", "_folder"])
    return sorted(whole & split)


@lru_cache(maxsize=512)
def _probe_file(reader_name: str, path: str, modified: float, fingerprint: Optional[str] = None,
                data_root: Optional[str] = None) -> Optional[str]:
    """Read one raw file with the reader's parser (one of ``data_root``'s readers); the problem, or
    None. ``modified`` and ``fingerprint`` (the reader's: an edited definition reads again) key the cache."""
    from .config.loader import check_parsed
    from .instruments.configured import get_reader

    reader = get_reader(reader_name, data_root)
    if reader is None:
        return None  # reported by the registry checks
    try:
        dataset = reader.parser.parse(
            {"probe": [path]},
            experiment_id="probe",
            instrument_type=reader.type,
            instrument_model=reader.model,
            instrument_name=reader.name,
        )
        check_parsed(dataset, reader.name)
    except Exception as exc:  # noqa: BLE001 - any failure means "not this reader's data"
        return str(exc)
    return None


@lru_cache(maxsize=4096)
def _sniff_file(reader_name: str, path: str, modified: float, fingerprint: Optional[str] = None,
                data_root: Optional[str] = None) -> Optional[str]:
    """The quick check of one raw file: for a definition, the format it would be read with (its
    ``contains`` text); the problem, or None. Cached like :func:`_probe_file`."""
    from .instruments.configured import get_reader
    from .parsers.tabular import select_format

    reader = get_reader(reader_name, data_root)
    if reader is None or reader.definition is None:
        return None
    try:
        select_format(reader.definition, path)
    except ValueError as exc:
        return str(exc)
    return None


def probe_raw_data(instrument_name: str, raw_data_filename: str, data_root: Optional[str] = None, *,
                   parsed: Optional[set] = None) -> Optional[str]:
    """Whether raw data reads as this instrument's data: the problem, or None.

    The reader is the instrument's reader of these files (:func:`~mfethuls.instruments.configured.reader_for`);
    only their first data file is read. With ``parsed`` (a set shared by the rows being checked),
    only the first file of each reader in each folder is read in full; the others get the quick
    check of :func:`_sniff_file`, so ticking a folder of many files stays quick. A file that passes
    it but still cannot be read is reported at ingest.
    Returns None when the files cannot be found (reported elsewhere).
    """
    from .manifest import find_data_files

    data_root = data_root or get_settings().data_root
    if not data_root:
        return None
    try:
        instrument = get_instrument(instrument_name, data_root)
    except ValueError:
        return None
    try:
        _, files = find_data_files(os.path.join(data_root, instrument.folder_name), raw_data_filename)
    except (FileNotFoundError, ValueError):
        return None
    try:
        reader = reader_for(instrument, files, data_root)
    except ValueError as exc:
        return str(exc)
    data = [f for f in files if reader.claims(f)]
    if not data:
        return None
    first = data[0]
    key = (reader.name, os.path.normcase(os.path.dirname(os.path.abspath(first))))
    fingerprint = getattr(reader.definition, "fingerprint", None)
    if parsed is not None:
        if key in parsed:
            return _sniff_file(reader.name, first, os.path.getmtime(first), fingerprint, data_root)
        parsed.add(key)
    return _probe_file(reader.name, first, os.path.getmtime(first), fingerprint, data_root)


def validate_proposed(registry: Registry, rows: pd.DataFrame, data_root: Optional[str] = None) -> List[dict]:
    """Validation results for new rows, checked together with the existing registry.

    The same checks as a registry preview (``validate_registry_dataframe``), plus three
    that matter for data found on disk: the instrument must be chosen, the raw data
    must be found exactly once (problems the general check only warns about), and it
    must read as the chosen instrument's data (:func:`probe_raw_data`), so files of
    another instrument are not registered and ingested as this one. One file per instrument
    and folder is read in full, the others are checked quickly (see :func:`probe_raw_data`).
    Returns one result per row: ``{"valid", "errors", "warnings", ...}``.
    """

    if rows.empty:
        return []
    with one_scan_per_folder():
        return _validate_proposed(registry, rows, data_root)


def _validate_proposed(registry: Registry, rows: pd.DataFrame, data_root: Optional[str]) -> List[dict]:
    from .registry_validator import validate_registry_dataframe

    data_root = data_root or get_settings().data_root
    helper = [c for c in rows.columns if str(c).startswith("_") or c == "include"]
    combined = pd.concat([registry.frame, rows.drop(columns=helper)], ignore_index=True)
    results = validate_registry_dataframe(combined, check_data_paths=True, data_root=data_root)["rows"]
    results = results[len(registry.frame):]

    parsed: set = set()
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
            problem = probe_raw_data(instrument, raw, data_root, parsed=parsed)
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


@dataclass
class UnclaimedFolder:
    """A folder in the data folder that no instrument reads (``folder_name``)."""

    folder_name: str
    files: List[str]  # paths relative to the folder, up to ``limit``
    file_count: int
    # True when counting stopped at ``max_count``: the folder holds more files.
    more: bool = False
    # The measurement type its name suggests (``DSC room B`` -> ``dsc``), see :func:`suggest_type`.
    suggested_type: Optional[str] = None

    @property
    def count_label(self) -> str:
        """``file_count`` for display: "1,000+" when counting stopped early."""
        return f"{self.file_count:,}+" if self.more else f"{self.file_count:,}"


def instrument_folders(data_root: Optional[str] = None) -> List[os.DirEntry]:
    """Folders directly under ``data_root`` that can hold an instrument's data.

    Hidden folders (``.mfethuls``) and mfethuls' own storage folder (``_storage``, or the
    configured storage folder when it is inside the data folder) are left out.
    """
    data_root = data_root or get_settings().data_root
    if not data_root or not os.path.isdir(data_root):
        return []
    storage = _storage_folders(data_root)
    return sorted(
        (entry for entry in os.scandir(data_root)
         if entry.is_dir() and not entry.name.startswith(".") and os.path.normcase(os.path.abspath(entry.path)) not in storage),
        key=lambda e: e.name.casefold(),
    )


def _storage_folders(data_root: str) -> set:
    """Where mfethuls stores parsed data, as normalised absolute paths."""
    settings = get_settings()
    folders = [os.path.join(data_root, "_storage")]
    if settings.local_storage:
        folders.append(settings.local_storage)
    return {os.path.normcase(os.path.abspath(folder)) for folder in folders}


def unclaimed_folders(
    data_root: Optional[str] = None, *, limit: int = 200, max_count: int = 1000
) -> List[UnclaimedFolder]:
    """Folders directly under ``data_root`` holding files but no instrument.

    Each needs an instrument: one of a type mfethuls reads, or a new reader ("Add instrument").
    Hidden folders (``.mfethuls``) and the storage folder are left out. Counting stops at
    ``max_count`` files per folder, so a large archive folder is not walked to the end.
    """
    known = {instrument.folder_name.casefold() for instrument in instruments(data_root)}
    found = []
    for entry in instrument_folders(data_root):
        if entry.name.casefold() in known:
            continue
        files, count, more = folder_files(entry.path, limit=limit, max_count=max_count)
        if count:
            found.append(UnclaimedFolder(entry.name, files, count, more, suggest_type(entry.name, data_root)))
    return found


def folder_files(path: str, *, limit: int = 200, max_count: int = 1000) -> tuple[List[str], int, bool]:
    """Files under ``path`` (relative to it, up to ``limit``), how many were counted, and whether
    counting stopped at ``max_count``. Hidden files and mfethuls' own files are left out."""
    files: List[str] = []
    count = 0
    for root, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if name in _IGNORED_NAMES or name.startswith("."):
                continue
            if count == max_count:
                return files, count, True
            count += 1
            if len(files) < limit:
                files.append(os.path.relpath(os.path.join(root, name), path))
    return files, count, False


def _words(text: str) -> set:
    return {word for word in re.split(r"[^a-z0-9]+", text.casefold()) if word}


def suggest_type(folder_name: str, data_root: Optional[str] = None) -> Optional[str]:
    """The measurement type ``folder_name`` names, or None: every word of the type, of one of its
    readers or of its built-in folder is a word of ``folder_name`` (``DSC room B`` -> ``dsc``,
    ``inSitu_UV`` -> ``uv_vis`` by its reader ``uv_insitu``, ``Rheometer 2024`` -> ``rheometer``).
    Only a single match is suggested."""
    words = _words(folder_name)
    names: Dict[str, set] = defaultdict(set)
    for reader in readers(data_root):
        names[reader.type].update({reader.type, reader.name})
    for instrument in instruments(data_root):
        names[instrument.type].add(instrument.default_folder or instrument.folder_name)
    matches = [t for t, candidates in names.items() if any(_words(n) and _words(n) <= words for n in candidates)]
    return matches[0] if len(matches) == 1 else None


def recognise_files(paths: Iterable[str], data_root: Optional[str] = None, *, limit: int = 5) -> Dict[str, int]:
    """How many of the first ``limit`` files each reader, of any type, reads: to suggest the type
    of a folder no instrument reads. Each reader that recognises a file reads it, and only those
    giving their type's required columns count (a Mettler DSC export has a TGA export's "Index"
    marker, but not its columns; a reader without a marker recognises any file of its ending).
    Ingest never does this: it only tries the readers of the instrument's type."""
    counts: Dict[str, int] = defaultdict(int)
    every = readers(data_root)
    for path in list(paths)[:limit]:
        found = [r for r in every if data_extensions(r.parser) is not None and r.claims(path) and r.recognises(path)]
        if found:
            modified = os.path.getmtime(path)
            found = [r for r in found
                     if _probe_file(r.name, path, modified, getattr(r.definition, "fingerprint", None),
                                    data_root) is None]
        for reader in found:
            counts[reader.name] += 1
    return dict(counts)
