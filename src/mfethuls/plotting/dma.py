from __future__ import annotations

from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import PlotError, _default_title, _require_columns, _values
from .labels import axis_label, legend_name, shared_axis_label
from .spec import Panel, PlotSpec, Trace


SUPPORTED_DMA_PROFILES = frozenset(
    {
        "oscillatory_temperature_sweep",
        "oscillatory_frequency_sweep",
        "oscillatory_strain_sweep",
        "oscillatory_time_sweep",
    }
)


_PROFILE_MAP = {
    "oscillatory_temperature_sweep": ("temperature_C", ["storage_modulus_mpa", "loss_modulus_mpa"]),
    "oscillatory_frequency_sweep": ("frequency_hz", ["storage_modulus_mpa", "loss_modulus_mpa"]),
    "oscillatory_strain_sweep": ("strain_pct", ["storage_modulus_mpa", "loss_modulus_mpa"]),
    "oscillatory_time_sweep": ("time_s", ["storage_modulus_mpa", "loss_modulus_mpa"]),
}


def is_supported_dma_profile(profile: Optional[str]) -> bool:
    """Return True if the profile is a supported DMA profile."""

    return bool(profile) and str(profile).strip() in SUPPORTED_DMA_PROFILES


def build_dma_spec(
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
            "plot_dma requires a supported measurement_profile: "
            f"{sorted(_PROFILE_MAP)}"
        )

    x_column, y_columns = _PROFILE_MAP[resolved_profile]
    if strict:
        _require_columns(dataset, [x_column] + y_columns, "plot_dma")

    traces = []
    for y_column in y_columns:
        if y_column in dataset.data.columns:
            traces.append(Trace(_values(dataset.data[x_column]), _values(dataset.data[y_column]), label=legend_name(y_column)))
        elif strict:
            raise PlotError(f"plot_dma requires canonical column {y_column!r}.")

    panel = Panel(
        traces=traces,
        title=title or _default_title(dataset, f"DMA - {resolved_profile.replace('_', ' ')}"),
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
    profile: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    backend: Optional[Backend] = None,
):
    """Plot DMA data for a supported measurement profile."""

    spec = build_dma_spec(
        dataset,
        profile=profile,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
