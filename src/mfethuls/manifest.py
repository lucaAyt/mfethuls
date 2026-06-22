"""Manifest backend: durable experiment_id assignment and raw data file discovery.

experiment_id is auto-assigned at first ingest and persisted so that re-ingestion
and DB resets always produce the same ID for the same raw data file.

Two backends are provided:
- FileManifestBackend  — local mode; reads/writes PATH_TO_DATA/.mfethuls_manifest.json
- PostgresManifestBackend — service mode; uses the experiments Postgres table
"""

from __future__ import annotations

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

    1. **File-stem match** — finds a file whose stem equals ``raw_data_filename``
       and collects all co-located non-parquet files (original behaviour).
    2. **Directory-name match** — finds a directory named ``raw_data_filename``
       and collects all files immediately inside it. This handles
       folder-per-experiment instruments (e.g. UV/Vis in-situ, NMR) where the
       experiment data lives in a named subfolder with no single anchor file.

    Both searches may contribute to the result (combined, deduplicated). Each
    search raises ``ValueError`` if the same name is found in more than one
    location. ``FileNotFoundError`` is raised when neither search finds anything.

    Returns:
        ``(parent_dir, sorted_file_paths)`` — the same contract as before.
    """
    target_stem = Path(raw_data_filename).stem

    file_matched_dirs: dict[str, None] = {}
    dir_matched_folders: list[str] = []

    for root, dirs, files in os.walk(instrument_data_path):
        for fname in files:
            fpath = Path(fname)
            if fpath.suffix.lower() == ".parquet":
                continue
            if fpath.stem == target_stem or fpath.name == raw_data_filename:
                file_matched_dirs[root] = None
                break
        for dirname in dirs:
            if dirname == raw_data_filename:
                dir_matched_folders.append(os.path.join(root, dirname))

    if len(file_matched_dirs) > 1:
        locations = "\n  ".join(sorted(file_matched_dirs))
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

    combined: set[str] = set()
    primary_dir: str | None = None

    if file_matched_dirs:
        parent_dir = next(iter(file_matched_dirs))
        combined.update(_collect_files(parent_dir))
        primary_dir = parent_dir

    if dir_matched_folders:
        folder = dir_matched_folders[0]
        combined.update(_collect_files(folder))
        primary_dir = primary_dir or folder

    if not combined:
        raise FileNotFoundError(
            f"No file or directory named {raw_data_filename!r} found under {instrument_data_path!r}. "
            "Check that PATH_TO_DATA is set correctly and the data exists."
        )

    return primary_dir, sorted(combined)


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
        DB resets and file rearrangement.

        Raises:
            ValueError: The stored experiment_name does not match the provided
                one — the name was changed after first ingest.
        """


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

    def get_or_create_experiment_id(
        self,
        *,
        instrument_name: str,
        raw_data_filename: str,
        experiment_name: str,
    ) -> str:
        manifest = self._read()
        for entry in manifest.get("mappings", []):
            if (
                entry.get("instrument_name") == instrument_name
                and entry.get("raw_data_filename") == raw_data_filename
            ):
                stored_name = entry.get("experiment_name")
                if stored_name != experiment_name:
                    raise ValueError(
                        f"Manifest entry for ({instrument_name!r}, {raw_data_filename!r}) was "
                        f"first ingested as experiment_name={stored_name!r} but the registry now "
                        f"has {experiment_name!r}. The experiment name must not change after first "
                        "ingest. Update the manifest entry or revert the registry name change."
                    )
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

    def all_mappings(self) -> List[Dict[str, Any]]:
        """Return all manifest entries (used by seed_postgres_from_manifest)."""
        return self._read().get("mappings", [])


# ── Postgres-backed backend ───────────────────────────────────────────────────

class PostgresManifestBackend(ManifestBackend):
    """Service-mode manifest backed by the Postgres experiments table.

    Uses INSERT … ON CONFLICT DO NOTHING + SELECT to guarantee idempotent,
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
            "ON CONFLICT (instrument_name, raw_data_filename) DO NOTHING;"
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

        stored_name = row[1]
        if stored_name != experiment_name:
            raise ValueError(
                f"Postgres experiments table entry for ({instrument_name!r}, {raw_data_filename!r}) "
                f"has name={stored_name!r} but the registry has {experiment_name!r}. "
                "The experiment name must not change after first ingest."
            )

        return row[0]


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
        "INSERT INTO experiments (name, experiment_id, instrument_name, raw_data_filename, registered_at) "
        "VALUES (:name, :experiment_id, :instrument_name, :raw_data_filename, now()) "
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
                },
            )
            inserted += result.rowcount

    logger.info("Seeded %d/%d manifest entries into Postgres.", inserted, len(mappings))
    return inserted
