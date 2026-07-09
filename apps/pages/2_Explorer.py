import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st

import _client as client

st.set_page_config(page_title="Explorer — mfethuls", layout="wide", page_icon="🔬")
st.title("Explorer")
st.caption("Select experiments, configure axes, and overlay curves.")

if client.mode() == "service":
    with st.sidebar:
        st.header("API connection")
        default_url = os.environ.get("MFETHULS_API_URL", "http://localhost:8000")
        default_key = os.environ.get("MFETHULS_API_KEY", "")
        st.session_state["api_url"] = st.text_input("API URL", value=st.session_state.get("api_url", default_url))
        st.session_state["api_key"] = st.text_input("API key", type="password", value=st.session_state.get("api_key", default_key))

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


def _finite_bounds(values: pd.Series) -> tuple[float, float] | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    lo, hi = float(numeric.min()), float(numeric.max())
    if lo == hi:
        pad = abs(lo) * 0.05 or 1.0
        return lo - pad, hi + pad
    return lo, hi

# ---------------------------------------------------------------------------
# Dataset selection
# ---------------------------------------------------------------------------
with st.spinner("Loading dataset list…"):
    try:
        datasets = client.list_datasets()
    except Exception as exc:
        st.error(f"Could not load datasets: {exc}")
        st.stop()

if not datasets:
    st.info("No datasets registered yet. Go to the Registry page to ingest experiments.")
    st.stop()

# Map human-readable label → internal DuckDB table_name.
label_to_name = {
    (d.get("experiment_name") or d["name"]): d["name"]
    for d in datasets
}

with st.sidebar:
    st.subheader("Datasets")
    selected_labels = st.multiselect("Select experiments to overlay", options=list(label_to_name.keys()))
    selected_names = [label_to_name[l] for l in selected_labels]
    limit = st.number_input("Row limit per dataset", min_value=100, max_value=1_000_000, value=5000, step=500)
    if st.button("Refresh dataset list"):
        client.list_datasets.clear()
        st.rerun()

if not selected_names:
    st.info("Select one or more experiments from the sidebar to begin.")
    st.stop()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
frames: list[pd.DataFrame] = []
for label, name in zip(selected_labels, selected_names):
    try:
        df = client.query_dataset(name, limit=int(limit))
        df["_experiment"] = label  # human-readable label for plot legend
        frames.append(df)
    except Exception as exc:
        st.error(f"Failed to load {name}: {exc}")

if not frames:
    st.stop()

data = pd.concat(frames, ignore_index=True)

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
col_a, col_b, col_c = st.columns(3)
col_a.metric("Rows", f"{len(data):,}")
col_b.metric("Columns", len(data.columns) - 1)  # exclude _experiment
col_c.metric("Experiments", len(selected_names))

# ---------------------------------------------------------------------------
# Plot controls
# ---------------------------------------------------------------------------
numeric_cols = data.select_dtypes(include="number").columns.tolist()
all_cols = [c for c in data.columns if c != "_experiment"]

if len(numeric_cols) < 1:
    st.warning("No numeric columns found in the selected datasets.")
    st.stop()

with st.expander("Plot settings", expanded=True):
    ctrl1, ctrl2, ctrl3 = st.columns(3)
    with ctrl1:
        plot_type = st.selectbox("Plot type", ["line", "scatter", "histogram", "box"])
        x_col = st.selectbox("X axis", numeric_cols, index=0)
    with ctrl2:
        y_options = [c for c in numeric_cols if c != x_col]
        y_cols = st.multiselect("Y axis (one or more)", y_options, default=y_options[:1] if y_options else [])
        hue_opts = ["_experiment"] + all_cols
        hue_choice = st.selectbox("Colour by", hue_opts, index=0)
        color_col = hue_choice
    with ctrl3:
        use_log_x = st.checkbox("Log X")
        use_log_y = st.checkbox("Log Y")
        # auto-invert for NMR/FTIR
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
    palette_name = st.selectbox("Colour palette", list(_DISCRETE.keys()), index=0)
    discrete_seq = _DISCRETE[palette_name]

if not y_cols and plot_type != "histogram":
    st.info("Select at least one Y axis column.")
    st.stop()

# ---------------------------------------------------------------------------
# Build figure
# ---------------------------------------------------------------------------
title = f"{x_col} vs {', '.join(y_cols)}" if y_cols else x_col

if len(y_cols) > 1 or color_col == "_experiment":
    # Melt so each Y series becomes a row; colour by metric or experiment
    id_vars = [x_col, "_experiment"] + ([color_col] if color_col not in {x_col, "_experiment"} else [])
    id_vars = list(dict.fromkeys(id_vars))  # dedup while preserving order
    long_df = data[id_vars + y_cols].melt(
        id_vars=id_vars, value_vars=y_cols, var_name="_y_metric", value_name="_y_value"
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
    fig = px.box(long_df, x="_y_metric" if "_y_metric" in long_df.columns else x_col,
                 y=y_series, color=color,
                 title=title, color_discrete_sequence=discrete_seq)
else:
    fig = px.scatter(long_df, x=x_col, y=y_series, color=color,
                     title=title, color_discrete_sequence=discrete_seq)

fig.update_xaxes(type="log" if use_log_x else "linear",
                 autorange="reversed" if invert_x else True)
fig.update_yaxes(type="log" if use_log_y else "linear")

# ---------------------------------------------------------------------------
# Export controls
# ---------------------------------------------------------------------------
with st.expander("Export", expanded=False):
    x_bounds = _finite_bounds(data[x_col])
    y_bounds = _finite_bounds(long_df[y_series]) if y_series in long_df.columns else None

    range_cols = st.columns(2)
    use_x_range = range_cols[0].checkbox("Limit X range")
    use_y_range = range_cols[1].checkbox("Limit Y range")

    if use_x_range and x_bounds:
        xr = st.columns(2)
        x_min = xr[0].number_input("X min", value=float(x_bounds[0]), format="%.6f")
        x_max = xr[1].number_input("X max", value=float(x_bounds[1]), format="%.6f")
        fig.update_xaxes(range=[x_min, x_max])

    if use_y_range and y_bounds:
        yr = st.columns(2)
        y_min = yr[0].number_input("Y min", value=float(y_bounds[0]), format="%.6f")
        y_max = yr[1].number_input("Y max", value=float(y_bounds[1]), format="%.6f")
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

# ---------------------------------------------------------------------------
# Render chart
# ---------------------------------------------------------------------------
st.plotly_chart(
    fig,
    use_container_width=True,
    config={
        "displaylogo": False,
        "toImageButtonOptions": {"format": "svg", "filename": "mfethuls_figure"},
    },
)

# ---------------------------------------------------------------------------
# Raw data preview
# ---------------------------------------------------------------------------
with st.expander("Raw data preview", expanded=False):
    preview = data.drop(columns=["_experiment"], errors="ignore")
    st.dataframe(preview, use_container_width=True)
