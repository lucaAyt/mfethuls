"""Backend-neutral description of a plot.

Family builders turn a dataset into a :class:`PlotSpec`; renderers in
``render_mpl`` and ``render_plotly`` draw the same spec with Matplotlib or Plotly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import numpy as np


Scale = Literal["linear", "log"]


class PlotError(ValueError):
    """Raised when a normalized dataset cannot be plotted."""


@dataclass
class Trace:
    """One line. ``color`` and ``linestyle`` use Matplotlib conventions."""

    x: np.ndarray
    y: np.ndarray
    label: Optional[str] = None
    color: Any = None
    linestyle: str = "-"
    mode: Literal["lines", "markers"] = "lines"
    # Position on the panel's colour bar; overrides ``color`` when the panel has one.
    color_value: Optional[float] = None
    # Plotly only: traces sharing a group are toggled together from the legend.
    legend_group: Optional[str] = None


@dataclass
class LegendEntry:
    label: str
    color: Any = None
    linestyle: str = "-"
    # Plotly only: clicking the entry toggles the traces with this legend_group.
    group: Optional[str] = None


@dataclass
class Legend:
    """A hand-built legend, used instead of one entry per trace."""

    title: Optional[str]
    entries: list[LegendEntry]


@dataclass
class Colorbar:
    """Continuous colour scale for traces that carry a ``color_value``."""

    title: Optional[str]
    vmin: float
    vmax: float
    cmap: str = "viridis"

    def color(self, value: float):
        """RGBA colour for ``value`` on this scale."""
        from matplotlib import colormaps

        span = self.vmax - self.vmin
        position = 0.5 if span == 0 else (value - self.vmin) / span
        return colormaps[self.cmap](position)


@dataclass
class Panel:
    traces: list[Trace] = field(default_factory=list)
    title: Optional[str] = None
    xlabel: Optional[str] = None
    ylabel: Optional[str] = None
    xscale: Scale = "linear"
    yscale: Scale = "linear"
    x_reversed: bool = False
    # Fixed axis limits as (low, high) in data units; None lets the backend choose.
    # A reversed x-axis still runs from high to low.
    xlim: Optional[tuple[float, float]] = None
    ylim: Optional[tuple[float, float]] = None
    # Show one legend entry per labelled trace.
    legend: bool = False
    legend_title: Optional[str] = None
    # Hand-built legends; when set they replace the per-trace legend.
    legends: list[Legend] = field(default_factory=list)
    colorbar: Optional[Colorbar] = None

    def trace_color(self, trace: Trace):
        """Colour to draw ``trace`` with: its colour-bar position if set, else ``trace.color``."""
        if self.colorbar is not None and trace.color_value is not None:
            return self.colorbar.color(trace.color_value)
        return trace.color


@dataclass
class PlotSpec:
    """One panel for a single plot or overlay, one panel per dataset for a facet."""

    panels: list[Panel]
    layout: Literal["single", "facet"] = "single"
    title: Optional[str] = None
    # Matplotlib only: use a constrained layout (room for legends outside the axes).
    constrained: bool = False

    @property
    def panel(self) -> Panel:
        return self.panels[0]
