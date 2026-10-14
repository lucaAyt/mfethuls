from __future__ import annotations

from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import PlotError, _default_title, _require_columns, _values
from .labels import axis_label, legend_name, shared_axis_label
from .spec import Panel, PlotSpec, Trace


SUPPORTED_RHEOLOGY_PROFILES = frozenset(
    {
        "oscillatory_frequency_sweep",
        "oscillatory_strain_sweep",
        "oscillatory_time_sweep",
        "flow_curve",
    }
)


_PROFILE_MAP = {
    "oscillatory_frequency_sweep": ("angular_frequency_rad_s", ["storage_modulus_pa", "loss_modulus_pa"]),
    "oscillatory_strain_sweep": ("strain_pct", ["storage_modulus_pa", "loss_modulus_pa"]),
    "oscillatory_time_sweep": ("time_s", ["storage_modulus_pa", "loss_modulus_pa"]),
    "flow_curve": ("shear_rate_s_inv", ["shear_stress_pa", "viscosity_pa_s"]),
}


def is_supported_rheology_profile(profile: Optional[str]) -> bool:
    """Return True if the profile is a supported rheometer profile."""

    return bool(profile) and str(profile).strip() in SUPPORTED_RHEOLOGY_PROFILES


def build_rheology_spec(
    dataset: Dataset,
    *,
    profile: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
) -> PlotSpec:
    resolved_profile = profile or str(dataset.metadata.get("measurement_profile") or "").strip() or None
    if resolved_profile not in _PROFILE_MAP:
        raise PlotError(
            "plot_rheology requires a supported measurement_profile: "
            f"{sorted(_PROFILE_MAP)}"
        )

    x_column, y_columns = _PROFILE_MAP[resolved_profile]
    if strict:
        _require_columns(dataset, [x_column] + y_columns, "plot_rheology")

    traces = []
    for y_column in y_columns:
        if y_column in dataset.data.columns:
            traces.append(Trace(_values(dataset.data[x_column]), _values(dataset.data[y_column]), label=legend_name(y_column)))
        elif strict:
            raise PlotError(f"plot_rheology requires canonical column {y_column!r}.")

    panel = Panel(
        traces=traces,
        title=title or _default_title(dataset, f"Rheology - {resolved_profile.replace('_', ' ')}"),
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
    profile: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    backend: Optional[Backend] = None,
):
    """Plot Rheology data for a supported measurement profile."""

    spec = build_rheology_spec(
        dataset,
        profile=profile,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
