from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from .core import PlotError, _default_title, _figure_and_axis, _require_columns
from .style import apply_axes_style


SUPPORTED_DMA_PROFILES = frozenset(
    {
        "oscillatory_temperature_sweep",
        "oscillatory_frequency_sweep",
        "oscillatory_strain_sweep",
        "oscillatory_time_sweep"
    }
)


_PROFILE_MAP = {
    "oscillatory_temperature_sweep": ("temperature_C", ["storage_modulus_mpa", "loss_modulus_mpa"]),
    "oscillatory_frequency_sweep": ("frequency_hz", ["storage_modulus_mpa", "loss_modulus_mpa"]),
    "oscillatory_strain_sweep": ("strain_pct", ["storage_modulus_mpa", "loss_modulus_mpa"]),
    "oscillatory_time_sweep": ("time_s", ["storage_modulus_mpa", "loss_modulus_mpa"])
}


def is_supported_dma_profile(profile: Optional[str]) -> bool:
    """Return True if the profile is a supported DMA profile."""

    return bool(profile) and str(profile).strip() in SUPPORTED_DMA_PROFILES


def plot_dma(
    dataset: Dataset,
    *,
    profile: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
) -> Tuple[object, object]:
    """Plot DMA data for a supported measurement profile."""

    resolved_profile = profile or str(dataset.metadata.get("measurement_profile") or "").strip() or None
    if resolved_profile not in _PROFILE_MAP:
        raise PlotError(
            "plot_dma requires a supported measurement_profile: "
            f"{sorted(_PROFILE_MAP)}"
        )

    x_column, y_columns = _PROFILE_MAP[resolved_profile]
    if strict:
        _require_columns(dataset, [x_column] + y_columns, "plot_dma")

    fig, axis = _figure_and_axis(ax)
    for y_column in y_columns:
        if y_column in dataset.data.columns:
            axis.plot(dataset.data[x_column], dataset.data[y_column], label=y_column)
        elif strict:
            raise PlotError(f"plot_dma requires canonical column {y_column!r}.")

    apply_axes_style(
        axis,
        title=title or _default_title(dataset, f"DMA - {resolved_profile}"),
        xlabel=x_column,
        ylabel=", ".join(y_columns),
    )
    axis.legend()
    return fig, axis
