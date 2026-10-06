from __future__ import annotations

from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import _default_title, _require_columns, _single_signal_spec
from .spec import PlotSpec


def build_nmr_spec(
    dataset: Dataset,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
) -> PlotSpec:
    x_column = "chemical_shift_ppm"
    signal = "intensity_a_u"

    if strict:
        _require_columns(dataset, [x_column, signal], "plot_nmr")

    return _single_signal_spec(
        dataset,
        x_column=x_column,
        y_column=signal,
        group_by=group_by,
        max_groups=max_groups,
        color="#8c564b",
        title=title or _default_title(dataset, "NMR"),
        # NMR spectra are shown from high to low chemical shift.
        x_reversed=True,
    )


def plot_nmr(
    dataset: Dataset,
    *,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    ax=None,
    title: Optional[str] = None,
    strict: bool = True,
    backend: Optional[Backend] = None,
):
    spec = build_nmr_spec(
        dataset,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
