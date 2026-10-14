"""Unified data-access layer for the Streamlit app.

Read path  → DuckDB / Parquet directly when the file is accessible on disk.
             This applies in both local mode AND the Streamlit container (shared
             DATA_ROOT volume), avoiding a HTTP + double-serialisation round trip.
             Dataset descriptions come from the DuckDB catalog (dataset_registry),
             which ingest fills from the registry, manifest and parsed dataset.
Write/management path → REST API (ingest trigger, job status, dataset delete).
             These operations require server-side coordination and go through FastAPI.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from mfethuls.config.mode import is_service_mode
from mfethuls.settings import get_settings


def mode() -> str:
    return "service" if is_service_mode() else "local"


# ---------------------------------------------------------------------------
# Service-mode HTTP helpers
# ---------------------------------------------------------------------------

def api_url() -> str:
    return (
        st.session_state.get("api_url")
        or get_settings().api_url
    ).rstrip("/")


def api_headers() -> Dict[str, str]:
    key = st.session_state.get("api_key") or get_settings().api_key or ""
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

_CATALOG_TEXT_FIELDS = (
    "experiment_id", "experiment_name", "raw_data_filename", "instrument_name",
    "instrument_type", "instrument_model", "sample_id", "run_id", "measurement_profile",
)


def _normalise_dataset(row: Dict[str, Any]) -> Dict[str, Any]:
    """A catalog row (DuckDB or API /datasets) with empty strings for missing text."""
    dataset = {
        "name": row.get("name") or row.get("table_name") or "",
        "storage_path": row.get("storage_path") or "",
        "registered_at": str(row.get("registered_at") or ""),
        "rows": row.get("rows"),
    }
    dataset.update({field: row.get(field) or "" for field in _CATALOG_TEXT_FIELDS})
    return dataset


def _local_db_path() -> str | None:
    """Return the DuckDB path if the file is accessible on disk."""
    from mfethuls.storage import _get_duckdb_path
    path = _get_duckdb_path()
    return path if os.path.exists(path) else None


@st.cache_data(show_spinner=False, ttl=30)
def list_datasets() -> List[Dict[str, Any]]:
    """Ingested datasets from the catalog: DuckDB directly, or the API as fallback."""
    db_path = _local_db_path()
    if db_path:
        from mfethuls.storage import duckdb_session
        with duckdb_session(db_path=db_path, read_only=True) as backend:
            return [_normalise_dataset(r) for r in backend.list_registered()]
    if mode() == "local":
        return []  # nothing ingested yet; there is no API to ask in local mode
    return [_normalise_dataset(r) for r in _get("/datasets")]


# Rows per API request when loading a whole dataset in service mode.
_API_PAGE_ROWS = 100_000


def _query_api(name: str, limit: int, offset: int) -> tuple[list, list]:
    result = _get(f"/dataset/{name}", limit=limit, offset=offset)
    return [c["name"] for c in result.get("columns", [])], result.get("rows", [])


# Cached for 10 minutes: whole datasets are expensive to reload. Refresh clears it.
@st.cache_data(show_spinner=False, ttl=600)
def query_dataset(name: str, limit: Optional[int] = None, offset: int = 0) -> pd.DataFrame:
    """Rows of a dataset; ``limit=None`` loads all of them."""
    # Direct read when DuckDB is on disk — avoids HTTP + double serialisation.
    db_path = _local_db_path()
    if db_path:
        from mfethuls.storage import duckdb_session
        with duckdb_session(db_path=db_path, read_only=True) as backend:
            safe = name.replace('"', '""')
            if limit is None:
                return backend.query(f'SELECT * FROM "{safe}" OFFSET ?', [offset])
            return backend.query(f'SELECT * FROM "{safe}" LIMIT ? OFFSET ?', [limit, offset])

    # Fallback: reconstruct DataFrame from API JSON responses, page by page for all rows.
    if limit is not None:
        cols, rows = _query_api(name, limit, offset)
        return pd.DataFrame(rows, columns=cols)

    cols, rows = [], []
    while True:
        cols, page = _query_api(name, _API_PAGE_ROWS, offset + len(rows))
        rows.extend(page)
        if len(page) < _API_PAGE_ROWS:
            break
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=600)
def registry_frame(path: str) -> pd.DataFrame:
    """The registry table at ``path`` (cached; cleared when rows are added)."""
    from mfethuls.experiments import Registry
    return Registry.load(path).frame


@st.cache_data(show_spinner=False, ttl=600)
def count_new_data(registry_path: str, data_root: str) -> int:
    """How many items under ``data_root`` the registry does not describe yet (cached)."""
    from mfethuls.discovery import discover_unregistered
    from mfethuls.experiments import Registry
    return sum(1 for item in discover_unregistered(Registry.load(registry_path), data_root) if not item.issue)


def clear_registry_caches() -> None:
    registry_frame.clear()
    count_new_data.clear()


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
    from mfethuls.experiments import Registry
    from mfethuls.config.loader import ingest_experiment_dataset
    from mfethuls.storage import DuckDBQueryBackend, _get_duckdb_path

    registry = Registry.load(registry_path)
    db_path = _get_duckdb_path()
    results = []
    with DuckDBQueryBackend(db_path=db_path, read_only=False) as qb:
        for name in experiment_names:
            try:
                result = ingest_experiment_dataset(
                    name, refresh=refresh, storage_mode="local",
                    cloud_provider=None, db_url=None, query_backend=qb, registry=registry,
                )
                results.append((name, result or {}))
            except Exception as exc:
                results.append((name, {"status": "error", "error": str(exc)}))
    list_datasets.clear()
    return results


# ---------------------------------------------------------------------------
# Reconcile (clean up ingested data against the registry)
# ---------------------------------------------------------------------------

def reconcile_plan(registry_path: str) -> Dict[str, Any]:
    """What reconcile would change; the server's registry is used in service mode."""
    if mode() == "service":
        return _get("/reconcile")
    from mfethuls.experiments import Registry
    from mfethuls.reconcile import open_stores, plan

    registry = Registry.load(registry_path)
    with open_stores() as stores:
        return plan(registry, stores).to_dict()


def reconcile_apply(registry_path: str, fingerprint: str, force: bool = False) -> List[Dict[str, Any]]:
    """Apply the reviewed plan. Raises RuntimeError if it changed since the check or is blocked."""
    if mode() == "service":
        import requests

        resp = requests.post(f"{api_url()}/reconcile", headers=api_headers(), timeout=600,
                             params={"fingerprint": fingerprint, "force": force})
        if resp.status_code == 409:
            raise RuntimeError(resp.json().get("detail"))
        resp.raise_for_status()
        results = resp.json()["results"]
    else:
        from mfethuls.experiments import Registry
        from mfethuls.reconcile import PlanChanged, ReconcileBlocked, apply_reviewed, open_stores

        registry = Registry.load(registry_path)
        with open_stores() as stores:
            try:
                results = apply_reviewed(registry, stores, fingerprint=fingerprint, force=force)
            except (PlanChanged, ReconcileBlocked) as exc:
                raise RuntimeError(str(exc)) from exc
    list_datasets.clear()
    query_dataset.clear()
    return results


# ---------------------------------------------------------------------------
# Jobs (service mode only)
# ---------------------------------------------------------------------------

def trigger_sync() -> Dict[str, Any]:
    import requests
    resp = requests.post(f"{api_url()}/sync", headers=api_headers(), timeout=300)
    resp.raise_for_status()
    return resp.json()


def list_jobs(status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    if mode() != "service":
        return []
    params: Dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    return _get("/jobs", **params)


def get_job(job_id: str) -> Dict[str, Any]:
    return _get(f"/jobs/{job_id}")
