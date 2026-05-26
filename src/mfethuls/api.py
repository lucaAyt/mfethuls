from __future__ import annotations

import io
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import pandas as pd

from .experiments import _normalize_optional_str
from .job_store import create_job, get_job as get_job_record
from .registry_validator import RegistryValidator
from .storage import DuckDBQueryBackend


app = FastAPI(title="mfethuls-mvp-api")

_QUERY_BACKEND: DuckDBQueryBackend | None = None


def _get_query_backend() -> DuckDBQueryBackend:
    global _QUERY_BACKEND
    if _QUERY_BACKEND is None:
        _QUERY_BACKEND = DuckDBQueryBackend()
    return _QUERY_BACKEND


def _get_api_storage_root() -> str:
    root = os.path.join(os.getcwd(), ".mfethuls_registry")
    os.makedirs(root, exist_ok=True)
    return root


def _read_tabular_content(content_bytes: bytes) -> pd.DataFrame:
    """Read a CSV/XLSX payload into a DataFrame."""

    try:
        return pd.read_excel(io.BytesIO(content_bytes))
    except Exception:
        try:
            return pd.read_csv(io.BytesIO(content_bytes))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not parse file: {exc}") from exc


class QueryRequest(BaseModel):
    project_id: str
    sql: str
    dataset_ids: Optional[List[str]] = None
    mode: str = "sync"
    limit: int = Field(default=1000, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


@app.post("/registry/preview")
async def registry_preview(file: UploadFile | None = File(None)) -> Dict[str, Any]:
    """Parse uploaded spreadsheet (CSV/XLSX) and return per-row validation."""

    if file is None:
        raise HTTPException(status_code=400, detail="file (CSV/XLSX) must be uploaded")

    content = await file.read()
    df = _read_tabular_content(content)

    required_cols = {"name", "experiment_id", "instrument_name"}
    missing = required_cols.difference(set(df.columns))
    if missing:
        raise HTTPException(status_code=400, detail={"missing_columns": sorted(list(missing))})

    rows: List[Dict[str, Any]] = []
    for idx, rec in enumerate(df.to_dict(orient="records"), start=1):
        name = rec.get("name")
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

@app.post("/ingest")
async def ingest(
    file: UploadFile | None = File(None),
    storage_mode: str = "local",
    cloud_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Start ingestion job. This endpoint is control-plane only."""

    if file is None:
        raise HTTPException(status_code=400, detail="file (CSV/XLSX) must be uploaded")

    content = await file.read()
    df = _read_tabular_content(content)

    required_cols = {"name", "experiment_id", "instrument_name"}
    missing = required_cols.difference(set(df.columns))
    if missing:
        raise HTTPException(status_code=400, detail={"missing_columns": sorted(list(missing))})

    job_id = uuid.uuid4().hex
    registry_path = os.path.join(_get_api_storage_root(), f"registry_{job_id}.parquet")
    df.to_parquet(registry_path, index=False)

    create_job(job_id, registry_path, storage_mode, cloud_provider)

    payload = {
        "job_id": job_id,
        "status": "queued",
        "registry_storage_path": registry_path,
    }
    return JSONResponse(content=payload, status_code=202, headers={"Location": f"/jobs/{job_id}"})


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    job = get_job_record(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/datasets")
async def list_datasets() -> List[Dict[str, Any]]:
    return [
        {
            "dataset_id": row["table_name"],
            "name": row["table_name"],
            "storage_mode": "local",
            "queryable": True,
            "storage_path": row["storage_path"],
            "registered_at": row["registered_at"],
        }
        for row in _get_query_backend().list_registered()
    ]


@app.post("/queries")
async def post_query(payload: QueryRequest) -> Dict[str, Any]:
    backend = _get_query_backend()

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


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
