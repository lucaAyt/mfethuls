"""DuckDB query backend integration."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Iterator

import pandas as pd

from .config import _get_duckdb_path, _get_duckdb_s3_config, _get_duckdb_s3_endpoint_host
from contextlib import contextmanager

try:
    import duckdb  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    duckdb = None  # type: ignore


def _get_duckdb():
    import sys

    storage_module = sys.modules.get("mfethuls.storage")
    return getattr(storage_module, "duckdb", duckdb)


class DuckDBQueryBackend:
    """DuckDB-backed query backend for Parquet datasets."""

    def __init__(self, db_path: Optional[str] = None, read_only: bool = False) -> None:
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
            init.execute(
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
            init.close()
        self._conn = _get_duckdb().connect(self.db_path, read_only=read_only)
        self._s3_configured = False
        self._ensure_registry()
        # Avoid rehydrating views in read-only mode because the registry
        # table may not exist and rehydration attempts will fail.
        if not self.read_only:
            self._rehydrate_views()

    @staticmethod
    def _is_s3_uri(storage_path: str) -> bool:
        return storage_path.strip().lower().startswith("s3://")

    @staticmethod
    def _is_materializable_storage_path(storage_path: str) -> bool:
        if DuckDBQueryBackend._is_s3_uri(storage_path):
            return True
        normalized = os.path.abspath(storage_path)
        return os.path.exists(normalized)

    @staticmethod
    def _sql_string(value: str) -> str:
        return value.replace("'", "''")

    def _ensure_s3_configured(self) -> None:
        if self._s3_configured:
            return
        self._configure_s3_access()
        self._s3_configured = True

    def _configure_s3_access(self) -> None:
        config = _get_duckdb_s3_config()
        if not all(config.get(key) for key in ("region", "endpoint", "access_key_id", "secret_access_key")):
            return

        try:
            self._conn.execute("INSTALL httpfs;")
            self._conn.execute("LOAD httpfs;")
        except Exception:
            pass

        endpoint_host = _get_duckdb_s3_endpoint_host(config.get("region"), config.get("endpoint"))
        if not endpoint_host:
            return

        self._conn.execute(
            f"""
            CREATE OR REPLACE SECRET do_spaces_secret (
                TYPE S3,
                PROVIDER CONFIG,
                KEY_ID '{self._sql_string(config.get('access_key_id', ''))}',
                SECRET '{self._sql_string(config.get('secret_access_key', ''))}',
                REGION '{self._sql_string(config.get('region', ''))}',
                ENDPOINT '{self._sql_string(endpoint_host)}',
                URL_STYLE 'vhost',
                USE_SSL TRUE
            );
            """
        )

    def _ensure_registry(self) -> None:
        if self.read_only:
            return
        self._conn.execute(
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

    def _rehydrate_views(self) -> None:
        rows = self._conn.execute(
            "SELECT table_name, storage_path FROM dataset_registry;"
        ).fetchall()
        for table_name, storage_path in rows:
            try:
                if self._is_s3_uri(storage_path):
                    self._ensure_s3_configured()
                if self._is_materializable_storage_path(storage_path):
                    self._conn.execute(
                        f'CREATE OR REPLACE VIEW "{self._sql_string(table_name)}" AS SELECT * FROM read_parquet(\'{self._sql_string(storage_path)}\');'
                    )
            except Exception:
                continue

    @staticmethod
    def _sanitize_table_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
        return safe or "dataset"

    def register_parquet(
        self,
        storage_path: str,
        table_name: Optional[str] = None,
        overwrite: bool = True,
        persist_view: bool = True,
        experiment_name: Optional[str] = None,
        raw_data_filename: Optional[str] = None,
    ) -> str:
        if self.read_only:
            raise RuntimeError("Cannot register parquet on a read-only DuckDB connection")
        inferred = table_name or os.path.splitext(os.path.basename(storage_path))[0]
        view_name = self._sanitize_table_name(inferred)
        if self._is_s3_uri(storage_path):
            self._ensure_s3_configured()
        if overwrite:
            try:
                self._conn.unregister(view_name)
            except Exception:
                pass
        if persist_view and self._is_materializable_storage_path(storage_path):
            self._conn.execute(
                f'CREATE OR REPLACE VIEW "{self._sql_string(view_name)}" AS SELECT * FROM read_parquet(\'{self._sql_string(storage_path)}\');'
            )
            self._conn.execute(
                """
                INSERT INTO dataset_registry (table_name, storage_path, experiment_name, raw_data_filename)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(table_name)
                DO UPDATE SET
                    storage_path = excluded.storage_path,
                    experiment_name = excluded.experiment_name,
                    raw_data_filename = excluded.raw_data_filename,
                    registered_at = now();
                """,
                [view_name, storage_path, experiment_name, raw_data_filename],
            )
        return view_name

    def list_registered(self) -> List[Dict[str, Any]]:
        res = self._conn.execute(
            "SELECT table_name, storage_path, experiment_name, raw_data_filename, registered_at "
            "FROM dataset_registry ORDER BY registered_at DESC;"
        )
        rows = res.fetchall()
        return [
            {
                "table_name": row[0],
                "storage_path": row[1],
                "experiment_name": row[2],
                "raw_data_filename": row[3],
                "registered_at": row[4],
            }
            for row in rows
        ]

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

    Mirrors the pattern used by the API layer but stays inside the storage package
    to avoid cross-package imports.
    """
    backend = DuckDBQueryBackend(db_path=db_path, read_only=read_only)
    try:
        yield backend
    finally:
        backend.close()
