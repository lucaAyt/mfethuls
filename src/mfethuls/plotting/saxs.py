from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from .core import _default_title, _figure_and_axis, _plot_grouped_single_signal, _require_columns
from .style import apply_axes_style


def plot_saxs(
    dataset: Dataset,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    x_column = "q_inv_nm"
    y_column = "intensity_a_u"
    if strict:
        _require_columns(dataset, [x_column, y_column], "plot_saxs")

    fig, axis = _figure_and_axis(ax)
    _plot_grouped_single_signal(
        dataset,
        x_column=x_column,
        y_column=y_column,
        ax=axis,
        group_by=group_by,
        max_groups=max_groups,
        color="#9467bd",
    )
    apply_axes_style(
        axis,
        title=title or _default_title(dataset, "SAXS"),
        xlabel=x_column,
        ylabel=y_column,
    )
    return fig, axis
