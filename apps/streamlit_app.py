import json
import os
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

from mfethuls.storage import DuckDBQueryBackend, _get_duckdb_path, get_postgres_db_url

try:
    from sqlalchemy import create_engine, text
except Exception:  # pragma: no cover - optional dependency
    create_engine = None  # type: ignore
    text = None  # type: ignore


st.set_page_config(page_title="mfethuls Explorer", layout="wide")

st.title("mfethuls Explorer")
st.caption("Explore registered datasets.")


def _get_backend() -> DuckDBQueryBackend:
    db_path = _get_duckdb_path()
    return DuckDBQueryBackend(db_path=db_path)


@st.cache_data(show_spinner=False)
def _load_registry_cached(db_path: str) -> pd.DataFrame:
    backend = DuckDBQueryBackend(db_path=db_path)
    try:
        rows = backend.list_registered()
        return pd.DataFrame(rows)
    finally:
        backend.close()


@st.cache_data(show_spinner=False)
def _query_table_cached(db_path: str, table_name: str, limit: int) -> pd.DataFrame:
    backend = DuckDBQueryBackend(db_path=db_path)
    try:
        safe_table = table_name.replace('"', '""')
        query = f"SELECT * FROM \"{safe_table}\" LIMIT {int(limit)}"
        return backend.query(query)
    finally:
        backend.close()


_POSTGRES_ENGINE = None


def _get_postgres_engine():
    global _POSTGRES_ENGINE
    if _POSTGRES_ENGINE is not None:
        return _POSTGRES_ENGINE
    if create_engine is None or text is None:
        return None
    db_url = get_postgres_db_url()
    if not db_url:
        return None
    _POSTGRES_ENGINE = create_engine(db_url)
    return _POSTGRES_ENGINE


def _get_instrument_from_postgres(storage_path: str) -> Optional[str]:
    engine = _get_postgres_engine()
    if engine is None:
        return None
    query = text(
        "SELECT instrument_name FROM datasets WHERE storage_path = :path ORDER BY created_at DESC LIMIT 1"
    )
    try:
        with engine.connect() as conn:
            res = conn.execute(query, {"path": storage_path})
            row = res.fetchone()
            if row and row[0] is not None and str(row[0]).strip():
                return str(row[0])
    except Exception:
        return None
    return None


def _get_instrument_label(storage_path: str) -> str:
    postgres_value = _get_instrument_from_postgres(storage_path)
    if postgres_value:
        return postgres_value
    meta_path = os.path.splitext(storage_path)[0] + ".metadata.json"
    if not os.path.exists(meta_path):
        return "(unknown)"
    try:
        with open(meta_path, encoding="utf8") as handle:
            metadata = json.load(handle)
    except Exception:
        return "(unknown)"
    value = metadata.get("instrument_name")
    if value is not None and str(value).strip():
        return str(value)
    return "(unknown)"


backend = _get_backend()
registry = _load_registry_cached(backend.db_path)

with st.sidebar.expander("Datasets", expanded=True):
    if registry.empty:
        st.warning("No datasets registered yet.")
        selected_tables: list[str] = []
    else:
        instrument_rows = []
        for _, row in registry.iterrows():
            instrument_rows.append(
                {
                    "table_name": row.get("table_name"),
                    "instrument": _get_instrument_label(str(row.get("storage_path", ""))),
                }
            )
        st.caption("Registered views and instruments")
        st.dataframe(pd.DataFrame(instrument_rows), use_container_width=True)

        selected_tables = st.multiselect(
            "Select registered views",
            options=registry["table_name"].tolist(),
        )

with st.sidebar.expander("Query", expanded=False):
    limit = st.number_input("Row limit", min_value=10, max_value=1000000, value=5000, step=10)

if selected_tables:
    combined_frames: list[pd.DataFrame] = []
    for table_name in selected_tables:
        try:
            frame = _query_table_cached(backend.db_path, table_name, int(limit))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to query {table_name}: {exc}")
            continue
        frame["_dataset_view"] = table_name
        combined_frames.append(frame)

    if not combined_frames:
        st.stop()

    data = pd.concat(combined_frames, ignore_index=True)

    st.subheader("Dataset info")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Rows", len(data))
    with col_b:
        st.metric("Columns", len(data.columns))
    with col_c:
        st.metric("Views", len(selected_tables))

    with st.expander("Preview", expanded=True):
        preview = data.drop(columns=["_dataset_view"], errors="ignore")
        st.dataframe(preview, use_container_width=True)

    with st.expander("Filters", expanded=False):
        filter_cols = ["(none)"] + data.columns.tolist()
        filter_col = st.selectbox("Filter column", options=filter_cols, index=0)
        if filter_col != "(none)":
            values = data[filter_col].dropna().astype(str).unique().tolist()
            values = sorted(values)
            selected_values = st.multiselect("Filter values", options=values)
            if selected_values:
                data = data[data[filter_col].astype(str).isin(selected_values)]

    with st.expander("Plot", expanded=True):
        if data.empty:
            st.info("No rows available for plotting.")
        else:
            numeric_cols = data.select_dtypes(include="number").columns.tolist()
        if len(numeric_cols) < 2:
            st.info("Need at least two numeric columns for a quick plot.")
        else:
            plot_type = st.selectbox("Plot type", options=["scatter", "line", "histogram", "box"], index=0)
            x_col = st.selectbox("X axis", options=numeric_cols, index=0)
            y_cols = st.multiselect("Y axis (one or more)", options=numeric_cols, default=[numeric_cols[1]])
            hue_options = ["(none)"] + data.columns.tolist()
            hue_choice = st.selectbox("Hue", options=hue_options, index=0)
            color_col = None if hue_choice == "(none)" else hue_choice
            use_log_x = st.checkbox("Log X", value=False)
            use_log_y = st.checkbox("Log Y", value=False)
            discrete_palettes = {
                "Plotly": px.colors.qualitative.Plotly,
                "D3": px.colors.qualitative.D3,
                "G10": px.colors.qualitative.G10,
                "T10": px.colors.qualitative.T10,
                "Bold": px.colors.qualitative.Bold,
                "Safe": px.colors.qualitative.Safe,
                "Dark2": px.colors.qualitative.Dark2,
                "Set2": px.colors.qualitative.Set2,
                "Pastel": px.colors.qualitative.Pastel,
            }
            continuous_palettes = {
                "Viridis": px.colors.sequential.Viridis,
                "Cividis": px.colors.sequential.Cividis,
                "Plasma": px.colors.sequential.Plasma,
                "Inferno": px.colors.sequential.Inferno,
                "Magma": px.colors.sequential.Magma,
                "Turbo": px.colors.sequential.Turbo,
                "Blues": px.colors.sequential.Blues,
                "Greens": px.colors.sequential.Greens,
                "Reds": px.colors.sequential.Reds,
            }
            palette_kind = st.selectbox("Palette type", options=["discrete", "continuous"], index=0)
            if palette_kind == "continuous":
                palette_name = st.selectbox("Color palette", options=list(continuous_palettes.keys()), index=0)
            else:
                palette_name = st.selectbox("Color palette", options=list(discrete_palettes.keys()), index=0)
            custom_color = None
            if color_col is None and len(y_cols) <= 1 and plot_type in {"scatter", "line"}:
                custom_color = st.color_picker("Single-series color", value="#1f77b4")

            if not y_cols and plot_type != "histogram":
                st.info("Select at least one Y axis column.")
            else:
                wide = data[[x_col, *y_cols]].copy() if y_cols else data[[x_col]].copy()
                long_df = wide.melt(id_vars=[x_col], value_vars=y_cols, var_name="_y_metric", value_name="_y_value")
                if color_col and not long_df.empty:
                    long_df[color_col] = data[color_col].values.repeat(len(y_cols))
                    color = color_col
                else:
                    color = "_y_metric"

                title = f"{x_col}"
                if y_cols:
                    title = f"{x_col} vs {', '.join(y_cols)}"

                discrete_sequence = None
                continuous_scale = None
                if palette_kind == "continuous" and color_col is not None:
                    continuous_scale = continuous_palettes[palette_name]
                else:
                    discrete_sequence = discrete_palettes[palette_name]

                if plot_type == "line":
                    fig = px.line(
                        long_df,
                        x=x_col,
                        y="_y_value",
                        color=color,
                        title=title,
                        color_discrete_sequence=discrete_sequence,
                    )
                elif plot_type == "histogram":
                    fig = px.histogram(
                        data,
                        x=x_col,
                        color=color_col,
                        title=f"Histogram: {x_col}",
                        color_discrete_sequence=discrete_sequence,
                    )
                elif plot_type == "box":
                    fig = px.box(
                        long_df,
                        x="_y_metric",
                        y="_y_value",
                        color=color,
                        title=title,
                        color_discrete_sequence=discrete_sequence,
                    )
                else:
                    fig = px.scatter(
                        long_df,
                        x=x_col,
                        y="_y_value",
                        color=color,
                        title=title,
                        color_discrete_sequence=discrete_sequence,
                    )

                if continuous_scale is not None:
                    fig.update_traces(marker={"colorscale": continuous_scale})
                    fig.update_coloraxes(colorscale=continuous_scale)

                if custom_color:
                    fig.update_traces(marker={"color": custom_color}, line={"color": custom_color})

                fig.update_yaxes(type="log" if use_log_y else "linear")
                fig.update_xaxes(type="log" if use_log_x else "linear")
                st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Register a dataset first, then refresh this page.")
