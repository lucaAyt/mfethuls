"""Plot several experiments together: overlay, stacked (offset) or one panel per experiment."""

from __future__ import annotations

import logging
from typing import Literal, Sequence

import numpy as np

from ..dataset import Dataset
from ..comparison import ComparisonSet
from .backend import Backend, render
from .core import PlotError, _definition_with_plot, _resolve_plot_kind, build_dataset_spec
from .dsc import dsc_overlay_legends, experiment_legend, experiment_legend_group, experiment_linestyle
from .labels import axis_label
from .nmr import nuclei, nucleus_axis_label, sort_nuclei, split_by_nucleus
from .normalise import LOG_MINMAX_NOTE, NORMALISE_METHODS, normalise_traces, normalised_label, window_text
from .spec import Colorbar, Panel, PlotSpec


LOGGER = logging.getLogger(__name__)

ComparisonMode = Literal["auto", "overlay", "stacked", "facet"]

# Stacked curves are shifted apart by this many times the tallest curve, so they don't touch.
STACK_GAP = 1.1


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
    """Resolve the x-axis column for a dataset from its instrument type.

    Strategy:
    1. For simple instrument types, use fixed x-column
    2. For DMA and rheology, the quantity the run swept (see ``sweeps.sweep_axis``)
    3. Return None if no suitable column found
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
    if resolved_kind.startswith("definition:"):
        definition = _definition_with_plot(dataset)
        candidate = definition.plot["x"] if definition is not None else None
        return candidate if candidate in columns else None

    if resolved_kind in ("dma", "rheology"):
        from .dma import DMA_AXES
        from .rheology import RHEOLOGY_AXES
        from .sweeps import sweep_axis

        return sweep_axis(dataset.data, DMA_AXES if resolved_kind == "dma" else RHEOLOGY_AXES)

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
    stacked_offset: float | Literal["auto"] = "auto",
    spacing: float = 1.0,
    normalise: str | None = None,
    normalise_x: tuple[float | None, float | None] | None = None,
    title: str | None = None,
    strict: bool = True,
) -> PlotSpec:
    """Build the backend-neutral spec that :func:`plot_experiments` renders.

    ``mode="stacked"`` shifts each experiment up from the one before: by ``stacked_offset``
    in y units (decades on a log y-axis), or with ``"auto"`` by ``spacing`` times 1.1 times
    the tallest experiment's y range. ``mode="facet"`` draws one panel per experiment; they
    share one x-axis when the experiments have the same x quantity.

    ``normalise`` (``"max"``, ``"minmax"`` or ``"area"``, see :mod:`~mfethuls.plotting.normalise`)
    scales each experiment's curves, before they are offset; the data is not changed. With
    ``normalise_x`` (``(low, high)`` in x units) only the points in that x range set the scale.
    Experiments that cannot be normalised are drawn as they are and listed in ``notes``.
    """
    if normalise is not None and normalise not in NORMALISE_METHODS:
        raise PlotError(f"Unknown normalise={normalise!r}; use one of {', '.join(NORMALISE_METHODS)}.")
    notes: list[str] = []

    comparison_set = _coerce_comparison_set(comparison)
    datasets = comparison_set.datasets
    labels = comparison_set.labels

    if not datasets:
        raise PlotError("plot_experiments requires at least one dataset.")

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

    nucleus = None
    if all(resolved == "nmr" for resolved in resolved_kinds) and mode != "facet":
        split = _nmr_by_nucleus(datasets, labels)
        nucleus = next(iter(split)) if len(split) == 1 else None
        if len(split) > 1:
            # 1H and 13C cover different ppm ranges: one overlay panel per nucleus.
            panels = []
            # Each experiment keeps one colour in every panel.
            colours = {label: EXPERIMENT_COLOURS[i % len(EXPERIMENT_COLOURS)] for i, label in enumerate(labels)}
            for nucleus in sort_nuclei(n for n in split if n is not None) + ([None] if None in split else []):
                parts, part_labels = split[nucleus]
                panel = build_experiments_spec(
                    ComparisonSet(datasets=parts, labels=part_labels), kind=kind, mode=mode, signal=signal,
                    group_by=group_by, max_groups=max_groups, stacked_offset=stacked_offset, spacing=spacing,
                    normalise=normalise, normalise_x=normalise_x, strict=strict,
                )
                notes.extend(n for n in panel.notes if n not in notes)
                panel = panel.panel
                panel.title = None
                panel.xlabel = nucleus_axis_label(nucleus)
                if len(datasets) > 1:
                    for trace in panel.traces:
                        trace.color = colours.get(str(trace.label).split(" | ")[0], trace.color)
                panels.append(panel)
            return PlotSpec(panels, layout="facet", title=title, notes=notes)

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

    if resolved_mode == "stacked" and stacked_offset != "auto" and not float(stacked_offset) > 0:
        raise PlotError("plot_experiments in stacked mode requires stacked_offset > 0 (or 'auto').")
    if resolved_mode == "stacked" and not spacing > 0:
        raise PlotError("plot_experiments in stacked mode requires spacing > 0.")

    if resolved_mode == "facet":
        panels = []
        for dataset, label in zip(datasets, labels):
            # Every panel of the dataset's plot (an NMR dataset has one per nucleus), named after it.
            for panel in build_dataset_spec(dataset, **dataset_kwargs).panels:
                panel.title = label
                if normalise:
                    _normalise_panel(panel, normalise, label, notes, normalise_x)
                panels.append(panel)
        return PlotSpec(panels, layout="facet", title=title, shared_x=x_compatible, notes=notes)

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
    if normalise:
        for panel, label in zip(panels, labels):
            _normalise_panel(panel, normalise, label, notes, normalise_x)
    colorbar = _shared_colorbar([panel.colorbar for panel in panels])
    by_experiment = all_dsc or colorbar is not None
    log_y = bool(panels) and panels[0].yscale == "log"
    step = stack_step(panels, stacked_offset, spacing, log=log_y) if resolved_mode == "stacked" else 0.0

    overlay = Panel(
        title=title or ("Comparison Offset" if resolved_mode == "stacked" else "Comparison Overlay"),
        xlabel=axis_label(shared_x),
        legend=colorbar is None,
        colorbar=colorbar,
    )
    segment_colors: dict[str, object] = {}
    # A family drawn in one fixed colour (FTIR orange, NMR brown, ...) would draw every
    # experiment alike: give each experiment its own colour instead.
    recolour = len(panels) > 1 and not all_dsc and colorbar is None and all(
        len({str(trace.color) for trace in panel.traces}) <= 1 for panel in panels)
    for idx, (panel, label) in enumerate(zip(panels, labels)):
        # Every dataset shares the x-axis, so its scale and direction carry over.
        if idx == 0:
            overlay.xscale = panel.xscale
            overlay.yscale = panel.yscale
            overlay.x_reversed = panel.x_reversed
        overlay.ylabel = panel.ylabel
        if nucleus:
            overlay.xlabel = panel.xlabel  # names the nucleus, e.g. 13C chemical shift

        for trace in panel.traces:
            if trace.label:
                segment_colors.setdefault(trace.label, trace.color)
                trace.label = f"{label} | {trace.label}"
            else:
                trace.label = label
            if recolour:
                trace.color = EXPERIMENT_COLOURS[idx % len(EXPERIMENT_COLOURS)]
            if resolved_mode == "stacked":
                # On a log axis a shift is a factor: decades.
                trace.y = trace.y * 10 ** (idx * step) if log_y else trace.y + idx * step
            if colorbar is not None:
                trace.linestyle = experiment_linestyle(idx)
            if by_experiment:
                trace.legend_group = experiment_legend_group(idx)
            overlay.traces.append(trace)

    if resolved_mode == "stacked":
        # Shifted values are not the data's: the axis says so and shows no numbers.
        overlay.ylabel = f"{overlay.ylabel} (offset)" if overlay.ylabel else "Offset"
        overlay.y_ticks = False

    if all_dsc and overlay.traces:
        overlay.legends = dsc_overlay_legends(segment_colors, labels)
    elif colorbar is not None and len(datasets) > 1:
        overlay.legends = [experiment_legend(labels)]

    return PlotSpec([overlay], notes=notes)


def _normalise_panel(panel: Panel, method: str, label: str, notes: list[str],
                     x_range: tuple[float | None, float | None] | None = None) -> None:
    """Normalise one experiment's curves together (over ``x_range``); say so on the y-axis, or note why not."""
    if normalise_traces(panel.traces, method, x_range):
        panel.ylabel = normalised_label(panel.ylabel)
        if method == "minmax" and panel.yscale == "log" and LOG_MINMAX_NOTE not in notes:
            notes.append(LOG_MINMAX_NOTE)
    else:
        where = f" over x {window_text(x_range)}" if x_range else ""
        notes.append(f"{label} is drawn as it is: it cannot be normalised ({NORMALISE_METHODS[method]}){where}.")


def stack_step(panels: Sequence[Panel], offset: float | str, spacing: float = 1.0, *, log: bool = False) -> float:
    """How far each stacked experiment is shifted from the one before.

    A number is used as it is. ``"auto"``: ``spacing`` times :data:`STACK_GAP` times the
    largest y range of one experiment (in decades on a log axis), so the curves don't overlap.
    """
    if offset != "auto":
        return float(offset)
    spans = []
    for panel in panels:
        values = [np.asarray(trace.y, dtype=float) for trace in panel.traces]
        values = np.concatenate(values) if values else np.array([])
        values = values[np.isfinite(values) & (values > 0)] if log else values[np.isfinite(values)]
        if values.size:
            low, high = (np.log10(values.min()), np.log10(values.max())) if log else (values.min(), values.max())
            spans.append(float(high - low))
    span = max(spans, default=0.0) or 1.0
    return STACK_GAP * spacing * span


def shares_x_axis(comparison: ComparisonSet | Sequence[Dataset], *, kind: str | None = None) -> bool:
    """True when the experiments can be drawn on one x-axis (together or stacked)."""
    datasets = _coerce_comparison_set(comparison).datasets
    kinds = [_resolve_plot_kind(dataset, kind) for dataset in datasets]
    if not datasets or not all(kinds):
        return False
    return _is_x_axis_compatible(datasets, kinds)[0]


# Matplotlib's default cycle (tab10), one colour per experiment in overlays.
EXPERIMENT_COLOURS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                      "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]


def _nmr_by_nucleus(datasets, labels) -> dict:
    """``{nucleus: ([datasets], [labels])}`` over all datasets; datasets without a nucleus go under None."""
    split: dict = {}
    for dataset, label in zip(datasets, labels):
        parts = split_by_nucleus(dataset) if nuclei(dataset) else [(None, dataset)]
        for nucleus, part in parts:
            entry = split.setdefault(nucleus, ([], []))
            entry[0].append(part)
            entry[1].append(label)
    return split


def plot_experiments(
    comparison: ComparisonSet | Sequence[Dataset],
    *,
    kind: str | None = None,
    mode: ComparisonMode = "auto",
    signal: str | None = None,
    group_by: str | None = None,
    max_groups: int = 50,
    stacked_offset: float | Literal["auto"] = "auto",
    spacing: float = 1.0,
    normalise: str | None = None,
    normalise_x: tuple[float | None, float | None] | None = None,
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
        spacing=spacing,
        normalise=normalise,
        normalise_x=normalise_x,
        title=title,
        strict=strict,
    )
    # A facet always creates its own figure; ax= only applies to overlay and stacked.
    return render(spec, backend=backend, ax=None if spec.layout == "facet" else ax)
