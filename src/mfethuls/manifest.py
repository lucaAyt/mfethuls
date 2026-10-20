"""Manifest backend: durable experiment_id assignment and raw data file discovery.

experiment_id is auto-assigned at first ingest and persisted so that re-ingestion
and DB resets always produce the same ID for the same raw data file. The ID is
keyed on (instrument_name, raw_data_filename); the experiment name comes from the
registry and may change, the manifest just records the latest one. Each entry
also keeps a ``content_hash`` of its raw files (see :func:`content_hash`).

:class:`FileManifestBackend` keeps the manifest in PATH_TO_DATA/.mfethuls_manifest.json.
Other backends implement :class:`ManifestBackend`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from filelock import FileLock

from ._files import replace_with_retry
from .naming import natural_key, stem_key

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".mfethuls_manifest.json"
# Copies a sync service keeps when two machines changed the manifest at once
# (OneDrive: ``.mfethuls_manifest-<COMPUTER>.json``). Merged copies are renamed with MERGED_SUFFIX.
CONFLICT_COPY_GLOB = ".mfethuls_manifest-*.json"
MERGED_SUFFIX = ".merged"
# Experiment IDs are derived from their key in this namespace (never change it: IDs would change).
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/lucaAyt/mfethuls/experiment-id")


class ManifestError(RuntimeError):
    """The manifest cannot be read; it is left untouched."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_experiment_id(instrument_name: Optional[str] = None, raw_data_filename: Optional[str] = None,
                           *, attempt: int = 0) -> str:
    """A 12-char hex experiment_id.

    With a key, the ID is derived from it (``instrument_name`` and :func:`stem_key` of
    ``raw_data_filename``): every machine gives the same experiment the same ID, so two
    manifests written at once (a synced data folder) agree, and a lost manifest is rebuilt
    with the same IDs. ``attempt`` > 0 gives the next ID for that key, for the rare case
    where the first is taken (an experiment relinked to another file keeps its old ID).
    Without a key the ID is random.
    """
    if instrument_name is None or raw_data_filename is None:
        return uuid.uuid4().hex[:12]
    key = f"{str(instrument_name).casefold()}/{stem_key(raw_data_filename)}"
    if attempt:
        key += f"#{attempt}"
    return uuid.uuid5(_ID_NAMESPACE, key).hex[:12]


def content_hash(paths: list[str]) -> str:
    """SHA-256 of an experiment's raw files, independent of their names and location.

    Hashes each file's bytes, then the sorted file hashes, so renaming or moving
    the files keeps the hash while any change to their contents alters it.
    """
    file_hashes = []
    for path in paths:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        file_hashes.append(digest.hexdigest())
    return hashlib.sha256("\n".join(sorted(file_hashes)).encode()).hexdigest()


def _collect_files(directory: str) -> list[str]:
    """Every file of a folder-per-experiment, also in its subfolders (Bruker NMR keeps the
    spectrum in ``<expno>/pdata/<procno>/``). Hidden folders, parquet files and the
    manifest are left out. Numbers in names sort as numbers (a series' ``__2`` before ``__10``)."""
    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        found.extend(os.path.join(root, f) for f in files if not f.endswith(".parquet") and f != MANIFEST_FILENAME)
    return sorted(found, key=natural_key)


def find_data_files(instrument_data_path: str, raw_data_filename: str) -> tuple[str, list[str]]:
    """Walk an instrument folder and return all files for raw_data_filename.

    Two searches run in a single os.walk:

    1. **File-stem match** — collects the non-parquet files whose stem equals
       ``raw_data_filename`` (e.g. ``poly1.txt`` and ``poly1.csv``). Other files
       in the same folder are ignored, so several experiments can share a folder.
    2. **Directory-name match** — finds a directory named ``raw_data_filename``
       and collects all files inside it, also in its subfolders. This handles
       folder-per-experiment instruments (e.g. UV/Vis in-situ, NMR) where the
       experiment data lives in a named subfolder with no single anchor file.

    Names are compared ignoring case (:func:`stem_key`); files whose stems differ only in
    case (``LUB446.txt`` and ``lub446.txt``, possible on Linux) are an error.

    Exactly one of the searches may match. A file inside the matching directory
    (``LUB055/LUB055.txt``) is not a conflict: the directory is the experiment.
    ``ValueError`` is raised if a file and a directory match in different places,
    or if either search matches in more than one location. ``FileNotFoundError``
    is raised when neither search finds anything.

    To mean only the files of one stem inside such a directory (registering it as
    one experiment per file), give the file name with its extension: ``LUB055.txt``.

    Returns:
        ``(parent_dir, sorted_file_paths)`` — the same contract as before.
    """
    target_stem = stem_key(Path(raw_data_filename).stem)
    target_name = stem_key(raw_data_filename)

    file_matches: dict[str, list[str]] = {}
    dir_matched_folders: list[str] = []

    for root, dirs, files in os.walk(instrument_data_path):
        for fname in files:
            fpath = Path(fname)
            if fpath.suffix.lower() == ".parquet":
                continue
            if stem_key(fpath.stem) == target_stem or stem_key(fpath.name) == target_name:
                file_matches.setdefault(root, []).append(os.path.join(root, fname))
        for dirname in dirs:
            if stem_key(dirname) == target_name:
                dir_matched_folders.append(os.path.join(root, dirname))

    for root, matched in file_matches.items():
        spellings = sorted({Path(path).stem for path in matched})
        if len(spellings) > 1:
            raise ValueError(
                f"raw_data_filename {raw_data_filename!r} matches files whose names differ only in case in "
                f"{root}: {', '.join(spellings)}. Rename one to remove ambiguity."
            )

    if len(file_matches) > 1:
        locations = "\n  ".join(sorted(file_matches))
        raise ValueError(
            f"raw_data_filename {raw_data_filename!r} matched files in multiple directories:\n"
            f"  {locations}\n"
            "Rename one of the files to remove ambiguity."
        )
    if len(dir_matched_folders) > 1:
        raise ValueError(
            f"raw_data_filename {raw_data_filename!r} matches directories in multiple locations:\n"
            + "\n".join(f"  {p}" for p in dir_matched_folders)
            + "\nRename one to remove ambiguity."
        )
    if file_matches and dir_matched_folders:
        folder = dir_matched_folders[0]
        if all(os.path.commonpath([root, folder]) == folder for root in file_matches):
            files = _collect_files(folder)
            if files:
                return folder, files
            parent_dir, matched = next(iter(file_matches.items()))
            return parent_dir, sorted(matched, key=natural_key)
        matched = next(iter(file_matches.values()))
        raise ValueError(
            f"raw_data_filename {raw_data_filename!r} matches both a file and a directory:\n"
            + "\n".join(f"  {p}" for p in sorted(matched))
            + f"\n  {dir_matched_folders[0]}{os.sep}\n"
            "Use either a single file (stem) or a folder per experiment, not both. "
            "Rename one to remove ambiguity."
        )

    if file_matches:
        parent_dir, matched = next(iter(file_matches.items()))
        return parent_dir, sorted(matched, key=natural_key)

    if dir_matched_folders:
        folder = dir_matched_folders[0]
        files = _collect_files(folder)
        if files:
            return folder, files

    raise FileNotFoundError(
        f"No file or directory named {raw_data_filename!r} found under {instrument_data_path!r}. "
        "Check that PATH_TO_DATA is set correctly and the data exists."
    )


# ── Abstract backend ──────────────────────────────────────────────────────────

class ManifestBackend(ABC):
    """Protocol for durable experiment_id assignment."""

    @abstractmethod
    def get_or_create_experiment_id(
        self,
        *,
        instrument_name: str,
        raw_data_filename: str,
        experiment_name: str,
    ) -> str:
        """Return the stored experiment_id for (instrument_name, raw_data_filename).

        On first call for a given pair, a new UUID is generated and persisted.
        Subsequent calls return the same ID, guaranteeing stability across
        DB resets and file rearrangement. The stored experiment_name is updated
        to ``experiment_name``: the registry decides the name.
        """

    @abstractmethod
    def record_content_hash(self, *, instrument_name: str, raw_data_filename: str, content_hash: str) -> None:
        """Store the :func:`content_hash` of an experiment's raw files on its entry."""

    @abstractmethod
    def forget(self, *, experiment_id: str) -> bool:
        """Remove the entry of ``experiment_id``; ``True`` if there was one."""

    @abstractmethod
    def relink(self, *, experiment_id: str, raw_data_filename: str) -> None:
        """Point the entry of ``experiment_id`` at renamed raw data, keeping the ID."""

    @abstractmethod
    def all_mappings(self) -> List[Dict[str, Any]]:
        """Every recorded experiment: ``instrument_name``, ``raw_data_filename``,
        ``experiment_id``, ``experiment_name`` and ``content_hash`` (``None`` until parsed)."""


# ── File-based backend ────────────────────────────────────────────────────────

class FileManifestBackend(ManifestBackend):
    """Local-mode manifest stored as JSON at PATH_TO_DATA/.mfethuls_manifest.json.

    Every change is read-modify-write under a lock file (``.mfethuls_manifest.json.lock``),
    so processes on this machine (the app, a notebook, the CLI) do not overwrite each
    other's entries. The lock does not reach other machines syncing the same folder.

    The file is replaced atomically: the new content goes to a temporary file that
    is flushed to disk and then swapped in, so readers see the old or the new
    manifest, never half of one. A manifest that cannot be read raises
    :class:`ManifestError` instead of starting over, which would lose every ID.

    Two machines can still write at once; a sync service then keeps both files
    (``CONFLICT_COPY_GLOB``). Their entries are merged when the manifest is read: an
    experiment in a copy only is added (its ID came from the same key, so both machines
    agree); one with a different ID in each is kept as in the main file and logged. After
    the next write a merged copy is renamed ``...json.merged`` (kept, not deleted).
    """

    LOCK_TIMEOUT_S = 60

    def __init__(self, data_root: str) -> None:
        self.data_root = data_root
        self._manifest_path = os.path.join(data_root, MANIFEST_FILENAME)

    def _read_file(self, path: str) -> Dict[str, Any]:
        with open(path, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ManifestError(
                    f"The manifest at {path!r} is not valid JSON ({exc}). It holds the ID of "
                    "every ingested experiment, so nothing was changed. Restore it from a backup or the "
                    "folder's version history (e.g. OneDrive), or fix the JSON by hand."
                ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("mappings", []), list):
            raise ManifestError(f"The manifest at {path!r} has no 'mappings' list.")
        return data

    def conflict_copies(self) -> List[str]:
        """Copies of the manifest a sync service kept beside it (not yet merged)."""
        return sorted(str(p) for p in Path(self.data_root).glob(CONFLICT_COPY_GLOB))

    def _read(self) -> Dict[str, Any]:
        """The manifest, with the entries of its conflict copies merged in."""
        if os.path.exists(self._manifest_path):
            data = self._read_file(self._manifest_path)
        else:
            data = {"version": "1.0", "mappings": []}
        for copy in self.conflict_copies():
            self._merge(data, self._read_file(copy), copy)
        return data

    def _merge(self, data: Dict[str, Any], other: Dict[str, Any], source: str) -> None:
        mappings = data.setdefault("mappings", [])
        ids = {entry.get("experiment_id") for entry in mappings}
        for entry in other.get("mappings", []):
            mine = self._find(data, entry.get("instrument_name", ""), entry.get("raw_data_filename", ""))
            if mine is None:
                if entry.get("experiment_id") in ids:
                    logger.warning("Manifest copy %s: experiment_id %s of %s/%s is already used; not merged.",
                                   os.path.basename(source), entry.get("experiment_id"),
                                   entry.get("instrument_name"), entry.get("raw_data_filename"))
                    continue
                mappings.append(dict(entry))
                ids.add(entry.get("experiment_id"))
            elif mine.get("experiment_id") != entry.get("experiment_id"):
                logger.warning("Manifest copy %s gives %s/%s the experiment_id %s; keeping %s from the manifest.",
                               os.path.basename(source), entry.get("instrument_name"),
                               entry.get("raw_data_filename"), entry.get("experiment_id"),
                               mine.get("experiment_id"))
            elif not mine.get("content_hash") and entry.get("content_hash"):
                mine["content_hash"] = entry["content_hash"]

    def _mark_merged(self, copies: List[str]) -> None:
        for copy in copies:
            try:
                replace_with_retry(copy, copy + MERGED_SUFFIX)
            except OSError as exc:  # merged again next time: merging is idempotent
                logger.warning("Could not rename the merged manifest copy %s: %s", copy, exc)

    def _write_atomic(self, manifest: Dict[str, Any]) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=self.data_root, prefix=MANIFEST_FILENAME + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            replace_with_retry(tmp_path, self._manifest_path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def _update(self, change: Callable[[Dict[str, Any]], Tuple[Any, bool]]) -> Any:
        """Apply ``change(manifest) -> (result, changed)`` under the lock; write if changed."""

        with FileLock(self._manifest_path + ".lock", timeout=self.LOCK_TIMEOUT_S):
            copies = self.conflict_copies()
            manifest = self._read()
            result, changed = change(manifest)
            if changed or copies:
                self._write_atomic(manifest)
                self._mark_merged(copies)
        return result

    @staticmethod
    def _find(manifest: Dict[str, Any], instrument_name: str, raw_data_filename: str) -> Optional[Dict[str, Any]]:
        instrument, raw = str(instrument_name).casefold(), stem_key(raw_data_filename)
        for entry in manifest.get("mappings", []):
            if (str(entry.get("instrument_name")).casefold() == instrument
                    and stem_key(entry.get("raw_data_filename", "")) == raw):
                return entry
        return None

    def get_or_create_experiment_id(
        self,
        *,
        instrument_name: str,
        raw_data_filename: str,
        experiment_name: str,
    ) -> str:
        def change(manifest):
            entry = self._find(manifest, instrument_name, raw_data_filename)
            if entry is not None:
                renamed = entry.get("experiment_name") != experiment_name
                entry["experiment_name"] = experiment_name
                return entry["experiment_id"], renamed
            used = {e.get("experiment_id") for e in manifest.get("mappings", [])}
            attempt = 0
            experiment_id = generate_experiment_id(instrument_name, raw_data_filename)
            while experiment_id in used:
                attempt += 1
                experiment_id = generate_experiment_id(instrument_name, raw_data_filename, attempt=attempt)
            manifest.setdefault("mappings", []).append(
                {
                    "instrument_name": instrument_name,
                    "raw_data_filename": raw_data_filename,
                    "experiment_id": experiment_id,
                    "experiment_name": experiment_name,
                    "first_ingested": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.debug("Assigned new experiment_id=%s for (%s, %s)", experiment_id, instrument_name, raw_data_filename)
            return experiment_id, True

        return self._update(change)

    def record_content_hash(self, *, instrument_name: str, raw_data_filename: str, content_hash: str) -> None:
        def change(manifest):
            entry = self._find(manifest, instrument_name, raw_data_filename)
            if entry is None or entry.get("content_hash") == content_hash:
                return None, False
            entry["content_hash"] = content_hash
            return None, True

        self._update(change)

    def forget(self, *, experiment_id: str) -> bool:
        def change(manifest):
            kept = [e for e in manifest.get("mappings", []) if e.get("experiment_id") != experiment_id]
            removed = len(kept) != len(manifest.get("mappings", []))
            manifest["mappings"] = kept
            return removed, removed

        return self._update(change)

    def relink(self, *, experiment_id: str, raw_data_filename: str) -> None:
        def change(manifest):
            for entry in manifest.get("mappings", []):
                if entry.get("experiment_id") == experiment_id:
                    entry["raw_data_filename"] = raw_data_filename
                    return None, True
            raise KeyError(f"No manifest entry with experiment_id {experiment_id!r}")

        self._update(change)

    def all_mappings(self) -> List[Dict[str, Any]]:
        return [{"content_hash": None, **entry} for entry in self._read().get("mappings", [])]
