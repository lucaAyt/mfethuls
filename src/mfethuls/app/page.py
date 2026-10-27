"""The mfethuls Streamlit page: sidebar (ingest, clean up, datasets, query) and the data view.

:func:`run` draws the page for an app backend, which says where data comes from:
:class:`mfethuls.app.backend.LocalBackend` for this computer. Start the app with
``mfethuls-app`` (see :mod:`mfethuls.app.launch`).
"""
from __future__ import annotations

import io
from dataclasses import replace
import os
import threading

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st
from plotly.colors import convert_colors_to_same_type

from mfethuls.app.appearance import ACCENTS, apply_appearance, apply_style, save_accent, saved_accent
from mfethuls.app.instruments import open_requested_dialog, render_instruments_section
from mfethuls.app.register import clear_scan_caches
from mfethuls.app.welcome import (
    ensure_registry,
    example_folder,
    is_set_up,
    landing_requested,
    mark_done,
    show_landing,
    render_example_settings,
    render_folder_layout,
    render_landing,
    render_loading_settings,
    render_guide_tracker,
    render_progress,
    render_setup,
    render_setup_form,
    row_limit as loading_row_limit,
    setup_requested,
)
from mfethuls.dataset import Dataset
from mfethuls.plotting import PlotError, PlotSpec, build_experiments_spec, plotly_config
from mfethuls.plotting.comparison import shares_x_axis, stack_step
from mfethuls.plotting.backend import render
from mfethuls.plotting.labels import axis_label, legend_name, shared_axis_label
from mfethuls.plotting.normalise import (
    LOG_MINMAX_NOTE,
    NORMALISE_METHODS,
    normalisation,
    normalised_label,
    window_text,
)
from mfethuls.plotting.spec import LINESTYLES, MARKERS, Colorbar, Legend, LegendEntry, Panel, Trace
from mfethuls.plotting.thin import (
    MAX_POINTS,
    MAX_SERIES_LINES,
    SVG_MAX_POINTS,
    spread_values,
    thin_spec,
    thinned_note,
)
from mfethuls.reconcile import LABELS as _RECONCILE_LABELS
from mfethuls.schema_normalization import add_elapsed_time

# The backend the page is drawn for; set by run().
backend = None

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
# A numeric colour column with more values than _MAX_LEGEND_ENTRIES gets a colour bar instead of
# a legend; with more than MAX_SERIES_LINES (e.g. one spectrum per time_s), that many lines spread
# over its values are drawn (plotting.thin).
_MAX_LEGEND_ENTRIES = 10
# Style legend entries are drawn in a neutral grey, so they don't read as colour groups.
_STYLE_LEGEND_COLOUR = "0.35"
_NO_STYLE = "(none)"
# Session key of the experiments chosen in the sidebar.
_PICKED = "picked_experiments"


def _column_title(column: str) -> str:
    return _LEGEND_TITLES.get(column, column)


def _uses_colorbar(df: pd.DataFrame, color: str | None) -> bool:
    return (
        color is not None
        and pd.api.types.is_numeric_dtype(df[color])
        and df[color].nunique() > _MAX_LEGEND_ENTRIES
    )


def _numeric_colour(df: pd.DataFrame, color: str | None) -> bool:
    """Whether lines coloured by ``color`` have numbers to order them by (a waterfall): e.g. time_s."""
    return (color is not None and color != "_experiment" and pd.api.types.is_numeric_dtype(df[color])
            and df[color].nunique() > 1)


def _xy_spec(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    color: str | None,
    mode: str,
    palette: list,
    style: str | None = None,
    cmap: str = "viridis",
    title: str,
    ylabel: str,
    log_x: bool,
    log_y: bool,
    invert_x: bool,
    layout: str = "overlay",
    spacing: float = 1.0,
) -> PlotSpec:
    """Line/scatter spec: one colour per value of ``color``, one line style (lines) or
    marker shape (scatter) per value of ``style``, and one line per experiment.

    ``layout`` "stacked" shifts each experiment up (see :func:`_laid_out`), "facet" gives
    each its own panel; "overlay" draws them together.
    """
    by_experiment = mode == "lines" or layout != "overlay"
    split = ["_experiment"] if by_experiment and "_experiment" in df.columns else []
    keys = list(dict.fromkeys(([color] if color else []) + ([style] if style else []) + split))
    colorbar = None
    if _uses_colorbar(df, color):
        colorbar = Colorbar(
            title=axis_label(color), vmin=float(df[color].min()), vmax=float(df[color].max()), cmap=cmap
        )
    appearances = LINESTYLES if mode == "lines" else MARKERS
    # Along a time axis the rows' order is the measurement's, whatever order the files were read in.
    by_time = mode == "lines" and (x == "time_s" or pd.api.types.is_datetime64_any_dtype(df[x]))

    traces: list[Trace] = []
    owners: list = []  # each trace's experiment
    levels: list = []  # each trace's numeric colour value (a waterfall's shift), or None
    numeric_colour = color is not None and pd.api.types.is_numeric_dtype(df[color])
    colour_index: dict[str, int] = {}
    style_index: dict[str, int] = {}
    groups = df.groupby(keys, dropna=False, sort=False, observed=True) if keys else [((), df)]
    for key, subset in groups:
        values = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
        colour_value = str(values[color]) if color else ""
        first = colour_value not in colour_index
        idx = colour_index.setdefault(colour_value, len(colour_index))
        appearance = appearances[style_index.setdefault(str(values[style]), len(style_index)) % len(appearances)] if style else None
        if by_time:
            subset = subset.sort_values(x, kind="stable")
        # A line through one point draws nothing: show it as a point.
        trace_mode = "markers" if mode == "lines" and len(subset) < 2 else mode
        traces.append(
            Trace(
                subset[x].to_numpy(),
                subset[y].to_numpy(),
                # Lines split per experiment share a colour; only the first gets a legend entry.
                # With a style column the legends are built below instead.
                label=_legend_entry(color, colour_value) if color and first and not style else None,
                color=palette[idx % len(palette)],
                color_value=float(values[color]) if colorbar is not None and pd.notna(values[color]) else None,
                mode=trace_mode,
                linestyle=appearance if appearance and trace_mode == "lines" else "-",
                marker=appearance if appearance and trace_mode == "markers" else "o",
                # A curve has one legend group: its colour's, or its style's when only styles are listed.
                legend_group=f"style:{values[style]}" if style and (not color or colorbar is not None)
                else colour_value,
            )
        )
        owners.append(values.get("_experiment"))
        levels.append(float(values[color]) if numeric_colour and pd.notna(values[color]) else None)

    legends: list[Legend] = []
    if style:
        marker = mode == "markers"
        if color and colorbar is None:
            legends.append(Legend(
                title=_LEGEND_TITLES.get(color) or legend_name(color),
                entries=[
                    LegendEntry(_legend_entry(color, value), color=palette[i % len(palette)], group=value,
                                marker="o" if marker else None)
                    for value, i in colour_index.items()
                ],
            ))
        legends.append(Legend(
            title=_LEGEND_TITLES.get(style) or legend_name(style),
            entries=[
                LegendEntry(
                    _legend_entry(style, value),
                    color=_STYLE_LEGEND_COLOUR,
                    linestyle="-" if marker else appearances[i % len(appearances)],
                    marker=appearances[i % len(appearances)] if marker else None,
                    group=f"style:{value}",
                )
                for value, i in style_index.items()
            ],
        ))

    panel = Panel(
        traces=traces,
        title=title,
        xlabel=axis_label(x),
        ylabel=ylabel,
        xscale="log" if log_x else "linear",
        yscale="log" if log_y else "linear",
        x_reversed=invert_x,
        legend=color is not None and colorbar is None and not style,
        legend_title=_LEGEND_TITLES.get(color) or legend_name(color),
        colorbar=colorbar,
        legends=legends,
    )
    if layout == "waterfall":
        return PlotSpec([_waterfall(panel, levels, spacing)])
    return _laid_out(panel, owners, layout, spacing)


def _points_own_lines(df: pd.DataFrame, color: str, style: str | None) -> bool:
    """True when colouring lines by ``color`` leaves most of them with one point: a line per
    ``time_s`` value on a time axis (one wavelength of a spectra series), which draws no line."""
    keys = [c for c in dict.fromkeys([color, style, "_experiment"]) if c and c in df.columns]
    sizes = df.groupby(keys, dropna=False, sort=False, observed=True).size()
    return len(sizes) > 1 and bool((sizes < 2).mean() > 0.5)


def _laid_out(panel: Panel, owners: list, layout: str, spacing: float) -> PlotSpec:
    """``panel`` with its experiments (``owners``, one per trace) together, offset or in panels.

    Offset: each experiment shifted up from the one before by ``spacing`` times 1.1 times the
    tallest experiment (decades on a log axis); the y-axis then shows no values. Panels: one
    per experiment, named after it, sharing the x-axis; hand-built legends go on the first.
    """
    names = list(dict.fromkeys(owner for owner in owners if owner is not None))
    if layout not in {"stacked", "facet"} or len(names) < 2:
        return PlotSpec([panel])
    by_name = {name: [t for t, owner in zip(panel.traces, owners) if owner == name] for name in names}
    if layout == "stacked":
        log = panel.yscale == "log"
        step = stack_step([Panel(traces=traces) for traces in by_name.values()], "auto", spacing, log=log)
        for position, name in enumerate(names):
            for trace in by_name[name]:
                y = trace.y.astype(float)
                trace.y = y * 10 ** (position * step) if log else y + position * step
        panel.ylabel = f"{panel.ylabel} (offset)" if panel.ylabel else "Offset"
        panel.y_ticks = False
        return PlotSpec([panel])
    panels = [replace(panel, traces=by_name[name], title=str(name), legends=panel.legends if i == 0 else [])
              for i, name in enumerate(names)]
    return PlotSpec(panels, layout="facet", title=panel.title, shared_x=True)


# How far a waterfall rises from its first line to its last, in Offset steps (1.1 times the tallest line).
WATERFALL_RISE = 3.0


def _waterfall(panel: Panel, levels: list, spacing: float) -> Panel:
    """``panel`` with each line shifted up by its ``levels`` value, its numeric colour (e.g. its
    time): the first line at the bottom, the last :data:`WATERFALL_RISE` Offset steps (with
    ``spacing``) above it (decades on a log axis), so a series of spectra reads like a 3D view.
    Lines without a level are left as they are; the y-axis then shows no values."""
    shifted = [(t, level) for t, level in zip(panel.traces, levels) if level is not None]
    values = [level for _, level in shifted]
    if len(set(values)) < 2:
        return panel
    log = panel.yscale == "log"
    rise = WATERFALL_RISE * stack_step([Panel(traces=[t]) for t, _ in shifted], "auto", spacing, log=log)
    low, high = min(values), max(values)
    for trace, level in shifted:
        shift = (level - low) / (high - low) * rise
        y = trace.y.astype(float)
        trace.y = y * 10 ** shift if log else y + shift
    panel.ylabel = f"{panel.ylabel} (offset)" if panel.ylabel else "Offset"
    panel.y_ticks = False
    return panel


def compact_text(df: pd.DataFrame) -> pd.DataFrame:
    """``df`` with its repetitive text columns as categories: the experiment, sample and file names
    repeat on every row (a 1.5 M-row in-situ series: 506 MB as text, 83 MB as categories). Columns
    whose values are mostly different stay as they are."""
    for column in df.columns:
        # Text is object (pandas 2) or its string type (pandas 3).
        text = df[column].dtype == object or isinstance(df[column].dtype, pd.StringDtype)
        if text and len(df) and df[column].nunique(dropna=True) <= len(df) // 2:
            df[column] = df[column].astype("category")
    return df


@st.cache_resource(show_spinner="Loading the experiments…", max_entries=4, ttl=1800)
def _selection(_backend, picked: tuple, row_limit, versions: tuple) -> tuple[pd.DataFrame | None, tuple]:
    """The rows of the ``picked`` ``(label, name)`` experiments in one frame (``_experiment`` = label),
    and the experiments that failed to load.

    Kept as one shared object (``st.cache_resource``): every rerun gets the same frame without copying
    or unpickling it, so it must never be changed in place. ``versions`` (each experiment's
    registration time and rows) loads it again after a re-ingest. A few selections are kept.
    """
    frames, failed = [], []
    for label, name in picked:
        try:
            # time_s for timestamped data stored before it was derived at ingest.
            df = add_elapsed_time(_backend.query_dataset(name, limit=row_limit))
        except Exception as exc:  # noqa: BLE001 - shown to the user
            failed.append(f"{name}: {exc}")
            continue
        df["_experiment"] = label
        frames.append(df)
    if not frames:
        return None, tuple(failed)
    return compact_text(pd.concat(frames, ignore_index=True)), tuple(failed)


def _builtin_datasets(data: pd.DataFrame, datasets_meta: dict) -> list[Dataset]:
    """One mfethuls Dataset per selected experiment, for the built-in instrument plots."""
    result = []
    for label, subset in data.groupby("_experiment", sort=False, observed=True):
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


# The sidebar's sections; INGESTED (set after an ingest) closes Ingest and opens Datasets.
_INGEST_KEY = "sidebar_ingest"
_INGEST_WAS_OPEN = "sidebar_ingest_was_open"
_DATASETS_KEY = "sidebar_datasets"
INGESTED = "just_ingested"

# How several experiments share a plot: the label shown, the library's mode.
_LAYOUTS = {"Together": "overlay", "Offset": "stacked", "Panels": "facet", "Waterfall": "waterfall"}
_LAYOUT_KEY = "plot_layout"


def _plot_toolbar(*, axis_options: bool = True, layouts: bool = False, waterfall: bool = False):
    """Row above the chart: axis limits, Log X / Log Y / Invert X, the layout of several
    experiments (with ``layouts``) or of a series of lines on a colour scale (with
    ``waterfall``), then a Download menu on the right.

    Returns the limits column, the Download menu and the options: the axis options (off
    without them), ``layout`` (the library's mode) and ``spacing`` (offset curves).
    """
    # One row, each control as wide as its label, so they sit together next to Axis limits.
    row = st.container(horizontal=True, gap="small", vertical_alignment="center")
    limits_col = row.container(width="content")
    options = {"log_x": False, "log_y": False, "invert_x": False, "layout": "overlay", "spacing": 1.0}
    if axis_options:
        options.update(log_x=row.checkbox("Log X"), log_y=row.checkbox("Log Y"), invert_x=row.checkbox("Invert X"))
    choices = ["Together", *(["Offset", "Panels"] if layouts else []), *(["Waterfall"] if waterfall else [])]
    if len(choices) > 1:
        if st.session_state.get(_LAYOUT_KEY) not in {None, *choices}:
            del st.session_state[_LAYOUT_KEY]  # e.g. Waterfall, after the colour scale went away
        help_text = ("Several experiments: together on one axis, offset (each shifted up, so the curves don't "
                     "overlap), or in panels one under the other, sharing the x-axis. " if layouts else "")
        if waterfall:
            help_text += ("Waterfall: each line shifted up by its colour value (e.g. its time), the first at "
                          "the bottom, like a 3D view of the series.")
        choice = row.segmented_control(
            "Layout", choices, default="Together", key=_LAYOUT_KEY, label_visibility="collapsed", help=help_text,
        ) or "Together"  # clicking the chosen layout again unselects it
        options["layout"] = _LAYOUTS[choice]
        if choice in {"Offset", "Waterfall"}:
            options["spacing"] = row.slider(
                "Spacing", 0.2, 3.0, 1.0, 0.1, key="plot_spacing", width=110, format="spacing %.1f×",
                label_visibility="collapsed", help="Spacing: how far apart the curves are, in multiples of the "
                                                   "tallest curve.")
    row.space("stretch")
    # wrap: Streamlit 1.66 in Firefox cuts popover labels in a row short ("Downlo…"); a second line instead.
    downloads = row.popover("Download", icon=":material/download:", wrap=True,
                            help="The figure as SVG or HTML, or its data as CSV.")
    return limits_col, downloads, options


_LIMIT_FIELDS = ("x_min", "x_max", "y_min", "y_max")


def _stored_limits(key: str) -> dict:
    """The limits typed for one plot, kept while the limits row is closed (closed widgets lose their state)."""
    return st.session_state.setdefault("_axis_limits", {}).setdefault(key, {})


def _x_window(key: str) -> tuple[float | None, float | None] | None:
    """The x limits typed for the plot ``key``, before it is drawn: Normalise uses them as its window.

    While the limits row is open its fields hold the newest values; once closed, the stored ones.
    """
    stored = _stored_limits(key)
    low, high = (st.session_state.get(f"{key}|{field}", stored.get(field)) for field in ("x_min", "x_max"))
    if low is None and high is None:
        return None
    if low is not None and high is not None and low > high:
        low, high = high, low
    return low, high


def _window_note(window, xlabel: str | None) -> None:
    st.caption(f":material/straighten: Normalised over {xlabel or 'x'} {window_text(window)} (the axis limits).")


def _reset_axis_limits(key: str) -> None:
    _stored_limits(key).clear()
    for field in _LIMIT_FIELDS:
        st.session_state.pop(f"{key}|{field}", None)


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


def _axis_limits(toggle_col, panel: Panel, key: str) -> None:
    """Axis limits for ``panel``: a toolbar toggle opens a row of min/max fields above the chart.

    The row sits between the toolbar and the chart, so it never covers the axes being
    adjusted. Empty fields stay automatic (their placeholder shows the automatic value);
    limits apply to the chart and the SVG, and stay applied when the row is closed.
    """
    stored = _stored_limits(key)
    is_open = toggle_col.toggle("Axis limits", key=f"{key}|open",
                                help="Set min/max per axis. The chart and the SVG use them.")
    axes = [("x", panel.xlabel, panel.xscale), ("y", panel.ylabel, panel.yscale)]
    autos = {axis: _trace_bounds([getattr(t, axis) for t in panel.traces], log=scale == "log") for axis, _, scale in axes}

    if is_open:
        columns = st.columns([1, 1, 1, 1, 1], vertical_alignment="bottom")
        for position, (axis, label, _) in enumerate(axes):
            auto = autos[axis]
            for offset, (end, index) in enumerate((("min", 0), ("max", 1))):
                field = f"{axis}_{end}"
                stored[field] = columns[2 * position + offset].number_input(
                    f"{axis.upper()} {end}", value=stored.get(field), format="%g", key=f"{key}|{field}",
                    placeholder=f"{auto[index]:.4g}" if auto else "auto", help=label or None,
                )
        columns[4].button("Reset", icon=":material/restart_alt:", on_click=_reset_axis_limits, args=(key,),
                          width="stretch", help="Back to automatic limits")

    applied = []
    for axis, _, scale in axes:
        limits, problem = _resolve_limits(stored.get(f"{axis}_min"), stored.get(f"{axis}_max"), autos[axis],
                                          log=scale == "log")
        if problem and is_open:
            st.warning(f"{axis.upper()}: {problem}", icon=":material/warning:")
        setattr(panel, f"{axis}lim", limits)
        if limits:
            applied.append(f"{axis.upper()} {limits[0]:g} to {limits[1]:g}")
    if applied and not is_open:
        st.caption(":material/crop_free: Axis limits: " + ", ".join(applied))


def _limits_unavailable(container, reason: str) -> None:
    container.toggle("Axis limits", disabled=True, help=reason, key="limits-unavailable")


def _csv_bytes(data: pd.DataFrame) -> bytes:
    """The rows behind the plot, every column, with the experiment's name first."""
    frame = data.rename(columns={"_experiment": "experiment"})
    if "experiment" in frame.columns:
        frame = frame[["experiment", *[c for c in frame.columns if c != "experiment"]]]
    return frame.to_csv(index=False).encode("utf-8")


def _download_buttons(menu, title: str, *, spec: PlotSpec | None, fig, data: pd.DataFrame, svg=None) -> None:
    """SVG, HTML and CSV downloads in the Download menu, generated only when clicked (large figures
    take a moment). ``svg`` makes the SVG file, when the figure is not drawn from ``spec``."""
    menu.download_button(
        "SVG figure",
        icon=":material/download:",
        help="Vector figure for publication, drawn with Matplotlib using the axis limits above.",
        data=svg or ((lambda: _svg_bytes(spec)) if spec is not None else (lambda: _figure_bytes(fig, "svg"))),
        file_name=_figure_download_name(title, "svg"),
        mime="image/svg+xml",
        width="stretch",
    )
    menu.download_button(
        "HTML figure",
        icon=":material/download:",
        help="Interactive Plotly figure as a standalone web page.",
        # The page's figure may be thinned for the screen: the file has every point.
        data=(lambda: _figure_bytes(render(spec, backend="plotly"), "html")) if spec is not None
        else (lambda: _figure_bytes(fig, "html")),
        file_name=_figure_download_name(title, "html"),
        mime="text/html",
        width="stretch",
    )
    menu.download_button(
        "CSV data",
        icon=":material/download:",
        help="The data of the selected experiments (after filters), every column, for plotting elsewhere.",
        data=lambda: _csv_bytes(data),
        file_name=_figure_download_name(title, "csv"),
        mime="text/csv",
        width="stretch",
    )


def _heatmap_plot(data: pd.DataFrame, x_col: str, y_cols: list[str], numeric_cols: list[str]) -> None:
    """The heatmap plot type: ``y_cols[0]`` as colour, ``x_col`` across, one row per value of a numeric
    column (time, by default), one heatmap per experiment."""
    from mfethuls.plotting.heatmap import heatmap_grid, matplotlib_heatmaps, plotly_heatmaps

    if not y_cols:
        st.info("Choose the value to colour by under Y axis.")
        return
    value = y_cols[0]
    if len(y_cols) > 1:
        st.caption(f":material/info: A heatmap shows one value: {_column_title(value)}.")
    row_options = [c for c in numeric_cols if c not in {x_col, value}]
    if not row_options:
        st.info("A heatmap needs a third numeric column for its rows, such as time.")
        return
    left, right = st.columns([1, 2], vertical_alignment="bottom")
    rows = left.selectbox("Rows", row_options, format_func=_column_title,
                          index=row_options.index("time_s") if "time_s" in row_options else 0,
                          help="One row per value of this column, e.g. one spectrum per time.")
    scale_row = right.container(horizontal=True, vertical_alignment="bottom")
    cmap = scale_row.selectbox("Colour scale", _CONTINUOUS_PALETTES, index=0)
    if scale_row.toggle("Reverse", key="heatmap-reverse", width="content"):
        cmap = f"{cmap}_r"
    invert_x = scale_row.checkbox("Invert X", key="heatmap-invert-x", width="content")
    limits_col, downloads, _ = _plot_toolbar(axis_options=False)
    _limits_unavailable(limits_col, "Available for line and scatter plots.")
    grids = []
    for label, subset in data.groupby("_experiment", sort=False, observed=True):
        try:
            grids.append(heatmap_grid(subset, x=x_col, value=value, rows=rows, title=str(label)))
        except ValueError as exc:
            st.caption(f":material/info: {label}: {exc}")
    if not grids:
        return
    for note in dict.fromkeys(n for g in grids for n in g.notes):
        st.caption(f":material/info: {note}")
    fig = plotly_heatmaps(grids, cmap=cmap, invert_x=invert_x)

    def svg() -> bytes:
        with _MATPLOTLIB_LOCK:
            figure = matplotlib_heatmaps(grids, cmap=cmap, invert_x=invert_x)
            buf = io.BytesIO()
            figure.savefig(buf, format="svg", bbox_inches="tight")
            plt.close(figure)
        return buf.getvalue()

    title = f"{_column_title(value)} heatmap"
    _download_buttons(downloads, title, spec=None, fig=fig, data=data, svg=svg)
    mark_done("plot")
    st.plotly_chart(fig, width="stretch", config=plotly_config(_figure_download_name(title, "svg")))


def _screen_figure(spec: PlotSpec):
    """The Plotly figure of ``spec`` for the page: thinned above MAX_POINTS points (SVG_MAX_POINTS
    with a reversed x axis, drawn in SVG), with a caption saying so (the downloads draw ``spec``
    itself, every point)."""
    svg = any(panel.x_reversed for panel in spec.panels)
    shown, kept, total = thin_spec(spec, SVG_MAX_POINTS if svg else MAX_POINTS)
    if kept < total:
        st.caption(f":material/info: {thinned_note(kept, total)}")
    return render(shown, backend="plotly")


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


# Columns with at most this many values are offered first in the filter (see filter_columns).
_MAX_FILTER_VALUES = 20
_FILTER_KEY = "plot_filter"


def filter_columns(data: pd.DataFrame) -> list[str]:
    """Columns most worth filtering on, offered first: text (or whole numbers) with 2 to 20 values
    that vary within an experiment, e.g. DSC's ``profile``, a ``segment``, or the curve ``name`` of a
    workbook; fewest values first. Columns that only say which experiment a row is from
    (``sample_id``, ``experiment_id``) are left out: experiments are chosen in the sidebar."""
    found = []
    for column in data.columns:
        if column == "_experiment":
            continue
        series = data[column]
        if pd.api.types.is_float_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
            continue
        count = series.nunique(dropna=True)
        if not 2 <= count <= _MAX_FILTER_VALUES:
            continue
        if "_experiment" in data and series.groupby(data["_experiment"], observed=True).nunique(dropna=True).max() < 2:
            continue
        found.append((count, column))
    return [column for _, column in sorted(found, key=lambda item: item[0])]


def apply_conditions(data: pd.DataFrame, conditions: dict) -> pd.DataFrame:
    """Rows whose value in each column is one of those chosen for it."""
    for column, values in conditions.items():
        data = data[data[column].astype(str).isin(values)]
    return data


def _clear_filter() -> None:
    for key in [k for k in st.session_state if str(k).startswith(_FILTER_KEY)]:
        del st.session_state[key]


def _plot_filter(container, data: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """The **Filter** button and its menu: one column and the values to keep; returns the rows kept
    and the condition, by column."""
    suggested = filter_columns(data)
    columns = suggested + [c for c in data.columns if c != "_experiment" and c not in suggested]
    column = st.session_state.get(f"{_FILTER_KEY}-column", _NO_STYLE)
    kept = st.session_state.get(f"{_FILTER_KEY}-values-{column}") if column != _NO_STYLE else None
    with container.popover(_filter_label(kept, suggested), icon=":material/filter_alt:",
                           type="primary" if kept else "secondary", key="plot-filter-menu", wrap=True,
                           help="Plot only the rows with some values, e.g. one DSC segment."):
        column = st.selectbox("Column", [_NO_STYLE, *columns], key=f"{_FILTER_KEY}-column",
                              format_func=_column_title)
        if column == _NO_STYLE:
            return data, {}
        # In the order they come in the data: a DSC program's segments as they were run.
        values = list(pd.unique(data[column].dropna().astype(str)))
        chosen = st.multiselect("Keep rows where it is", values, key=f"{_FILTER_KEY}-values-{column}",
                                placeholder="Choose values")
    conditions = {column: chosen} if chosen else {}
    return apply_conditions(data, conditions), conditions


_NORMALISE_KEY = "plot_normalise"
# What each method does, in the menu.
_NORMALISE_HELP = {
    "max": "The largest value of each experiment becomes 1 (a negative peak -1).",
    "minmax": "Each experiment runs from 0 (its lowest value) to 1 (its highest).",
    "area": "The area under each experiment's curves becomes 1.",
}


def _normalise_menu(container) -> str | None:
    """The **Normalise** button and its menu; returns the method chosen, or None.

    Display only: each experiment's curves are scaled together, the data stays as it is. With x
    axis limits, only the points inside them set the scale (see :func:`_x_window`).
    """
    method = st.session_state.get(_NORMALISE_KEY)
    label = f"Normalised: {NORMALISE_METHODS[method].lower()}" if method else "Normalise"
    with container.popover(label, icon=":material/height:", type="primary" if method else "secondary",
                           key="plot-normalise-menu", wrap=True,
                           help="Compare curves by their shape: scale each experiment, without changing the data."):
        method = st.radio("Scale each experiment so that", [None, *NORMALISE_METHODS], key=_NORMALISE_KEY,
                          on_change=_clear_y_limits,
                          format_func=lambda m: "As measured" if m is None else NORMALISE_METHODS[m],
                          captions=["The values as stored.", *_NORMALISE_HELP.values()])
    return method


def _clear_y_limits() -> None:
    """Y limits are in the plot's units, which normalising changes: forget them (the x limits stay)."""
    for stored in st.session_state.get("_axis_limits", {}).values():
        stored.pop("y_min", None)
        stored.pop("y_max", None)
    for key in [k for k in st.session_state if str(k).endswith(("|y_min", "|y_max"))]:
        del st.session_state[key]


def _normalised_frame(df: pd.DataFrame, x: str, y: str, method: str, lines: list[str] | None = None,
                      x_range: tuple[float | None, float | None] | None = None) -> tuple[pd.DataFrame, list[str]]:
    """``df`` with each experiment's (and Y column's) ``y`` normalised; the experiments left as they are.

    ``lines`` are the columns that split an experiment into the lines drawn (colour, style): the
    area is summed over those lines, so a DSC run's heating and cooling are each integrated on
    their own instead of as one curve zigzagging between them. With ``x_range`` only the rows in
    that x range set the scale (the axis limits); every row is scaled.
    """
    keys = [k for k in ("_experiment", "_y_metric") if k in df.columns]
    lines = [c for c in dict.fromkeys(lines or []) if c in df.columns and c not in keys]
    df = df.copy()
    df[y] = pd.to_numeric(df[y], errors="coerce").astype(float)
    unchanged = []
    groups = df.groupby(keys, sort=False, dropna=False, observed=True) if keys else [("", df)]
    for key, rows in groups:
        parts = [part for _, part in rows.groupby(lines, sort=False, dropna=False, observed=True)] if lines else [rows]
        found = normalisation([p[x].to_numpy() for p in parts], [p[y].to_numpy() for p in parts], method, x_range)
        if found is None:
            unchanged.append(" · ".join(map(str, key if isinstance(key, tuple) else (key,))))
            continue
        shift, factor = found
        df.loc[rows.index, y] = (rows[y] - shift) * factor
    return df, unchanged


def _filter_label(kept: list | None, suggested: list[str]) -> str:
    """What the Filter button says: the values kept (``Filter: Heating_1 +1``) when it is on,
    otherwise the column most worth filtering on (``Filter by profile``)."""
    if kept:
        first = kept[0] if len(kept[0]) <= 24 else kept[0][:23] + "…"
        return f"Filter: {first}" + (f" +{len(kept) - 1}" if len(kept) > 1 else "")
    return f"Filter by {_column_title(suggested[0])}" if suggested else "Filter"


def _filter_note(kept: int, total: int, conditions: dict) -> None:
    """Under the chart: what the plot leaves out, with a way back to all rows."""
    if not conditions:
        return
    said = "; ".join(f"{_column_title(c)} is {', '.join(v)}" for c, v in conditions.items())
    text_col, clear_col = st.columns([5, 1], vertical_alignment="center")
    text_col.caption(f":material/filter_alt: Showing **{kept:,}** of {total:,} rows: {said}.")
    clear_col.button("Clear", icon=":material/filter_alt_off:", key=f"{_FILTER_KEY}-clear", width="stretch",
                     on_click=_clear_filter, help="Plot all rows again")


def _experiment_label(dataset: dict) -> str:
    return dataset.get("experiment_name") or dataset["name"]


def _instrument(dataset: dict) -> str:
    return dataset.get("instrument_name") or dataset.get("instrument_type") or ""


def _experiment_picker(datasets: list[dict]) -> list[str]:
    """The experiments to plot: one list (no table under it for the list to cover), narrowed by
    instrument with one click, each entry with its sample and run."""
    by_label = {_experiment_label(d): d for d in datasets}
    instruments = sorted({_instrument(d) for d in datasets} - {""})
    shown = list(by_label)
    if len(instruments) > 1:
        picked = st.pills("Instrument", instruments, selection_mode="multi", key="pick_instruments",
                          help="Show only these instruments' experiments in the list below.")
        if picked:
            shown = [label for label, d in by_label.items() if _instrument(d) in picked]
    # Experiments already chosen stay chosen while the list shows other instruments.
    chosen = [label for label in st.session_state.get(_PICKED, []) if label in by_label]
    options = shown + [label for label in chosen if label not in shown]

    def describe(label: str) -> str:
        d = by_label[label]
        return " · ".join(str(part) for part in (label, d.get("sample_id"), d.get("run_id")) if part)

    picked = st.multiselect("Select experiments to plot", options, key=_PICKED, format_func=describe,
                            placeholder="Choose experiments")
    count = len(datasets)
    st.caption(f"{count} experiment{'s' if count != 1 else ''} ingested"
               + (f", {len(shown)} shown" if len(shown) != count else "") + ".")
    return picked


@st.cache_data(show_spinner=False, ttl=300)
def _cleanup_count(_backend, registry_path: str, registry_modified: float, datasets: tuple) -> int:
    """How many changes Clean up would make; cached until the registry or the datasets change."""
    try:
        return len(_backend.reconcile_plan(registry_path)["actions"])
    except Exception:  # noqa: BLE001 - only a hint; Clean up itself reports the problem
        return 0


def _cleanup_hint(registry_path: str, datasets: list[dict]) -> None:
    """A note when ingested data no longer matches the registry, opening Clean up with its plan."""
    if not datasets or not registry_path or not os.path.exists(registry_path):
        return
    count = _cleanup_count(backend, registry_path, os.path.getmtime(registry_path),
                           tuple(sorted(d["name"] for d in datasets)))
    if not count:
        return
    st.info(f"The registry changed: **{count}** stored experiment{'s' if count != 1 else ''} "
            f"{'need' if count != 1 else 'needs'} updating.", icon=":material/mop:")
    if st.button("Review", icon=":material/fact_check:", width="stretch", key="cleanup-hint"):
        try:
            st.session_state["reconcile_plan"] = backend.reconcile_plan(registry_path)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not check: {exc}")
            return
        _settings_dialog(registry_path)


def _cleanup_section(registry_path: str) -> None:
    """Check ingested data against the registry, show the plan, and apply it on confirmation."""
    st.caption(
        "Compares what was ingested with the registry: forgets experiments removed from it, "
        "updates renamed or corrected ones and deletes stored files nothing uses. Raw data is never touched."
    )
    if st.button("Check", icon=":material/fact_check:", disabled=not registry_path, width="stretch"):
        try:
            st.session_state["reconcile_plan"] = backend.reconcile_plan(registry_path)
        except Exception as exc:
            st.error(f"Could not check: {exc}")
    plan = st.session_state.get("reconcile_plan")
    if not plan:
        return

    if plan["actions"]:
        counts = " · ".join(f"{_RECONCILE_LABELS[k]} {n}" for k, n in plan["counts"].items() if n)
        st.markdown(f"**{counts}**")
        st.dataframe(
            pd.DataFrame([
                {"action": _RECONCILE_LABELS[a["kind"]], "experiment": a["name"] or a["experiment_id"],
                 "why": a["reason"], "files": len(a["paths"]) or ""}
                for a in plan["actions"]
            ]),
            hide_index=True, width="stretch",
        )
    else:
        st.success("Everything ingested matches the registry.")
    if plan["pending"]:
        st.caption(f"Never ingested ({len(plan['pending'])}): {', '.join(plan['pending'])}")
    for names in plan["duplicates"]:
        st.caption(f"Identical raw data: {', '.join(names)}")
    if not plan["actions"]:
        return

    confirmed = True
    if plan["blocked"]:
        st.warning(plan["blocked_reason"])
        confirmed = st.checkbox(f"Yes, forget {plan['forgets']} experiments")
    if st.button("Apply", type="primary", disabled=not confirmed, width="stretch"):
        try:
            with st.spinner("Cleaning up…"):
                results = backend.reconcile_apply(registry_path, plan["fingerprint"], force=plan["blocked"])
        except Exception as exc:
            st.session_state["reconcile_message"] = f"⚠ Not applied: {exc}"
        else:
            failed = [r for r in results if r["status"] == "error"]
            text = f"Applied {len(results) - len(failed)} of {len(results)} changes."
            if failed:
                text = "⚠ " + text + " Failed: " + "; ".join(
                    f"{r['name'] or r['experiment_id']} ({r['error']})" for r in failed)
            st.session_state["reconcile_message"] = text
        st.session_state.pop("reconcile_plan", None)
        _cleanup_count.clear()
        st.rerun()



@st.dialog("Settings", width="large")
def _settings_dialog(registry_path: str) -> None:
    with st.expander(":material/folder: Data folder and registry", expanded=not is_set_up()):
        render_setup_form(backend, key="settings")
        st.markdown("**How to organise the data folder**")
        render_folder_layout()
    with st.expander(":material/biotech: Instruments"):
        render_instruments_section(backend, registry_path)
    with st.expander(":material/mop: Clean up", expanded=bool(st.session_state.get("reconcile_plan"))):
        _cleanup_section(registry_path)
    with st.expander(":material/database: Data loading"):
        render_loading_settings()
    if getattr(backend, "offers_example", False):
        with st.expander(":material/science: Example data", expanded=bool(example_folder())):
            render_example_settings(backend)
    with st.expander(":material/palette: Appearance"):
        _appearance_section()


def _choose_accent() -> None:
    save_accent(st.session_state["accent"])
    apply_appearance()
    st.session_state["accent_changed"] = True


def _appearance_section() -> None:
    names = list(ACCENTS)
    st.radio("Accent colour", names, index=names.index(saved_accent()), key="accent", horizontal=True,
             on_change=_choose_accent, help="Buttons, toggles and the progress bar. Saved for this computer.")
    if st.session_state.pop("accent_changed", False):
        # The theme reaches the browser when a run starts: one more run shows it.
        st.rerun()


# The sidebar's getting-started tracker for this run: where it goes and what it shows.
_guide: dict = {}


def _draw_guide() -> None:
    if _guide and not _guide["drawn"]:
        _guide["drawn"] = True
        with _guide["slot"]:
            render_guide_tracker(_guide["datasets"])


def _stop() -> None:
    """``st.stop()``, after drawing the getting-started tracker."""
    _draw_guide()
    st.stop()


@st.fragment
def _explore(data: pd.DataFrame, datasets: list, selected_names: list) -> None:
    """The Preview and the Plot. A fragment: changing a plot option reruns only this part, not the
    loading of the experiments and the sidebar above it."""

    # ---------------------------------------------------------------------------
    # Preview
    # ---------------------------------------------------------------------------
    with st.expander(":material/table_view: **Preview**", expanded=True):
        # The table is sent to the browser on every rerun, so whole datasets would slow the app.
        st.dataframe(
            data.drop(columns=["_experiment"], errors="ignore").head(_PREVIEW_ROWS),
            width="stretch",
        )
        if len(data) > _PREVIEW_ROWS:
            st.caption(f"Showing the first {_PREVIEW_ROWS:,} of {len(data):,} rows. Plots use all rows.")

    # ---------------------------------------------------------------------------
    # Plot (its Filter next to what it changes)
    # ---------------------------------------------------------------------------
    with st.expander(":material/show_chart: **Plot**", expanded=True):
        all_rows = len(data)
        # The toggle, then the Filter button next to it, where the eye starts reading the section.
        top_row = st.container(horizontal=True, gap="medium", vertical_alignment="center")
        builtin_col = top_row.container(width="content")
        data, conditions = _plot_filter(top_row, data)
        normalise = _normalise_menu(top_row)
        numeric_cols = data.select_dtypes(include="number").columns.tolist()

        use_builtin = builtin_col.toggle(
            "Built-in instrument plot",
            value=False,
            help="Use the mfethuls plot for each instrument, e.g. heat flow vs temperature for DSC.",
        )

        if use_builtin:
            datasets_meta = {(d.get("experiment_name") or d["name"]): d for d in datasets}
            experiments = _builtin_datasets(data, datasets_meta)
            several = len(experiments) > 1
            together = several and shares_x_axis(experiments)
            if several and not together:
                st.caption(":material/view_agenda: One panel per experiment: their x-axes differ.")
            limits_col, downloads, layout = _plot_toolbar(axis_options=False, layouts=together)
            comparison_mode = layout["layout"] if together else "auto"
            limits_key = "|".join(["limits", "builtin", comparison_mode, *selected_names])
            window = _x_window(limits_key) if normalise and comparison_mode != "facet" else None
            try:
                spec = build_experiments_spec(experiments, mode=comparison_mode, spacing=layout["spacing"],
                                              normalise=normalise, normalise_x=window)
            except PlotError as exc:
                st.warning(f"No built-in plot for this selection: {exc}")
            else:
                for note in spec.notes:
                    st.caption(f":material/info: {note}")
                if window and spec.layout == "single":
                    _window_note(window, spec.panel.xlabel)
                title = spec.title or spec.panel.title or "mfethuls"
                if spec.layout == "single":
                    _axis_limits(limits_col, spec.panel, limits_key)
                else:
                    _limits_unavailable(limits_col, "Not available for figures with one panel per experiment.")
                fig = _screen_figure(spec)
                _download_buttons(downloads, title, spec=spec, fig=fig, data=data)
                mark_done("plot")
                st.plotly_chart(
                    fig,
                    width="stretch",
                    config=plotly_config(_figure_download_name(title, "svg")),
                )

        elif len(numeric_cols) < 1:
            st.info("No numeric columns available for plotting.")
        else:
            # What to plot: type and axes.
            type_col, x_axis_col, y_axis_col = st.columns([1, 1, 2])
            plot_type = type_col.selectbox("Plot type", ["line", "scatter", "histogram", "box", "heatmap"],
                                           help="Heatmap: a series (e.g. spectra over time) as one image, every "
                                                "spectrum a row.")
            x_col = x_axis_col.selectbox("X axis", numeric_cols, index=0)
            y_options = [c for c in numeric_cols if c != x_col]
            # Changing X changes the Y options, which makes Streamlit start the Y box afresh:
            # keep the previous Y columns instead of falling back to the first option (often the old X).
            kept = [c for c in st.session_state.get("_y_cols", []) if c in y_options]
            y_cols = y_axis_col.multiselect("Y axis", y_options, default=kept or y_options[:1])
            st.session_state["_y_cols"] = y_cols

            if plot_type == "heatmap":
                _heatmap_plot(data, x_col, y_cols, numeric_cols)
            else:

                # How to tell lines apart: colour, and line style / marker shape side by side.
                hue_opts = ["_experiment"] + [c for c in data.columns if c != "_experiment"]
                colour_by_col, style_by_col, palette_col = st.columns([1, 1, 2], vertical_alignment="bottom")
                color_col = colour_by_col.selectbox("Colour by", hue_opts, index=0, format_func=_column_title)
                # Line styles (line plots) or marker shapes (scatter) by a second column; "Signal" is the Y column.
                style_opts = [_NO_STYLE, *hue_opts, *(["_y_metric"] if len(y_cols) > 1 else [])]
                style_col = style_by_col.selectbox(
                    "Style by", style_opts, index=0, format_func=_column_title,
                    disabled=plot_type not in {"line", "scatter"},
                    help="Line plots: one line style per value. Scatter plots: one marker shape per value.",
                )
                style_col = None if style_col == _NO_STYLE or plot_type not in {"line", "scatter"} else style_col

                # A numeric colour column with many values (e.g. time_s) is drawn on a colour scale.
                continuous = (
                    plot_type in {"line", "scatter"}
                    and color_col != "_experiment"
                    and _uses_colorbar(data, color_col)
                )
                discrete_seq = _DISCRETE_PALETTES["Plotly"]
                cmap = "viridis"
                if continuous:
                    scale_row = palette_col.container(horizontal=True, vertical_alignment="bottom")
                    cmap = scale_row.selectbox("Colour scale", _CONTINUOUS_PALETTES, index=0)
                    if scale_row.toggle("Reverse", help="Flip the colour scale, e.g. dark for late times.",
                                        width="content"):
                        cmap = f"{cmap}_r"
                else:
                    palette_name = palette_col.selectbox("Colour palette", list(_DISCRETE_PALETTES), index=0)
                    discrete_seq = _DISCRETE_PALETTES[palette_name]

                if not y_cols and plot_type != "histogram":
                    st.info("Select at least one Y axis column.")
                else:
                    title = f"{x_col} vs {', '.join(y_cols)}" if y_cols else x_col

                    if len(y_cols) > 1 or color_col == "_experiment":
                        id_vars = [x_col, "_experiment"] + [
                            c for c in (color_col, style_col) if c and c not in {x_col, "_experiment", "_y_metric"}
                        ]
                        id_vars = list(dict.fromkeys(id_vars))
                        long_df = data[id_vars + y_cols].melt(
                            id_vars=id_vars,
                            value_vars=y_cols,
                            var_name="_y_metric",
                            value_name="_y_value",
                        )
                        # Several Y columns coloured by experiment: tell the signals apart by colour,
                        # unless they are already told apart by style.
                        by_signal = len(y_cols) > 1 and color_col == "_experiment" and style_col != "_y_metric"
                        color = "_y_metric" if by_signal else color_col
                        y_series = "_y_value"
                    else:
                        long_df = data  # read only from here on: no copy of every row
                        y_series = y_cols[0] if y_cols else x_col
                        color = color_col

                    several = plot_type in {"line", "scatter"} and data["_experiment"].nunique() > 1
                    limits_col, downloads, axis = _plot_toolbar(layouts=several,
                                                                waterfall=plot_type == "line" and _numeric_colour(long_df, color))
                    use_log_x, use_log_y, invert_x = axis["log_x"], axis["log_y"], axis["invert_x"]
                    if plot_type in {"line", "scatter"}:
                        # WebGL (Plotly) on screen, thinned above MAX_POINTS (plotting.thin); Matplotlib for the SVG.
                        values = long_df[color].nunique(dropna=False) if color else 0
                        if color and _uses_colorbar(long_df, color) and values > MAX_SERIES_LINES:
                            # A long series (spectra over time): an even spread of its lines on the colour scale.
                            shown = spread_values(long_df[color])
                            long_df = long_df[long_df[color].isin(shown)]
                            st.caption(f":material/info: {_column_title(color)} has {values:,} values: showing "
                                       f"{len(shown)} of them, spread evenly from first to last. The heatmap plot type "
                                       "shows them all.")
                        elif color and not _uses_colorbar(long_df, color) and values > _MAX_COLOUR_GROUPS:
                            st.caption(f"'{color}' has more than {_MAX_COLOUR_GROUPS} values; drawing without colour "
                                       "groups.")
                            color = None
                        mode = "lines" if plot_type == "line" else "markers"
                        style = style_col
                        max_styles = len(LINESTYLES if mode == "lines" else MARKERS)
                        if style and long_df[style].nunique(dropna=False) > max_styles:
                            st.caption(f"'{_column_title(style)}' has more than {max_styles} values; "
                                       "drawing without styles.")
                            style = None
                        if mode == "lines" and color and color != "_experiment" and _points_own_lines(long_df, color, style):
                            st.caption(f"Each {_column_title(color)} value has one point here, so each experiment's "
                                       "points are joined in one line, coloured by experiment.")
                            color = "_experiment" if "_experiment" in long_df.columns else None
                        ylabel = shared_axis_label(y_cols)
                        limits_key = "|".join(["limits", x_col, *y_cols])
                        window = _x_window(limits_key) if normalise and axis["layout"] != "facet" else None
                        if normalise:
                            long_df, unchanged = _normalised_frame(long_df, x_col, y_series, normalise,
                                                                   lines=[c for c in (color, style) if c], x_range=window)
                            if window:
                                _window_note(window, axis_label(x_col))
                            ylabel = normalised_label(ylabel)
                            if unchanged:
                                st.caption(f":material/info: Drawn as they are, since they cannot be normalised "
                                           f"({NORMALISE_METHODS[normalise]}): {', '.join(unchanged)}.")
                            if normalise == "minmax" and use_log_y:
                                st.caption(f":material/info: {LOG_MINMAX_NOTE}")
                        palette, _ = convert_colors_to_same_type(list(discrete_seq), colortype="tuple")
                        spec = _xy_spec(
                            long_df,
                            x=x_col,
                            y=y_series,
                            color=color,
                            style=style,
                            mode=mode,
                            palette=palette,
                            cmap=cmap,
                            title=title,
                            ylabel=ylabel,
                            log_x=use_log_x,
                            log_y=use_log_y,
                            invert_x=invert_x,
                            layout=axis["layout"],
                            spacing=axis["spacing"],
                        )
                        if spec.layout == "single":
                            _axis_limits(limits_col, spec.panel, limits_key)
                        else:
                            _limits_unavailable(limits_col, "Not available for figures with one panel per experiment.")
                        if axis["layout"] == "waterfall" and spec.panel.y_ticks:
                            st.caption(":material/info: Waterfall shifts each line by its colour value; these "
                                       "lines have no numeric colour, so they are drawn together.")
                        if mode == "lines" and any(t.mode == "markers" for p in spec.panels for t in p.traces):
                            st.caption("Some lines have only one point, so they are drawn as points.")
                        fig = _screen_figure(spec)
                    else:
                        _limits_unavailable(limits_col, "Available for line and scatter plots.")
                        if normalise:
                            st.caption(":material/info: Normalise applies to line and scatter plots.")
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

                    _download_buttons(downloads, title, spec=spec, fig=fig, data=data)
                    mark_done("plot")
                    st.plotly_chart(
                        fig,
                        width="stretch",
                        config=plotly_config(_figure_download_name(title, "svg")),
                    )
        _filter_note(len(data), all_rows, conditions)


def run(app_backend) -> None:
    """Draw the page, with data from ``app_backend`` (e.g. :class:`~mfethuls.app.backend.LocalBackend`)."""

    global backend
    backend = app_backend
    apply_appearance()
    if getattr(backend, "edits_settings", False):
        ensure_registry()
    # The landing page starts without the sidebar, so it stays uncluttered.
    first_visit = not is_set_up() and not example_folder()
    st.set_page_config(page_title="mfethuls", layout="wide", page_icon="🧪",
                       initial_sidebar_state="collapsed" if first_visit else "expanded")
    apply_style()

    message = st.session_state.pop("reconcile_message", None)
    if message:
        st.toast(message, icon=":material/warning:" if message.startswith("⚠") else ":material/check_circle:")
    message = st.session_state.pop("ingest_message", None)
    if message:
        st.toast(message, icon=":material/check_circle:")

    # ===========================================================================
    # SIDEBAR
    # ===========================================================================
    # The settings button sits at the top; it needs the registry path the Ingest section uses.
    settings_row = st.sidebar.container()
    # Getting-started progress; filled at the end of the run, so this run's plot already counts.
    global _guide
    _guide = {"slot": st.sidebar.container(), "datasets": [], "drawn": False}
    backend.render_status()

    try:
        datasets = backend.list_datasets()
        datasets_error = None
    except Exception as exc:
        datasets, datasets_error = [], exc

    # After ingesting, the next step is the data: close Ingest and open Datasets.
    if st.session_state.pop(INGESTED, False):
        st.session_state[_INGEST_KEY] = False
        st.session_state[_DATASETS_KEY] = True
    # Open while nothing is ingested yet: that is where a new user goes next.
    ingest = st.sidebar.expander(":material/input: **Ingest**", expanded=not datasets, key=_INGEST_KEY,
                                 on_change="rerun")
    # Drawn only while open: its count of new data scans the whole data folder (seconds on a synced drive).
    # Each time it is opened, that scan is done again, so files copied in since show up.
    if ingest.open and not st.session_state.get(_INGEST_WAS_OPEN):
        clear_scan_caches()
    st.session_state[_INGEST_WAS_OPEN] = ingest.open
    if ingest.open:
        with ingest:
            registry_path = backend.render_ingest()
    else:
        registry_path = backend.registry_path()

    with settings_row:
        st.header("mfethuls", anchor=False)  # no link icon on hover
        if example_folder():
            st.caption(":material/science: Example data")
        # Labelled buttons: icons alone were not recognised as the way to these pages.
        home_col, settings_col = st.columns(2, gap="small")
        if home_col.button("Home", icon=":material/home:", width="stretch",
                           help="What mfethuls is, and how to get started"):
            show_landing()
            st.rerun()
        if settings_col.button("Settings", icon=":material/settings:", width="stretch",
                               help="Data folder and registry, instruments, clean up, data loading, example data"):
            _settings_dialog(registry_path)
    open_requested_dialog(backend)

    # ---------------------------------------------------------------------------
    # Datasets expander
    # ---------------------------------------------------------------------------
    with st.sidebar.expander(":material/dataset: **Datasets**", expanded=True, key=_DATASETS_KEY,
                             on_change="rerun"):
        if datasets_error is not None:
            st.error(f"Could not load datasets: {datasets_error}")
        _cleanup_hint(registry_path, datasets)

        if not datasets:
            st.info("Nothing ingested yet: open **Ingest** above.", icon=":material/arrow_upward:")
            selected_labels: list[str] = []
            label_to_name: dict[str, str] = {}
        else:
            label_to_name = {_experiment_label(d): d["name"] for d in datasets}
            selected_labels = _experiment_picker(datasets)
        if st.button("Reload list", icon=":material/refresh:", width="stretch",
                     help="Read the stored datasets again, e.g. after ingesting from Python"):
            backend.clear_caches()
            st.rerun()

    # ===========================================================================
    # MAIN CONTENT
    # ===========================================================================

    selected_names = [label_to_name[label] for label in selected_labels] if selected_labels else []
    _guide["datasets"] = datasets

    if landing_requested():
        render_landing(backend)
        _stop()
    if setup_requested():
        render_setup(backend)
        _stop()
    if not selected_names:
        if is_set_up() or example_folder():
            render_progress(backend, datasets)
        else:
            render_landing(backend)
        _stop()
    row_limit = loading_row_limit()
    mark_done("select")

    # ---------------------------------------------------------------------------
    # Load data
    # ---------------------------------------------------------------------------
    by_name = {d["name"]: d for d in datasets}
    # A re-ingested experiment is registered again: a new version, so it is loaded again.
    versions = tuple((name, str(by_name.get(name, {}).get("registered_at")), by_name.get(name, {}).get("rows"))
                     for name in selected_names)
    loaded, failed = _selection(backend, tuple(zip(selected_labels, selected_names)), row_limit, versions)
    for message in failed:
        st.error(f"Failed to load {message}")
    if loaded is None:
        _stop()
    data = loaded.copy(deep=False)  # the cached frame is shared by every rerun: never change it in place

    # ---------------------------------------------------------------------------
    # Dataset info
    # ---------------------------------------------------------------------------
    st.subheader("Dataset info", anchor=False, divider="gray")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Rows", f"{len(data):,}")
    col_b.metric("Columns", len(data.columns) - 1)
    col_c.metric("Experiments", len(selected_names))
    st.dataframe(pd.DataFrame([{
        "experiment": label, "instrument": _instrument(by_name.get(name, {})),
        "sample_id": by_name.get(name, {}).get("sample_id") or "", "run_id": by_name.get(name, {}).get("run_id") or "",
    } for label, name in zip(selected_labels, selected_names)]), hide_index=True, width="stretch")

    _explore(data, datasets, list(selected_names))
    _draw_guide()
