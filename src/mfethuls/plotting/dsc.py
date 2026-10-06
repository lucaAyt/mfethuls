from __future__ import annotations

from typing import Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from ..dataset import Dataset
from .core import _default_title, _figure_and_axis, _plot_grouped_single_signal, _require_columns
from .style import apply_axes_style


# Colour map and shade range per segment type. Later cycles get darker shades:
# heating runs orange -> red, cooling light -> dark blue, isothermal grey -> black.
_SEGMENT_CMAPS = {
    "heating": ("OrRd", 0.45, 0.95),
    "cooling": ("Blues", 0.45, 0.95),
    "isothermal": ("Greys", 0.55, 0.95),
}

# One line style per experiment when several DSC experiments share an axis.
DSC_EXPERIMENT_LINESTYLES = ["-", "--", ":", "-."]


def _is_boundary_profile_label(label: object) -> bool:
    """Return True for profile labels that represent cycle boundaries."""

    text = str(label).casefold()
    return "start" in text or "end" in text


def _segment_type(label: str) -> Optional[str]:
    text = label.casefold()
    for segment_type in _SEGMENT_CMAPS:
        if text.startswith(segment_type):
            return segment_type
    return None


def dsc_segment_colors(labels: Sequence[str]) -> dict:
    """Map profile labels to colours, shading each segment type by cycle order.

    ``labels`` must be in measurement order (``Heating_0`` before ``Heating_1``).
    Labels that are not heating, cooling or isothermal get no colour, so
    Matplotlib's default colour cycle applies.
    """

    by_type: dict[str, list[str]] = {}
    for label in labels:
        segment_type = _segment_type(label)
        if segment_type and label not in by_type.setdefault(segment_type, []):
            by_type[segment_type].append(label)

    colors = {}
    for segment_type, type_labels in by_type.items():
        cmap_name, low, high = _SEGMENT_CMAPS[segment_type]
        cmap = plt.get_cmap(cmap_name)
        shades = [high] if len(type_labels) == 1 else np.linspace(low, high, len(type_labels))
        colors.update({label: cmap(shade) for label, shade in zip(type_labels, shades)})
    return colors


def add_dsc_overlay_legend(axis, experiment_labels: Sequence[str]) -> None:
    """Replace the per-line legend of a DSC overlay with two short legends.

    Lines on the axis are labelled ``"<experiment> | <segment>"`` by the comparison
    overlay. Colour shows the segment and line style shows the experiment, so one
    entry per segment and one per experiment is enough.
    """

    segment_colors: dict[str, object] = {}
    for line in axis.lines:
        label = str(line.get_label())
        if " | " in label:
            segment_colors.setdefault(label.split(" | ", 1)[1], line.get_color())

    segment_handles = [
        Line2D([], [], color=color, label=segment) for segment, color in segment_colors.items()
    ]
    experiment_handles = [
        Line2D(
            [],
            [],
            color="black",
            linestyle=DSC_EXPERIMENT_LINESTYLES[idx % len(DSC_EXPERIMENT_LINESTYLES)],
            label=label,
        )
        for idx, label in enumerate(experiment_labels)
    ]

    legend_kwargs = {"loc": "upper left", "frameon": False, "fontsize": "small"}
    segments = axis.legend(
        handles=segment_handles, title="Segment", bbox_to_anchor=(1.02, 1.0), **legend_kwargs
    )
    axis.add_artist(segments)
    axis.legend(
        handles=experiment_handles,
        title="Experiment",
        bbox_to_anchor=(1.02, 0.35),
        **legend_kwargs,
    )


def plot_dsc(
    dataset: Dataset,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    linestyle: str = "-",
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
        # Start/end groups are single transition points from across the whole run;
        # drawing them as lines connects distant points, so leave them out.
        groups = []
        for group_value, subset in df.groupby(resolved_group_by, dropna=False, sort=False):
            label = "<missing>" if pd.isna(group_value) else str(group_value)
            if not _is_boundary_profile_label(label):
                groups.append((label, subset))
        colors = dsc_segment_colors([label for label, _ in groups]) if resolved_group_by == "profile" else {}
        for label_value, subset in groups:
            axis.plot(
                subset[x_column],
                subset[y_column],
                label=label_value,
                color=colors.get(label_value),
                linestyle=linestyle,
            )

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
