from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from .core import PlotError, _default_title, _figure_and_axis, _require_columns
from .style import apply_axes_style


def plot_sec(
    dataset: Dataset,
    *,
    detector: Optional[str] = None,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    x_column = "retention_time_min"
    y_column = "detector_response_a_u"
    detector_column = "detector_name"
    required = [x_column, y_column]
    if detector is not None or detector_column in dataset.data.columns:
        required.append(detector_column)
    if strict:
        _require_columns(dataset, required, "plot_sec")

    fig, axis = _figure_and_axis(ax)
    if detector is not None and detector_column in dataset.data.columns:
        subset = dataset.data[dataset.data[detector_column] == detector]
        axis.plot(subset[x_column], subset[y_column], label=detector)
        axis.legend()
    elif detector_column in dataset.data.columns:
        for detector_name, subset in dataset.data.groupby(detector_column):
            axis.plot(subset[x_column], subset[y_column], label=str(detector_name))
        axis.legend()
    else:
        axis.plot(dataset.data[x_column], dataset.data[y_column])

    apply_axes_style(
        axis,
        title=title or _default_title(dataset, "SEC"),
        xlabel=x_column,
        ylabel=y_column,
    )
    return fig, axis
