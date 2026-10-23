"""Draw a :class:`PlotSpec` with Plotly (interactive, WebGL).

Lines use ``Scattergl`` so hundreds of thousands of points stay responsive without
downsampling. Plotly's own SVG export rasterizes WebGL traces; for a vector SVG,
render the same spec with the Matplotlib backend.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from matplotlib.colors import to_hex

from .labels import mathtext_to_html as _text
from .spec import Colorbar, Panel, PlotSpec


FACET_PANEL_HEIGHT_PX = 280
SINGLE_HEIGHT_PX = 450

LINE_WIDTH = 2.5
FONT_SIZE = 16
TITLE_FONT_SIZE = 20

# WebGL lines only take named dashes; long dashes stay visible on dense data,
# where short ones blur into a solid line.
_DASHES = {"-": "solid", "--": "longdash", ":": "dot", "-.": "longdashdot"}
# Matplotlib marker codes as Plotly symbols (all available in WebGL).
_SYMBOLS = {"o": "circle", "s": "square", "^": "triangle-up", "D": "diamond", "v": "triangle-down",
            "P": "cross", "X": "x", "*": "star"}


def plotly_config(filename: str = "figure") -> dict:
    """Plotly ``config`` with the modebar download button set to SVG."""

    return {
        "displaylogo": False,
        "toImageButtonOptions": {"format": "svg", "filename": filename},
    }


def _color(value: Any) -> Optional[str]:
    return None if value is None else to_hex(value)


def _line(color: Any, linestyle: str) -> dict:
    line = {"width": LINE_WIDTH, "dash": _DASHES.get(linestyle, "solid")}
    hex_color = _color(color)
    if hex_color is not None:
        line["color"] = hex_color
    return line


def _add_colorbar(fig, colorbar: Colorbar, *, row: Optional[int]) -> None:
    """Draw the colour bar from a data-less marker trace, beside its subplot row."""

    import plotly.graph_objects as go
    from matplotlib import colormaps

    cmap = colormaps[colorbar.cmap]
    colorscale = [[step / 10, to_hex(cmap(step / 10))] for step in range(11)]
    bar: dict[str, Any] = {"title": {"text": _text(colorbar.title), "side": "right"}}
    if row is not None:
        bottom, top = fig.layout["yaxis" if row == 1 else f"yaxis{row}"].domain
        bar.update(y=(bottom + top) / 2, len=top - bottom, yanchor="middle")

    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker={
                "color": [colorbar.vmin],
                "cmin": colorbar.vmin,
                "cmax": colorbar.vmax,
                "colorscale": colorscale,
                "showscale": True,
                "colorbar": bar,
            },
            showlegend=False,
            hoverinfo="skip",
        ),
        **({"row": row, "col": 1} if row is not None else {}),
    )


def _add_panel_traces(fig, panel: Panel, *, row: Optional[int], shown: Optional[set] = None) -> None:
    """Add ``panel``'s traces (to subplot ``row`` of a facet).

    ``shown`` collects the legend entries of a facet's earlier panels: a label already in
    the legend is not listed again, and its curves in every panel toggle together.
    """
    import plotly.graph_objects as go

    position = {"row": row, "col": 1} if row is not None else {}

    for trace in panel.traces:
        color = panel.trace_color(trace)
        in_legend = bool(trace.label) and panel.legend and not panel.legends
        group = trace.legend_group
        if shown is not None and in_legend:
            group = group or f"label:{trace.label}"
            in_legend = group not in shown
            shown.add(group)
        fig.add_trace(
            go.Scattergl(
                x=trace.x,
                y=trace.y,
                mode=trace.mode,
                name=_text(trace.label) or "",
                line=_line(color, trace.linestyle),
                marker={"size": 5, "color": _color(color), "symbol": _SYMBOLS.get(trace.marker, "circle")},
                legendgroup=group,
                showlegend=in_legend,
            ),
            **position,
        )

    if panel.colorbar is not None:
        _add_colorbar(fig, panel.colorbar, row=row)

    # Hand-built legends are drawn as data-less entries, one Plotly legend each.
    for idx, spec_legend in enumerate(panel.legends):
        legend_id = "legend" if idx == 0 else f"legend{idx + 1}"
        for entry in spec_legend.entries:
            fig.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers" if entry.marker else "lines",
                    name=_text(entry.label),
                    line=_line(entry.color, entry.linestyle),
                    marker={"color": _color(entry.color), "symbol": _SYMBOLS.get(entry.marker or "o", "circle")},
                    legendgroup=entry.group or f"{spec_legend.title}:{entry.label}",
                    legend=legend_id,
                    showlegend=True,
                    hoverinfo="skip",
                ),
                **position,
            )
        # Plotly does not stack legends, so the first sits right of the plot and later
        # ones run horizontally above it instead of overlapping.
        if idx == 0:
            placement = {"y": 1.0, "yanchor": "top"}
        else:
            placement = {
                "orientation": "h",
                "x": 1.0,
                "xanchor": "right",
                "y": 1.02 + 0.08 * (idx - 1),
                "yanchor": "bottom",
            }
        # Plotly gives a curve one legend group: entries no curve belongs to (the line styles,
        # when the curves are grouped by colour) would hide only themselves, so they don't react.
        groups = {trace.legend_group for trace in panel.traces}
        if not any(entry.group and entry.group in groups for entry in spec_legend.entries):
            placement.update(itemclick=False, itemdoubleclick=False)
        fig.update_layout({legend_id: {"title": {"text": _text(spec_legend.title)}, "font": {"size": FONT_SIZE - 2}, **placement}})


# Log axes: label decades only, written as powers of ten (10², not 100 or "1k").
_LOG_AXIS = {"dtick": 1, "exponentformat": "power", "minor": {"ticks": "outside", "showgrid": True}}


def _axis_range(limits: tuple[float, float], scale: str, reversed_: bool = False) -> list[float]:
    """Plotly range for data-unit limits: log axes take log10 values, reversed axes high to low."""

    low, high = limits
    if scale == "log":
        low, high = math.log10(low), math.log10(high)
    return [high, low] if reversed_ else [low, high]


def _axis_options(panel: Panel) -> tuple[dict, dict]:
    xaxis: dict[str, Any] = {"title": {"text": _text(panel.xlabel)}, "type": panel.xscale}
    if panel.xlim is not None:
        xaxis["range"] = _axis_range(panel.xlim, panel.xscale, panel.x_reversed)
    elif panel.x_reversed:
        xaxis["autorange"] = "reversed"
    yaxis: dict[str, Any] = {"title": {"text": _text(panel.ylabel)}, "type": panel.yscale}
    if not panel.y_ticks:
        yaxis["showticklabels"] = False
    if panel.ylim is not None:
        yaxis["range"] = _axis_range(panel.ylim, panel.yscale)
    for axis, scale in ((xaxis, panel.xscale), (yaxis, panel.yscale)):
        if scale == "log":
            axis.update(_LOG_AXIS)
    return xaxis, yaxis


def render(spec: PlotSpec):
    """Return a ``plotly.graph_objects.Figure``."""

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if spec.layout == "facet":
        count = len(spec.panels)
        spacing = min(0.08, 0.5 / (count - 1)) if count > 1 else 0.0
        if spec.shared_x:
            spacing = min(0.03, 0.3 / (count - 1)) if count > 1 else 0.0
        titles = [_text(panel.title) or "" for panel in spec.panels]
        if any(titles) and spec.shared_x:
            spacing = max(spacing, min(0.06, 0.3 / (count - 1)) if count > 1 else 0.0)  # room for the names
        fig = make_subplots(rows=count, cols=1, vertical_spacing=spacing, shared_xaxes=spec.shared_x,
                            subplot_titles=titles if any(titles) else None)
        # Each panel is named after its experiment, small and on the left, like a legend.
        fig.update_annotations(font={"size": FONT_SIZE}, x=0, xanchor="left")
        shown: set = set()
        for row, panel in enumerate(spec.panels, start=1):
            _add_panel_traces(fig, panel, row=row, shown=shown)
            xaxis, yaxis = _axis_options(panel)
            if spec.shared_x and row < count:
                xaxis["title"] = {"text": None}  # one x-axis: named under the last panel
            fig.update_xaxes(xaxis, row=row, col=1)
            fig.update_yaxes(yaxis, row=row, col=1)
        fig.update_layout(height=FACET_PANEL_HEIGHT_PX * count + 80, title={"text": _text(spec.title) or ""})
    else:
        panel = spec.panel
        fig = go.Figure()
        _add_panel_traces(fig, panel, row=None)
        xaxis, yaxis = _axis_options(panel)
        fig.update_layout(
            xaxis=xaxis,
            yaxis=yaxis,
            height=SINGLE_HEIGHT_PX,
            title={"text": _text(spec.title or panel.title)},
        )
        if panel.legend_title and not panel.legends:
            fig.update_layout(legend={"title": {"text": _text(panel.legend_title)}})

    fig.update_layout(
        template="plotly_white",
        hovermode="closest",
        margin={"t": 70},
        font={"size": FONT_SIZE},
        title_font={"size": TITLE_FONT_SIZE},
        legend_font={"size": FONT_SIZE - 2},
    )
    return fig
