import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
import streamlit as st
import pandas as pd

import _client as client

st.set_page_config(page_title="Jobs — mfethuls", layout="wide", page_icon="⚙️")
st.title("Jobs")

if client.mode() != "service":
    st.info("Job monitoring is only available in service mode (`MFETHULS_MODE=service`).")
    st.stop()

with st.sidebar:
    st.header("API connection")
    default_url = os.environ.get("MFETHULS_API_URL", "http://localhost:8000")
    default_key = os.environ.get("MFETHULS_API_KEY", "")
    st.session_state["api_url"] = st.text_input("API URL", value=st.session_state.get("api_url", default_url))
    st.session_state["api_key"] = st.text_input("API key", type="password", value=st.session_state.get("api_key", default_key))

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
ctrl1, ctrl2, ctrl3 = st.columns([2, 1, 1])
with ctrl1:
    status_filter = st.selectbox("Filter by status", ["all", "queued", "running", "completed", "failed"], index=0)
with ctrl2:
    limit = st.number_input("Limit", min_value=5, max_value=100, value=20, step=5)
with ctrl3:
    auto_refresh = st.toggle("Auto-refresh (10s)", value=False)

# ---------------------------------------------------------------------------
# Load jobs
# ---------------------------------------------------------------------------
status_arg = None if status_filter == "all" else status_filter

try:
    jobs = client.list_jobs(status=status_arg, limit=int(limit))
except Exception as exc:
    st.error(f"Could not load jobs: {exc}")
    st.stop()

if not jobs:
    st.info("No jobs found.")
else:
    _STATUS_COLOURS = {
        "queued": "🟡",
        "running": "🔵",
        "completed": "🟢",
        "failed": "🔴",
    }

    rows = []
    for j in jobs:
        status = j.get("status", "")
        rows.append({
            "icon": _STATUS_COLOURS.get(status, "⚪"),
            "job_id": j.get("job_id", "")[:12] + "…",
            "status": status,
            "progress": j.get("progress", 0),
            "message": j.get("message") or "",
            "storage_mode": j.get("storage_mode") or "",
            "created_at": str(j.get("created_at") or ""),
            "updated_at": str(j.get("updated_at") or ""),
            "_full_id": j.get("job_id", ""),
        })

    df_jobs = pd.DataFrame(rows)
    st.dataframe(
        df_jobs[["icon", "job_id", "status", "progress", "message", "storage_mode", "created_at", "updated_at"]],
        use_container_width=True,
        hide_index=True,
    )

    # ---------------------------------------------------------------------------
    # Inspect a single job
    # ---------------------------------------------------------------------------
    st.divider()
    st.subheader("Job detail")
    job_options = {f"{r['job_id']} ({r['status']})": r["_full_id"] for r in rows}
    chosen_label = st.selectbox("Job", options=list(job_options.keys()))
    chosen_id = job_options[chosen_label]

    if st.button("Load job"):
        try:
            job = client.get_job(chosen_id)
        except Exception as exc:
            st.error(f"Could not load job: {exc}")
            st.stop()

        status = job.get("status", "")
        progress = job.get("progress", 0)

        col1, col2, col3 = st.columns(3)
        col1.metric("Status", f"{_STATUS_COLOURS.get(status, '⚪')} {status}")
        col2.metric("Progress", f"{progress}%")
        col3.metric("Storage mode", job.get("storage_mode") or "—")

        st.progress(int(progress) / 100)

        if job.get("message"):
            st.caption(f"Message: {job['message']}")

        datasets = job.get("datasets") or []
        if datasets:
            st.subheader(f"Datasets ({len(datasets)})")
            df_ds = pd.DataFrame(datasets)
            st.dataframe(df_ds, use_container_width=True)

        with st.expander("Full job record", expanded=False):
            st.json(job)

# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------
if auto_refresh:
    time.sleep(10)
    st.rerun()
