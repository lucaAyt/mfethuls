from __future__ import annotations

import logging
from typing import Literal, Sequence

import matplotlib.pyplot as plt

from ..dataset import Dataset
from ..comparison import ComparisonSet
from .core import PlotError, _resolve_plot_kind, plot_dataset


LOGGER = logging.getLogger(__name__)

ComparisonMode = Literal["auto", "overlay", "stacked", "facet"]


def _label_for_dataset(dataset: Dataset, index: int) -> str:
    metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}

    experiment_name = metadata.get("experiment_name")
    if experiment_name:
        return str(experiment_name)

    experiment_id = dataset.experiment_id
    if experiment_id:
        return str(experiment_id)

    return f"dataset_{index + 1}"


def _coerce_comparison_set(comparison: ComparisonSet | Sequence[Dataset]) -> ComparisonSet:
    if isinstance(comparison, ComparisonSet):
        return comparison

    datasets = list(comparison)
    labels = [_label_for_dataset(dataset, idx) for idx, dataset in enumerate(datasets)]
    return ComparisonSet(datasets=datasets, labels=labels)


def _resolve_x_column(dataset: Dataset, resolved_kind: str) -> str | None:
    columns = set(dataset.data.columns)

    simple_x = {
        "uv_vis": "wavelength_nm",
        "ftir": "wavenumber_cm_inv",
        "dsc": "temperature_C",
        "tga": "temperature_C",
        "saxs": "q_inv_nm",
        "ms": "mz",
        "sec": "retention_time_min",
        "nmr": "chemical_shift_ppm",
    }
    if resolved_kind in simple_x:
        candidate = simple_x[resolved_kind]
        return candidate if candidate in columns else None

    if resolved_kind == "dma":
        from .dma import _PROFILE_MAP as _DMA_PROFILE_MAP

        profile = str(dataset.metadata.get("measurement_profile") or "").strip()
        if profile in _DMA_PROFILE_MAP:
            candidate = _DMA_PROFILE_MAP[profile][0]
            return candidate if candidate in columns else None

        for candidate in ("frequency_hz", "temperature_C", "strain_pct", "time_s"):
            if candidate in columns:
                return candidate
        return None

    if resolved_kind == "rheology":
        from .rheology import _PROFILE_MAP as _RHEOLOGY_PROFILE_MAP

        profile = str(dataset.metadata.get("measurement_profile") or "").strip()
        if profile in _RHEOLOGY_PROFILE_MAP:
            candidate = _RHEOLOGY_PROFILE_MAP[profile][0]
            return candidate if candidate in columns else None

        for candidate in ("angular_frequency_rad_s", "strain_pct", "time_s", "shear_rate_s_inv"):
            if candidate in columns:
                return candidate
        return None

    return None


def _is_x_axis_compatible(datasets: Sequence[Dataset], kinds: Sequence[str]) -> tuple[bool, str | None]:
    x_columns: list[str] = []
    for dataset, resolved_kind in zip(datasets, kinds):
        x_column = _resolve_x_column(dataset, resolved_kind)
        if not x_column:
            return False, None
        x_columns.append(x_column)

    unique = sorted(set(x_columns))
    if len(unique) != 1:
        return False, None
    return True, unique[0]


def _label_new_lines(axis, *, start_idx: int, dataset_label: str) -> None:
    new_lines = axis.lines[start_idx:]
    if not new_lines:
        return

    for line in new_lines:
        current = str(line.get_label() or "")
        if current and not current.startswith("_"):
            line.set_label(f"{dataset_label} | {current}")
        else:
            line.set_label(dataset_label)


def plot_experiments(
    comparison: ComparisonSet | Sequence[Dataset],
    *,
    kind: str | None = None,
    mode: ComparisonMode = "auto",
    signal: str | None = None,
    group_by: str | None = None,
    max_groups: int = 50,
    stacked_offset: float = 0.0,
    ax=None,
    title: str | None = None,
    strict: bool = True,
):
    comparison_set = _coerce_comparison_set(comparison)
    datasets = comparison_set.datasets
    labels = comparison_set.labels

    if not datasets:
        raise PlotError("plot_comparison requires at least one dataset.")

    resolved_kinds: list[str] = []
    for dataset in datasets:
        resolved_kind = _resolve_plot_kind(dataset, kind)
        if not resolved_kind:
            raise PlotError(
                "Could not infer a plot kind for one or more datasets. "
                "Pass kind explicitly or provide canonical columns for a supported family."
            )
        resolved_kinds.append(resolved_kind)

    x_compatible, shared_x = _is_x_axis_compatible(datasets, resolved_kinds)

    resolved_mode = mode
    if mode == "auto":
        resolved_mode = "overlay" if x_compatible else "facet"
        if resolved_mode == "facet" and len(set(resolved_kinds)) > 1:
            LOGGER.warning(
                "Comparison mode auto selected facet with mixed inferred plot families: %s",
                sorted(set(resolved_kinds)),
            )

    if resolved_mode not in {"overlay", "stacked", "facet"}:
        raise PlotError(f"Unsupported comparison mode: {resolved_mode!r}.")

    if resolved_mode in {"overlay", "stacked"} and not x_compatible:
        raise PlotError(
            "Comparison mode requires x-axis compatible datasets, but canonical x-axis could not be shared."
        )

    if resolved_mode == "stacked" and stacked_offset <= 0:
        raise PlotError("plot_comparison in stacked mode requires stacked_offset > 0.")

    if resolved_mode == "facet":
        fig, axes = plt.subplots(len(datasets), 1, squeeze=False)
        flat_axes = list(axes.ravel())
        for idx, (dataset, label) in enumerate(zip(datasets, labels)):
            plot_dataset(
                dataset,
                kind=kind,
                group_by=group_by,
                max_groups=max_groups,
                signal=signal,
                ax=flat_axes[idx],
                title=None,
                strict=strict,
            )
            flat_axes[idx].set_title("")

        if len(flat_axes) > 1:
            fig.subplots_adjust(hspace=0.45)
        if title:
            fig.suptitle(title)
        return fig, axes

    if ax is not None:
        fig, axis = ax.figure, ax
    else:
        fig, axis = plt.subplots()

    for idx, (dataset, label) in enumerate(zip(datasets, labels)):
        start = len(axis.lines)
        plot_dataset(
            dataset,
            kind=kind,
            group_by=group_by,
            max_groups=max_groups,
            signal=signal,
            ax=axis,
            title=None,
            strict=strict,
        )

        # TODO: x-axis being reverted back after stacking
        if resolved_mode == "stacked":
            for line in axis.lines[start:]:
                line.set_ydata(line.get_ydata() + (idx * stacked_offset))

        _label_new_lines(axis, start_idx=start, dataset_label=label)

    axis.set_title(title or ("Comparison Stacked" if resolved_mode == "stacked" else "Comparison Overlay"))
    if axis.lines:
        axis.legend()
    if shared_x:
        axis.set_xlabel(shared_x)

    return fig, axis


def plot_comparison(
    comparison: ComparisonSet | Sequence[Dataset],
    *,
    kind: str | None = None,
    mode: ComparisonMode = "auto",
    signal: str | None = None,
    group_by: str | None = None,
    max_groups: int = 50,
    stacked_offset: float = 0.0,
    ax=None,
    title: str | None = None,
    strict: bool = True,
):
    """Compatibility wrapper for plot_experiments."""

    return plot_experiments(
        comparison,
        kind=kind,
        mode=mode,
        signal=signal,
        group_by=group_by,
        max_groups=max_groups,
        stacked_offset=stacked_offset,
        ax=ax,
        title=title,
        strict=strict,
    )
