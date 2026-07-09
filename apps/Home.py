import os
import streamlit as st

from _client import mode, api_url, health_check

st.set_page_config(page_title="mfethuls", layout="wide", page_icon="🧪")

# ---------------------------------------------------------------------------
# Sidebar — API config (service mode only)
# ---------------------------------------------------------------------------
if mode() == "service":
    with st.sidebar:
        st.header("API connection")
        default_url = os.environ.get("MFETHULS_API_URL", "http://localhost:8000")
        default_key = os.environ.get("MFETHULS_API_KEY", "")
        st.session_state["api_url"] = st.text_input("API URL", value=st.session_state.get("api_url", default_url))
        st.session_state["api_key"] = st.text_input("API key", type="password", value=st.session_state.get("api_key", default_key))
        ok, msg = health_check()
        if ok:
            st.success(f"✓ {msg}")
        else:
            st.error(f"✗ {msg}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
st.title("mfethuls")
st.caption("Laboratory data management and scientific exploration platform.")

current_mode = mode()
if current_mode == "service":
    st.info(f"Mode: **service** — connected to `{api_url()}`")
else:
    st.info("Mode: **local** — reading data directly from disk")

st.divider()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.subheader("Registry")
    st.write("Preview your experiment registry, validate rows, and trigger ingestion.")
    st.page_link("pages/1_Registry.py", label="Open Registry →")

with col2:
    st.subheader("Explorer")
    st.write("Overlay multi-experiment curves, configure axes, and export publication figures.")
    st.page_link("pages/2_Explorer.py", label="Open Explorer →")

with col3:
    st.subheader("Datasets")
    st.write("Browse all registered datasets, inspect columns and metadata.")
    st.page_link("pages/3_Datasets.py", label="Open Datasets →")

with col4:
    st.subheader("Jobs")
    if current_mode == "service":
        st.write("Monitor ingest job status and progress in real time.")
    else:
        st.write("Job monitoring is available in service mode only.")
    st.page_link("pages/4_Jobs.py", label="Open Jobs →")
