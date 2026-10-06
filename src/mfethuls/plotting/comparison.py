from __future__ import annotations

import logging
from typing import Literal, Sequence

from ..dataset import Dataset
from ..comparison import ComparisonSet
from .backend import Backend, render
from .core import PlotError, _resolve_plot_kind, build_dataset_spec
from .dsc import dsc_overlay_legends, experiment_legend, experiment_legend_group, experiment_linestyle
from .labels import axis_label
from .spec import Colorbar, Panel, PlotSpec


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
    """Resolve the x-axis column for a dataset based on instrument type and measurement profile.
    
    Strategy:
    1. For simple instrument types, use fixed x-column
    2. For profile-dependent types (DMA, rheology), use canonical measurement_profile to select x-column
    3. Fall back to generic candidates if profile not recognized or missing
    4. Return None if no suitable column found
    """
    columns = set(dataset.data.columns)

    simple_x = {
        "uv_vis": "wavelength_nm",
        "fluorescence": "wavelength_nm",
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
        if profile and profile in _DMA_PROFILE_MAP:
            candidate = _DMA_PROFILE_MAP[profile][0]
            if candidate in columns:
                return candidate
        
        # Fall back to generic candidates when profile not recognized
        if profile:
            LOGGER.debug(
                "DMA x-column: canonical profile '%s' not in profile map, using fallback candidates",
                profile,
            )
        
        for candidate in ("frequency_hz", "temperature_C", "strain_pct", "time_s"):
            if candidate in columns:
                return candidate
        return None

    if resolved_kind == "rheology":
        from .rheology import _PROFILE_MAP as _RHEOLOGY_PROFILE_MAP

        profile = str(dataset.metadata.get("measurement_profile") or "").strip()
        if profile and profile in _RHEOLOGY_PROFILE_MAP:
            candidate = _RHEOLOGY_PROFILE_MAP[profile][0]
            if candidate in columns:
                return candidate
        
        # Fall back to generic candidates when profile not recognized
        if profile:
            LOGGER.debug(
                "Rheology x-column: canonical profile '%s' not in profile map, using fallback candidates",
                profile,
            )

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


def _shared_colorbar(colorbars: Sequence[Colorbar | None]) -> Colorbar | None:
    """One colour bar spanning all datasets, when every dataset has one for the same quantity."""

    if not colorbars or not all(colorbars) or len({(c.title, c.cmap) for c in colorbars}) != 1:
        return None
    return Colorbar(
        title=colorbars[0].title,
        vmin=min(c.vmin for c in colorbars),
        vmax=max(c.vmax for c in colorbars),
        cmap=colorbars[0].cmap,
    )


def build_experiments_spec(
    comparison: ComparisonSet | Sequence[Dataset],
    *,
    kind: str | None = None,
    mode: ComparisonMode = "auto",
    signal: str | None = None,
    group_by: str | None = None,
    max_groups: int = 50,
    stacked_offset: float = 0.0,
    title: str | None = None,
    strict: bool = True,
) -> PlotSpec:
    """Build the backend-neutral spec that :func:`plot_experiments` renders."""

    comparison_set = _coerce_comparison_set(comparison)
    datasets = comparison_set.datasets
    labels = comparison_set.labels

    if not datasets:
        raise PlotError("plot_comparison requires at least one dataset.")

    dataset_kwargs = {
        "kind": kind,
        "group_by": group_by,
        "max_groups": max_groups,
        "title": None,
        "strict": strict,
    }
    if signal is not None:
        dataset_kwargs["signal"] = signal

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
        panels = []
        for dataset in datasets:
            panel = build_dataset_spec(dataset, **dataset_kwargs).panel
            panel.title = None
            panels.append(panel)
        return PlotSpec(panels, layout="facet", title=title)

    all_dsc = all(resolved == "dsc" for resolved in resolved_kinds)
    panels = []
    for idx, dataset in enumerate(datasets):
        overlay_kwargs = dict(dataset_kwargs)
        # DSC overlays: colour shows the segment, line style shows the experiment.
        if all_dsc:
            overlay_kwargs["linestyle"] = experiment_linestyle(idx)
        panels.append(build_dataset_spec(dataset, **overlay_kwargs).panel)

    # Colour-bar overlays (e.g. spectra coloured by time_s): colour shows the value,
    # line style shows the experiment.
    colorbar = _shared_colorbar([panel.colorbar for panel in panels])
    by_experiment = all_dsc or colorbar is not None

    overlay = Panel(
        title=title or ("Comparison Stacked" if resolved_mode == "stacked" else "Comparison Overlay"),
        xlabel=axis_label(shared_x),
        legend=colorbar is None,
        colorbar=colorbar,
    )
    segment_colors: dict[str, object] = {}
    for idx, (panel, label) in enumerate(zip(panels, labels)):
        # Every dataset shares the x-axis, so its scale and direction carry over.
        if idx == 0:
            overlay.xscale = panel.xscale
            overlay.yscale = panel.yscale
            overlay.x_reversed = panel.x_reversed
        overlay.ylabel = panel.ylabel

        for trace in panel.traces:
            if trace.label:
                segment_colors.setdefault(trace.label, trace.color)
                trace.label = f"{label} | {trace.label}"
            else:
                trace.label = label
            if resolved_mode == "stacked":
                trace.y = trace.y + (idx * stacked_offset)
            if colorbar is not None:
                trace.linestyle = experiment_linestyle(idx)
            if by_experiment:
                trace.legend_group = experiment_legend_group(idx)
            overlay.traces.append(trace)

    if all_dsc and overlay.traces:
        overlay.legends = dsc_overlay_legends(segment_colors, labels)
    elif colorbar is not None and len(datasets) > 1:
        overlay.legends = [experiment_legend(labels)]

    return PlotSpec([overlay], constrained=True)


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
    backend: Backend | None = None,
):
    """Plot several experiments together.

    ``mode="auto"`` overlays datasets that share an x-axis and otherwise draws one
    panel per dataset. Returns ``(fig, ax)`` (``(fig, axes)`` for a facet) with the
    matplotlib backend and a Plotly ``Figure`` with the plotly backend.
    """

    spec = build_experiments_spec(
        comparison,
        kind=kind,
        mode=mode,
        signal=signal,
        group_by=group_by,
        max_groups=max_groups,
        stacked_offset=stacked_offset,
        title=title,
        strict=strict,
    )
    # A facet always creates its own figure; ax= only applies to overlay and stacked.
    return render(spec, backend=backend, ax=None if spec.layout == "facet" else ax)


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
    backend: Backend | None = None,
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
        backend=backend,
    )
