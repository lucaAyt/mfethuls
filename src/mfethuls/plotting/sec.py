from __future__ import annotations

import logging
from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import PlotError, _default_title, _require_columns, _values
from .labels import axis_label, legend_name
from .spec import Panel, PlotSpec, Trace


LOGGER = logging.getLogger(__name__)


def build_sec_spec(
    dataset: Dataset,
    *,
    detector: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
) -> PlotSpec:
    x_column = "retention_time_min"
    y_column = "detector_response_a_u"
    detector_column = "detector_name"
    required = [x_column, y_column]
    if detector is not None or detector_column in dataset.data.columns:
        required.append(detector_column)
    if strict:
        _require_columns(dataset, required, "plot_sec")

    df = dataset.data
    traces: list[Trace] = []
    legend_title: Optional[str] = None
    if group_by is not None:
        if group_by not in df.columns:
            raise PlotError(f"group_by column {group_by!r} is not present in dataset.")
        group_count = int(df[group_by].nunique(dropna=False))
        if group_count > max_groups:
            LOGGER.warning(
                "Skipping grouped SEC plot: grouper %r has %d groups, exceeding max_groups=%d. "
                "Pass a lower-cardinality group_by or increase max_groups.",
                group_by,
                group_count,
                max_groups,
            )
        else:
            for group_value, subset in df.groupby(group_by, dropna=False, sort=False):
                label_value = "<missing>" if group_value is None else str(group_value)
                traces.append(Trace(_values(subset[x_column]), _values(subset[y_column]), label=label_value))
            legend_title = group_by
    elif detector is not None and detector_column in df.columns:
        subset = df[df[detector_column] == detector]
        traces.append(Trace(_values(subset[x_column]), _values(subset[y_column]), label=detector))
    elif detector_column in df.columns:
        for detector_name, subset in df.groupby(detector_column):
            traces.append(Trace(_values(subset[x_column]), _values(subset[y_column]), label=str(detector_name)))
    else:
        traces.append(Trace(_values(df[x_column]), _values(df[y_column])))

    panel = Panel(
        traces=traces,
        title=title or _default_title(dataset, "SEC"),
        xlabel=axis_label(x_column),
        ylabel=axis_label(y_column),
        legend=True,
        legend_title=legend_name(legend_title),
    )
    return PlotSpec([panel])


def plot_sec(
    dataset: Dataset,
    *,
    detector: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    backend: Optional[Backend] = None,
):
    spec = build_sec_spec(
        dataset,
        detector=detector,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
