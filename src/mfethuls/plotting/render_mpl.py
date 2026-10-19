"""Draw a :class:`PlotSpec` with Matplotlib (publication and vector export)."""

from __future__ import annotations

import math
from typing import Any, Tuple

from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.ticker import AutoMinorLocator

from .spec import Colorbar, Panel, PlotSpec
from .style import apply_axes_style, new_figure, publication_style


# Facet figure size in inches: fixed width for inline display, fixed height per panel.
FACET_WIDTH_IN = 7.0
FACET_PANEL_HEIGHT_IN = 2.8

# Legends go right of the axes so they never cover the data. A legend taller than this
# share of the figure height is split into columns (the figure widens instead of the
# axes being squashed).
_LEGEND_HEIGHT_SHARE = 0.9

# Outside legends and colour bars widen the figure until the axes are within this
# many inches of their width without them.
_WIDTH_TOLERANCE_IN = 0.05


def _legend_handle(entry) -> Line2D:
    if entry.marker:
        return Line2D([], [], color=entry.color, linestyle="none", marker=entry.marker)
    return Line2D([], [], color=entry.color, linestyle=entry.linestyle)


def _draw_hand_built_legends(axis, panel: Panel) -> None:
    """All hand-built legends as one legend right of the axes, one titled section each.

    One Matplotlib legend, not one per section: constrained layout and tight bounding
    boxes only account for the axes' own legend, so extra legends would be clipped
    from the figure and from saved files.
    """

    handles, labels, headers = [], [], []
    for idx, spec_legend in enumerate(panel.legends):
        if idx > 0:
            # A blank row, then the section title as a bold row without a handle.
            handles += [Line2D([], [], linestyle="none")] * 2
            labels += ["", spec_legend.title or ""]
            headers.append(len(labels) - 1)
        handles += [_legend_handle(entry) for entry in spec_legend.entries]
        labels += [entry.label for entry in spec_legend.entries]

    legend = axis.legend(
        handles,
        labels,
        title=panel.legends[0].title,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        frameon=False,
        fontsize="small",
        alignment="left",
        ncols=_legend_columns(axis, len(labels), titled=True, fontsize="small"),
    )
    title_size = legend.get_title().get_fontsize()
    texts = legend.get_texts()
    for idx in headers:
        texts[idx].set_fontsize(title_size)


def _legend_columns(axis, entries: int, *, titled: bool, fontsize="medium") -> int:
    """Columns so that a legend of ``entries`` rows fits the figure height."""
    from matplotlib.font_manager import FontProperties

    size_pt = FontProperties(size=fontsize).get_size_in_points()
    row_in = size_pt * 1.5 / 72  # text plus the default label spacing
    rows = max(1, int(axis.figure.get_figheight() * _LEGEND_HEIGHT_SHARE / row_in) - (1 if titled else 0))
    return max(1, math.ceil(entries / rows))


def _draw_legends(axis, panel: Panel) -> None:
    if panel.legends:
        _draw_hand_built_legends(axis, panel)
        return

    labelled = sum(1 for trace in panel.traces if trace.label)
    if panel.legend and labelled:
        axis.legend(title=panel.legend_title, loc="upper left", bbox_to_anchor=(1.02, 1.0), frameon=False,
                    ncols=_legend_columns(axis, labelled, titled=bool(panel.legend_title)))


def _draw_colorbar(axis, colorbar: Colorbar) -> None:
    mappable = ScalarMappable(norm=Normalize(colorbar.vmin, colorbar.vmax), cmap=colorbar.cmap)
    axis.figure.colorbar(mappable, ax=axis, label=colorbar.title)


def draw_panel(axis, panel: Panel, *, colorbar: bool = True) -> None:
    """Draw one panel onto an existing Matplotlib axis.

    Titles are not drawn: publication figures carry their title in the caption
    (``ax.set_title`` adds one). Legends sit right of the axes.
    """

    if panel.xscale == "log":
        axis.set_xscale("log")
    if panel.yscale == "log":
        axis.set_yscale("log")

    for trace in panel.traces:
        if trace.mode == "markers":
            kwargs: dict[str, Any] = {"linestyle": "none", "marker": trace.marker, "markersize": 2}
        else:
            kwargs = {"linestyle": trace.linestyle}
        if trace.label is not None:
            kwargs["label"] = trace.label
        color = panel.trace_color(trace)
        if color is not None:
            kwargs["color"] = color
        axis.plot(trace.x, trace.y, **kwargs)

    if panel.xlim is not None:
        axis.set_xlim(*panel.xlim)
    if panel.ylim is not None:
        axis.set_ylim(*panel.ylim)
    if panel.x_reversed:
        left, right = axis.get_xlim()
        if left < right:
            axis.set_xlim(right, left)

    # One minor tick between major ticks; log axes keep Matplotlib's log minor ticks.
    if panel.xscale == "linear":
        axis.xaxis.set_minor_locator(AutoMinorLocator(2))
    if panel.yscale == "linear":
        axis.yaxis.set_minor_locator(AutoMinorLocator(2))

    apply_axes_style(axis, xlabel=panel.xlabel, ylabel=panel.ylabel)
    _draw_legends(axis, panel)
    if colorbar and panel.colorbar is not None:
        _draw_colorbar(axis, panel.colorbar)


def _axes_width_in(fig, data_axes) -> float:
    fig.draw_without_rendering()
    return min(axis.get_position().width for axis in data_axes) * fig.get_figwidth()


def _add_colorbars_keeping_axes_width(fig, data_axes, panels) -> None:
    """Add colour bars, then widen the figure so outside legends and colour bars don't shrink the axes.

    Constrained layout makes room for them by narrowing the axes. The target is the
    axes width without them (legends hidden, colour bars not yet added); the figure
    then grows until the axes are back to that width.
    """

    legends = [axis.get_legend() for axis in data_axes if axis.get_legend() is not None]

    if not legends and all(panel.colorbar is None for panel in panels):
        return

    for legend in legends:
        legend.set_visible(False)
    target = _axes_width_in(fig, data_axes)
    for legend in legends:
        legend.set_visible(True)
    # Make room for the widest legend first: a legend of several columns can be wider than
    # the axes, and constrained layout gives up (axes collapse) instead of narrowing them.
    if legends:
        renderer = fig.canvas.get_renderer()
        widest = max(legend.get_window_extent(renderer).width for legend in legends) / fig.dpi
        fig.set_figwidth(fig.get_figwidth() + widest)

    for axis, panel in zip(data_axes, panels):
        if panel.colorbar is not None:
            _draw_colorbar(axis, panel.colorbar)

    # A few passes, as text and padding do not scale exactly with the figure width.
    # Each pass is a full layout, so stop within _WIDTH_TOLERANCE_IN of the target.
    for _ in range(4):
        missing = target - _axes_width_in(fig, data_axes)
        if missing < _WIDTH_TOLERANCE_IN:
            break
        fig.set_figwidth(fig.get_figwidth() + missing)


def render(spec: PlotSpec, ax=None) -> Tuple[Any, Any]:
    """Return ``(fig, ax)``, or ``(fig, axes)`` with shape ``(n, 1)`` for a facet."""

    # Drawing onto the caller's axis keeps the caller's style.
    if ax is not None and spec.layout != "facet":
        draw_panel(ax, spec.panel)
        return ax.figure, ax

    # Figures created here use the light publication style, whatever the notebook theme.
    with publication_style():
        if spec.layout == "facet":
            count = len(spec.panels)
            fig, axes = new_figure(
                count,
                1,
                squeeze=False,
                figsize=(FACET_WIDTH_IN, FACET_PANEL_HEIGHT_IN * count),
                layout="constrained",
            )
            for axis, panel in zip(axes.ravel(), spec.panels):
                draw_panel(axis, panel, colorbar=False)
            data_axes, result = list(axes.ravel()), (fig, axes)
        else:
            # Constrained layout so that widening the figure below keeps the axes size.
            fig, axis = new_figure(layout="constrained")
            draw_panel(axis, spec.panel, colorbar=False)
            data_axes, result = [axis], (fig, axis)
        _add_colorbars_keeping_axes_width(fig, data_axes, spec.panels)
    return result
