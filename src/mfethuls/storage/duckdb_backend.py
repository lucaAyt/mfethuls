"""DuckDB query backend integration."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Iterator

import pandas as pd

from .catalog import CATALOG_FIELDS, CatalogRecord
from ..naming import view_name
from .config import _get_duckdb_path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Fields copied from a dataset's .metadata.json sidecar when backfilling older catalog rows.
_SIDECAR_FIELDS = (
    "experiment_id", "experiment_name", "instrument_name", "instrument_type",
    "instrument_model", "sample_id", "run_id", "reader_fingerprint", "reader",
)

try:
    import duckdb  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    duckdb = None  # type: ignore


def _get_duckdb():
    import sys

    storage_module = sys.modules.get("mfethuls.storage")
    return getattr(storage_module, "duckdb", duckdb)


def _create_catalog(conn) -> None:
    """Create ``dataset_registry`` and add catalog columns missing from older databases."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_registry (
            table_name TEXT PRIMARY KEY,
            storage_path TEXT NOT NULL,
            experiment_name TEXT,
            raw_data_filename TEXT,
            registered_at TIMESTAMP DEFAULT now()
        );
        """
    )
    for column, sql_type in CATALOG_FIELDS.items():
        conn.execute(f"ALTER TABLE dataset_registry ADD COLUMN IF NOT EXISTS {column} {sql_type};")


def _sidecar_path(storage_path: str) -> str:
    base, _ = os.path.splitext(storage_path)
    return f"{base}.metadata.json"


def _backfill_catalog(conn) -> int:
    """Fill catalog rows registered before the catalog had full records.

    Rows without an ``experiment_id`` get their fields from the dataset's
    ``.metadata.json`` sidecar and their row count from the Parquet file. Only local
    files are read, and a database without such rows costs one query. Returns the
    number of rows updated.
    """

    rows = conn.execute(
        "SELECT table_name, storage_path FROM dataset_registry WHERE experiment_id IS NULL;"
    ).fetchall()
    updated = 0
    for table_name, storage_path in rows:
        sidecar = _sidecar_path(storage_path)
        if DuckDBQueryBackend._is_remote_uri(storage_path) or not os.path.exists(sidecar):
            continue
        try:
            with open(sidecar, encoding="utf8") as handle:
                metadata = json.load(handle)
            values = {name: metadata.get(name) for name in _SIDECAR_FIELDS}
            values["rows"] = conn.execute("SELECT count(*) FROM read_parquet(?);", [storage_path]).fetchone()[0]
            assignments = ", ".join(f"{name} = coalesce(?, {name})" for name in values)
            conn.execute(
                f"UPDATE dataset_registry SET {assignments} WHERE table_name = ?;",
                [*values.values(), table_name],
            )
            updated += 1
        except Exception:
            logger.warning("Could not backfill catalog row %r from %s", table_name, sidecar)
    return updated


class DuckDBQueryBackend:
    """DuckDB-backed query backend for Parquet datasets."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        read_only: bool = False,
        setup: Optional[Callable[[Any], None]] = None,
    ) -> None:
        """Open the catalog at ``db_path`` (default: in the storage folder).

        ``setup(connection)`` runs right after connecting, before views are
        recreated, e.g. to give DuckDB credentials for Parquet files in the cloud.
        """
        if _get_duckdb() is None:
            raise RuntimeError("duckdb is required for DuckDBQueryBackend. Install duckdb.")

        resolved = db_path or _get_duckdb_path()
        self.db_path = resolved if resolved == ":memory:" else os.path.abspath(resolved)
        self.read_only = read_only
        # DuckDB cannot create files or tables in read-only mode. On a fresh
        # deployment the file and schema won't exist yet, so initialise them
        # with a brief write-mode connection before opening read-only.
        if read_only and self.db_path != ":memory:":
            init = _get_duckdb().connect(self.db_path, read_only=False)
            _create_catalog(init)
            _backfill_catalog(init)
            init.close()
        self._conn = _get_duckdb().connect(self.db_path, read_only=read_only)
        if setup is not None:
            setup(self._conn)
        self._ensure_registry()
        # Avoid rehydrating views in read-only mode because the registry
        # table may not exist and rehydration attempts will fail.
        if not self.read_only:
            self._rehydrate_views()
            self.backfill_catalog()

    @staticmethod
    def _is_remote_uri(storage_path: str) -> bool:
        """A cloud location (``s3://``, ``az://``, ...); readable once ``setup`` configured access."""
        return "://" in storage_path

    @staticmethod
    def _is_materializable_storage_path(storage_path: str) -> bool:
        if DuckDBQueryBackend._is_remote_uri(storage_path):
            return True
        normalized = os.path.abspath(storage_path)
        return os.path.exists(normalized)

    @staticmethod
    def _sql_string(value: str) -> str:
        return value.replace("'", "''")

    def _ensure_registry(self) -> None:
        if self.read_only:
            return
        _create_catalog(self._conn)

    def backfill_catalog(self) -> int:
        """Fill catalog rows registered before the catalog had full records (see ``_backfill_catalog``)."""

        if self.read_only:
            return 0
        return _backfill_catalog(self._conn)

    def _rehydrate_views(self) -> None:
        rows = self._conn.execute(
            "SELECT table_name, storage_path FROM dataset_registry;"
        ).fetchall()
        for table_name, storage_path in rows:
            try:
                if self._is_materializable_storage_path(storage_path):
                    self._conn.execute(
                        f'CREATE OR REPLACE VIEW "{self._sql_string(table_name)}" AS SELECT * FROM read_parquet(\'{self._sql_string(storage_path)}\');'
                    )
            except Exception:
                continue

    @staticmethod
    def _sanitize_table_name(name: str) -> str:
        return view_name(name)

    def register_parquet(
        self,
        storage_path: str,
        table_name: Optional[str] = None,
        overwrite: bool = True,
        persist_view: bool = True,
        record: Optional[CatalogRecord] = None,
    ) -> str:
        """Create the view for ``storage_path`` and upsert its catalog row.

        ``record`` fills the catalog row; without it only the view and path are stored.
        """

        if self.read_only:
            raise RuntimeError("Cannot register parquet on a read-only DuckDB connection")
        fields = record.fields() if record is not None else {}
        if record is not None:
            table_name = table_name or record.table_name
        inferred = table_name or os.path.splitext(os.path.basename(storage_path))[0]
        view_name = self._sanitize_table_name(inferred)
        if overwrite:
            try:
                self._conn.unregister(view_name)
            except Exception:
                pass
        if persist_view and self._is_materializable_storage_path(storage_path):
            self._conn.execute(
                f'CREATE OR REPLACE VIEW "{self._sql_string(view_name)}" AS SELECT * FROM read_parquet(\'{self._sql_string(storage_path)}\');'
            )
            columns = ["table_name", "storage_path", *fields]
            updates = ", ".join(f"{column} = excluded.{column}" for column in columns[1:])
            placeholders = ", ".join("?" for _ in columns)
            self._conn.execute(
                f"""
                INSERT INTO dataset_registry ({', '.join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(table_name)
                DO UPDATE SET {updates}, registered_at = now();
                """,
                [view_name, storage_path, *fields.values()],
            )
            if fields.get("experiment_id"):
                self._remove_superseded(fields["experiment_id"], keep=view_name)
        return view_name

    def _remove_superseded(self, experiment_id: str, *, keep: str) -> None:
        """Drop older catalog rows and views of the same experiment under another name.

        The view and file names include sample and run, so correcting either in
        the registry registers the experiment under a new name. The old Parquet
        file is user data and stays on disk; it is named in a warning.
        """

        stale = self._conn.execute(
            "SELECT table_name, storage_path FROM dataset_registry WHERE experiment_id = ? AND table_name <> ?;",
            [experiment_id, keep],
        ).fetchall()
        for table_name, old_path in stale:
            self.remove_dataset(table_name)
            logger.warning(
                "Experiment %s is now registered as %r; removed the old catalog entry %r. "
                "Its file %s is no longer used and can be deleted.",
                experiment_id, keep, table_name, old_path,
            )

    def list_registered(self) -> List[Dict[str, Any]]:
        """All catalog rows, newest first, as dictionaries of every column."""

        columns = ["table_name", "storage_path", *CATALOG_FIELDS, "registered_at"]
        rows = self._conn.execute(
            f"SELECT {', '.join(columns)} FROM dataset_registry ORDER BY registered_at DESC;"
        ).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def remove_dataset(self, table_name: str) -> None:
        if self.read_only:
            raise RuntimeError("Cannot remove dataset on a read-only DuckDB connection")
        safe = self._sql_string(table_name)
        try:
            self._conn.execute(f'DROP VIEW IF EXISTS "{safe}"')
        except Exception:
            pass
        self._conn.execute(
            "DELETE FROM dataset_registry WHERE table_name = ?",
            [table_name],
        )

    def query(self, sql: str, params: Optional[List[Any]] = None) -> pd.DataFrame:
        if params is None:
            params = []
        return self._conn.execute(sql, params).fetch_df()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "DuckDBQueryBackend":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


@contextmanager
def duckdb_session(*, db_path: Optional[str] = None, read_only: bool = True) -> Iterator["DuckDBQueryBackend"]:
    """Open a short-lived DuckDBQueryBackend and close it on exit.

    Opens read-only by default: the app reads the catalog this way, so it does not
    hold DuckDB's single-writer lock while an ingest may need it.
    """
    backend = DuckDBQueryBackend(db_path=db_path, read_only=read_only)
    try:
        yield backend
    finally:
        backend.close()
