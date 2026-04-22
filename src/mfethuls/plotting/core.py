from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

import matplotlib.pyplot as plt

from ..dataset import Dataset
from .style import apply_axes_style


class PlotError(ValueError):
    """Raised when a normalized dataset cannot be plotted."""


def _figure_and_axis(ax=None):
    if ax is not None:
        return ax.figure, ax
    fig, new_ax = plt.subplots()
    return fig, new_ax


def _require_columns(dataset: Dataset, required: list[str], plot_name: str) -> None:
    missing = [column for column in required if column not in dataset.data.columns]
    if missing:
        raise PlotError(f"{plot_name} requires canonical columns {required!r}; missing {missing!r}.")


def _default_title(dataset: Dataset, fallback: str) -> str:
    experiment_name = dataset.metadata.get("experiment_name")
    if experiment_name:
        return f"{fallback} - {experiment_name}"
    experiment_id = dataset.experiment_id
    if experiment_id:
        return f"{fallback} - {experiment_id}"
    return fallback


def _line_plot(
    dataset: Dataset,
    x_column: str,
    y_columns: list[str],
    *,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[Any, Any]:
    required = [x_column] + y_columns
    if strict:
        _require_columns(dataset, required, "plot")

    fig, axis = _figure_and_axis(ax)
    x_values = dataset.data[x_column]

    for y_column in y_columns:
        if y_column not in dataset.data.columns:
            if strict:
                raise PlotError(f"plot requires canonical column {y_column!r}.")
            continue
        axis.plot(x_values, dataset.data[y_column], label=y_column)

    apply_axes_style(axis, title=title, xlabel=x_column, ylabel=", ".join(y_columns))
    if len(y_columns) > 1:
        axis.legend()
    return fig, axis


def plot_dataset(
    dataset: Dataset,
    kind: Optional[str] = None,
    *,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    **kwargs: Any,
) -> Tuple[Any, Any]:
    """Plot a normalized dataset using canonical columns only."""

    from .dsc import plot_dsc
    from .ms import plot_ms
    from .nmr import plot_nmr
    from .rheology import plot_rheology
    from .saxs import plot_saxs
    from .sec import plot_sec
    from .tga import plot_tga
    from .uv_vis import plot_uv_vis

    resolved_kind = kind
    if resolved_kind is None:
        columns = set(dataset.data.columns)
        profile = str(dataset.metadata.get("measurement_profile") or "").strip()
        if {"wavelength_nm"}.issubset(columns):
            resolved_kind = "uv_vis"
        elif {"temperature_C", "heat_flow_mW"}.issubset(columns):
            resolved_kind = "dsc"
        elif {"temperature_C", "mass_pct"}.issubset(columns):
            resolved_kind = "tga"
        elif {"q_inv_nm", "intensity_a_u"}.issubset(columns):
            resolved_kind = "saxs"
        elif {"mz", "intensity_a_u"}.issubset(columns):
            resolved_kind = "ms"
        elif {"retention_time_min", "detector_response_a_u"}.issubset(columns):
            resolved_kind = "sec"
        elif {"chemical_shift_ppm", "intensity_a_u"}.issubset(columns):
            resolved_kind = "nmr"
        elif profile:
            resolved_kind = "rheology"

    if resolved_kind == "uv_vis":
        return plot_uv_vis(dataset, ax=ax, title=title, strict=strict, **kwargs)
    if resolved_kind == "dsc":
        return plot_dsc(dataset, ax=ax, title=title, strict=strict)
    if resolved_kind == "ms":
        return plot_ms(dataset, ax=ax, title=title, strict=strict)
    if resolved_kind == "tga":
        return plot_tga(dataset, ax=ax, title=title, strict=strict, **kwargs)
    if resolved_kind == "rheology":
        return plot_rheology(dataset, ax=ax, title=title, strict=strict, **kwargs)
    if resolved_kind == "sec":
        return plot_sec(dataset, ax=ax, title=title, strict=strict, **kwargs)
    if resolved_kind == "saxs":
        return plot_saxs(dataset, ax=ax, title=title, strict=strict)
    if resolved_kind == "nmr":
        return plot_nmr(dataset, ax=ax, title=title, strict=strict)

    raise PlotError(
        "Could not infer a plot kind from the normalized dataset. "
        "Pass kind explicitly or provide canonical columns for a supported family."
    )
