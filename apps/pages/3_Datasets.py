import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import streamlit as st
import pandas as pd

import _client as client

st.set_page_config(page_title="Datasets — mfethuls", layout="wide", page_icon="📦")
st.title("Datasets")

if client.mode() == "service":
    with st.sidebar:
        st.header("API connection")
        default_url = os.environ.get("MFETHULS_API_URL", "http://localhost:8000")
        default_key = os.environ.get("MFETHULS_API_KEY", "")
        st.session_state["api_url"] = st.text_input("API URL", value=st.session_state.get("api_url", default_url))
        st.session_state["api_key"] = st.text_input("API key", type="password", value=st.session_state.get("api_key", default_key))


def _read_metadata(storage_path: str) -> dict:
    meta_path = os.path.splitext(storage_path)[0] + ".metadata.json"
    if not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path, encoding="utf8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _storage_label(storage_path: str) -> str:
    if storage_path.startswith(("s3://", "az://", "https://")):
        return "cloud"
    return "local"


# ---------------------------------------------------------------------------
# Load datasets
# ---------------------------------------------------------------------------
col_refresh, _ = st.columns([1, 5])
if col_refresh.button("Refresh"):
    client.list_datasets.clear()
    st.rerun()

with st.spinner("Loading…"):
    try:
        datasets = client.list_datasets()
    except Exception as exc:
        st.error(f"Could not load datasets: {exc}")
        st.stop()

if not datasets:
    st.info("No datasets registered yet. Go to the Registry page to ingest experiments.")
    st.stop()

# ---------------------------------------------------------------------------
# Build summary table
# ---------------------------------------------------------------------------
rows = []
for d in datasets:
    storage_path = d.get("storage_path", "")
    meta = _read_metadata(storage_path)
    rows.append({
        "name": d.get("name", ""),
        "instrument": meta.get("instrument_name") or meta.get("instrument_type") or "",
        "sample_id": meta.get("sample_id") or "",
        "run_id": meta.get("run_id") or "",
        "storage": _storage_label(storage_path),
        "registered_at": d.get("registered_at", ""),
        "storage_path": storage_path,
    })

df_summary = pd.DataFrame(rows)

show_paths = st.toggle("Show full paths", value=False)
display_cols = ["name", "instrument", "sample_id", "run_id", "storage", "registered_at"]
if show_paths:
    display_cols.append("storage_path")

st.dataframe(df_summary[display_cols], use_container_width=True)
st.caption(f"{len(datasets)} dataset(s) registered.")

# ---------------------------------------------------------------------------
# Inspect a single dataset
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Inspect dataset")

selected = st.selectbox("Dataset", options=[d["name"] for d in datasets])
limit = st.number_input("Row limit", min_value=10, max_value=100_000, value=200, step=100)

if st.button("Load"):
    with st.spinner(f"Querying {selected}…"):
        try:
            df = client.query_dataset(selected, limit=int(limit))
        except Exception as exc:
            st.error(f"Query failed: {exc}")
            st.stop()

    meta = _read_metadata(next((d["storage_path"] for d in datasets if d["name"] == selected), ""))

    if meta:
        with st.expander("Metadata", expanded=False):
            st.json(meta)

    col1, col2 = st.columns(2)
    col1.metric("Rows", f"{len(df):,}")
    col2.metric("Columns", len(df.columns))

    with st.expander("Column types", expanded=False):
        dtype_df = pd.DataFrame({"column": df.columns, "dtype": [str(t) for t in df.dtypes]})
        st.dataframe(dtype_df, use_container_width=True, hide_index=True)

    st.dataframe(df, use_container_width=True)

# ---------------------------------------------------------------------------
# Delete dataset
# ---------------------------------------------------------------------------
st.divider()
with st.expander("Delete dataset", expanded=False):
    del_name = st.selectbox("Dataset to delete", options=[d["name"] for d in datasets], key="del_select")
    if st.button("Delete", type="primary"):
        try:
            client.delete_dataset(del_name)
            st.success(f"Deleted `{del_name}`.")
            client.list_datasets.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"Delete failed: {exc}")
