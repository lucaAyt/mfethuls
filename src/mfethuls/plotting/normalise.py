"""Display-only normalisation: scale each experiment's curves so they can be compared by shape.

The stored data is never changed; only what is drawn. An experiment is normalised as a
whole (all its curves with one factor), so a DSC run's heating and cooling segments keep
their sizes relative to each other.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

import numpy as np

from .spec import Trace

# The methods, as the app names them.
NORMALISE_METHODS = {
    "max": "Max = 1",
    "minmax": "0 to 1",
    "area": "Area = 1",
}

_trapezoid = getattr(np, "trapezoid", None) or np.trapz  # numpy < 2 has only trapz

# 0 to 1 puts each lowest value at 0, which a log axis can't show.
LOG_MINMAX_NOTE = ("0 to 1 puts each experiment's lowest value at 0, which a log y-axis can't show: "
                   "those points are left out. Max = 1 keeps them.")


def normalisation(xs: Sequence, ys: Sequence, method: str,
                  x_range: Optional[tuple[Optional[float], Optional[float]]] = None) -> Optional[tuple[float, float]]:
    """``(shift, factor)`` that normalise the curves ``(xs[i], ys[i])`` together: ``(y - shift) * factor``.

    With ``x_range`` (``(low, high)``, either may be None) only the points inside it set the
    factors, e.g. one peak picked with the axis limits; the factors apply to every point.

    - ``"max"``: the largest absolute value becomes 1 (a negative peak becomes -1).
    - ``"minmax"``: the lowest value becomes 0 and the highest 1.
    - ``"area"``: the area under the curves becomes 1. Each curve's area is its net integral
      over x (parts below zero count against parts above), made positive; the curves' areas are summed.

    None when it cannot be done: no finite values, a flat curve, or no area.
    """
    if method not in NORMALISE_METHODS:
        raise ValueError(f"Unknown normalisation {method!r}; use one of {', '.join(NORMALISE_METHODS)}.")
    xs = [np.asarray(x, dtype=float) for x in xs]
    values = [np.asarray(y, dtype=float) for y in ys]
    if x_range is not None:
        low, high = x_range
        inside = [np.isfinite(x) & (x >= (-np.inf if low is None else low)) & (x <= (np.inf if high is None else high))
                  for x in xs]
        xs = [x[keep] for x, keep in zip(xs, inside)]
        values = [y[keep] for y, keep in zip(values, inside)]
    finite = np.concatenate([v[np.isfinite(v)] for v in values]) if values else np.array([])
    if not finite.size:
        return None
    if method == "max":
        peak = float(np.abs(finite).max())
        return (0.0, 1.0 / peak) if peak > 0 else None
    if method == "minmax":
        low, high = float(finite.min()), float(finite.max())
        return (low, 1.0 / (high - low)) if high > low else None
    area = 0.0
    for x, y in zip(xs, values):
        keep = np.isfinite(x) & np.isfinite(y)
        if keep.sum() > 1:
            order = np.argsort(x[keep], kind="stable")
            area += abs(float(_trapezoid(y[keep][order], x[keep][order])))
    return (0.0, 1.0 / area) if area > 0 else None


def normalise_traces(traces: Sequence[Trace], method: str,
                     x_range: Optional[tuple[Optional[float], Optional[float]]] = None) -> bool:
    """Normalise ``traces`` together, in place (one experiment's curves), over ``x_range`` if given;
    False if left unchanged."""
    found = normalisation([t.x for t in traces], [t.y for t in traces], method, x_range)
    if found is None:
        return False
    shift, factor = found
    for trace in traces:
        trace.y = (np.asarray(trace.y, dtype=float) - shift) * factor
    return True


def window_text(x_range: tuple[Optional[float], Optional[float]]) -> str:
    """``x_range`` in words: "50 to 150", "from 50", "up to 150"."""
    low, high = x_range
    if low is not None and high is not None:
        return f"{low:g} to {high:g}"
    return f"from {low:g}" if low is not None else f"up to {high:g}"


def normalised_label(label: Optional[str]) -> str:
    """The y-axis label of normalised curves: their unit goes, they have none any more.

    ``"Heat flow (mW)"`` becomes ``"Heat flow (normalised)"``.
    """
    name = re.sub(r"\s*\([^()]*\)\s*$", "", label or "").strip()
    return f"{name} (normalised)" if name else "Normalised"
