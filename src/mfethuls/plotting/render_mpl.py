"""Draw a :class:`PlotSpec` with Matplotlib (publication and vector export)."""

from __future__ import annotations

from typing import Any, Tuple

from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.ticker import AutoMinorLocator

from .spec import Colorbar, Panel, PlotSpec
from .style import apply_axes_style, new_figure, publication_style


# Facet figure size in inches: fixed width for inline display, fixed height per panel.
FACET_WIDTH_IN = 7.0
FACET_PANEL_HEIGHT_IN = 2.8

# Legends with more entries than this, and all facet legends, go right of the axes
# so they don't cover the data.
_MAX_INSIDE_LEGEND_ENTRIES = 4

# Vertical gap, in axes fractions, between hand-built legends stacked right of the axes.
_LEGEND_GAP = 0.05

# Outside legends and colour bars widen the figure until the axes are within this
# many inches of their width without them.
_WIDTH_TOLERANCE_IN = 0.05


def _stack_legends(axis) -> None:
    """Place each hand-built legend just below the previous one, right of the axes."""

    legends = [artist for artist in axis.artists if isinstance(artist, Legend)] + [axis.get_legend()]
    if len(legends) < 2:
        return

    figure = axis.figure
    figure.draw_without_rendering()
    renderer = figure.canvas.get_renderer()
    to_axes = axis.transAxes.inverted()
    for previous, legend in zip(legends, legends[1:]):
        bottom = to_axes.transform(previous.get_window_extent(renderer).p0)[1]
        legend.set_bbox_to_anchor((1.02, bottom - _LEGEND_GAP), transform=axis.transAxes)


def _draw_legends(axis, panel: Panel, *, outside: bool) -> None:
    if panel.legends:
        legend_kwargs = {"loc": "upper left", "frameon": False, "fontsize": "small"}
        for idx, spec_legend in enumerate(panel.legends):
            handles = [
                Line2D([], [], color=entry.color, linestyle=entry.linestyle, label=entry.label)
                for entry in spec_legend.entries
            ]
            legend = axis.legend(
                handles=handles,
                title=spec_legend.title,
                bbox_to_anchor=(1.02, 1.0),
                **legend_kwargs,
            )
            # A later axis.legend() call replaces the current one, so keep earlier ones as artists.
            if idx < len(panel.legends) - 1:
                axis.add_artist(legend)
        _stack_legends(axis)
        return

    labelled = sum(1 for trace in panel.traces if trace.label)
    if panel.legend and labelled:
        if outside or labelled > _MAX_INSIDE_LEGEND_ENTRIES:
            axis.legend(title=panel.legend_title, loc="upper left", bbox_to_anchor=(1.02, 1.0), frameon=False)
        else:
            axis.legend(title=panel.legend_title)


def _draw_colorbar(axis, colorbar: Colorbar) -> None:
    mappable = ScalarMappable(norm=Normalize(colorbar.vmin, colorbar.vmax), cmap=colorbar.cmap)
    axis.figure.colorbar(mappable, ax=axis, label=colorbar.title)


def draw_panel(axis, panel: Panel, *, legend_outside: bool = False, colorbar: bool = True) -> None:
    """Draw one panel onto an existing Matplotlib axis."""

    if panel.xscale == "log":
        axis.set_xscale("log")
    if panel.yscale == "log":
        axis.set_yscale("log")

    for trace in panel.traces:
        if trace.mode == "markers":
            kwargs: dict[str, Any] = {"linestyle": "none", "marker": "o", "markersize": 2}
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

    apply_axes_style(axis, title=panel.title, xlabel=panel.xlabel, ylabel=panel.ylabel)
    _draw_legends(axis, panel, outside=legend_outside)
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

    legends = []
    for axis in data_axes:
        legends += [artist for artist in axis.artists if isinstance(artist, Legend)]
        if axis.get_legend() is not None:
            legends.append(axis.get_legend())

    if not legends and all(panel.colorbar is None for panel in panels):
        return

    for legend in legends:
        legend.set_visible(False)
    target = _axes_width_in(fig, data_axes)
    for legend in legends:
        legend.set_visible(True)

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
                draw_panel(axis, panel, legend_outside=True, colorbar=False)
            if spec.title:
                fig.suptitle(spec.title)
            data_axes, result = list(axes.ravel()), (fig, axes)
        else:
            # Constrained layout so that widening the figure below keeps the axes size.
            fig, axis = new_figure(layout="constrained")
            draw_panel(axis, spec.panel, colorbar=False)
            data_axes, result = [axis], (fig, axis)
        _add_colorbars_keeping_axes_width(fig, data_axes, spec.panels)
    return result
