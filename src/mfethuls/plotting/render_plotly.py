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


def _add_panel_traces(fig, panel: Panel, *, row: Optional[int]) -> None:
    import plotly.graph_objects as go

    position = {"row": row, "col": 1} if row is not None else {}

    for trace in panel.traces:
        color = panel.trace_color(trace)
        fig.add_trace(
            go.Scattergl(
                x=trace.x,
                y=trace.y,
                mode=trace.mode,
                name=_text(trace.label) or "",
                line=_line(color, trace.linestyle),
                marker={"size": 5, "color": _color(color)},
                legendgroup=trace.legend_group,
                showlegend=bool(trace.label) and panel.legend and not panel.legends,
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
                    mode="lines",
                    name=_text(entry.label),
                    line=_line(entry.color, entry.linestyle),
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
        fig = make_subplots(rows=count, cols=1, vertical_spacing=spacing)
        for row, panel in enumerate(spec.panels, start=1):
            _add_panel_traces(fig, panel, row=row)
            xaxis, yaxis = _axis_options(panel)
            fig.update_xaxes(xaxis, row=row, col=1)
            fig.update_yaxes(yaxis, row=row, col=1)
        fig.update_layout(height=FACET_PANEL_HEIGHT_PX * count + 80, title={"text": _text(spec.title)})
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
