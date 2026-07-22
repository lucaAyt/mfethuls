"""Metadata persistence backends (Postgres)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


def _get_create_engine():
    import sys

    storage_module = sys.modules.get("mfethuls.storage")
    return getattr(storage_module, "create_engine", create_engine)

from .config import _get_package_version
from .types import DatasetMetadata, MetadataBackend


class PostgresMetadataBackend(MetadataBackend):
    """Postgres-backed metadata storage using SQLAlchemy."""

    def __init__(self, db_url: str) -> None:
        self.engine = _get_create_engine()(db_url)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        create_experiments = """
        CREATE TABLE IF NOT EXISTS experiments (
            id SERIAL PRIMARY KEY,
            name TEXT,
            experiment_id TEXT UNIQUE,
            instrument_name TEXT,
            raw_data_filename TEXT,
            instrument_type TEXT,
            sample_id TEXT,
            status TEXT,
            registry_measurement_profile TEXT,
            raw_registry_row JSONB,
            registered_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            UNIQUE (instrument_name, raw_data_filename)
        );
        """

        create_datasets = """
        CREATE TABLE IF NOT EXISTS datasets (
            id SERIAL PRIMARY KEY,

            -- Core identifiers (indexed for filtering)
            experiment_id TEXT NOT NULL,
            sample_id TEXT,
            run_id TEXT,
            experiment_name TEXT,
            raw_data_filename TEXT,

            -- Instrument info (indexed for filtering)
            instrument_name TEXT NOT NULL,
            instrument_type TEXT,
            instrument_model TEXT,

            -- Data storage info
            dataset_name TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            local_storage_path TEXT,
            cloud_storage_path TEXT,
            storage_format TEXT DEFAULT 'parquet',

            -- Data shape
            rows INTEGER,
            cols INTEGER,

            -- Processing metadata
            schema_version TEXT,
            measurement_profile TEXT,
            mfethuls_version TEXT,
            schema_normalization JSONB,

            -- Full audit trail (rich provenance metadata)
            provenance JSONB,

            -- Timestamps
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),

            UNIQUE (experiment_id, dataset_name)
        );
        """

        with self.engine.connect() as conn:
            conn.execute(text(create_experiments))
            conn.execute(text(create_datasets))
            conn.commit()

    def persist_metadata(self, metadata: DatasetMetadata) -> Optional[int]:
        insert_sql = text(
            "INSERT INTO datasets ("
            "experiment_id, sample_id, run_id, experiment_name, raw_data_filename, "
            "instrument_name, instrument_type, instrument_model, "
            "dataset_name, storage_path, local_storage_path, cloud_storage_path, storage_format, "
            "rows, cols, schema_version, measurement_profile, mfethuls_version, schema_normalization, provenance, created_at, updated_at"
            ") VALUES ("
            ":experiment_id, :sample_id, :run_id, :experiment_name, :raw_data_filename, "
            ":instrument_name, :instrument_type, :instrument_model, "
            ":dataset_name, :storage_path, :local_storage_path, :cloud_storage_path, :storage_format, "
            ":rows, :cols, :schema_version, :measurement_profile, :mfethuls_version, :schema_normalization, :provenance, now(), now()"
            ") ON CONFLICT (experiment_id, dataset_name) DO UPDATE SET "
            "sample_id = EXCLUDED.sample_id, "
            "run_id = EXCLUDED.run_id, "
            "experiment_name = EXCLUDED.experiment_name, "
            "raw_data_filename = EXCLUDED.raw_data_filename, "
            "instrument_name = EXCLUDED.instrument_name, "
            "instrument_type = EXCLUDED.instrument_type, "
            "instrument_model = EXCLUDED.instrument_model, "
            "storage_path = EXCLUDED.storage_path, "
            "local_storage_path = EXCLUDED.local_storage_path, "
            "cloud_storage_path = EXCLUDED.cloud_storage_path, "
            "storage_format = EXCLUDED.storage_format, "
            "rows = EXCLUDED.rows, "
            "cols = EXCLUDED.cols, "
            "schema_version = EXCLUDED.schema_version, "
            "measurement_profile = EXCLUDED.measurement_profile, "
            "mfethuls_version = EXCLUDED.mfethuls_version, "
            "schema_normalization = EXCLUDED.schema_normalization, "
            "provenance = EXCLUDED.provenance, "
            "updated_at = now() "
            "RETURNING id;"
        )

        schema_norm = metadata.get("schema_normalization")
        provenance = metadata.get("provenance")

        params = {
            "experiment_id": metadata.get("experiment_id"),
            "sample_id": metadata.get("sample_id"),
            "run_id": metadata.get("run_id"),
            "experiment_name": metadata.get("experiment_name"),
            "raw_data_filename": metadata.get("raw_data_filename"),
            "instrument_name": metadata.get("instrument_name"),
            "instrument_type": metadata.get("instrument_type"),
            "instrument_model": metadata.get("instrument_model"),
            "dataset_name": metadata.get("dataset_name"),
            "storage_path": metadata.get("storage_path"),
            "local_storage_path": metadata.get("local_storage_path"),
            "cloud_storage_path": metadata.get("cloud_storage_path"),
            "storage_format": metadata.get("storage_format", "parquet"),
            "rows": metadata.get("rows"),
            "cols": metadata.get("cols"),
            "schema_version": metadata.get("schema_version"),
            "measurement_profile": metadata.get("measurement_profile"),
            "schema_normalization": json.dumps(schema_norm) if isinstance(schema_norm, dict) else schema_norm,
            "provenance": json.dumps(provenance) if isinstance(provenance, dict) else provenance,
            "mfethuls_version": metadata.get("mfethuls_version") or _get_package_version(),
        }
        try:
            with self.engine.connect() as conn:
                res = conn.execute(insert_sql, params)
                conn.commit()
                row = res.fetchone()
                if row is not None:
                    return int(row[0])
        except SQLAlchemyError:
            raise
        return None

    def list_datasets(self, limit: int = 100, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        filters = filters or {}
        where_clauses: List[str] = []
        params: Dict[str, Any] = {"limit": limit}

        allowed = (
            "instrument_name",
            "instrument_type",
            "schema_version",
            "mfethuls_version",
            "experiment_id",
            "measurement_profile",
            "local_storage_path",
            "cloud_storage_path",
        )
        for key in allowed:
            if key in filters and filters[key] is not None:
                where_clauses.append(f"{key} = :{key}")
                params[key] = filters[key]

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql = f"SELECT * FROM datasets {where_sql} ORDER BY updated_at DESC NULLS LAST, created_at DESC LIMIT :limit"

        with self.engine.connect() as conn:
            res = conn.execute(text(sql), params)
            try:
                rows = [dict(r) for r in res.mappings().all()]
            except Exception:
                rows = [dict(r._mapping) for r in res.fetchall()]
        return rows

    def get_dataset_by_id(self, dataset_id: int) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM datasets WHERE id = :id LIMIT 1"
        with self.engine.connect() as conn:
            res = conn.execute(text(sql), {"id": dataset_id})
            try:
                row = res.mappings().first()
            except Exception:
                fetched = res.fetchone()
                row = dict(fetched._mapping) if fetched is not None else None
        return dict(row) if row is not None else None

    def get_dataset_by_name(self, experiment_name: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM datasets WHERE experiment_name = :name ORDER BY created_at DESC LIMIT 1"
        with self.engine.connect() as conn:
            res = conn.execute(text(sql), {"name": experiment_name})
            try:
                row = res.mappings().first()
            except Exception:
                fetched = res.fetchone()
                row = dict(fetched._mapping) if fetched is not None else None
        return dict(row) if row is not None else None
