"""Where the app gets its data: the backend :func:`mfethuls.app.page.run` draws the page for.

:class:`LocalBackend` works on this computer: the registry file, the data folder and
the local stores (manifest, Parquet files, DuckDB catalog). Other backends subclass
it and override what differs, e.g. reading datasets through an API.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from mfethuls.app.register import clear_registry_caches, new_data_prompt, registry_frame
from mfethuls.app.welcome import is_set_up
from mfethuls.settings import get_settings

_CATALOG_TEXT_FIELDS = (
    "experiment_id", "experiment_name", "raw_data_filename", "instrument_name",
    "instrument_type", "instrument_model", "sample_id", "run_id", "measurement_profile",
)


def normalise_dataset(row: Dict[str, Any]) -> Dict[str, Any]:
    """A catalog row with empty strings for missing text, and its view name as ``name``."""
    dataset = {
        "name": row.get("name") or row.get("table_name") or "",
        "storage_path": row.get("storage_path") or "",
        "registered_at": str(row.get("registered_at") or ""),
        "rows": row.get("rows"),
    }
    dataset.update({field: row.get(field) or "" for field in _CATALOG_TEXT_FIELDS})
    return dataset


def local_catalog_path() -> Optional[str]:
    """The DuckDB catalog file, if it exists on this computer."""
    from mfethuls.storage import _get_duckdb_path

    path = _get_duckdb_path()
    return path if os.path.exists(path) else None


def list_local_datasets() -> List[Dict[str, Any]]:
    """Ingested datasets from the local DuckDB catalog (cached for 30 s, per catalog)."""
    db_path = local_catalog_path()
    return _list_catalog(db_path) if db_path else []


@st.cache_data(show_spinner=False, ttl=30)
def _list_catalog(db_path: str) -> List[Dict[str, Any]]:
    from mfethuls.storage import duckdb_session

    with duckdb_session(db_path=db_path, read_only=True) as catalog:
        return [normalise_dataset(row) for row in catalog.list_registered()]


# Cached for 10 minutes: whole datasets are expensive to reload. Refresh clears it.
def query_local_dataset(name: str, limit: Optional[int] = None, offset: int = 0) -> pd.DataFrame:
    """Rows of a dataset from the local catalog; ``limit=None`` loads all of them."""
    return _query_catalog(local_catalog_path(), name, limit, offset)


@st.cache_data(show_spinner=False, ttl=600)
def _query_catalog(db_path: str, name: str, limit: Optional[int], offset: int) -> pd.DataFrame:
    from mfethuls.storage import duckdb_session

    with duckdb_session(db_path=db_path, read_only=True) as catalog:
        safe = name.replace('"', '""')
        if limit is None:
            return catalog.query(f'SELECT * FROM "{safe}" OFFSET ?', [offset])
        return catalog.query(f'SELECT * FROM "{safe}" LIMIT ? OFFSET ?', [limit, offset])


class LocalBackend:
    """The app on this computer: it reads and writes the registry file and the local stores."""

    # The "Register new data" dialog may append rows to the registry file.
    writes_registry = True
    # The getting-started page offers to switch to a copy of the bundled examples and to
    # open the Python tutorial (it starts marimo on the computer running the app).
    offers_example = True
    # ⚙ Settings may change the data folder, registry and storage folder saved on the
    # computer running the app (and lists folders there while they are typed).
    # A backend serving other people sets this and offers_example to False.
    edits_settings = True

    @property
    def writes_definitions(self) -> bool:
        """Whether "Add instrument" may save definitions in the data folder (else: offered as downloads).

        Where the registry is kept elsewhere (OneDrive), so is the data folder's ``.mfethuls``.
        """
        return self.writes_registry

    # -- sidebar ------------------------------------------------------------

    def render_status(self) -> None:
        """Anything shown at the top of the sidebar (nothing locally)."""

    def render_ingest(self) -> str:
        """The Ingest sidebar section; returns the registry path in use."""
        registry_path = get_settings().registry_path or ""
        if not is_set_up():
            st.caption("Choose your data folder and registry first: **⚙ Settings** → Data folder and registry.")
            return registry_path
        st.caption(f"Registry: `{os.path.basename(registry_path)}`")
        refresh_ingest = st.checkbox("Re-parse even if cached", value=False)

        experiment_names: List[str] = []
        if registry_path:
            new_data_prompt(self, registry_path)
            try:
                experiment_names = registry_frame(registry_path).get("name", pd.Series(dtype=str)).dropna().astype(str).tolist()
            except Exception as exc:
                st.error(f"Could not load registry: {exc}")

        selected: List[str] = []
        if experiment_names:
            select_all = st.checkbox("Select all", value=False)
            selected = experiment_names if select_all else st.multiselect("Experiments", options=experiment_names)
            st.caption(f"{len(selected)} selected.")
        elif registry_path:
            st.info("No experiments found.")

        if st.button("Ingest", disabled=not selected, width="stretch"):
            progress_bar = st.progress(0)
            results: List[tuple] = []
            for i, name in enumerate(selected):
                results.extend(self.ingest([name], registry_path, refresh=refresh_ingest))
                progress_bar.progress((i + 1) / len(selected))

            counts: Dict[str, int] = {}
            for name, result in results:
                status = result.get("status", "unknown")
                counts[status] = counts.get(status, 0) + 1
                if status == "error":
                    st.error(f"{name}: {result.get('error', '')}")
            st.success("Done — " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
            self.clear_caches()
            st.rerun()
        return registry_path

    # -- data -----------------------------------------------------------------

    def list_datasets(self) -> List[Dict[str, Any]]:
        return list_local_datasets()

    def query_dataset(self, name: str, limit: Optional[int] = None, offset: int = 0) -> pd.DataFrame:
        return query_local_dataset(name, limit, offset)

    def clear_caches(self) -> None:
        _list_catalog.clear()
        _query_catalog.clear()

    def ingest(self, names: List[str], registry_path: str, refresh: bool = False) -> List[tuple]:
        """Ingest experiments into the local stores; returns ``(name, result)`` pairs."""
        from mfethuls.config.loader import ingest_experiment_dataset
        from mfethuls.experiments import Registry
        from mfethuls.stores import open_local_stores

        registry = Registry.load(registry_path)
        results = []
        with open_local_stores() as stores:
            for name in names:
                try:
                    result = ingest_experiment_dataset(name, refresh=refresh, registry=registry, stores=stores)
                    results.append((name, result or {}))
                except Exception as exc:
                    results.append((name, {"status": "error", "error": str(exc)}))
        _list_catalog.clear()
        return results

    # -- clean up ---------------------------------------------------------------

    def reconcile_plan(self, registry_path: str) -> Dict[str, Any]:
        from mfethuls.experiments import Registry
        from mfethuls.reconcile import plan
        from mfethuls.stores import open_local_stores

        with open_local_stores() as stores:
            return plan(Registry.load(registry_path), stores).to_dict()

    def reconcile_apply(self, registry_path: str, fingerprint: str, force: bool = False) -> List[Dict[str, Any]]:
        """Apply the reviewed plan; RuntimeError if it changed since the check or is blocked."""
        from mfethuls.experiments import Registry
        from mfethuls.reconcile import PlanChanged, ReconcileBlocked, apply_reviewed
        from mfethuls.stores import open_local_stores

        with open_local_stores() as stores:
            try:
                results = apply_reviewed(Registry.load(registry_path), stores, fingerprint=fingerprint, force=force)
            except (PlanChanged, ReconcileBlocked) as exc:
                raise RuntimeError(str(exc)) from exc
        clear_registry_caches()
        self.clear_caches()
        return results
