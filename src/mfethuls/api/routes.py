"""API route handlers."""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..experiments import _normalize_optional_str
from ..registry_validator import RegistryValidator
from ..config.mode import is_service_mode
from ..storage.job_store import create_job, get_job as get_job_record
from .schemas import QueryRequest
from .utils import get_api_storage_root, get_query_backend, read_tabular_content

router = APIRouter()


def _ensure_service_mode() -> None:
    if not is_service_mode():
        raise HTTPException(status_code=400, detail="API is only available in service mode")


@router.post("/registry/preview")
async def registry_preview(file: UploadFile | None = File(None)) -> Dict[str, Any]:
    """Parse uploaded spreadsheet (CSV/XLSX) and return per-row validation."""

    _ensure_service_mode()

    if file is None:
        raise HTTPException(status_code=400, detail="file (CSV/XLSX) must be uploaded")

    content = await file.read()
    df = read_tabular_content(content)

    required_cols = {"name", "experiment_id", "instrument_name"}
    missing = required_cols.difference(set(df.columns))
    if missing:
        raise HTTPException(status_code=400, detail={"missing_columns": sorted(list(missing))})

    rows: List[Dict[str, Any]] = []
    for idx, rec in enumerate(df.to_dict(orient="records"), start=1):
        experiment_id = rec.get("experiment_id")
        instrument_name = _normalize_optional_str(rec.get("instrument_name"))

        valid = True
        warnings: List[Dict[str, str]] = []
        try:
            RegistryValidator.validate_experiment_id(experiment_id)
        except Exception:
            valid = False
            warnings.append({"field": "experiment_id", "message": "invalid format"})

        if instrument_name is None:
            warnings.append({"field": "instrument_name", "message": "missing instrument_name"})

        rows.append({"row_number": idx, "values": rec, "valid": valid, "warnings": warnings})

    return {"rows": rows}


@router.post("/ingest")
async def ingest(
    file: UploadFile | None = File(None),
    storage_mode: str = "local",
    cloud_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Start ingestion job. This endpoint is control-plane only."""

    _ensure_service_mode()

    if file is None:
        raise HTTPException(status_code=400, detail="file (CSV/XLSX) must be uploaded")

    content = await file.read()
    df = read_tabular_content(content)

    required_cols = {"name", "experiment_id", "instrument_name"}
    missing = required_cols.difference(set(df.columns))
    if missing:
        raise HTTPException(status_code=400, detail={"missing_columns": sorted(list(missing))})

    job_id = uuid.uuid4().hex
    registry_path = os.path.join(get_api_storage_root(), f"registry_{job_id}.parquet")
    df.to_parquet(registry_path, index=False)

    create_job(job_id, registry_path, storage_mode, cloud_provider)

    payload = {
        "job_id": job_id,
        "status": "queued",
        "registry_storage_path": registry_path,
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
    return [
        {
            "dataset_id": row["table_name"],
            "name": row["table_name"],
            "storage_mode": "local",
            "queryable": True,
            "storage_path": row["storage_path"],
            "registered_at": row["registered_at"],
        }
        for row in get_query_backend().list_registered()
    ]


@router.post("/queries")
async def post_query(payload: QueryRequest) -> Dict[str, Any]:
    _ensure_service_mode()
    backend = get_query_backend()

    if payload.dataset_ids:
        registered = {row["table_name"] for row in backend.list_registered()}
        missing = [dataset_id for dataset_id in payload.dataset_ids if dataset_id not in registered]
        if missing:
            raise HTTPException(status_code=404, detail={"missing_dataset_ids": missing})

    query_id = uuid.uuid4().hex
    started = pd.Timestamp.utcnow()
    base_sql = payload.sql.strip().rstrip(";")
    paginated_sql = f"SELECT * FROM ({base_sql}) AS q LIMIT {payload.limit} OFFSET {payload.offset}"
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
