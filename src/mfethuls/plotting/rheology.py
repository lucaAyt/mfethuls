from __future__ import annotations

from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import PlotError, _default_title, _require_columns, _values
from .labels import axis_label, legend_name, shared_axis_label
from .spec import Panel, PlotSpec, Trace
from .sweeps import SWEEP_NAMES, sweep_axis

# Swept quantities in the order they are looked for (see sweeps.sweep_axis); time last.
RHEOLOGY_AXES = ("shear_rate_s_inv", "angular_frequency_rad_s", "strain_pct", "temperature_C", "time_s")
_MODULI = ["storage_modulus_pa", "loss_modulus_pa"]
# A flow curve: stress and viscosity against shear rate.
_FLOW = ["shear_stress_pa", "viscosity_pa_s"]


def build_rheology_spec(
    dataset: Dataset,
    *,
    x: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
) -> PlotSpec:
    """Rheometer moduli (stress and viscosity for a flow curve) against the quantity the run
    swept, read from the data (see :mod:`~mfethuls.plotting.sweeps`), or against ``x``."""
    x_column = x or sweep_axis(dataset.data, RHEOLOGY_AXES)
    if x_column is None:
        raise PlotError(f"plot_rheology needs one of the columns {', '.join(RHEOLOGY_AXES)}.")
    y_columns = list(_FLOW if x_column == "shear_rate_s_inv" else _MODULI)
    if strict:
        _require_columns(dataset, [x_column] + y_columns, "plot_rheology")

    traces = []
    for y_column in y_columns:
        if y_column in dataset.data.columns:
            traces.append(Trace(_values(dataset.data[x_column]), _values(dataset.data[y_column]), label=legend_name(y_column)))
        elif strict:
            raise PlotError(f"plot_rheology requires canonical column {y_column!r}.")

    sweep = SWEEP_NAMES.get(x_column, f"against {x_column}")
    panel = Panel(
        traces=traces,
        title=title or _default_title(dataset, f"Rheology - {sweep}"),
        xlabel=axis_label(x_column),
        ylabel=shared_axis_label(y_columns),
        # Log-log scaling unless the x-axis is time or temperature.
        xscale="linear" if x_column in ("time_s", "temperature_C") else "log",
        yscale="log",
        legend=True,
    )
    return PlotSpec([panel])


def plot_rheology(
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
    """Plot Rheometer data against the swept quantity (or ``x``)."""

    spec = build_rheology_spec(
        dataset,
        x=x,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
