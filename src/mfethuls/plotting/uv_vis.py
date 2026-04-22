from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from .core import PlotError, _default_title, _figure_and_axis, _require_columns
from .style import apply_axes_style


def plot_uv_vis(
    dataset: Dataset,
    *,
    signal: Optional[str] = None,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    x_column = "wavelength_nm"
    if signal is None:
        if "absorbance_a_u" in dataset.data.columns:
            signal = "absorbance_a_u"
        elif "transmittance_pct" in dataset.data.columns:
            signal = "transmittance_pct"

    if signal is None:
        raise PlotError("plot_uv_vis requires absorbance_a_u or transmittance_pct.")

    if strict:
        _require_columns(dataset, [x_column, signal], "plot_uv_vis")

    fig, axis = _figure_and_axis(ax)
    axis.plot(dataset.data[x_column], dataset.data[signal], color="#1f77b4")
    apply_axes_style(
        axis,
        title=title or _default_title(dataset, "UV/Vis"),
        xlabel=x_column,
        ylabel=signal,
    )
    return fig, axis
