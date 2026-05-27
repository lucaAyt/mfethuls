"""DuckDB query backend integration."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import pandas as pd

from .config import _get_duckdb_path, _get_duckdb_s3_config, _get_duckdb_s3_endpoint_host

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
        self._conn = _get_duckdb().connect(self.db_path, read_only=read_only)
        self._s3_configured = False
        self._ensure_registry()
        self._rehydrate_views()

    @staticmethod
    def _is_s3_uri(storage_path: str) -> bool:
        return storage_path.strip().lower().startswith("s3://")

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
                KEY_ID '{config.get('access_key_id')}',
                SECRET '{config.get('secret_access_key')}',
                REGION '{config.get('region')}',
                ENDPOINT '{endpoint_host}',
                URL_STYLE 'vhost',
                USE_SSL TRUE
            );
            """
        )

    def _ensure_registry(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_registry (
                table_name TEXT PRIMARY KEY,
                storage_path TEXT NOT NULL,
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
                relation = self._conn.from_parquet(storage_path)
                try:
                    self._conn.unregister(table_name)
                except Exception:
                    pass
                self._conn.register(table_name, relation)
            except Exception:
                continue

    @staticmethod
    def _sanitize_table_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
        return safe or "dataset"

    def register_parquet(self, storage_path: str, table_name: Optional[str] = None, overwrite: bool = True) -> str:
        inferred = table_name or os.path.splitext(os.path.basename(storage_path))[0]
        view_name = self._sanitize_table_name(inferred)
        if self._is_s3_uri(storage_path):
            self._ensure_s3_configured()
        relation = self._conn.from_parquet(storage_path)
        if overwrite:
            try:
                self._conn.unregister(view_name)
            except Exception:
                pass
        self._conn.register(view_name, relation)
        self._conn.execute(
            """
            INSERT INTO dataset_registry (table_name, storage_path)
            VALUES (?, ?)
            ON CONFLICT(table_name)
            DO UPDATE SET storage_path = excluded.storage_path, registered_at = now();
            """,
            [view_name, storage_path],
        )
        return view_name

    def list_registered(self) -> List[Dict[str, Any]]:
        res = self._conn.execute(
            "SELECT table_name, storage_path, registered_at FROM dataset_registry ORDER BY registered_at DESC;"
        )
        rows = res.fetchall()
        return [
            {
                "table_name": row[0],
                "storage_path": row[1],
                "registered_at": row[2],
            }
            for row in rows
        ]

    def query(self, sql: str) -> pd.DataFrame:
        return self._conn.execute(sql).fetch_df()

    def get_sqlalchemy_url(self) -> str:
        if self.db_path == ":memory:":
            return "duckdb:///:memory:"
        path = self.db_path.replace("\\", "/")
        return f"duckdb:///{path}"

    def close(self) -> None:
        self._conn.close()
