"""A heatmap of a series: one row per value of a column (e.g. time_s), the x column across, colour = a value.

For in-situ runs (hundreds or thousands of spectra over time) a heatmap shows every spectrum at
once, as one image the browser draws quickly. Rows or x values beyond what an image can show
(:data:`MAX_ROWS`, :data:`MAX_COLUMNS`) are combined into equal bins and averaged, and the note
says so; within the limits every value is its own cell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from .labels import axis_label

MAX_ROWS = 600
MAX_COLUMNS = 1200


@dataclass
class HeatmapGrid:
    """Cells of one heatmap: ``z[row, column]`` (NaN where there is no data), with the row and column positions."""

    z: np.ndarray
    x: np.ndarray
    rows: np.ndarray
    xlabel: str
    rowlabel: str
    valuelabel: str
    title: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def _cells(values: np.ndarray, limit: int) -> Tuple[np.ndarray, np.ndarray, bool]:
    """Each value's cell index, the cells' positions, and whether values were binned (more than ``limit``)."""
    distinct = np.unique(values)
    if len(distinct) <= limit:
        return np.searchsorted(distinct, values), distinct, False
    edges = np.linspace(distinct[0], distinct[-1], limit + 1)
    index = np.clip(np.searchsorted(edges, values, side="right") - 1, 0, limit - 1)
    return index, (edges[:-1] + edges[1:]) / 2, True


def heatmap_grid(df: pd.DataFrame, *, x: str, value: str, rows: str, title: Optional[str] = None,
                 max_rows: int = MAX_ROWS, max_columns: int = MAX_COLUMNS) -> HeatmapGrid:
    """The heatmap of ``value`` over ``x`` (across) and ``rows`` (down), each cell the mean of its values."""
    frame = pd.DataFrame({
        "x": pd.to_numeric(df[x], errors="coerce"),
        "row": pd.to_numeric(df[rows], errors="coerce"),
        "z": pd.to_numeric(df[value], errors="coerce"),
    }).dropna()
    if frame.empty:
        raise ValueError(f"No rows with numbers in {x}, {rows} and {value}.")
    row_index, row_positions, rows_binned = _cells(frame["row"].to_numpy(), max_rows)
    x_index, x_positions, x_binned = _cells(frame["x"].to_numpy(), max_columns)
    flat = row_index * len(x_positions) + x_index
    size = len(row_positions) * len(x_positions)
    sums = np.bincount(flat, weights=frame["z"].to_numpy(), minlength=size)
    counts = np.bincount(flat, minlength=size)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan).reshape(len(row_positions), len(x_positions))
    notes = []
    if rows_binned:
        notes.append(f"{frame['row'].nunique():,} {axis_label(rows)} values in {len(row_positions)} rows: each row "
                     "is the mean of the values in its range.")
    if x_binned:
        notes.append(f"{frame['x'].nunique():,} {axis_label(x)} values in {len(x_positions)} columns: each the mean "
                     "of the values in its range.")
    return HeatmapGrid(z=z, x=x_positions, rows=row_positions, xlabel=axis_label(x), rowlabel=axis_label(rows),
                       valuelabel=axis_label(value), title=title, notes=notes)


def _plotly_scale(cmap: str, steps: int = 11) -> list:
    from matplotlib import colormaps

    colormap = colormaps[cmap]
    return [[i / (steps - 1), "rgb({:.0f},{:.0f},{:.0f})".format(*(255 * np.array(colormap(i / (steps - 1))[:3])))]
            for i in range(steps)]


def plotly_heatmaps(grids: List[HeatmapGrid], *, cmap: str = "viridis", invert_x: bool = False):
    """One Plotly heatmap per grid, stacked (one per experiment), sharing the x-axis and the colour scale."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    low = np.nanmin([np.nanmin(g.z) for g in grids])
    high = np.nanmax([np.nanmax(g.z) for g in grids])
    fig = make_subplots(rows=len(grids), cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=[g.title or "" for g in grids] if len(grids) > 1 else None)
    for row, grid in enumerate(grids, start=1):
        # 32-bit values: plenty for a colour, half the bytes sent to the browser.
        fig.add_trace(go.Heatmap(z=grid.z.astype(np.float32), x=grid.x, y=grid.rows, colorscale=_plotly_scale(cmap), zmin=low, zmax=high,
                                 showscale=row == 1, colorbar={"title": {"text": grid.valuelabel}},
                                 hovertemplate=f"{grid.xlabel}: %{{x}}<br>{grid.rowlabel}: %{{y}}<br>"
                                               f"{grid.valuelabel}: %{{z}}<extra></extra>"),
                      row=row, col=1)
        fig.update_yaxes(title_text=grid.rowlabel, row=row, col=1)
    fig.update_xaxes(title_text=grids[-1].xlabel, row=len(grids), col=1)
    if invert_x:
        fig.update_xaxes(autorange="reversed")
    fig.update_layout(height=max(420, 320 * len(grids)), title=grids[0].title if len(grids) == 1 else None)
    return fig


def matplotlib_heatmaps(grids: List[HeatmapGrid], *, cmap: str = "viridis", invert_x: bool = False):
    """The same heatmaps drawn with Matplotlib (the vector SVG for publication)."""
    import matplotlib.pyplot as plt

    from .style import publication_style

    low = np.nanmin([np.nanmin(g.z) for g in grids])
    high = np.nanmax([np.nanmax(g.z) for g in grids])
    with publication_style():
        fig, axes = plt.subplots(len(grids), 1, figsize=(7, 3.2 * len(grids)), sharex=True, squeeze=False)
        for ax, grid in zip(axes[:, 0], grids):
            mesh = ax.pcolormesh(grid.x, grid.rows, grid.z, cmap=cmap, vmin=low, vmax=high, shading="nearest",
                                 rasterized=True)
            ax.set_ylabel(grid.rowlabel)
            if grid.title and len(grids) > 1:
                ax.set_title(grid.title)
        axes[-1, 0].set_xlabel(grids[-1].xlabel)
        if invert_x:
            axes[-1, 0].invert_xaxis()
        fig.colorbar(mesh, ax=axes[:, 0].tolist(), label=grids[0].valuelabel)
    return fig
