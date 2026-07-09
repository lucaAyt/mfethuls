"""mfethuls Streamlit app — single-page, three-tab layout.

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

# ---------------------------------------------------------------------------
# Sidebar — API config (service mode only)
# ---------------------------------------------------------------------------
if client.mode() == "service":
    with st.sidebar:
        st.header("API")
        default_url = os.environ.get("MFETHULS_API_URL", "http://localhost:8000")
        default_key = os.environ.get("MFETHULS_API_KEY", "")
        st.session_state["api_url"] = st.text_input(
            "URL", value=st.session_state.get("api_url", default_url)
        )
        st.session_state["api_key"] = st.text_input(
            "Key", type="password", value=st.session_state.get("api_key", default_key)
        )
        ok, msg = client.health_check()
        st.success(f"✓ {msg}") if ok else st.error(f"✗ {msg}")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("mfethuls")
mode_label = "service" if client.mode() == "service" else "local"
st.caption(f"Mode: **{mode_label}**")

tab_ingest, tab_explorer, tab_datasets = st.tabs(["Ingest", "Explorer", "Datasets"])


# ===========================================================================
# INGEST TAB
# ===========================================================================
with tab_ingest:

    # -----------------------------------------------------------------------
    # Local mode
    # -----------------------------------------------------------------------
    if client.mode() == "local":
        registry_path = st.text_input(
            "Experiment registry path",
            value=os.environ.get("PATH_TO_REGISTRY", ""),
            help="Path to a CSV or XLSX experiments registry file.",
        )

        if st.button("Preview & validate", key="local_validate"):
            with st.spinner("Validating…"):
                try:
                    result = client.preview_registry()
                    summary = result.get("summary", {})
                    rows = result.get("rows", [])
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total", summary.get("total", len(rows)))
                    c2.metric("Valid", summary.get("valid", 0))
                    c3.metric("Invalid", summary.get("invalid", 0))
                    if rows:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True)
                except Exception as exc:
                    st.error(f"Validation failed: {exc}")

        st.divider()

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

        if experiment_names:
            select_all = st.checkbox("Select all", value=False)
            selected = (
                experiment_names
                if select_all
                else st.multiselect("Experiments to ingest", options=experiment_names)
            )
            st.caption(f"{len(selected)} experiment(s) selected.")
        else:
            selected = []
            if registry_path:
                st.info("No experiments found in registry.")

        refresh = st.checkbox("Re-parse even if cached", value=False)

        if st.button("Run ingest", disabled=not selected, type="primary"):
            progress_bar = st.progress(0, text="Starting…")
            status_text = st.empty()
            total = len(selected)
            results = []
            for i, name in enumerate(selected):
                status_text.caption(f"Ingesting {name} ({i + 1}/{total})…")
                progress_bar.progress((i) / total, text=f"{i}/{total} experiments")
                res_list = client.local_ingest([name], registry_path, refresh=refresh)
                results.extend(res_list)
            progress_bar.progress(1.0, text="Done")
            status_text.empty()

            counts: dict[str, int] = {}
            errors = []
            for exp_name, res in results:
                s = res.get("status", "unknown")
                counts[s] = counts.get(s, 0) + 1
                if s == "error":
                    errors.append((exp_name, res.get("error", "")))

            for exp_name, err in errors:
                st.error(f"{exp_name}: {err}")
            summary_str = ", ".join(f"{k}: {v}" for k, v in counts.items())
            st.success(f"Ingestion complete — {summary_str}")
            client.list_datasets.clear()

    # -----------------------------------------------------------------------
    # Service mode
    # -----------------------------------------------------------------------
    else:
        st.caption(
            "The registry CSV must be present at `PATH_TO_REGISTRY` on the server. "
            "Upload here only to preview/validate without triggering an ingest."
        )

        uploaded = st.file_uploader("Preview registry (optional)", type=["csv", "xlsx"])
        if st.button("Preview & validate", key="svc_validate"):
            with st.spinner("Validating…"):
                try:
                    file_bytes = uploaded.read() if uploaded else None
                    fname = uploaded.name if uploaded else None
                    result = client.preview_registry(file_bytes=file_bytes, filename=fname)
                    summary = result.get("summary", {})
                    rows = result.get("rows", [])
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total", summary.get("total", len(rows)))
                    c2.metric("Valid", summary.get("valid", 0))
                    c3.metric("Invalid", summary.get("invalid", 0))
                    if rows:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True)
                except Exception as exc:
                    st.error(f"Validation failed: {exc}")

        st.divider()

        storage_mode = st.selectbox("Storage mode", ["local", "cloud", "both"], index=0)
        cloud_provider = None
        if storage_mode in {"cloud", "both"}:
            cloud_provider = st.selectbox("Cloud provider", ["s3", "azure"])
        allow_invalid = st.checkbox("Allow invalid rows", value=False)

        if st.button("Run ingest", type="primary"):
            try:
                result = client.trigger_ingest_service(
                    storage_mode=storage_mode,
                    cloud_provider=cloud_provider,
                    allow_invalid=allow_invalid,
                )
                st.session_state["ingest_job_id"] = result.get("job_id")
            except Exception as exc:
                st.error(f"Failed to queue job: {exc}")

        # Live progress polling
        job_id = st.session_state.get("ingest_job_id")
        if job_id:
            try:
                job = client.get_job(job_id)
            except Exception as exc:
                st.error(f"Could not fetch job status: {exc}")
                st.session_state["ingest_job_id"] = None
                job = None

            if job:
                status = job.get("status", "")
                progress = int(job.get("progress", 0))
                message = job.get("message") or ""

                _STATUS_ICON = {
                    "queued": "🟡",
                    "running": "🔵",
                    "completed": "🟢",
                    "failed": "🔴",
                }
                st.markdown(
                    f"{_STATUS_ICON.get(status, '⚪')} **{status}** — {message}"
                )
                st.progress(progress / 100)

                if status in ("queued", "running"):
                    time.sleep(2)
                    st.rerun()
                elif status == "completed":
                    st.success("Ingest complete!")
                    client.list_datasets.clear()
                    st.session_state["ingest_job_id"] = None
                elif status == "failed":
                    st.error(f"Ingest failed: {message}")
                    st.session_state["ingest_job_id"] = None


# ===========================================================================
# EXPLORER TAB
# ===========================================================================
with tab_explorer:

    # Helpers ----------------------------------------------------------------
    def _figure_bytes(fig, fmt: str) -> bytes:
        if fmt == "html":
            return fig.to_html(include_plotlyjs="cdn", full_html=True).encode("utf8")
        return pio.to_image(fig, format=fmt)

    def _figure_download_name(title: str, fmt: str) -> str:
        safe = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in title
        ).strip("_")
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

    # Dataset selection ------------------------------------------------------
    with st.spinner("Loading dataset list…"):
        try:
            datasets = client.list_datasets()
        except Exception as exc:
            st.error(f"Could not load datasets: {exc}")
            datasets = []

    if not datasets:
        st.info("No datasets registered yet. Use the Ingest tab to add experiments.")
    else:
        label_to_name = {
            (d.get("experiment_name") or d["name"]): d["name"] for d in datasets
        }

        sel_col, opt_col = st.columns([3, 1])
        with sel_col:
            selected_labels = st.multiselect(
                "Experiments to overlay", options=list(label_to_name.keys())
            )
        with opt_col:
            limit = st.number_input(
                "Row limit", min_value=100, max_value=1_000_000, value=5000, step=500
            )
            if st.button("Refresh list", key="exp_refresh"):
                client.list_datasets.clear()
                st.rerun()

        selected_names = [label_to_name[l] for l in selected_labels]

        if not selected_names:
            st.info("Select one or more experiments above to begin.")
        else:
            # Load data ------------------------------------------------------
            frames: list[pd.DataFrame] = []
            for label, name in zip(selected_labels, selected_names):
                try:
                    df = client.query_dataset(name, limit=int(limit))
                    df["_experiment"] = label
                    frames.append(df)
                except Exception as exc:
                    st.error(f"Failed to load {name}: {exc}")

            if not frames:
                st.stop()

            data = pd.concat(frames, ignore_index=True)

            # Metrics --------------------------------------------------------
            m1, m2, m3 = st.columns(3)
            m1.metric("Rows", f"{len(data):,}")
            m2.metric("Columns", len(data.columns) - 1)
            m3.metric("Experiments", len(selected_names))

            # Filters --------------------------------------------------------
            filter_cols = [c for c in data.columns if c != "_experiment"]
            with st.expander("Filters", expanded=False):
                filter_col = st.selectbox(
                    "Filter column",
                    options=["(none)"] + filter_cols,
                    index=0,
                    key="exp_filter_col",
                )
                if filter_col != "(none)":
                    raw_vals = sorted(
                        data[filter_col].dropna().astype(str).unique().tolist()
                    )
                    sel_vals = st.multiselect(
                        "Keep values", options=raw_vals, key="exp_filter_vals"
                    )
                    if sel_vals:
                        data = data[data[filter_col].astype(str).isin(sel_vals)]

            # Plot settings --------------------------------------------------
            numeric_cols = data.select_dtypes(include="number").columns.tolist()
            all_cols = [c for c in data.columns if c != "_experiment"]

            if len(numeric_cols) < 1:
                st.warning("No numeric columns in selected datasets.")
            else:
                with st.expander("Plot settings", expanded=True):
                    ctrl1, ctrl2, ctrl3 = st.columns(3)
                    with ctrl1:
                        plot_type = st.selectbox(
                            "Plot type", ["line", "scatter", "histogram", "box"]
                        )
                        x_col = st.selectbox("X axis", numeric_cols, index=0)
                    with ctrl2:
                        y_options = [c for c in numeric_cols if c != x_col]
                        y_cols = st.multiselect(
                            "Y axis",
                            y_options,
                            default=y_options[:1] if y_options else [],
                        )
                        hue_opts = ["_experiment"] + all_cols
                        color_col = st.selectbox("Colour by", hue_opts, index=0)
                    with ctrl3:
                        use_log_x = st.checkbox("Log X")
                        use_log_y = st.checkbox("Log Y")
                        invert_x = st.checkbox("Invert X axis", value=False)

                    _DISCRETE = {
                        "Plotly": px.colors.qualitative.Plotly,
                        "D3": px.colors.qualitative.D3,
                        "G10": px.colors.qualitative.G10,
                        "Bold": px.colors.qualitative.Bold,
                        "Safe": px.colors.qualitative.Safe,
                        "Dark2": px.colors.qualitative.Dark2,
                        "Set2": px.colors.qualitative.Set2,
                    }
                    palette_name = st.selectbox(
                        "Colour palette", list(_DISCRETE.keys()), index=0
                    )
                    discrete_seq = _DISCRETE[palette_name]

                if not y_cols and plot_type != "histogram":
                    st.info("Select at least one Y axis column.")
                else:
                    # Build figure -------------------------------------------
                    title = (
                        f"{x_col} vs {', '.join(y_cols)}" if y_cols else x_col
                    )

                    if len(y_cols) > 1 or color_col == "_experiment":
                        id_vars = [x_col, "_experiment"] + (
                            [color_col]
                            if color_col not in {x_col, "_experiment"}
                            else []
                        )
                        id_vars = list(dict.fromkeys(id_vars))
                        long_df = data[id_vars + y_cols].melt(
                            id_vars=id_vars,
                            value_vars=y_cols,
                            var_name="_y_metric",
                            value_name="_y_value",
                        )
                        color = (
                            "_y_metric"
                            if len(y_cols) > 1 and color_col == "_experiment"
                            else color_col
                        )
                        y_series = "_y_value"
                    else:
                        long_df = data.copy()
                        y_series = y_cols[0] if y_cols else x_col
                        color = color_col

                    if plot_type == "line":
                        fig = px.line(
                            long_df, x=x_col, y=y_series, color=color,
                            title=title, color_discrete_sequence=discrete_seq,
                        )
                    elif plot_type == "histogram":
                        fig = px.histogram(
                            data, x=x_col, color=color_col,
                            title=f"Histogram: {x_col}",
                            color_discrete_sequence=discrete_seq,
                        )
                    elif plot_type == "box":
                        fig = px.box(
                            long_df,
                            x="_y_metric" if "_y_metric" in long_df.columns else x_col,
                            y=y_series, color=color,
                            title=title, color_discrete_sequence=discrete_seq,
                        )
                    else:
                        fig = px.scatter(
                            long_df, x=x_col, y=y_series, color=color,
                            title=title, color_discrete_sequence=discrete_seq,
                        )

                    fig.update_xaxes(
                        type="log" if use_log_x else "linear",
                        autorange="reversed" if invert_x else True,
                    )
                    fig.update_yaxes(type="log" if use_log_y else "linear")

                    # Export -------------------------------------------------
                    with st.expander("Export", expanded=False):
                        x_bounds = _finite_bounds(data[x_col])
                        y_bounds = (
                            _finite_bounds(long_df[y_series])
                            if y_series in long_df.columns
                            else None
                        )
                        rc = st.columns(2)
                        use_x_range = rc[0].checkbox("Limit X range")
                        use_y_range = rc[1].checkbox("Limit Y range")
                        if use_x_range and x_bounds:
                            xr = st.columns(2)
                            x_min = xr[0].number_input(
                                "X min", value=float(x_bounds[0]), format="%.6f"
                            )
                            x_max = xr[1].number_input(
                                "X max", value=float(x_bounds[1]), format="%.6f"
                            )
                            fig.update_xaxes(range=[x_min, x_max])
                        if use_y_range and y_bounds:
                            yr = st.columns(2)
                            y_min = yr[0].number_input(
                                "Y min", value=float(y_bounds[0]), format="%.6f"
                            )
                            y_max = yr[1].number_input(
                                "Y max", value=float(y_bounds[1]), format="%.6f"
                            )
                            fig.update_yaxes(range=[y_min, y_max])

                        st.divider()
                        dl_cols = st.columns(3)
                        for col, fmt, mime in zip(
                            dl_cols,
                            ["svg", "png", "html"],
                            ["image/svg+xml", "image/png", "text/html"],
                        ):
                            try:
                                col.download_button(
                                    f"Download {fmt.upper()}",
                                    data=_figure_bytes(fig, fmt),
                                    file_name=_figure_download_name(title, fmt),
                                    mime=mime,
                                    use_container_width=True,
                                )
                            except Exception as exc:
                                col.warning(f"{fmt.upper()} unavailable: {exc}")

                    # Chart --------------------------------------------------
                    st.plotly_chart(
                        fig,
                        use_container_width=True,
                        config={
                            "displaylogo": False,
                            "toImageButtonOptions": {
                                "format": "svg",
                                "filename": "mfethuls_figure",
                            },
                        },
                    )

                    with st.expander("Raw data preview", expanded=False):
                        st.dataframe(
                            data.drop(columns=["_experiment"], errors="ignore"),
                            use_container_width=True,
                        )


# ===========================================================================
# DATASETS TAB
# ===========================================================================
with tab_datasets:

    def _storage_label(storage_path: str) -> str:
        return (
            "cloud"
            if storage_path.startswith(("s3://", "az://", "https://"))
            else "local"
        )

    col_refresh, _ = st.columns([1, 5])
    if col_refresh.button("Refresh", key="ds_refresh"):
        client.list_datasets.clear()
        st.rerun()

    with st.spinner("Loading…"):
        try:
            ds_datasets = client.list_datasets()
        except Exception as exc:
            st.error(f"Could not load datasets: {exc}")
            ds_datasets = []

    if not ds_datasets:
        st.info("No datasets registered yet. Use the Ingest tab to add experiments.")
    else:
        rows = []
        for d in ds_datasets:
            rows.append({
                "experiment_name": d.get("experiment_name") or d.get("name", ""),
                "sample_id": d.get("sample_id") or "",
                "run_id": d.get("run_id") or "",
                "instrument": d.get("instrument_name") or d.get("instrument_type") or "",
                "storage": _storage_label(d.get("storage_path", "")),
                "registered_at": d.get("registered_at", ""),
                "storage_path": d.get("storage_path", ""),
                "_name": d["name"],
            })

        df_summary = pd.DataFrame(rows)
        show_paths = st.toggle("Show full paths", value=False)
        display_cols = [
            "experiment_name", "sample_id", "run_id", "instrument",
            "storage", "registered_at",
        ]
        if show_paths:
            display_cols.append("storage_path")

        st.dataframe(df_summary[display_cols], use_container_width=True)
        st.caption(f"{len(ds_datasets)} dataset(s) registered.")

        # Inspect ------------------------------------------------------------
        st.divider()
        st.subheader("Inspect")

        label_to_name_ds = {
            (d.get("experiment_name") or d["name"]): d["name"] for d in ds_datasets
        }
        sel_label = st.selectbox("Dataset", options=list(label_to_name_ds.keys()))
        sel_name = label_to_name_ds[sel_label]
        row_limit = st.number_input(
            "Row limit", min_value=10, max_value=100_000, value=200, step=100
        )

        if st.button("Load", key="ds_load"):
            with st.spinner(f"Querying {sel_name}…"):
                try:
                    df = client.query_dataset(sel_name, limit=int(row_limit))
                except Exception as exc:
                    st.error(f"Query failed: {exc}")
                    df = None

            if df is not None:
                meta = next((d for d in ds_datasets if d["name"] == sel_name), {})
                display_meta = {k: v for k, v in meta.items() if v and k != "storage_path"}
                if display_meta:
                    with st.expander("Metadata", expanded=False):
                        st.json(display_meta)

                mc1, mc2 = st.columns(2)
                mc1.metric("Rows", f"{len(df):,}")
                mc2.metric("Columns", len(df.columns))

                with st.expander("Column types", expanded=False):
                    st.dataframe(
                        pd.DataFrame(
                            {"column": df.columns, "dtype": [str(t) for t in df.dtypes]}
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

                st.dataframe(df, use_container_width=True)

        # Delete -------------------------------------------------------------
        st.divider()
        with st.expander("Delete dataset", expanded=False):
            del_name = st.selectbox(
                "Dataset to delete",
                options=[d["name"] for d in ds_datasets],
                key="del_select",
            )
            if st.button("Delete", type="primary", key="ds_delete"):
                try:
                    client.delete_dataset(del_name)
                    st.success(f"Deleted `{del_name}`.")
                    client.list_datasets.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")
