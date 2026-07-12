from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

from . import get_postgres_db_url

try:
    from sqlalchemy import create_engine, text
except Exception as exc:  # pragma: no cover - optional dependency
    raise RuntimeError("sqlalchemy is required for the job store.") from exc

_ENGINE = None
_SCHEMA_READY = False


def _get_job_db_url() -> str:
    url = os.environ.get("MFETHULS_JOB_DB_URL") or get_postgres_db_url()
    if not url:
        raise RuntimeError("Postgres is required for the job store. Set MFETHULS_JOB_DB_URL or enable MFETHULS_POSTGRES_*. ")
    return url


def _get_engine():
    global _ENGINE, _SCHEMA_READY
    if _ENGINE is None:
        _ENGINE = create_engine(_get_job_db_url(), future=True)
    if not _SCHEMA_READY:
        _ensure_schema(_ENGINE)
        _SCHEMA_READY = True
    return _ENGINE


def _ensure_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ingest_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    progress INT NOT NULL DEFAULT 0,
                    message TEXT,
                    storage_mode TEXT,
                    cloud_provider TEXT,
                    job_registry_storage_path TEXT,
                    registry_table TEXT,
                    datasets JSONB,
                    refresh BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL DEFAULT now(),
                    updated_at TIMESTAMP NOT NULL DEFAULT now()
                );
                """
            )
        )
        # Migrate existing tables that pre-date the refresh column.
        conn.execute(text(
            "ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS refresh BOOLEAN NOT NULL DEFAULT FALSE;"
        ))

def _row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    datasets = data.get("datasets")
    if isinstance(datasets, str):
        try:
            data["datasets"] = json.loads(datasets)
        except Exception:
            data["datasets"] = []
    return data


def create_job(
    job_id: Optional[str],
    job_registry_storage_path: str,
    storage_mode: Optional[str],
    cloud_provider: Optional[str],
    refresh: bool = False,
) -> str:
    engine = _get_engine()
    resolved_job_id = job_id or uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ingest_jobs (
                    job_id,
                    status,
                    progress,
                    message,
                    storage_mode,
                    cloud_provider,
                    job_registry_storage_path,
                    refresh
                )
                VALUES (:job_id, 'queued', 0, 'queued', :storage_mode, :cloud_provider, :job_registry_storage_path, :refresh);
                """
            ),
            {
                "job_id": resolved_job_id,
                "storage_mode": storage_mode,
                "cloud_provider": cloud_provider,
                "job_registry_storage_path": job_registry_storage_path,
                "refresh": refresh,
            },
        )
    return resolved_job_id


def update_job(job_id: str, **fields: Any) -> Dict[str, Any]:
    if not fields:
        return get_job(job_id) or {}

    assignments = []
    params: Dict[str, Any] = {"job_id": job_id}
    for key, value in fields.items():
        if key == "datasets":
            params[key] = json.dumps(value)
            assignments.append(f"{key} = CAST(:{key} AS JSONB)")
        else:
            params[key] = value
            assignments.append(f"{key} = :{key}")

    assignments.append("updated_at = now()")
    stmt = f"UPDATE ingest_jobs SET {', '.join(assignments)} WHERE job_id = :job_id;"

    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text(stmt), params)

    return get_job(job_id) or {}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    engine = _get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                SELECT job_id, status, progress, message, storage_mode, cloud_provider,
                       job_registry_storage_path, registry_table, datasets, created_at, updated_at
                FROM ingest_jobs
                WHERE job_id = :job_id;
                """
            ),
            {"job_id": job_id},
        )
        row = result.mappings().first()
    if row is None:
        return None
    return _row_to_dict(row)


def claim_next_job() -> Optional[Dict[str, Any]]:
    engine = _get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                WITH next_job AS (
                    SELECT job_id
                    FROM ingest_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE ingest_jobs
                SET status = 'running', updated_at = now()
                WHERE job_id IN (SELECT job_id FROM next_job)
                RETURNING job_id, status, progress, message, storage_mode, cloud_provider,
                          job_registry_storage_path, registry_table, datasets, created_at, updated_at;
                """
            )
        )
        row = result.mappings().first()
    if row is None:
        return None
    return _row_to_dict(row)


def list_jobs(status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    engine = _get_engine()
    sql = """
        SELECT job_id, status, progress, message, storage_mode, cloud_provider,
               job_registry_storage_path, registry_table, datasets, created_at, updated_at
        FROM ingest_jobs
    """
    params: Dict[str, Any] = {"limit": limit}
    if status:
        sql += " WHERE status = :status"
        params["status"] = status
    sql += " ORDER BY created_at DESC LIMIT :limit;"

    with engine.begin() as conn:
        result = conn.execute(text(sql), params)
        rows = result.mappings().all()
    return [_row_to_dict(row) for row in rows]
