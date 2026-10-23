from __future__ import annotations

from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import PlotError, _default_title, _require_columns, _values
from .labels import axis_label, legend_name, shared_axis_label
from .spec import Panel, PlotSpec, Trace
from .sweeps import SWEEP_NAMES, sweep_axis

# Swept quantities in the order they are looked for (see sweeps.sweep_axis); time last.
DMA_AXES = ("temperature_C", "frequency_hz", "strain_pct", "time_s")
_MODULI = ["storage_modulus_mpa", "loss_modulus_mpa"]


def build_dma_spec(
    dataset: Dataset,
    *,
    x: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
) -> PlotSpec:
    """DMA moduli against the quantity the run swept, read from the data (see
    :mod:`~mfethuls.plotting.sweeps`), or against ``x``."""
    x_column = x or sweep_axis(dataset.data, DMA_AXES)
    if x_column is None:
        raise PlotError(f"plot_dma needs one of the columns {', '.join(DMA_AXES)}.")
    y_columns = list(_MODULI)
    if strict:
        _require_columns(dataset, [x_column] + y_columns, "plot_dma")

    traces = []
    for y_column in y_columns:
        if y_column in dataset.data.columns:
            traces.append(Trace(_values(dataset.data[x_column]), _values(dataset.data[y_column]), label=legend_name(y_column)))
        elif strict:
            raise PlotError(f"plot_dma requires canonical column {y_column!r}.")

    sweep = SWEEP_NAMES.get(x_column, f"against {x_column}")
    panel = Panel(
        traces=traces,
        title=title or _default_title(dataset, f"DMA - {sweep}"),
        xlabel=axis_label(x_column),
        ylabel=shared_axis_label(y_columns),
        # Log-log scaling unless the x-axis is time or temperature.
        xscale="linear" if x_column in ("time_s", "temperature_C") else "log",
        yscale="log",
        legend=True,
    )
    return PlotSpec([panel])


def plot_dma(
    dataset: Dataset,
    *,
    x: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    backend: Optional[Backend] = None,
):
    """Plot DMA data against the swept quantity (or ``x``)."""

    spec = build_dma_spec(
        dataset,
        x=x,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
