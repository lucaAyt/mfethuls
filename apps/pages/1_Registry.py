import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
import pandas as pd

import _client as client

st.set_page_config(page_title="Registry — mfethuls", layout="wide", page_icon="📋")
st.title("Registry")

# ---------------------------------------------------------------------------
# Sidebar — API config passthrough (service mode)
# ---------------------------------------------------------------------------
if client.mode() == "service":
    with st.sidebar:
        st.header("API connection")
        default_url = os.environ.get("MFETHULS_API_URL", "http://localhost:8000")
        default_key = os.environ.get("MFETHULS_API_KEY", "")
        st.session_state["api_url"] = st.text_input("API URL", value=st.session_state.get("api_url", default_url))
        st.session_state["api_key"] = st.text_input("API key", type="password", value=st.session_state.get("api_key", default_key))

# ---------------------------------------------------------------------------
# Registry source
# ---------------------------------------------------------------------------
if client.mode() == "local":
    registry_path = st.text_input(
        "Experiment registry path",
        value=os.environ.get("PATH_TO_REGISTRY", ""),
        help="Path to a CSV or XLSX experiments registry file.",
    )
    uploaded_file = None
else:
    st.caption("Upload a registry CSV/XLSX to preview it, or leave empty to use the server's `PATH_TO_REGISTRY`.")
    uploaded_file = st.file_uploader("Upload registry (optional)", type=["csv", "xlsx"])
    registry_path = None

# ---------------------------------------------------------------------------
# Preview / validate
# ---------------------------------------------------------------------------
if st.button("Preview & validate"):
    with st.spinner("Validating registry…"):
        try:
            if client.mode() == "local":
                if not registry_path:
                    st.error("Provide a registry path.")
                    st.stop()
                result = client.preview_registry()
            else:
                file_bytes = uploaded_file.read() if uploaded_file else None
                fname = uploaded_file.name if uploaded_file else None
                result = client.preview_registry(file_bytes=file_bytes, filename=fname)

            summary = result.get("summary", {})
            rows = result.get("rows", [])

            col1, col2, col3 = st.columns(3)
            col1.metric("Total rows", summary.get("total", len(rows)))
            col2.metric("Valid", summary.get("valid", 0))
            col3.metric("Invalid", summary.get("invalid", 0))

            if rows:
                df_preview = pd.DataFrame(rows)
                st.dataframe(df_preview, use_container_width=True)
        except Exception as exc:
            st.error(f"Validation failed: {exc}")

st.divider()

# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
st.subheader("Ingest")

if client.mode() == "local":
    refresh = st.checkbox("Re-parse even if cached", value=False)

    experiment_names: list[str] = []
    if registry_path:
        try:
            from mfethuls.experiments import load_experiment_registry
            @st.cache_data(show_spinner=False)
            def _load_registry(path: str) -> pd.DataFrame:
                return load_experiment_registry(path)
            exp_df = _load_registry(registry_path)
            experiment_names = (
                exp_df.get("name", pd.Series(dtype=str))
                .dropna()
                .astype(str)
                .tolist()
            )
        except Exception as exc:
            st.error(f"Could not load registry: {exc}")

    if experiment_names:
        select_all = st.checkbox("Select all", value=False)
        selected = experiment_names if select_all else st.multiselect("Experiments to ingest", options=experiment_names)
        st.caption(f"{len(selected)} experiment(s) selected.")
    else:
        selected = []
        st.info("Provide a valid registry path to list experiments.")

    if st.button("Run ingest", disabled=not selected):
        total = len(selected)
        progress = st.progress(0)
        with st.spinner("Ingesting…"):
            results = client.local_ingest(selected, registry_path, refresh=refresh)

        counts: dict[str, int] = {}
        errors = []
        for name, res in results:
            status = res.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
            if status == "error":
                errors.append((name, res.get("error", "")))
            progress.progress(results.index((name, res)) / total if (name, res) in results else 1.0)

        progress.progress(1.0)
        if errors:
            for name, err in errors:
                st.error(f"{name}: {err}")
        summary_str = ", ".join(f"{k}: {v}" for k, v in counts.items())
        st.success(f"Ingestion complete — {summary_str}")
        st.cache_data.clear()

else:
    storage_mode = st.selectbox("Storage mode", ["local", "cloud", "both"], index=0)
    cloud_provider = None
    if storage_mode in {"cloud", "both"}:
        cloud_provider = st.selectbox("Cloud provider", ["s3", "azure"])
    allow_invalid = st.checkbox("Allow invalid rows", value=False)

    if st.button("Trigger ingest"):
        with st.spinner("Queuing job…"):
            try:
                result = client.trigger_ingest_service(
                    storage_mode=storage_mode,
                    cloud_provider=cloud_provider,
                    allow_invalid=allow_invalid,
                )
                job_id = result.get("job_id")
                st.success(f"Job queued — ID: `{job_id}`")
                st.caption("Monitor progress on the Jobs page.")
            except Exception as exc:
                st.error(f"Ingest failed: {exc}")
