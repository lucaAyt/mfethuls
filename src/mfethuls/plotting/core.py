from __future__ import annotations

import logging
from typing import Any, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..dataset import Dataset
from .backend import Backend, render
from .labels import axis_label, legend_name
from .spec import Colorbar, Panel, PlotError, PlotSpec, Scale, Trace


LOGGER = logging.getLogger(__name__)

# More groups than this get a gradient: a colour bar for numeric groups (e.g. time_s),
# otherwise a viridis-shaded legend.
_MAX_LEGEND_GROUPS = 10

__all__ = ["PlotError", "build_dataset_spec", "plot_dataset"]


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


def _values(series: pd.Series) -> np.ndarray:
    return series.to_numpy()


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

    # time_s is derived from timestamp (see add_elapsed_time), so they always tie;
    # the numeric one can drive a continuous colour scale.
    if {"timestamp", "time_s"} <= set(tied_best_columns):
        tied_best_columns.remove("timestamp")
        best_column = tied_best_columns[0]

    if len(tied_best_columns) > 1:
        LOGGER.warning(
            "Grouping inference tie detected for columns %s at score %.4f; selecting %r by column order. "
            "Pass group_by explicitly to control tie-break behavior.",
            tied_best_columns,
            best_score,
            best_column,
        )

    return best_column


def _grouped_single_signal_traces(
    dataset: Dataset,
    *,
    x_column: str,
    y_column: str,
    group_by: Optional[str],
    max_groups: int,
    color: Optional[str] = None,
) -> tuple[list[Trace], Optional[str], Optional[Colorbar]]:
    """Build the traces for a single-signal line with optional grouping.

    Returns the traces, the grouping column used (if any) and, for many groups of a
    numeric column such as ``time_s``, a colour bar that replaces the legend.
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
        return [Trace(_values(df[x_column]), _values(df[y_column]), color=color)], None, None

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
        return [], None, None

    group_values = df[resolved_group]
    if group_count > _MAX_LEGEND_GROUPS and pd.api.types.is_numeric_dtype(group_values):
        colorbar = Colorbar(
            title=axis_label(resolved_group),
            vmin=float(group_values.min()),
            vmax=float(group_values.max()),
        )
        traces = [
            Trace(
                _values(subset[x_column]),
                _values(subset[y_column]),
                label=str(group_value),
                color="grey" if pd.isna(group_value) else None,
                color_value=None if pd.isna(group_value) else float(group_value),
            )
            for group_value, subset in df.groupby(resolved_group, dropna=False, sort=False)
        ]
        return traces, resolved_group, colorbar

    gradient_colors = None
    if group_count > _MAX_LEGEND_GROUPS:
        cmap = plt.get_cmap("viridis")
        denominator = max(group_count - 1, 1)
        gradient_colors = iter(cmap(idx / denominator) for idx in range(group_count))

    traces = []
    for group_value, subset in df.groupby(resolved_group, dropna=False, sort=False):
        traces.append(
            Trace(
                _values(subset[x_column]),
                _values(subset[y_column]),
                label="<missing>" if group_value is None else str(group_value),
                color=None if gradient_colors is None else next(gradient_colors),
            )
        )
    return traces, resolved_group, None


def _single_signal_spec(
    dataset: Dataset,
    *,
    x_column: str,
    y_column: str,
    group_by: Optional[str],
    max_groups: int,
    color: str,
    title: str,
    xscale: Scale = "linear",
    yscale: Scale = "linear",
    x_reversed: bool = False,
) -> PlotSpec:
    """Spec for the common case: one signal against one x column, optionally grouped."""

    traces, legend_title, colorbar = _grouped_single_signal_traces(
        dataset,
        x_column=x_column,
        y_column=y_column,
        group_by=group_by,
        max_groups=max_groups,
        color=color,
    )
    panel = Panel(
        traces=traces,
        title=title,
        xlabel=axis_label(x_column),
        ylabel=axis_label(y_column),
        xscale=xscale,
        yscale=yscale,
        x_reversed=x_reversed,
        legend=legend_title is not None and colorbar is None,
        legend_title=legend_name(legend_title),
        colorbar=colorbar,
    )
    return PlotSpec([panel])


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
    if instrument_type == "fluorescence":
        return "fluorescence"
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

    if {"wavelength_nm", "emission_counts"}.issubset(columns):
        return "fluorescence"
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


def build_dataset_spec(
    dataset: Dataset,
    kind: Optional[str] = None,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 50,
    title: Optional[str] = None,
    strict: bool = True,
    **kwargs: Any,
) -> PlotSpec:
    """Build the backend-neutral spec that :func:`plot_dataset` renders."""

    from .dma import build_dma_spec
    from .dsc import build_dsc_spec
    from .fluorescence import build_fluorescence_spec
    from .ftir import build_ftir_spec
    from .ms import build_ms_spec
    from .nmr import build_nmr_spec
    from .rheology import build_rheology_spec
    from .saxs import build_saxs_spec
    from .sec import build_sec_spec
    from .tga import build_tga_spec
    from .uv_vis import build_uv_vis_spec

    # Families that take extra keyword arguments (signal, profile, detector) get **kwargs.
    builders = {
        "uv_vis": (build_uv_vis_spec, True),
        "fluorescence": (build_fluorescence_spec, True),
        "ftir": (build_ftir_spec, True),
        "dma": (build_dma_spec, True),
        "ms": (build_ms_spec, False),
        "tga": (build_tga_spec, True),
        "rheology": (build_rheology_spec, True),
        "sec": (build_sec_spec, True),
        "saxs": (build_saxs_spec, False),
        "nmr": (build_nmr_spec, False),
    }

    resolved_kind = _resolve_plot_kind(dataset, kind)
    common = {"group_by": group_by, "max_groups": max_groups, "title": title, "strict": strict}

    if resolved_kind == "dsc":
        return build_dsc_spec(dataset, linestyle=kwargs.get("linestyle", "-"), **common)
    if resolved_kind in builders:
        builder, takes_kwargs = builders[resolved_kind]
        return builder(dataset, **common, **(kwargs if takes_kwargs else {}))

    raise PlotError(
        "Could not infer a plot kind from the normalized dataset. "
        "Pass kind explicitly or provide canonical columns for a supported family."
    )


def plot_dataset(
    dataset: Dataset,
    kind: Optional[str] = None,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 50,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    backend: Optional[Backend] = None,
    **kwargs: Any,
):
    """Plot a normalized dataset using canonical columns only.

    Returns ``(fig, ax)`` with the matplotlib backend and a Plotly ``Figure`` with
    the plotly backend (see :func:`set_default_backend`).
    """

    spec = build_dataset_spec(
        dataset,
        kind,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
        **kwargs,
    )
    return render(spec, backend=backend, ax=ax)
