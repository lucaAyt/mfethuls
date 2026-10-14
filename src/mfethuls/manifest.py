"""Manifest backend: durable experiment_id assignment and raw data file discovery.

experiment_id is auto-assigned at first ingest and persisted so that re-ingestion
and DB resets always produce the same ID for the same raw data file. The ID is
keyed on (instrument_name, raw_data_filename); the experiment name comes from the
registry and may change, the manifest just records the latest one. Each entry
also keeps a ``content_hash`` of its raw files (see :func:`content_hash`).

Two backends are provided:
- FileManifestBackend  — local mode; reads/writes PATH_TO_DATA/.mfethuls_manifest.json
- PostgresManifestBackend — service mode; uses the experiments Postgres table
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".mfethuls_manifest.json"
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]+$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_experiment_id() -> str:
    """Generate a 12-char hex UUID suitable for use as an internal experiment_id."""
    return uuid.uuid4().hex[:12]


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
    return sorted(
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
        and not f.endswith(".parquet")
        and f != MANIFEST_FILENAME
    )


def find_data_files(instrument_data_path: str, raw_data_filename: str) -> tuple[str, list[str]]:
    """Walk an instrument folder and return all files for raw_data_filename.

    Two searches run in a single os.walk:

    1. **File-stem match** — collects the non-parquet files whose stem equals
       ``raw_data_filename`` (e.g. ``poly1.txt`` and ``poly1.csv``). Other files
       in the same folder are ignored, so several experiments can share a folder.
    2. **Directory-name match** — finds a directory named ``raw_data_filename``
       and collects all files immediately inside it. This handles
       folder-per-experiment instruments (e.g. UV/Vis in-situ, NMR) where the
       experiment data lives in a named subfolder with no single anchor file.

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
    target_stem = Path(raw_data_filename).stem

    file_matches: dict[str, list[str]] = {}
    dir_matched_folders: list[str] = []

    for root, dirs, files in os.walk(instrument_data_path):
        for fname in files:
            fpath = Path(fname)
            if fpath.suffix.lower() == ".parquet":
                continue
            if fpath.stem == target_stem or fpath.name == raw_data_filename:
                file_matches.setdefault(root, []).append(os.path.join(root, fname))
        for dirname in dirs:
            if dirname == raw_data_filename:
                dir_matched_folders.append(os.path.join(root, dirname))

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
            return parent_dir, sorted(matched)
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
        return parent_dir, sorted(matched)

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
    def all_mappings(self) -> List[Dict[str, Any]]:
        """Every recorded experiment: ``instrument_name``, ``raw_data_filename``,
        ``experiment_id``, ``experiment_name`` and ``content_hash`` (``None`` until parsed)."""


# ── File-based backend ────────────────────────────────────────────────────────

class FileManifestBackend(ManifestBackend):
    """Local-mode manifest stored as JSON at PATH_TO_DATA/.mfethuls_manifest.json.

    Writes are atomic (write-to-temp + os.replace) so concurrent single-machine
    ingestion is safe.
    """

    def __init__(self, data_root: str) -> None:
        self.data_root = data_root
        self._manifest_path = os.path.join(data_root, MANIFEST_FILENAME)

    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self._manifest_path):
            return {"version": "1.0", "mappings": []}
        with open(self._manifest_path, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError:
                logger.warning("Manifest file at %r is corrupted — starting fresh.", self._manifest_path)
                return {"version": "1.0", "mappings": []}
        return data

    def _write_atomic(self, manifest: Dict[str, Any]) -> None:
        tmp_path = self._manifest_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        os.replace(tmp_path, self._manifest_path)

    @staticmethod
    def _find(manifest: Dict[str, Any], instrument_name: str, raw_data_filename: str) -> Optional[Dict[str, Any]]:
        for entry in manifest.get("mappings", []):
            if entry.get("instrument_name") == instrument_name and entry.get("raw_data_filename") == raw_data_filename:
                return entry
        return None

    def get_or_create_experiment_id(
        self,
        *,
        instrument_name: str,
        raw_data_filename: str,
        experiment_name: str,
    ) -> str:
        manifest = self._read()
        entry = self._find(manifest, instrument_name, raw_data_filename)
        if entry is not None:
            if entry.get("experiment_name") != experiment_name:
                entry["experiment_name"] = experiment_name
                self._write_atomic(manifest)
            return entry["experiment_id"]

        experiment_id = generate_experiment_id()
        manifest.setdefault("mappings", []).append(
            {
                "instrument_name": instrument_name,
                "raw_data_filename": raw_data_filename,
                "experiment_id": experiment_id,
                "experiment_name": experiment_name,
                "first_ingested": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write_atomic(manifest)
        logger.debug(
            "Assigned new experiment_id=%s for (%s, %s)",
            experiment_id,
            instrument_name,
            raw_data_filename,
        )
        return experiment_id

    def record_content_hash(self, *, instrument_name: str, raw_data_filename: str, content_hash: str) -> None:
        manifest = self._read()
        entry = self._find(manifest, instrument_name, raw_data_filename)
        if entry is not None and entry.get("content_hash") != content_hash:
            entry["content_hash"] = content_hash
            self._write_atomic(manifest)

    def all_mappings(self) -> List[Dict[str, Any]]:
        return [{"content_hash": None, **entry} for entry in self._read().get("mappings", [])]


# ── Postgres-backed backend ───────────────────────────────────────────────────

class PostgresManifestBackend(ManifestBackend):
    """Service-mode manifest backed by the Postgres experiments table.

    Uses INSERT … ON CONFLICT DO UPDATE (the name) + SELECT to guarantee idempotent,
    race-free ID assignment under concurrent ingestion from multiple workers.

    Requires the experiments table to have a UNIQUE constraint on
    (instrument_name, raw_data_filename) — added by metadata.py _ensure_tables().
    """

    def __init__(self, db_url: str) -> None:
        from sqlalchemy import create_engine
        self.engine = create_engine(db_url)

    def get_or_create_experiment_id(
        self,
        *,
        instrument_name: str,
        raw_data_filename: str,
        experiment_name: str,
    ) -> str:
        from sqlalchemy import text

        select_sql = text(
            "SELECT experiment_id, name FROM experiments "
            "WHERE instrument_name = :instrument_name AND raw_data_filename = :raw_data_filename "
            "LIMIT 1;"
        )
        insert_sql = text(
            "INSERT INTO experiments (name, experiment_id, instrument_name, raw_data_filename, registered_at) "
            "VALUES (:name, :experiment_id, :instrument_name, :raw_data_filename, now()) "
            "ON CONFLICT (instrument_name, raw_data_filename) DO UPDATE SET name = EXCLUDED.name;"
        )

        candidate_id = generate_experiment_id()

        with self.engine.begin() as conn:
            conn.execute(
                insert_sql,
                {
                    "name": experiment_name,
                    "experiment_id": candidate_id,
                    "instrument_name": instrument_name,
                    "raw_data_filename": raw_data_filename,
                },
            )
            row = conn.execute(
                select_sql,
                {"instrument_name": instrument_name, "raw_data_filename": raw_data_filename},
            ).fetchone()

        if row is None:
            raise RuntimeError(
                f"Failed to assign experiment_id for ({instrument_name!r}, {raw_data_filename!r}). "
                "This should not happen — please check Postgres connectivity."
            )

        return row[0]

    def record_content_hash(self, *, instrument_name: str, raw_data_filename: str, content_hash: str) -> None:
        from sqlalchemy import text

        sql = text(
            "UPDATE experiments SET content_hash = :content_hash "
            "WHERE instrument_name = :instrument_name AND raw_data_filename = :raw_data_filename;"
        )
        with self.engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "content_hash": content_hash,
                    "instrument_name": instrument_name,
                    "raw_data_filename": raw_data_filename,
                },
            )

    def all_mappings(self) -> List[Dict[str, Any]]:
        from sqlalchemy import text

        sql = text("SELECT instrument_name, raw_data_filename, experiment_id, name, content_hash FROM experiments;")
        with self.engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [
            {
                "instrument_name": r[0],
                "raw_data_filename": r[1],
                "experiment_id": r[2],
                "experiment_name": r[3],
                "content_hash": r[4],
            }
            for r in rows
        ]


# ── Factory ───────────────────────────────────────────────────────────────────

def get_manifest_backend(
    *,
    data_root: Optional[str],
    db_url: Optional[str],
) -> ManifestBackend:
    """Return the appropriate ManifestBackend for the current mode.

    Postgres is preferred when ``db_url`` is provided (service mode).
    Falls back to the file-based backend for local mode.
    """
    if db_url:
        return PostgresManifestBackend(db_url)
    if not data_root:
        raise ValueError(
            "Cannot create a manifest backend: neither db_url nor data_root is set. "
            "Set PATH_TO_DATA or provide a Postgres db_url."
        )
    return FileManifestBackend(data_root)


# ── Disaster recovery ─────────────────────────────────────────────────────────

def seed_postgres_from_manifest(data_root: str, db_url: str) -> int:
    """Re-populate the Postgres experiments table from the local manifest file.

    Safe to run multiple times — uses INSERT … ON CONFLICT DO NOTHING so
    existing rows are never overwritten.

    Returns the number of rows inserted.
    """
    from sqlalchemy import create_engine, text

    file_backend = FileManifestBackend(data_root)
    mappings = file_backend.all_mappings()
    if not mappings:
        logger.info("Manifest file is empty — nothing to seed.")
        return 0

    engine = create_engine(db_url)
    insert_sql = text(
        "INSERT INTO experiments "
        "(name, experiment_id, instrument_name, raw_data_filename, content_hash, registered_at) "
        "VALUES (:name, :experiment_id, :instrument_name, :raw_data_filename, :content_hash, now()) "
        "ON CONFLICT (instrument_name, raw_data_filename) DO NOTHING;"
    )

    inserted = 0
    with engine.begin() as conn:
        for entry in mappings:
            result = conn.execute(
                insert_sql,
                {
                    "name": entry.get("experiment_name"),
                    "experiment_id": entry.get("experiment_id"),
                    "instrument_name": entry.get("instrument_name"),
                    "raw_data_filename": entry.get("raw_data_filename"),
                    "content_hash": entry.get("content_hash"),
                },
            )
            inserted += result.rowcount

    logger.info("Seeded %d/%d manifest entries into Postgres.", inserted, len(mappings))
    return inserted
