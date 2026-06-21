import json
import os

import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st

from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.config.mode import is_service_mode
from mfethuls.experiments import load_experiment_registry
from mfethuls.storage import DuckDBQueryBackend, _get_duckdb_path, duckdb_session

# Streamlit is a local-only tool (notebooks/interactive exploration).
if is_service_mode():
    st.warning("Streamlit is designed for local mode only. Use the API for service data.")


st.set_page_config(page_title="mfethuls Explorer", layout="wide")

st.title("mfethuls Explorer")
st.caption("Explore registered datasets.")

@st.cache_data(show_spinner=False)
def _load_registry_cached(db_path: str) -> pd.DataFrame:
    with duckdb_session(db_path=db_path, read_only=True) as backend:
        rows = backend.list_registered()
        return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _query_table_cached(db_path: str, table_name: str, limit: int) -> pd.DataFrame:
    with duckdb_session(db_path=db_path, read_only=True) as backend:
        safe_table = table_name.replace('"', '""')
        paginated_sql = f'SELECT * FROM "{safe_table}" LIMIT ?'
        return backend.query(paginated_sql, [int(limit)])


def _figure_bytes(fig, fmt: str) -> bytes:
    if fmt == "html":
        return fig.to_html(include_plotlyjs="cdn", full_html=True).encode("utf8")
    return pio.to_image(fig, format=fmt)


def _figure_download_name(title: str, fmt: str) -> str:
    safe_title = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in title).strip("_")
    if not safe_title:
        safe_title = "figure"
    return f"{safe_title}.{fmt}"


def _finite_bounds(values: pd.Series) -> tuple[float, float] | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    lower = float(numeric.min())
    upper = float(numeric.max())
    if lower == upper:
        pad = abs(lower) * 0.05 or 1.0
        return lower - pad, upper + pad
    return lower, upper


@st.cache_data(show_spinner=False)
def _load_experiment_registry_cached(path: str) -> pd.DataFrame:
    return load_experiment_registry(path)


def _read_metadata(storage_path: str) -> dict:
    meta_path = os.path.splitext(storage_path)[0] + ".metadata.json"
    if not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path, encoding="utf8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _storage_label(storage_path: str) -> str:
    if storage_path.startswith(("s3://", "az://", "https://")):
        return "☁️ cloud"
    return "📁 local"


db_path = _get_duckdb_path()
registry = _load_registry_cached(db_path)

with st.sidebar.expander("Ingest", expanded=False):
    st.caption("Local ingestion: parses raw files and writes to local storage only.")
    registry_path = os.environ.get("PATH_TO_REGISTRY", "")
    registry_path = st.text_input("Experiment registry path", value=registry_path)
    refresh_ingest = st.checkbox("Re-parse even if cached", value=False)

    experiment_names: list[str] = []
    if registry_path:
        try:
            exp_registry = _load_experiment_registry_cached(registry_path)
            experiment_names = (
                exp_registry.get("name", pd.Series(dtype=str))
                .dropna()
                .astype(str)
                .tolist()
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to load experiment registry: {exc}")

    selected_experiments: list[str] = []
    if experiment_names:
        select_all = st.checkbox("Select all experiments", value=False)
        if select_all:
            selected_experiments = experiment_names
            st.caption(f"Selected {len(selected_experiments)} experiments.")
        else:
            selected_experiments = st.multiselect("Experiments", options=experiment_names)
    else:
        st.info("Provide a valid registry path to list experiments.")

    if st.button("Ingest experiments", disabled=not selected_experiments):
        total = len(selected_experiments)
        progress = st.progress(0) if total > 1 else None
        results: list[tuple[str, dict]] = []
        failures: list[str] = []
        with st.spinner("Ingesting experiments..."):
            with DuckDBQueryBackend(db_path=db_path, read_only=False) as ingest_backend:
                for idx, experiment_name in enumerate(selected_experiments, start=1):
                    try:
                        result = ingest_experiment_dataset(
                            experiment_name,
                            refresh=refresh_ingest,
                            storage_mode="local",
                            cloud_provider=None,
                            db_url=None,
                            query_backend=ingest_backend,
                        )
                        results.append((experiment_name, result or {}))
                    except Exception as exc:  # noqa: BLE001
                        failures.append(experiment_name)
                        st.error(f"{experiment_name}: {exc}")
                    if progress is not None:
                        progress.progress(idx / total)

        status_counts: dict[str, int] = {}
        for _, result in results:
            status = str(result.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        if failures:
            st.warning(f"{len(failures)} experiments failed.")
        st.success("Ingestion complete.")
        if status_counts:
            summary = ", ".join(f"{k}: {v}" for k, v in status_counts.items())
            st.caption(f"Status summary: {summary}")
        st.cache_data.clear()
        st.rerun()

with st.sidebar.expander("Datasets", expanded=True):
    if registry.empty:
        st.warning("No datasets registered yet.")
        selected_tables: list[str] = []
        # keep mapping of table -> storage path for display; queries use DuckDB
        table_to_storage_path: dict[str, str] = {}
    else:
        instrument_rows = []
        table_to_storage_path = {}
        for _, row in registry.iterrows():
            storage_path = str(row.get("storage_path", ""))
            table_name = str(row.get("table_name") or "")
            if table_name:
                table_to_storage_path[table_name] = storage_path
            meta = _read_metadata(storage_path)
            instrument_rows.append(
                {
                    "id": table_name,
                    "name": meta.get("name") or meta.get("experiment_name") or "",
                    "instrument": meta.get("instrument_name") or "",
                    "storage": _storage_label(storage_path),
                    "storage_path": storage_path,
                }
            )
        st.caption("Registered views and instruments")
        df_rows = pd.DataFrame(instrument_rows)
        try:
            df_rows = df_rows.iloc[::-1].reset_index(drop=True)
        except Exception:
            pass
        show_paths = st.toggle("Show full paths", value=False)
        display_cols = ["id", "name", "instrument", "storage_path" if show_paths else "storage"]
        st.dataframe(df_rows[display_cols], use_container_width=True)

        selected_tables = st.multiselect(
            "Select registered views",
            options=df_rows["id"].tolist(),
        )

with st.sidebar.expander("Query", expanded=False):
    limit = st.number_input("Row limit", min_value=10, max_value=1000000, value=5000, step=10)

if selected_tables:
    combined_frames: list[pd.DataFrame] = []
    for table_name in selected_tables:
        try:
            frame = _query_table_cached(db_path, table_name, int(limit))
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
        numeric_cols = data.select_dtypes(include="number").columns.tolist() if not data.empty else []
        if data.empty:
            st.info("No rows available for plotting.")
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
            selected_instruments = {
                (_read_metadata(table_to_storage_path.get(t, "")).get("instrument_name") or "").lower()
                for t in selected_tables
            }
            invert_x = any(i in {"nmr", "ftir"} for i in selected_instruments)
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

                x_bounds = _finite_bounds(data[x_col])
                y_bounds = _finite_bounds(long_df["_y_value"]) if not long_df.empty else None

                save_plot_export_slot = None
                with st.expander("Export plot", expanded=False):
                    st.caption(
                        "Use these controls to define the saved zoomed view. The browser's mouse zoom state is not available to Streamlit."
                    )
                    range_cols = st.columns(2)
                    x_min_default = x_bounds[0] if x_bounds else None
                    x_max_default = x_bounds[1] if x_bounds else None
                    y_min_default = y_bounds[0] if y_bounds else None
                    y_max_default = y_bounds[1] if y_bounds else None

                    use_custom_x_range = range_cols[0].checkbox("Limit X range", value=False)
                    use_custom_y_range = range_cols[1].checkbox("Limit Y range", value=False)

                    x_min = x_max = None
                    y_min = y_max = None
                    if use_custom_x_range and x_bounds:
                        x_range_cols = st.columns(2)
                        x_min = x_range_cols[0].number_input("X min", value=float(x_min_default), format="%.6f")
                        x_max = x_range_cols[1].number_input("X max", value=float(x_max_default), format="%.6f")
                    elif use_custom_x_range:
                        st.info("X range controls are unavailable because the selected X axis has no numeric bounds.")

                    if use_custom_y_range and y_bounds:
                        y_range_cols = st.columns(2)
                        y_min = y_range_cols[0].number_input("Y min", value=float(y_min_default), format="%.6f")
                        y_max = y_range_cols[1].number_input("Y max", value=float(y_max_default), format="%.6f")
                    elif use_custom_y_range:
                        st.info("Y range controls are unavailable because the selected Y axis has no numeric bounds.")

                    st.divider()
                    st.caption("Save the adjusted figure from the current panel state.")
                    save_plot_export_slot = st.container()

                fig.update_yaxes(type="log" if use_log_y else "linear")
                fig.update_xaxes(type="log" if use_log_x else "linear", autorange="reversed" if invert_x else True)
                if use_custom_x_range and x_bounds and x_min is not None and x_max is not None:
                    fig.update_xaxes(range=[x_min, x_max])
                if use_custom_y_range and y_bounds and y_min is not None and y_max is not None:
                    fig.update_yaxes(range=[y_min, y_max])

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    config={
                        "displaylogo": False,
                        "toImageButtonOptions": {"format": "svg", "filename": "mfethuls_figure"},
                    },
                )

                if save_plot_export_slot is not None:
                    with save_plot_export_slot:
                        export_cols = st.columns(2)
                        for col, fmt in zip(export_cols, ["svg", "png"]):
                            label = fmt.upper()
                            try:
                                export_bytes = _figure_bytes(fig, fmt)
                                col.download_button(
                                    f"Download {label}",
                                    data=export_bytes,
                                    file_name=_figure_download_name(title, fmt),
                                    mime={
                                        "svg": "image/svg+xml",
                                        "png": "image/png",
                                    }[fmt],
                                    use_container_width=True,
                                )
                            except Exception as exc:  # noqa: BLE001
                                col.download_button(
                                    f"Download {label}",
                                    data=f"Export to {label} is unavailable: {exc}".encode("utf8"),
                                    file_name=_figure_download_name(title, "txt"),
                                    mime="text/plain",
                                    use_container_width=True,
                                )
else:
    st.info("Register a dataset first, then refresh this page.")
