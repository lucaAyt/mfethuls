from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from .core import PlotError, _default_title, _figure_and_axis, _require_columns
from .style import apply_axes_style


def plot_tga(
    dataset: Dataset,
    *,
    signal: Optional[str] = None,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    x_column = "temperature_C"
    if signal is None:
        signal = "mass_pct" if "mass_pct" in dataset.data.columns else "d_mass_dt_pct_min"

    if signal not in dataset.data.columns:
        raise PlotError("plot_tga requires mass_pct or d_mass_dt_pct_min.")

    if strict:
        _require_columns(dataset, [x_column, signal], "plot_tga")

    fig, axis = _figure_and_axis(ax)
    axis.plot(dataset.data[x_column], dataset.data[signal], color="#2ca02c")
    apply_axes_style(
        axis,
        title=title or _default_title(dataset, "TGA"),
        xlabel=x_column,
        ylabel=signal,
    )
    return fig, axis
