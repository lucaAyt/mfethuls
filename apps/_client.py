"""Unified data-access layer for the Streamlit app.

Read path  → DuckDB / Parquet directly when the file is accessible on disk.
             This applies in both local mode AND the Streamlit container (shared
             DATA_ROOT volume), avoiding a HTTP + double-serialisation round trip.
Write/management path → REST API (ingest trigger, job status, dataset delete).
             These operations require server-side coordination and go through FastAPI.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from mfethuls.config.mode import is_service_mode


def mode() -> str:
    return "service" if is_service_mode() else "local"


# ---------------------------------------------------------------------------
# Service-mode helpers
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
# Datasets
# ---------------------------------------------------------------------------

def _normalise_dataset(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a dataset row from either local DuckDB or the API."""
    return {
        "name": row.get("name") or row.get("table_name") or "",
        "storage_path": row.get("storage_path") or "",
        "experiment_name": row.get("experiment_name") or "",
        "registered_at": str(row.get("registered_at") or ""),
    }


def _local_db_path() -> str | None:
    """Return the DuckDB path if the file exists on the local/mounted filesystem."""
    from mfethuls.storage import _get_duckdb_path
    path = _get_duckdb_path()
    return path if os.path.exists(path) else None


@st.cache_data(show_spinner=False, ttl=30)
def list_datasets() -> List[Dict[str, Any]]:
    # Direct read when DuckDB is accessible — local mode and Streamlit container (shared volume).
    db_path = _local_db_path()
    if db_path:
        from mfethuls.storage import duckdb_session
        with duckdb_session(db_path=db_path, read_only=True) as backend:
            return [_normalise_dataset(r) for r in backend.list_registered()]

    # Fallback: remote deployment where only the API is reachable.
    rows = _get("/datasets")
    return [_normalise_dataset(r) for r in rows]


@st.cache_data(show_spinner=False, ttl=30)
def query_dataset(name: str, limit: int = 5000, offset: int = 0) -> pd.DataFrame:
    # Direct read when DuckDB is accessible — avoids HTTP + double serialisation.
    db_path = _local_db_path()
    if db_path:
        from mfethuls.storage import duckdb_session
        with duckdb_session(db_path=db_path, read_only=True) as backend:
            safe = name.replace('"', '""')
            return backend.query(f'SELECT * FROM "{safe}" LIMIT ? OFFSET ?', [limit, offset])

    # Fallback: remote deployment, reconstruct DataFrame from JSON response.
    result = _get(f"/dataset/{name}", limit=limit, offset=offset)
    cols = [c["name"] for c in result.get("columns", [])]
    return pd.DataFrame(result.get("rows", []), columns=cols)


def delete_dataset(name: str) -> Dict[str, Any]:
    if mode() == "service":
        import requests
        resp = requests.delete(
            f"{api_url()}/dataset/{name}", headers=api_headers(), timeout=15
        )
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
        return _get("/registry/preview")  # use server-side PATH_TO_REGISTRY

    from mfethuls.registry_validator import validate_registry_dataframe

    if file_bytes:
        from mfethuls.api.utils import read_tabular_content_bytes
        df = read_tabular_content_bytes(file_bytes)
    else:
        from mfethuls.experiments import resolve_registry_path, read_tabular_content
        path = resolve_registry_path(os.environ.get("PATH_TO_REGISTRY"))
        df = read_tabular_content(path)

    data_root = os.environ.get("PATH_TO_DATA")
    return validate_registry_dataframe(
        df,
        check_data_paths=bool(data_root),
        data_root=data_root,
    )


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def trigger_ingest_service(
    storage_mode: str = "local",
    cloud_provider: Optional[str] = None,
    allow_invalid: bool = False,
) -> Dict[str, Any]:
    import requests
    params: Dict[str, Any] = {"storage_mode": storage_mode, "allow_invalid": allow_invalid}
    if cloud_provider:
        params["cloud_provider"] = cloud_provider
    resp = requests.post(
        f"{api_url()}/ingest",
        headers=api_headers(),
        params=params,
        timeout=30,
    )
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
                    name,
                    refresh=refresh,
                    storage_mode="local",
                    cloud_provider=None,
                    db_url=None,
                    query_backend=qb,
                )
                results.append((name, result or {}))
            except Exception as exc:
                results.append((name, {"status": "error", "error": str(exc)}))
    list_datasets.clear()
    return results


# ---------------------------------------------------------------------------
# Jobs (service mode only)
# ---------------------------------------------------------------------------

def list_jobs(status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    if mode() != "service":
        return []
    params: Dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    return _get("/jobs", **params)


def get_job(job_id: str) -> Dict[str, Any]:
    return _get(f"/jobs/{job_id}")
