from __future__ import annotations

from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import _default_title, _require_columns, _single_signal_spec
from .spec import PlotSpec


def build_fluorescence_spec(
    dataset: Dataset,
    *,
    signal: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
) -> PlotSpec:
    x_column = "wavelength_nm"
    signal = signal or "emission_counts"

    if strict:
        _require_columns(dataset, [x_column, signal], "plot_fluorescence")

    return _single_signal_spec(
        dataset,
        x_column=x_column,
        y_column=signal,
        group_by=group_by,
        max_groups=max_groups,
        color="#1f77b4",
        title=title or _default_title(dataset, "Fluorescence"),
    )


def plot_fluorescence(
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
    spec = build_fluorescence_spec(
        dataset,
        signal=signal,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
