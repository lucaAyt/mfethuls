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


def plot_ftir(
    dataset: Dataset,
    *,
    signal: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    """Plot FTIR data using canonical columns.

    Expects ``wavenumber_cm_inv`` as x-axis and either ``absorbance_a_u`` or
    ``transmittance_pct`` as signal.
    """

    x_column = "wavenumber_cm_inv"
    if signal is None:
        if "absorbance_a_u" in dataset.data.columns:
            signal = "absorbance_a_u"
        elif "transmittance_pct" in dataset.data.columns:
            signal = "transmittance_pct"

    if signal is None:
        raise PlotError("plot_ftir requires absorbance_a_u or transmittance_pct.")

    if strict:
        _require_columns(dataset, [x_column, signal], "plot_ftir")

    fig, axis = _figure_and_axis(ax)
    _plot_grouped_single_signal(
        dataset,
        x_column=x_column,
        y_column=signal,
        ax=axis,
        group_by=group_by,
        max_groups=max_groups,
        color="#ff7f0e",
    )
    # FTIR is conventionally shown from high to low wavenumber.
    axis.set_xlim(axis.get_xlim()[::-1])
    apply_axes_style(
        axis,
        title=title or _default_title(dataset, "FTIR"),
        xlabel=x_column,
        ylabel=signal,
    )
    return fig, axis
