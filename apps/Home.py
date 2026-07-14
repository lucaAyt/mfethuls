"""mfethuls Streamlit app.

Entry point:
    streamlit run apps/Home.py
"""
from __future__ import annotations

import os
import time

import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st

import _client as client

st.set_page_config(page_title="mfethuls", layout="wide", page_icon="🧪")

st.title("mfethuls")
st.caption("Laboratory data management and scientific exploration platform.")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _figure_bytes(fig, fmt: str) -> bytes:
    if fmt == "html":
        return fig.to_html(include_plotlyjs="cdn", full_html=True).encode("utf8")
    return pio.to_image(fig, format=fmt)


def _figure_download_name(title: str, fmt: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in title).strip("_")
    return f"{safe or 'figure'}.{fmt}"


def _finite_bounds(values: pd.Series):
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    lo, hi = float(numeric.min()), float(numeric.max())
    if lo == hi:
        pad = abs(lo) * 0.05 or 1.0
        return lo - pad, hi + pad
    return lo, hi


def _storage_label(path: str) -> str:
    return "☁️ cloud" if path.startswith(("s3://", "az://", "https://")) else "📁 local"


# ===========================================================================
# SIDEBAR
# ===========================================================================

# ---------------------------------------------------------------------------
# API health (service mode only — credentials come from env vars)
# ---------------------------------------------------------------------------
if client.mode() == "service":
    with st.sidebar:
        ok, msg = client.health_check()
        if ok:
            st.success(f"✓ API {msg}")
        else:
            st.error(f"✗ API {msg}")
        st.divider()

# ---------------------------------------------------------------------------
# Ingest expander
# ---------------------------------------------------------------------------
with st.sidebar.expander("Ingest", expanded=False):

    if client.mode() == "local":
        registry_path = st.text_input(
            "Experiment registry path",
            value=os.environ.get("PATH_TO_REGISTRY", ""),
        )
        refresh_ingest = st.checkbox("Re-parse even if cached", value=False)

        experiment_names: list[str] = []
        if registry_path:
            try:
                from mfethuls.experiments import load_experiment_registry

                @st.cache_data(show_spinner=False)
                def _load_reg(path: str) -> pd.DataFrame:
                    return load_experiment_registry(path)

                exp_df = _load_reg(registry_path)
                experiment_names = (
                    exp_df.get("name", pd.Series(dtype=str))
                    .dropna()
                    .astype(str)
                    .tolist()
                )
            except Exception as exc:
                st.error(f"Could not load registry: {exc}")

        selected_experiments: list[str] = []
        if experiment_names:
            select_all = st.checkbox("Select all", value=False)
            selected_experiments = (
                experiment_names
                if select_all
                else st.multiselect("Experiments", options=experiment_names)
            )
            st.caption(f"{len(selected_experiments)} selected.")
        elif registry_path:
            st.info("No experiments found.")

        if st.button("Ingest", disabled=not selected_experiments, use_container_width=True):
            total = len(selected_experiments)
            progress_bar = st.progress(0)
            results: list[tuple[str, dict]] = []
            for i, name in enumerate(selected_experiments):
                res_list = client.local_ingest([name], registry_path, refresh=refresh_ingest)
                results.extend(res_list)
                progress_bar.progress((i + 1) / total)

            counts: dict[str, int] = {}
            errors = []
            for exp_name, res in results:
                s = res.get("status", "unknown")
                counts[s] = counts.get(s, 0) + 1
                if s == "error":
                    errors.append((exp_name, res.get("error", "")))

            for exp_name, err in errors:
                st.error(f"{exp_name}: {err}")
            summary = ", ".join(f"{k}: {v}" for k, v in counts.items())
            st.success(f"Done — {summary}")
            client.list_datasets.clear()
            st.rerun()

    else:
        # Service mode
        if st.button("Sync from OneDrive", use_container_width=True):
            with st.spinner("Syncing from OneDrive… this may take a minute"):
                try:
                    client.trigger_sync()
                    st.session_state["registry_experiments"] = client.list_registry_experiments()
                except Exception as exc:
                    st.error(f"Sync failed: {exc}")

        refresh_ingest = st.checkbox("Re-ingest even if cached", value=False)

        experiment_names = st.session_state.get("registry_experiments", [])
        select_all = False
        selected_experiments: list[str] = []
        if experiment_names:
            select_all = st.checkbox("Select all experiments", value=False)
            if select_all:
                selected_experiments = experiment_names
                st.caption(f"Selected {len(selected_experiments)} experiments.")
            else:
                selected_experiments = st.multiselect("Experiments", options=experiment_names)
        elif "registry_experiments" in st.session_state:
            st.info("No experiments found in registry.")
        else:
            st.caption("Sync to load the experiment list.")

        storage_mode = st.selectbox("Storage mode", ["local", "cloud", "both"], index=0)
        cloud_provider = None
        if storage_mode in {"cloud", "both"}:
            cloud_provider = st.selectbox("Cloud provider", ["s3", "azure"])
        allow_invalid = st.checkbox("Allow invalid rows", value=False)

        if st.button("Ingest experiments", disabled=not selected_experiments, use_container_width=True):
            try:
                result = client.trigger_ingest_service(
                    storage_mode=storage_mode,
                    cloud_provider=cloud_provider,
                    allow_invalid=allow_invalid,
                    experiments=None if select_all else selected_experiments,
                    refresh=refresh_ingest,
                )
                st.session_state["ingest_job_id"] = result.get("job_id")
            except Exception as exc:
                st.error(f"Failed: {exc}")

        job_id = st.session_state.get("ingest_job_id")
        if job_id:
            try:
                job = client.get_job(job_id)
                status = job.get("status", "")
                progress = int(job.get("progress", 0))
                message = job.get("message") or ""
                _ICON = {"queued": "🟡", "running": "🔵", "completed": "🟢", "failed": "🔴"}
                st.markdown(f"{_ICON.get(status, '⚪')} **{status}**")
                if message:
                    st.caption(message)
                st.progress(progress / 100)
                if status in ("queued", "running"):
                    time.sleep(2)
                    st.rerun()
                elif status == "completed":
                    datasets = job.get("datasets") or []
                    counts: dict[str, int] = {}
                    failed_names: list[str] = []
                    for d in datasets:
                        s = d.get("status", "unknown")
                        counts[s] = counts.get(s, 0) + 1
                        if s == "failed":
                            failed_names.append(d.get("name") or d.get("experiment_id") or "?")
                    summary = ", ".join(f"{k}: {v}" for k, v in counts.items()) or "no results"
                    if failed_names:
                        st.warning(f"Completed with errors — {summary}")
                        with st.expander(f"{len(failed_names)} failed"):
                            for n in failed_names:
                                st.caption(f"✗ {n}")
                    else:
                        st.success(f"Ingestion complete — {summary}")
                    client.list_datasets.clear()
                    st.session_state["ingest_job_id"] = None
                elif status == "failed":
                    st.error(f"Ingest failed: {message}")
                    st.session_state["ingest_job_id"] = None
            except Exception as exc:
                st.error(f"Could not fetch job status: {exc}")
                st.session_state["ingest_job_id"] = None

# ---------------------------------------------------------------------------
# Datasets expander
# ---------------------------------------------------------------------------
with st.sidebar.expander("Datasets", expanded=True):
    if st.button("Refresh", use_container_width=True):
        client.list_datasets.clear()
        st.rerun()

    try:
        datasets = client.list_datasets()
    except Exception as exc:
        st.error(f"Could not load datasets: {exc}")
        datasets = []

    if not datasets:
        st.warning("No datasets registered yet.")
        selected_labels: list[str] = []
        label_to_name: dict[str, str] = {}
    else:
        rows = []
        for d in datasets:
            rows.append({
                "name": d.get("experiment_name") or d["name"],
                "sample_id": d.get("sample_id") or "",
                "run_id": d.get("run_id") or "",
                "instrument": d.get("instrument_name") or d.get("instrument_type") or "",
                "storage": _storage_label(d.get("storage_path", "")),
                "_key": d["name"],
            })

        df_reg = pd.DataFrame(rows)
        show_paths = st.toggle("Show storage", value=False)
        display_cols = ["name", "sample_id", "run_id", "instrument"]
        if show_paths:
            display_cols.append("storage")
        st.dataframe(df_reg[display_cols], use_container_width=True, hide_index=True)

        label_to_name = {
            (d.get("experiment_name") or d["name"]): d["name"] for d in datasets
        }
        selected_labels = st.multiselect(
            "Select experiments to plot",
            options=list(label_to_name.keys()),
        )

# ---------------------------------------------------------------------------
# Query expander
# ---------------------------------------------------------------------------
with st.sidebar.expander("Query", expanded=False):
    row_limit = st.number_input(
        "Row limit", min_value=10, max_value=1_000_000, value=5000, step=500
    )

# ===========================================================================
# MAIN CONTENT
# ===========================================================================

selected_names = [label_to_name[l] for l in selected_labels] if selected_labels else []

if not selected_names:
    st.info("Select one or more experiments from the **Datasets** sidebar to begin.")
    st.stop()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
frames: list[pd.DataFrame] = []
for label, name in zip(selected_labels, selected_names):
    try:
        df = client.query_dataset(name, limit=int(row_limit))
        df["_experiment"] = label
        frames.append(df)
    except Exception as exc:
        st.error(f"Failed to load {name}: {exc}")

if not frames:
    st.stop()

data = pd.concat(frames, ignore_index=True)

# ---------------------------------------------------------------------------
# Dataset info
# ---------------------------------------------------------------------------
st.subheader("Dataset info")
col_a, col_b, col_c = st.columns(3)
col_a.metric("Rows", f"{len(data):,}")
col_b.metric("Columns", len(data.columns) - 1)
col_c.metric("Experiments", len(selected_names))

# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------
with st.expander("Preview", expanded=True):
    st.dataframe(
        data.drop(columns=["_experiment"], errors="ignore"),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
with st.expander("Filters", expanded=False):
    filter_cols = [c for c in data.columns if c != "_experiment"]
    filter_col = st.selectbox("Filter column", options=["(none)"] + filter_cols, index=0)
    if filter_col != "(none)":
        raw_vals = sorted(data[filter_col].dropna().astype(str).unique().tolist())
        sel_vals = st.multiselect("Keep values", options=raw_vals)
        if sel_vals:
            data = data[data[filter_col].astype(str).isin(sel_vals)]

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
with st.expander("Plot", expanded=True):
    numeric_cols = data.select_dtypes(include="number").columns.tolist()

    if len(numeric_cols) < 1:
        st.info("No numeric columns available for plotting.")
    else:
        ctrl1, ctrl2, ctrl3 = st.columns(3)
        with ctrl1:
            plot_type = st.selectbox("Plot type", ["line", "scatter", "histogram", "box"])
            x_col = st.selectbox("X axis", numeric_cols, index=0)
        with ctrl2:
            hue_opts = ["_experiment"] + [c for c in data.columns if c != "_experiment"]
            color_col = st.selectbox("Colour by", hue_opts, index=0)
            y_options = [c for c in numeric_cols if c != x_col]
            y_cols = st.multiselect("Y axis", y_options, default=y_options[:1] if y_options else [])
        with ctrl3:
            use_log_x = st.checkbox("Log X")
            use_log_y = st.checkbox("Log Y")
            invert_x = st.checkbox("Invert X axis", value=False)

        _PALETTES = {
            "Plotly": px.colors.qualitative.Plotly,
            "D3": px.colors.qualitative.D3,
            "G10": px.colors.qualitative.G10,
            "Bold": px.colors.qualitative.Bold,
            "Safe": px.colors.qualitative.Safe,
            "Dark2": px.colors.qualitative.Dark2,
            "Set2": px.colors.qualitative.Set2,
        }
        palette_name = st.selectbox("Colour palette", list(_PALETTES.keys()), index=0)
        discrete_seq = _PALETTES[palette_name]

        if not y_cols and plot_type != "histogram":
            st.info("Select at least one Y axis column.")
        else:
            title = f"{x_col} vs {', '.join(y_cols)}" if y_cols else x_col

            if len(y_cols) > 1 or color_col == "_experiment":
                id_vars = [x_col, "_experiment"] + (
                    [color_col] if color_col not in {x_col, "_experiment"} else []
                )
                id_vars = list(dict.fromkeys(id_vars))
                long_df = data[id_vars + y_cols].melt(
                    id_vars=id_vars,
                    value_vars=y_cols,
                    var_name="_y_metric",
                    value_name="_y_value",
                )
                color = "_y_metric" if len(y_cols) > 1 and color_col == "_experiment" else color_col
                y_series = "_y_value"
            else:
                long_df = data.copy()
                y_series = y_cols[0] if y_cols else x_col
                color = color_col

            if plot_type == "line":
                fig = px.line(long_df, x=x_col, y=y_series, color=color,
                              title=title, color_discrete_sequence=discrete_seq)
            elif plot_type == "histogram":
                fig = px.histogram(data, x=x_col, color=color_col,
                                   title=f"Histogram: {x_col}", color_discrete_sequence=discrete_seq)
            elif plot_type == "box":
                fig = px.box(long_df,
                             x="_y_metric" if "_y_metric" in long_df.columns else x_col,
                             y=y_series, color=color,
                             title=title, color_discrete_sequence=discrete_seq)
            else:
                fig = px.scatter(long_df, x=x_col, y=y_series, color=color,
                                 title=title, color_discrete_sequence=discrete_seq)

            fig.update_xaxes(type="log" if use_log_x else "linear",
                             autorange="reversed" if invert_x else True)
            fig.update_yaxes(type="log" if use_log_y else "linear")

            # Export ---------------------------------------------------------
            with st.expander("Export plot", expanded=False):
                dl1, dl2 = st.columns(2)
                dl1.download_button(
                    "Download SVG",
                    data=_figure_bytes(fig, "svg"),
                    file_name=_figure_download_name(title, "svg"),
                    mime="image/svg+xml",
                    use_container_width=True,
                )
                dl2.download_button(
                    "Download HTML",
                    data=_figure_bytes(fig, "html"),
                    file_name=_figure_download_name(title, "html"),
                    mime="text/html",
                    use_container_width=True,
                )

            st.plotly_chart(
                fig,
                use_container_width=True,
                config={
                    "displaylogo": False,
                    "toImageButtonOptions": {
                        "format": "svg",
                        "filename": _figure_download_name(title, "svg"),
                    },
                },
            )
