"""API route handlers."""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from ..config.mode import is_service_mode
from ..registry_validator import validate_registry_dataframe
from ..experiments import resolve_registry_path, read_tabular_content
from ..storage.job_store import create_job, get_job as get_job_record
from .schemas import QueryRequest
from .utils import duckdb_session, get_api_storage_root, read_tabular_content_bytes

router = APIRouter()


def _ensure_service_mode() -> None:
    if not is_service_mode():
        raise HTTPException(status_code=400, detail="API is only available in service mode")


async def _read_registry_upload_async(file: UploadFile) -> pd.DataFrame:
    if file is not None:
        content = await file.read()
        return read_tabular_content_bytes(content)
    raise HTTPException(status_code=400, detail="No file (CSV/XLSX) uploaded from path; check path")


# This is for when a file is being checked (uploaded). PATH_TO_REGISTRY and the registry 
# is in our mfethuls-api volume. We should check the file paths routing aswell.
@router.post("/registry/preview")
async def registry_preview(file: UploadFile | None = File(None)) -> Dict[str, Any]:
    """Parse uploaded spreadsheet (CSV/XLSX) and return per-row validation."""

    _ensure_service_mode()

    if file:
        df = await _read_registry_upload_async(file)
    else:
        registry_path = resolve_registry_path(os.environ.get("PATH_TO_REGISTRY"))
        df = read_tabular_content(registry_path)

    data_root = os.environ.get("PATH_TO_DATA")
    return validate_registry_dataframe(
        df,
        check_data_paths=bool(data_root),
        data_root=data_root,
    )


@router.post("/ingest")
async def ingest(
    file: UploadFile | None = File(None),
    storage_mode: str = "local",
    cloud_provider: Optional[str] = None,
    allow_invalid: bool = Query(False),
) -> Dict[str, Any]:
    """Start ingestion job. This endpoint is control-plane only."""

    _ensure_service_mode()
    registry_path = resolve_registry_path(os.environ.get("PATH_TO_REGISTRY")) # Must exist

    if file:
        df = await _read_registry_upload_async(file)
    else:
        df = read_tabular_content(registry_path)

    data_root = os.environ.get("PATH_TO_DATA")
    validation = validate_registry_dataframe(
        df,
        check_data_paths=bool(data_root),
        data_root=data_root,
    )
    if not allow_invalid and validation["summary"]["invalid"] > 0:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Registry contains invalid rows",
                "summary": validation["summary"],
                "invalid_rows": [row for row in validation["rows"] if not row["valid"]],
            },
        )

    job_id = uuid.uuid4().hex
    job_registry_path = os.path.join(get_api_storage_root(), f"job_registry_record_for_{job_id}.parquet")
    df.to_parquet(job_registry_path, index=False)

    create_job(job_id, job_registry_path, storage_mode, cloud_provider)

    payload = {
        "job_id": job_id,
        "status": "queued",
        "job_registry_storage_path": job_registry_path,
    }
    return JSONResponse(content=payload, status_code=202, headers={"Location": f"/jobs/{job_id}"})


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    _ensure_service_mode()
    job = get_job_record(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/datasets")
async def list_datasets() -> List[Dict[str, Any]]:
    _ensure_service_mode()
    with duckdb_session(read_only=True) as backend:
        return [
            {
                "dataset_id": row["table_name"],
                "name": row["table_name"],
                "storage_mode": "local",
                "queryable": True,
                "storage_path": row["storage_path"],
                "registered_at": row["registered_at"],
            }
            for row in backend.list_registered()
        ]

@router.get("/experiments/{table_name}")
async def get_experiment_data(table_name: str, 
                              limit: int = Query(default=100, ge=1), 
                              offset: int = Query(default=0, ge=0)
) -> Dict[str, Any]:
    _ensure_service_mode()
    safe_table = table_name.replace('"', '""')

    with duckdb_session(read_only=True) as backend:
        registered = {row["table_name"] for row in backend.list_registered()}
        if safe_table not in registered:
            raise HTTPException(status_code=400, detail=f"Dataset {safe_table} not found")

        query_id = uuid.uuid4().hex
        started = pd.Timestamp.utcnow()
        paginated_sql = f'SELECT * FROM "{safe_table}" LIMIT ? OFFSET ?'
        try:
            frame = backend.query(paginated_sql, [limit, offset])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Query failed: {exc}") from exc

    execution_ms = int((pd.Timestamp.utcnow() - started).total_seconds() * 1000)

    return {
        "query_id": query_id,
        "status": "completed",
        "columns": [{"name": name, "type": str(dtype)} for name, dtype in frame.dtypes.items()],
        "rows": frame.values.tolist(),
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned_rows": len(frame.index),
        },
        "execution_ms": execution_ms,
    }


# TODO: Move this to a "parameterised" JSON approach. 
# We dont want to allow arbitrary SQL in the API for security reasons, 
# but we can allow users to define parameterised queries in a config and then call them with parameters via the API. 
# This is just for testing currently.
@router.post("/queries")
async def post_query(payload: QueryRequest) -> Dict[str, Any]:
    _ensure_service_mode()

    with duckdb_session(read_only=True) as backend:
        if payload.dataset_ids:
            registered = {row["table_name"] for row in backend.list_registered()}
            missing = [
                dataset_id for dataset_id in payload.dataset_ids if dataset_id not in registered
            ]
            if missing:
                raise HTTPException(status_code=404, detail={"missing_dataset_ids": missing})

        query_id = uuid.uuid4().hex
        started = pd.Timestamp.utcnow()
        base_sql = payload.sql.strip().rstrip(";")
        paginated_sql = (
            f"SELECT * FROM ({base_sql}) AS q LIMIT {payload.limit} OFFSET {payload.offset}"
        )
        try:
            frame = backend.query(paginated_sql)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Query failed: {exc}") from exc

    execution_ms = int((pd.Timestamp.utcnow() - started).total_seconds() * 1000)

    return {
        "query_id": query_id,
        "status": "completed",
        "columns": [{"name": name, "type": str(dtype)} for name, dtype in frame.dtypes.items()],
        "rows": frame.values.tolist(),
        "pagination": {
            "limit": payload.limit,
            "offset": payload.offset,
            "returned_rows": len(frame.index),
        },
        "execution_ms": execution_ms,
    }


@router.get("/health")
async def health() -> Dict[str, str]:
    _ensure_service_mode()
    return {"status": "ok"}
