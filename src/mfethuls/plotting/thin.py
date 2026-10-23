"""Figures the screen can show: fewer lines of a long series, fewer points on very long lines.

A plot about 1,000 pixels wide cannot show 1.5 million points: sending them all to the browser
makes the app slow and the tab use gigabytes. For display only:

- a series with many lines (an in-situ run of 1,500 spectra) shows :data:`MAX_SERIES_LINES` of them,
  spread evenly over its colour values (time), see :func:`spread_values`;
- a figure with more than :data:`MAX_POINTS` points keeps, on each line, the first and last point
  and the lowest and highest point of each short stretch (:func:`minmax_indices`): peaks, dips and
  edges stay where they are, only points the screen would draw on top of each other go.

Exports (SVG, CSV) and the stored data keep every point.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Tuple

import numpy as np
import pandas as pd

from .spec import PlotSpec

# A figure with more points than this is thinned for the screen.
MAX_POINTS = 300_000
# A series with more lines than this (spectra over time) shows this many, spread over its values.
MAX_SERIES_LINES = 100
# Lines up to this long are never thinned: it would save little and coarsen them visibly.
_MIN_POINTS_PER_LINE = 2_000


def spread_values(values, count: int = MAX_SERIES_LINES) -> np.ndarray:
    """``count`` of the distinct values in ``values``, evenly spread from the lowest to the highest
    (both included); all of them, sorted, when there are no more than ``count``."""
    series = pd.Series(values).dropna()
    distinct = np.sort(series.unique())
    if len(distinct) <= count:
        return distinct
    positions = np.unique(np.round(np.linspace(0, len(distinct) - 1, count)).astype(int))
    return distinct[positions]


def minmax_indices(y, target: int) -> np.ndarray:
    """Indices of about ``target`` points of ``y`` that keep its shape, in order.

    ``y`` is cut into ``target // 2`` stretches of equal length; each keeps its lowest and its
    highest point, and the first and last points are always kept. Missing values are never
    chosen as a stretch's extreme.
    """
    values = np.asarray(y, dtype=float)
    count = len(values)
    if count <= target:
        return np.arange(count)
    stretches = max(target // 2, 1)
    size = -(-count // stretches)  # ceiling division
    padded = np.full(stretches * size, np.nan)
    padded[:count] = values
    rows = padded.reshape(stretches, size)
    low = np.where(np.isnan(rows), np.inf, rows).argmin(axis=1)
    high = np.where(np.isnan(rows), -np.inf, rows).argmax(axis=1)
    starts = np.arange(stretches) * size
    chosen = np.concatenate([starts + low, starts + high, [0, count - 1]])
    return np.unique(chosen[chosen < count])


def point_count(spec: PlotSpec) -> int:
    return sum(len(trace.x) for panel in spec.panels for trace in panel.traces)


def thin_spec(spec: PlotSpec, max_points: int = MAX_POINTS) -> Tuple[PlotSpec, int, int]:
    """``spec`` with at most about ``max_points`` points, for the screen; and the points shown and in all.

    Each line keeps a share of ``max_points`` in proportion to its length, chosen by
    :func:`minmax_indices`; lines of up to 2,000 points stay whole. A spec within the limit is
    returned as it is.
    """
    total = point_count(spec)
    if total <= max_points:
        return spec, total, total
    panels = []
    for panel in spec.panels:
        traces = []
        for trace in panel.traces:
            target = max(int(max_points * len(trace.x) / total), _MIN_POINTS_PER_LINE)
            keep = minmax_indices(trace.y, target)
            traces.append(trace if len(keep) == len(trace.x) else
                          replace(trace, x=np.asarray(trace.x)[keep], y=np.asarray(trace.y)[keep]))
        panels.append(replace(panel, traces=traces))
    thinned = replace(spec, panels=panels)
    return thinned, point_count(thinned), total


def thinned_note(shown: int, total: int) -> str:
    """The caption for a thinned figure."""
    return (f"Showing {shown:,} of {total:,} points on screen: the lowest and highest of each short stretch "
            "of every line, so peaks and edges stay. Exports keep every point.")
