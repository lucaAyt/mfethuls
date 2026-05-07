from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

import matplotlib.pyplot as plt

from ..dataset import Dataset
from .style import apply_axes_style


LOGGER = logging.getLogger(__name__)


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


def _duplicate_row_count(df, key_columns: list[str]) -> int:
    """Count rows participating in duplicates for the given key columns."""

    if not key_columns:
        return 0
    return int(df.duplicated(subset=key_columns, keep=False).sum())


def _resolve_grouping_column(
    dataset: Dataset,
    *,
    key_columns: list[str],
    exclude_columns: list[str],
    group_by: Optional[str],
    max_groups: int,
) -> Optional[str]:
    """Resolve grouping column from explicit choice or data-driven inference."""

    if max_groups < 2:
        raise PlotError("max_groups must be at least 2.")

    df = dataset.data
    if group_by is not None:
        if group_by not in df.columns:
            raise PlotError(f"group_by column {group_by!r} is not present in dataset.")
        return group_by

    baseline_duplicates = _duplicate_row_count(df, key_columns)
    if baseline_duplicates == 0:
        return None

    excluded = set(exclude_columns) | set(key_columns)
    candidates: list[str] = []
    for column in df.columns:
        if column in excluded:
            continue
        series = df[column]
        non_null_ratio = float(series.notna().mean())
        if non_null_ratio < 0.8:
            continue
        cardinality = int(series.nunique(dropna=True))
        if cardinality < 2:
            continue
        candidates.append(column)

    if not candidates:
        return None

    best_column: Optional[str] = None
    best_score = -1.0
    tied_best_columns: list[str] = []
    for column in candidates:
        grouped_duplicates = 0
        for _, subset in df.groupby(column, dropna=False, sort=False):
            grouped_duplicates += _duplicate_row_count(subset, key_columns)

        score = 1.0 - (grouped_duplicates / max(baseline_duplicates, 1))
        if score > best_score:
            best_score = score
            best_column = column
            tied_best_columns = [column]
        elif score == best_score and best_column is not None:
            tied_best_columns.append(column)

    if best_column is None or best_score <= 0:
        return None

    if len(tied_best_columns) > 1:
        LOGGER.warning(
            "Grouping inference tie detected for columns %s at score %.4f; selecting %r by column order. "
            "Pass group_by explicitly to control tie-break behavior.",
            tied_best_columns,
            best_score,
            best_column,
        )

    return best_column


def _plot_grouped_single_signal(
    dataset: Dataset,
    *,
    x_column: str,
    y_column: str,
    ax,
    group_by: Optional[str],
    max_groups: int,
    color: Optional[str] = None,
) -> Optional[str]:
    """Plot a single-signal line with optional grouping.

    Returns the grouping column used, if any.
    """

    resolved_group = _resolve_grouping_column(
        dataset,
        key_columns=[x_column],
        exclude_columns=[y_column],
        group_by=group_by,
        max_groups=max_groups,
    )

    df = dataset.data
    if not resolved_group:
        ax.plot(df[x_column], df[y_column], color=color)
        return None

    group_count = int(df[resolved_group].nunique(dropna=False))
    if group_count > max_groups:
        LOGGER.warning(
            "Skipping grouped plot for %r: inferred/selected grouper %r has %d groups, exceeding max_groups=%d. "
            "Pass a lower-cardinality group_by or increase max_groups.",
            y_column,
            resolved_group,
            group_count,
            max_groups,
        )
        return None

    use_gradient_palette = group_count > 10
    gradient_colors = None
    if use_gradient_palette:
        cmap = plt.get_cmap("viridis")
        denominator = max(group_count - 1, 1)
        gradient_colors = iter(cmap(idx / denominator) for idx in range(group_count))

    for group_value, subset in df.groupby(resolved_group, dropna=False, sort=False):
        label_value = "<missing>" if group_value is None else str(group_value)
        if gradient_colors is None:
            ax.plot(subset[x_column], subset[y_column], label=label_value)
        else:
            ax.plot(
                subset[x_column],
                subset[y_column],
                label=label_value,
                color=next(gradient_colors),
            )
    ax.legend(title=resolved_group)
    return resolved_group


def _resolve_plot_kind(dataset: Dataset, kind: Optional[str]) -> Optional[str]:
    """Resolve the plotting family from an explicit kind, metadata, then columns."""

    if kind is not None:
        return kind

    from .dma import is_supported_dma_profile
    from .rheology import is_supported_rheology_profile

    metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}
    columns = set(dataset.data.columns)
    instrument_type = str(metadata.get("instrument_type") or "").strip().casefold()
    measurement_profile = str(metadata.get("measurement_profile") or "").strip()

    if instrument_type == "dma":
        return "dma"
    if instrument_type == "rheometer":
        return "rheology"
    if instrument_type == "uv_vis":
        return "uv_vis"
    if instrument_type == "ftir":
        return "ftir"
    if instrument_type == "dsc":
        return "dsc"
    if instrument_type == "tga":
        return "tga"
    if instrument_type == "saxs":
        return "saxs"
    if instrument_type == "ms":
        return "ms"
    if instrument_type == "sec":
        return "sec"
    if instrument_type == "nmr":
        return "nmr"

    if is_supported_dma_profile(measurement_profile):
        return "dma"
    if is_supported_rheology_profile(measurement_profile):
        return "rheology"

    if {"wavelength_nm"}.issubset(columns):
        return "uv_vis"
    if {"wavenumber_cm_inv"}.issubset(columns):
        return "ftir"
    if {"frequency_hz", "storage_modulus_mpa", "loss_modulus_mpa"}.issubset(columns):
        return "dma"
    if {"temperature_C", "storage_modulus_mpa", "loss_modulus_mpa"}.issubset(columns):
        return "dma"
    if {"strain_pct", "storage_modulus_mpa", "loss_modulus_mpa"}.issubset(columns):
        return "dma"
    if {"temperature_C", "heat_flow_mW"}.issubset(columns):
        return "dsc"
    if {"temperature_C", "mass_pct"}.issubset(columns):
        return "tga"
    if {"q_inv_nm", "intensity_a_u"}.issubset(columns):
        return "saxs"
    if {"mz", "intensity_a_u"}.issubset(columns):
        return "ms"
    if {"retention_time_min", "detector_response_a_u"}.issubset(columns):
        return "sec"
    if {"chemical_shift_ppm", "intensity_a_u"}.issubset(columns):
        return "nmr"

    return None


def plot_dataset(
    dataset: Dataset,
    kind: Optional[str] = None,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 50,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    **kwargs: Any,
) -> Tuple[Any, Any]:
    """Plot a normalized dataset using canonical columns only."""

    from .dma import plot_dma
    from .dsc import plot_dsc
    from .ftir import plot_ftir
    from .ms import plot_ms
    from .nmr import plot_nmr
    from .rheology import plot_rheology
    from .saxs import plot_saxs
    from .sec import plot_sec
    from .tga import plot_tga
    from .uv_vis import plot_uv_vis

    resolved_kind = _resolve_plot_kind(dataset, kind)

    if resolved_kind == "uv_vis":
        return plot_uv_vis(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
            **kwargs,
        )
    if resolved_kind == "ftir":
        return plot_ftir(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
            **kwargs,
        )
    if resolved_kind == "dma":
        return plot_dma(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
            **kwargs,
        )
    if resolved_kind == "dsc":
        return plot_dsc(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
        )
    if resolved_kind == "ms":
        return plot_ms(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
        )
    if resolved_kind == "tga":
        return plot_tga(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
            **kwargs,
        )
    if resolved_kind == "rheology":
        return plot_rheology(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
            **kwargs,
        )
    if resolved_kind == "sec":
        return plot_sec(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
            **kwargs,
        )
    if resolved_kind == "saxs":
        return plot_saxs(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
        )
    if resolved_kind == "nmr":
        return plot_nmr(
            dataset,
            group_by=group_by,
            max_groups=max_groups,
            ax=ax,
            title=title,
            strict=strict,
        )

    raise PlotError(
        "Could not infer a plot kind from the normalized dataset. "
        "Pass kind explicitly or provide canonical columns for a supported family."
    )
