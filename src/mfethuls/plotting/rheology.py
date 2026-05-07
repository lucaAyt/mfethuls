from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from .core import PlotError, _default_title, _figure_and_axis, _require_columns
from .style import apply_axes_style


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


def plot_rheology(
    dataset: Dataset,
    *,
    profile: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    resolved_profile = profile or str(dataset.metadata.get("measurement_profile") or "").strip() or None
    if resolved_profile not in _PROFILE_MAP:
        raise PlotError(
            "plot_rheology requires a supported measurement_profile: "
            f"{sorted(_PROFILE_MAP)}"
        )

    x_column, y_columns = _PROFILE_MAP[resolved_profile]
    if strict:
        _require_columns(dataset, [x_column] + y_columns, "plot_rheology")

    fig, axis = _figure_and_axis(ax)
    # For rheology, we default to log-log scaling unless the x-axis is time or temperature.
    if x_column not in ("time_s", "temperature_C"):
        axis.set_xscale("log")
    axis.set_yscale("log")
    
    for y_column in y_columns:
        if y_column in dataset.data.columns:
            axis.plot(dataset.data[x_column], dataset.data[y_column], label=y_column)
        elif strict:
            raise PlotError(f"plot_rheology requires canonical column {y_column!r}.")

    apply_axes_style(
        axis,
        title=title or _default_title(dataset, f"Rheology - {resolved_profile}"),
        xlabel=x_column,
        ylabel=", ".join(y_columns),
    )
    axis.legend()
    return fig, axis
