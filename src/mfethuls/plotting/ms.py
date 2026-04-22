from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from .core import _default_title, _figure_and_axis, _require_columns
from .style import apply_axes_style


def plot_ms(
    dataset: Dataset,
    *,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    x_column = "mz"
    y_column = "intensity_a_u"
    if strict:
        _require_columns(dataset, [x_column, y_column], "plot_ms")

    fig, axis = _figure_and_axis(ax)
    axis.plot(dataset.data[x_column], dataset.data[y_column], color="#17becf")
    apply_axes_style(
        axis,
        title=title or _default_title(dataset, "MS"),
        xlabel=x_column,
        ylabel=y_column,
    )
    return fig, axis