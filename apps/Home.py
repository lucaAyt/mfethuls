"""mfethuls Streamlit app.

Entry point:
    streamlit run apps/Home.py
"""
from __future__ import annotations

import io
import os
import threading
import time

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st
from plotly.colors import convert_colors_to_same_type

import _client as client
from mfethuls.dataset import Dataset
from mfethuls.plotting import PlotError, PlotSpec, build_experiments_spec, plotly_config
from mfethuls.plotting.backend import render
from mfethuls.plotting.labels import axis_label, legend_name, shared_axis_label
from mfethuls.plotting.spec import Colorbar, Panel, Trace
from mfethuls.schema_normalization import add_elapsed_time

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


# Downloads are generated on click in a separate thread; pyplot is not thread-safe.
_MATPLOTLIB_LOCK = threading.Lock()


def _svg_bytes(spec: PlotSpec) -> bytes:
    """Vector SVG via Matplotlib, sized like the notebook figures; Plotly would rasterize WebGL traces."""
    with _MATPLOTLIB_LOCK:
        fig, _ = render(spec, backend="matplotlib")
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", bbox_inches="tight")
        plt.close(fig)
    return buf.getvalue()


# Colour choices for the generic plot: discrete palettes for categories, Matplotlib
# colour maps (used by both renderers) for numeric colour columns with many values.
_DISCRETE_PALETTES = {
    "Plotly": px.colors.qualitative.Plotly,
    "D3": px.colors.qualitative.D3,
    "G10": px.colors.qualitative.G10,
    "Bold": px.colors.qualitative.Bold,
    "Safe": px.colors.qualitative.Safe,
    "Dark2": px.colors.qualitative.Dark2,
    "Set2": px.colors.qualitative.Set2,
}
_CONTINUOUS_PALETTES = [
    "viridis", "plasma", "inferno", "magma", "cividis", "turbo",
    "coolwarm", "RdBu", "Spectral", "Blues", "Reds", "Greys",
]

# Rows shown in the Preview table.
_PREVIEW_ROWS = 1_000

# Legend titles for the app's helper columns.
_LEGEND_TITLES = {"_experiment": "Experiment", "_y_metric": "Signal"}


def _legend_entry(color: str, value: str) -> str:
    """Readable legend entry; values of _y_metric are column names."""
    return legend_name(value) if color == "_y_metric" else value


# Colouring by a text column with more distinct values than this draws one uncoloured series.
_MAX_COLOUR_GROUPS = 50
# A numeric colour column with more values than _MAX_LEGEND_ENTRIES gets a colour bar
# instead of a legend, up to _MAX_COLORBAR_GROUPS lines (e.g. one per spectrum in time_s).
_MAX_LEGEND_ENTRIES = 10
_MAX_COLORBAR_GROUPS = 300


def _uses_colorbar(df: pd.DataFrame, color: str | None) -> bool:
    return (
        color is not None
        and pd.api.types.is_numeric_dtype(df[color])
        and df[color].nunique() > _MAX_LEGEND_ENTRIES
    )


def _xy_spec(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    color: str | None,
    mode: str,
    palette: list,
    cmap: str = "viridis",
    title: str,
    ylabel: str,
    log_x: bool,
    log_y: bool,
    invert_x: bool,
) -> PlotSpec:
    """Line/scatter spec: one colour per value of ``color``, one line per experiment."""
    split = ["_experiment"] if mode == "lines" and "_experiment" in df.columns else []
    keys = list(dict.fromkeys(([color] if color else []) + split))
    colorbar = None
    if _uses_colorbar(df, color):
        colorbar = Colorbar(
            title=axis_label(color), vmin=float(df[color].min()), vmax=float(df[color].max()), cmap=cmap
        )

    traces: list[Trace] = []
    colour_index: dict[str, int] = {}
    groups = df.groupby(keys, dropna=False, sort=False) if keys else [((), df)]
    for key, subset in groups:
        key = key if isinstance(key, tuple) else (key,)
        colour_value = str(key[0]) if color else ""
        first = colour_value not in colour_index
        idx = colour_index.setdefault(colour_value, len(colour_index))
        traces.append(
            Trace(
                subset[x].to_numpy(),
                subset[y].to_numpy(),
                # Lines split per experiment share a colour; only the first gets a legend entry.
                label=_legend_entry(color, colour_value) if color and first else None,
                color=palette[idx % len(palette)],
                color_value=float(key[0]) if colorbar is not None and pd.notna(key[0]) else None,
                mode=mode,
                legend_group=colour_value,
            )
        )

    panel = Panel(
        traces=traces,
        title=title,
        xlabel=axis_label(x),
        ylabel=ylabel,
        xscale="log" if log_x else "linear",
        yscale="log" if log_y else "linear",
        x_reversed=invert_x,
        legend=color is not None and colorbar is None,
        legend_title=_LEGEND_TITLES.get(color) or legend_name(color),
        colorbar=colorbar,
    )
    return PlotSpec([panel])


def _builtin_datasets(data: pd.DataFrame, datasets_meta: dict) -> list[Dataset]:
    """One mfethuls Dataset per selected experiment, for the built-in instrument plots."""
    result = []
    for label, subset in data.groupby("_experiment", sort=False):
        meta = datasets_meta.get(label, {})
        result.append(
            Dataset(
                data=subset.drop(columns=["_experiment"]).reset_index(drop=True),
                metadata={
                    "experiment_name": label,
                    "instrument_type": meta.get("instrument_type") or None,
                },
            )
        )
    return result


def _plot_toolbar():
    """Row above the chart: axis limits, SVG download, HTML download."""
    limits_col, svg_col, html_col, _ = st.columns([1, 1, 1, 3], vertical_alignment="bottom")
    return limits_col, svg_col, html_col


_LIMIT_FIELDS = ("x_min", "x_max", "y_min", "y_max")


def _reset_axis_limits(key: str) -> None:
    for field in _LIMIT_FIELDS:
        st.session_state[f"{key}|{field}"] = None


def _trace_bounds(arrays: list, *, log: bool):
    """Automatic (low, high) over all traces; positive values only on a log axis."""
    values = pd.concat([pd.Series(array) for array in arrays], ignore_index=True) if arrays else pd.Series(dtype=float)
    values = pd.to_numeric(values, errors="coerce")
    return _finite_bounds(values[values > 0] if log else values)


def _resolve_limits(low, high, auto, *, log: bool):
    """Turn the two inputs into (low, high) limits, or None with a message when they don't work."""
    if low is None and high is None:
        return None, None
    if auto is None and (low is None or high is None):
        return None, "Set both limits for this axis."
    low = auto[0] if low is None else low
    high = auto[1] if high is None else high
    if low >= high:
        return None, "Min must be smaller than max."
    if log and low <= 0:
        return None, "A log axis needs limits above zero."
    return (low, high), None


def _axis_limits_popover(container, panel: Panel, key: str) -> None:
    """Min/max fields per axis that set ``panel.xlim``/``panel.ylim``; empty fields stay automatic."""
    customised = any(st.session_state.get(f"{key}|{field}") is not None for field in _LIMIT_FIELDS)
    with container.popover(
        "Axis limits",
        icon=":material/crop_free:",
        type="primary" if customised else "secondary",
        width="stretch",
    ):
        st.caption("Leave a field empty for the automatic limit. Limits apply to the chart and the SVG.")
        for axis, label, scale in (("x", panel.xlabel, panel.xscale), ("y", panel.ylabel, panel.yscale)):
            log = scale == "log"
            auto = _trace_bounds([getattr(trace, axis) for trace in panel.traces], log=log)
            st.markdown(f"**{label or axis.upper()}**")
            low_col, high_col = st.columns(2)
            low = low_col.number_input(
                "Min", value=None, format="%g", key=f"{key}|{axis}_min",
                placeholder=f"{auto[0]:.4g}" if auto else "auto",
            )
            high = high_col.number_input(
                "Max", value=None, format="%g", key=f"{key}|{axis}_max",
                placeholder=f"{auto[1]:.4g}" if auto else "auto",
            )
            limits, problem = _resolve_limits(low, high, auto, log=log)
            if problem:
                st.warning(problem, icon=":material/warning:")
            setattr(panel, f"{axis}lim", limits)
        st.button(
            "Reset to automatic",
            icon=":material/restart_alt:",
            on_click=_reset_axis_limits,
            args=(key,),
            width="stretch",
        )


def _limits_unavailable(container, reason: str) -> None:
    container.popover("Axis limits", icon=":material/crop_free:", disabled=True, help=reason, width="stretch")


def _download_buttons(svg_col, html_col, title: str, *, spec: PlotSpec | None, fig) -> None:
    """SVG and HTML downloads, generated only when clicked (large figures take a moment)."""
    svg_col.download_button(
        "SVG",
        icon=":material/download:",
        help="Vector figure for publication, drawn with Matplotlib using the axis limits above.",
        data=(lambda: _svg_bytes(spec)) if spec is not None else (lambda: _figure_bytes(fig, "svg")),
        file_name=_figure_download_name(title, "svg"),
        mime="image/svg+xml",
        width="stretch",
    )
    html_col.download_button(
        "HTML",
        icon=":material/download:",
        help="Interactive Plotly figure as a standalone web page.",
        data=lambda: _figure_bytes(fig, "html"),
        file_name=_figure_download_name(title, "html"),
        mime="text/html",
        width="stretch",
    )


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

        if st.button("Ingest", disabled=not selected_experiments, width="stretch"):
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
            client.query_dataset.clear()
            st.rerun()

    else:
        # Service mode
        if st.button("Sync from OneDrive", width="stretch"):
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

        if st.button("Ingest experiments", disabled=not selected_experiments, width="stretch"):
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
                    client.query_dataset.clear()
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
    if st.button("Refresh", width="stretch"):
        client.list_datasets.clear()
        client.query_dataset.clear()
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
        st.dataframe(df_reg[display_cols], width="stretch", hide_index=True)

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
    load_all_rows = st.toggle(
        "Load all rows",
        value=True,
        help="Plots and SVG exports use every data point. Turn off to load fewer rows "
        "per experiment when browsing very large datasets.",
    )
    row_limit = None
    if not load_all_rows:
        row_limit = int(st.number_input("Rows per experiment", min_value=10, value=5000, step=500))

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
        # time_s for timestamped data stored before it was derived at ingest.
        df = add_elapsed_time(client.query_dataset(name, limit=row_limit))
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
    # The table is sent to the browser on every rerun, so whole datasets would slow the app.
    st.dataframe(
        data.drop(columns=["_experiment"], errors="ignore").head(_PREVIEW_ROWS),
        width="stretch",
    )
    if len(data) > _PREVIEW_ROWS:
        st.caption(f"Showing the first {_PREVIEW_ROWS:,} of {len(data):,} rows. Plots use all rows.")

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

    use_builtin = st.toggle(
        "Built-in instrument plot",
        value=False,
        help="Use the mfethuls plot for each instrument, e.g. heat flow vs temperature for DSC.",
    )

    if use_builtin:
        comparison_mode = st.selectbox("Comparison mode", ["auto", "overlay", "facet"], index=0)
        datasets_meta = {(d.get("experiment_name") or d["name"]): d for d in datasets}
        try:
            spec = build_experiments_spec(_builtin_datasets(data, datasets_meta), mode=comparison_mode)
        except PlotError as exc:
            st.warning(f"No built-in plot for this selection: {exc}")
        else:
            title = spec.title or spec.panel.title or "mfethuls"
            limits_col, svg_col, html_col = _plot_toolbar()
            if spec.layout == "single":
                key = "|".join(["limits", "builtin", comparison_mode, *selected_names])
                _axis_limits_popover(limits_col, spec.panel, key)
            else:
                _limits_unavailable(limits_col, "Not available for figures with one panel per experiment.")
            fig = render(spec, backend="plotly")
            _download_buttons(svg_col, html_col, title, spec=spec, fig=fig)
            st.plotly_chart(
                fig,
                width="stretch",
                config=plotly_config(_figure_download_name(title, "svg")),
            )

    elif len(numeric_cols) < 1:
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

        # A numeric colour column with many values (e.g. time_s) is drawn on a colour scale.
        continuous = (
            plot_type in {"line", "scatter"}
            and color_col != "_experiment"
            and _uses_colorbar(data, color_col)
            and data[color_col].nunique() <= _MAX_COLORBAR_GROUPS
        )
        discrete_seq = _DISCRETE_PALETTES["Plotly"]
        cmap = "viridis"
        if continuous:
            scale_col, reverse_col = st.columns([3, 1], vertical_alignment="bottom")
            cmap = scale_col.selectbox("Colour scale", _CONTINUOUS_PALETTES, index=0)
            if reverse_col.toggle("Reverse", help="Flip the colour scale, e.g. dark for late times."):
                cmap = f"{cmap}_r"
        else:
            palette_name = st.selectbox("Colour palette", list(_DISCRETE_PALETTES), index=0)
            discrete_seq = _DISCRETE_PALETTES[palette_name]

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

            limits_col, svg_col, html_col = _plot_toolbar()
            if plot_type in {"line", "scatter"}:
                # WebGL (Plotly) on screen and Matplotlib for the vector SVG: no downsampling.
                max_groups = _MAX_COLORBAR_GROUPS if _uses_colorbar(long_df, color) else _MAX_COLOUR_GROUPS
                if long_df[color].nunique(dropna=False) > max_groups:
                    st.caption(f"'{color}' has more than {max_groups} values; drawing without colour groups.")
                    color = None
                palette, _ = convert_colors_to_same_type(list(discrete_seq), colortype="tuple")
                spec = _xy_spec(
                    long_df,
                    x=x_col,
                    y=y_series,
                    color=color,
                    mode="lines" if plot_type == "line" else "markers",
                    palette=palette,
                    cmap=cmap,
                    title=title,
                    ylabel=shared_axis_label(y_cols),
                    log_x=use_log_x,
                    log_y=use_log_y,
                    invert_x=invert_x,
                )
                _axis_limits_popover(limits_col, spec.panel, "|".join(["limits", x_col, *y_cols]))
                fig = render(spec, backend="plotly")
            else:
                _limits_unavailable(limits_col, "Available for line and scatter plots.")
                if plot_type == "histogram":
                    fig = px.histogram(data, x=x_col, color=color_col,
                                       title=f"Histogram: {x_col}", color_discrete_sequence=discrete_seq)
                else:
                    fig = px.box(long_df,
                                 x="_y_metric" if "_y_metric" in long_df.columns else x_col,
                                 y=y_series, color=color,
                                 title=title, color_discrete_sequence=discrete_seq)
                fig.update_xaxes(type="log" if use_log_x else "linear",
                                 autorange="reversed" if invert_x else True)
                fig.update_yaxes(type="log" if use_log_y else "linear")
                spec = None

            _download_buttons(svg_col, html_col, title, spec=spec, fig=fig)
            st.plotly_chart(
                fig,
                width="stretch",
                config=plotly_config(_figure_download_name(title, "svg")),
            )
