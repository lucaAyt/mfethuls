from __future__ import annotations

from typing import Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..dataset import Dataset
from .backend import Backend, render
from .core import _default_title, _grouped_single_signal_traces, _require_columns, _values
from .labels import axis_label, legend_name
from .spec import Legend, LegendEntry, Panel, PlotSpec, Trace


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


def dsc_overlay_legends(segment_colors: dict, experiment_labels: Sequence[str]) -> list[Legend]:
    """Two short legends for a DSC overlay: colour shows the segment, line style the experiment."""

    segments = Legend(
        title="Segment",
        entries=[LegendEntry(segment, color=color) for segment, color in segment_colors.items()],
    )
    return [segments, experiment_legend(experiment_labels)]


def experiment_linestyle(index: int) -> str:
    return DSC_EXPERIMENT_LINESTYLES[index % len(DSC_EXPERIMENT_LINESTYLES)]


def experiment_legend(experiment_labels: Sequence[str]) -> Legend:
    """Legend with one line style per experiment, for overlays where colour encodes something else."""

    return Legend(
        title="Experiment",
        entries=[
            LegendEntry(label, color="black", linestyle=experiment_linestyle(idx), group=experiment_legend_group(idx))
            for idx, label in enumerate(experiment_labels)
        ],
    )


def experiment_legend_group(index: int) -> str:
    return f"experiment:{index}"


def build_dsc_spec(
    dataset: Dataset,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
    linestyle: str = "-",
) -> PlotSpec:
    x_column = "temperature_C"
    y_column = "heat_flow_mW"
    resolved_group_by = group_by
    if resolved_group_by is None and "profile" in dataset.data.columns:
        resolved_group_by = "profile"

    if strict:
        _require_columns(dataset, [x_column, y_column], "plot_dsc")

    legend_title: Optional[str] = None
    colorbar = None
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
        traces = [
            Trace(
                _values(subset[x_column]),
                _values(subset[y_column]),
                label=label_value,
                color=colors.get(label_value),
                linestyle=linestyle,
            )
            for label_value, subset in groups
        ]
        legend_title = resolved_group_by
    else:
        traces, legend_title, colorbar = _grouped_single_signal_traces(
            dataset,
            x_column=x_column,
            y_column=y_column,
            group_by=resolved_group_by,
            max_groups=max_groups,
            color="#d62728",
        )
        for trace in traces:
            trace.linestyle = linestyle

    panel = Panel(
        traces=traces,
        title=title or _default_title(dataset, "DSC"),
        xlabel=axis_label(x_column),
        ylabel=axis_label(y_column),
        legend=legend_title is not None and colorbar is None,
        legend_title=legend_name(legend_title),
        colorbar=colorbar,
    )
    return PlotSpec([panel])


def plot_dsc(
    dataset: Dataset,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    linestyle: str = "-",
    backend: Optional[Backend] = None,
):
    spec = build_dsc_spec(
        dataset,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
        linestyle=linestyle,
    )
    return render(spec, backend=backend, ax=ax)
