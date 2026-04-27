from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from .core import (
    PlotError,
    _default_title,
    _figure_and_axis,
    _plot_grouped_single_signal,
    _require_columns,
)
from .style import apply_axes_style


def plot_tga(
    dataset: Dataset,
    *,
    signal: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
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
    _plot_grouped_single_signal(
        dataset,
        x_column=x_column,
        y_column=signal,
        ax=axis,
        group_by=group_by,
        max_groups=max_groups,
        color="#2ca02c",
    )
    apply_axes_style(
        axis,
        title=title or _default_title(dataset, "TGA"),
        xlabel=x_column,
        ylabel=signal,
    )
    return fig, axis
