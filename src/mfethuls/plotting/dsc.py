from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd

from ..dataset import Dataset
from .core import _default_title, _figure_and_axis, _plot_grouped_single_signal, _require_columns
from .style import apply_axes_style


def _is_boundary_profile_label(label: object) -> bool:
    """Return True for profile labels that represent cycle boundaries."""

    text = str(label).casefold()
    return "start" in text or "end" in text


def plot_dsc(
    dataset: Dataset,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    x_column = "temperature_C"
    y_column = "heat_flow_mW"
    resolved_group_by = group_by
    if resolved_group_by is None and "profile" in dataset.data.columns:
        resolved_group_by = "profile"

    if strict:
        _require_columns(dataset, [x_column, y_column], "plot_dsc")

    fig, axis = _figure_and_axis(ax)
    if resolved_group_by:
        df = dataset.data
        for group_value, subset in df.groupby(resolved_group_by, dropna=False, sort=False):
            label_value = "<missing>" if pd.isna(group_value) else str(group_value)
            label = label_value if not _is_boundary_profile_label(label_value) else "_nolegend_"
            axis.plot(subset[x_column], subset[y_column], label=label)

        handles, labels = axis.get_legend_handles_labels()
        if any(label and not label.startswith("_") for label in labels):
            axis.legend(title=resolved_group_by)
    else:
        _plot_grouped_single_signal(
            dataset,
            x_column=x_column,
            y_column=y_column,
            ax=axis,
            group_by=resolved_group_by,
            max_groups=max_groups,
            color="#d62728",
        )
    apply_axes_style(
        axis,
        title=title or _default_title(dataset, "DSC"),
        xlabel=x_column,
        ylabel=y_column,
    )
    return fig, axis
