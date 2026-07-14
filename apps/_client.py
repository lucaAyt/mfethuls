"""Unified data-access layer for the Streamlit app.

Read path  → DuckDB / Parquet directly when the file is accessible on disk.
             This applies in both local mode AND the Streamlit container (shared
             DATA_ROOT volume), avoiding a HTTP + double-serialisation round trip.
             Metadata enrichment uses Postgres (service mode) or .metadata.json
             sidecars (local mode) — same naming conventions in both.
Write/management path → REST API (ingest trigger, job status, dataset delete).
             These operations require server-side coordination and go through FastAPI.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from mfethuls.config.mode import is_service_mode


def mode() -> str:
    return "service" if is_service_mode() else "local"


# ---------------------------------------------------------------------------
# Service-mode HTTP helpers
# ---------------------------------------------------------------------------

def api_url() -> str:
    return (
        st.session_state.get("api_url")
        or os.environ.get("MFETHULS_API_URL", "http://localhost:8000")
    ).rstrip("/")


def api_headers() -> Dict[str, str]:
    key = st.session_state.get("api_key") or os.environ.get("MFETHULS_API_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _get(path: str, **params) -> Any:
    import requests
    resp = requests.get(f"{api_url()}{path}", headers=api_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, **kwargs) -> Any:
    import requests
    resp = requests.post(f"{api_url()}{path}", headers=api_headers(), timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def health_check() -> tuple[bool, str]:
    if mode() == "local":
        return True, "local mode — no server required"
    try:
        import requests
        resp = requests.get(f"{api_url()}/health", timeout=5)
        if resp.status_code == 200:
            return True, "connected"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Metadata enrichment helpers
# ---------------------------------------------------------------------------

def _read_metadata_json(storage_path: str) -> Dict[str, Any]:
    """Read the .metadata.json sidecar next to a Parquet file."""
    if not storage_path or storage_path.startswith(("s3://", "az://", "https://")):
        return {}
    meta_path = os.path.splitext(storage_path)[0] + ".metadata.json"
    if not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path, encoding="utf8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _enrich_from_postgres(datasets: List[Dict[str, Any]]) -> bool:
    """Enrich dataset dicts in-place using the Postgres metadata table.

    Joins on experiment_name — consistent across both Postgres (experiment_name
    column) and DuckDB dataset_registry (experiment_name column set by worker).
    Note: dataset_name in Postgres uses _dataset_basename (hex-id based) while
    DuckDB table_name uses _view_basename (human name based) — they never match,
    so dataset_name is intentionally not used as the join key.

    Only writes fields for datasets that have a Postgres match; unmatched
    datasets are left untouched so the .metadata.json fallback can fill them.

    Returns True if Postgres was reachable, False otherwise.
    """
    try:
        from mfethuls.storage import get_postgres_db_url
        from mfethuls.storage.metadata import PostgresMetadataBackend
        pg_url = get_postgres_db_url()
        if not pg_url:
            return False
        backend = PostgresMetadataBackend(pg_url)
        pg_rows = backend.list_datasets(limit=2000)
        # Index by experiment_name — present in both Postgres and DuckDB registry.
        pg_by_exp: Dict[str, Dict[str, Any]] = {}
        for r in pg_rows:
            exp_name = r.get("experiment_name")
            if exp_name and exp_name not in pg_by_exp:
                pg_by_exp[exp_name] = r
        for d in datasets:
            pg = pg_by_exp.get(d.get("experiment_name") or "")
            if not pg:
                continue  # no match — leave blank so .metadata.json can fill in
            d["instrument_name"] = pg.get("instrument_name") or ""
            d["instrument_type"] = pg.get("instrument_type") or ""
            d["instrument_model"] = pg.get("instrument_model") or ""
            d["sample_id"] = pg.get("sample_id") or ""
            d["run_id"] = pg.get("run_id") or ""
            d["experiment_name"] = pg.get("experiment_name") or d.get("experiment_name") or ""
            d["raw_data_filename"] = pg.get("raw_data_filename") or d.get("raw_data_filename") or ""
        return True
    except Exception:
        return False


def _enrich_from_metadata_json(datasets: List[Dict[str, Any]]) -> None:
    """Fill empty enrichment fields from .metadata.json sidecars.

    Uses `or`-based assignment so it only replaces empty strings, never
    overwriting values already populated by Postgres enrichment.
    """
    for d in datasets:
        meta = _read_metadata_json(d.get("storage_path", ""))
        if not meta:
            continue
        d["instrument_name"] = d.get("instrument_name") or meta.get("instrument_name") or ""
        d["instrument_type"] = d.get("instrument_type") or meta.get("instrument_type") or ""
        d["instrument_model"] = d.get("instrument_model") or meta.get("instrument_model") or ""
        d["sample_id"] = d.get("sample_id") or meta.get("sample_id") or ""
        d["run_id"] = d.get("run_id") or meta.get("run_id") or ""
        d["experiment_name"] = d.get("experiment_name") or meta.get("experiment_name") or ""
        d["raw_data_filename"] = d.get("raw_data_filename") or meta.get("raw_data_filename") or ""


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

def _normalise_dataset(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": row.get("name") or row.get("table_name") or "",
        "storage_path": row.get("storage_path") or "",
        "experiment_name": row.get("experiment_name") or "",
        "raw_data_filename": row.get("raw_data_filename") or "",
        "registered_at": str(row.get("registered_at") or ""),
        # enriched fields — populated by _enrich_* below
        "instrument_name": "",
        "instrument_type": "",
        "instrument_model": "",
        "sample_id": "",
        "run_id": "",
    }


def _local_db_path() -> str | None:
    """Return the DuckDB path if the file is accessible on disk."""
    from mfethuls.storage import _get_duckdb_path
    path = _get_duckdb_path()
    return path if os.path.exists(path) else None


@st.cache_data(show_spinner=False, ttl=30)
def list_datasets() -> List[Dict[str, Any]]:
    # Load base list from DuckDB (direct) or API (fallback).
    db_path = _local_db_path()
    if db_path:
        from mfethuls.storage import duckdb_session
        with duckdb_session(db_path=db_path, read_only=True) as backend:
            datasets = [_normalise_dataset(r) for r in backend.list_registered()]
    else:
        rows = _get("/datasets")
        datasets = [_normalise_dataset(r) for r in rows]

    # Enrich with instrument/sample/run info.
    # Postgres fills matched rows; .metadata.json fills whatever Postgres left blank.
    _enrich_from_postgres(datasets)
    _enrich_from_metadata_json(datasets)

    return datasets


@st.cache_data(show_spinner=False, ttl=30)
def query_dataset(name: str, limit: int = 5000, offset: int = 0) -> pd.DataFrame:
    # Direct read when DuckDB is on disk — avoids HTTP + double serialisation.
    db_path = _local_db_path()
    if db_path:
        from mfethuls.storage import duckdb_session
        with duckdb_session(db_path=db_path, read_only=True) as backend:
            safe = name.replace('"', '""')
            return backend.query(f'SELECT * FROM "{safe}" LIMIT ? OFFSET ?', [limit, offset])

    # Fallback: reconstruct DataFrame from API JSON response.
    result = _get(f"/dataset/{name}", limit=limit, offset=offset)
    cols = [c["name"] for c in result.get("columns", [])]
    return pd.DataFrame(result.get("rows", []), columns=cols)


def delete_dataset(name: str) -> Dict[str, Any]:
    # Deletes always go through the API — requires a DuckDB write lock on the server.
    if mode() == "service":
        import requests
        resp = requests.delete(f"{api_url()}/dataset/{name}", headers=api_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    from mfethuls.storage import _get_duckdb_path, duckdb_session
    db_path = _get_duckdb_path()
    with duckdb_session(db_path=db_path, read_only=False) as backend:
        backend.remove_dataset(name)
    return {"deleted": name}


# ---------------------------------------------------------------------------
# Registry preview
# ---------------------------------------------------------------------------

def preview_registry(
    file_bytes: Optional[bytes] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    if mode() == "service":
        if file_bytes:
            import requests
            resp = requests.post(
                f"{api_url()}/registry/preview",
                headers=api_headers(),
                files={"file": (filename or "registry.csv", file_bytes)},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        return _get("/registry/preview")

    from mfethuls.registry_validator import validate_registry_dataframe
    if file_bytes:
        from mfethuls.api.utils import read_tabular_content_bytes
        df = read_tabular_content_bytes(file_bytes)
    else:
        from mfethuls.experiments import resolve_registry_path, read_tabular_content
        path = resolve_registry_path(os.environ.get("PATH_TO_REGISTRY"))
        df = read_tabular_content(path)

    data_root = os.environ.get("PATH_TO_DATA")
    return validate_registry_dataframe(df, check_data_paths=bool(data_root), data_root=data_root)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def list_registry_experiments() -> List[str]:
    """Return experiment names from the server-side registry (via /registry/preview)."""
    result = _post("/registry/preview")
    return [r["values"]["name"] for r in result.get("rows", []) if r["values"].get("name")]


def trigger_ingest_service(
    storage_mode: str = "local",
    cloud_provider: Optional[str] = None,
    allow_invalid: bool = False,
    experiments: Optional[List[str]] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    import requests
    params: Dict[str, Any] = {"storage_mode": storage_mode, "allow_invalid": allow_invalid, "refresh": refresh}
    if cloud_provider:
        params["cloud_provider"] = cloud_provider
    if experiments:
        params["experiments"] = ",".join(experiments)
    resp = requests.post(f"{api_url()}/ingest", headers=api_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def local_ingest(
    experiment_names: List[str],
    registry_path: str,
    refresh: bool = False,
) -> List[tuple[str, Dict[str, Any]]]:
    from mfethuls.experiments import load_experiment_registry, clear_experiment_registry
    from mfethuls.config.loader import ingest_experiment_dataset
    from mfethuls.storage import DuckDBQueryBackend, _get_duckdb_path

    clear_experiment_registry()
    load_experiment_registry(registry_path)
    db_path = _get_duckdb_path()
    results = []
    with DuckDBQueryBackend(db_path=db_path, read_only=False) as qb:
        for name in experiment_names:
            try:
                result = ingest_experiment_dataset(
                    name, refresh=refresh, storage_mode="local",
                    cloud_provider=None, db_url=None, query_backend=qb,
                )
                results.append((name, result or {}))
            except Exception as exc:
                results.append((name, {"status": "error", "error": str(exc)}))
    list_datasets.clear()
    return results


# ---------------------------------------------------------------------------
# Jobs (service mode only)
# ---------------------------------------------------------------------------

def trigger_sync() -> Dict[str, Any]:
    return _post("/sync")


def get_sync_status() -> Dict[str, Any]:
    return _get("/sync/status")


def list_jobs(status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    if mode() != "service":
        return []
    params: Dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    return _get("/jobs", **params)


def get_job(job_id: str) -> Dict[str, Any]:
    return _get(f"/jobs/{job_id}")
