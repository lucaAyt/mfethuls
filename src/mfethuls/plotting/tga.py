from __future__ import annotations

from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import PlotError, _default_title, _require_columns, _single_signal_spec
from .spec import PlotSpec


def build_tga_spec(
    dataset: Dataset,
    *,
    signal: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
) -> PlotSpec:
    x_column = "temperature_C"
    if signal is None:
        signal = "mass_pct" if "mass_pct" in dataset.data.columns else "d_mass_dt_pct_min"

    if signal not in dataset.data.columns:
        raise PlotError("plot_tga requires mass_pct or d_mass_dt_pct_min.")

    if strict:
        _require_columns(dataset, [x_column, signal], "plot_tga")

    return _single_signal_spec(
        dataset,
        x_column=x_column,
        y_column=signal,
        group_by=group_by,
        max_groups=max_groups,
        color="#2ca02c",
        title=title or _default_title(dataset, "TGA"),
    )


def plot_tga(
    dataset: Dataset,
    *,
    signal: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    backend: Optional[Backend] = None,
):
    spec = build_tga_spec(
        dataset,
        signal=signal,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
