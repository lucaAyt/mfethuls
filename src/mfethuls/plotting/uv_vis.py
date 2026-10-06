from __future__ import annotations

from typing import Optional

from ..dataset import Dataset
from .backend import Backend, render
from .core import PlotError, _default_title, _require_columns, _single_signal_spec
from .spec import PlotSpec


def build_uv_vis_spec(
    dataset: Dataset,
    *,
    signal: Optional[str] = None,
    group_by: Optional[str] = None,
    max_groups: int = 20,
    title: Optional[str] = None,
    strict: bool = True,
) -> PlotSpec:
    x_column = "wavelength_nm"
    if signal is None:
        if "absorbance_a_u" in dataset.data.columns:
            signal = "absorbance_a_u"
        elif "transmittance_pct" in dataset.data.columns:
            signal = "transmittance_pct"

    if signal is None:
        raise PlotError("plot_uv_vis requires absorbance_a_u or transmittance_pct.")

    if strict:
        _require_columns(dataset, [x_column, signal], "plot_uv_vis")

    return _single_signal_spec(
        dataset,
        x_column=x_column,
        y_column=signal,
        group_by=group_by,
        max_groups=max_groups,
        color="#1f77b4",
        title=title or _default_title(dataset, "UV/Vis"),
    )


def plot_uv_vis(
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
    spec = build_uv_vis_spec(
        dataset,
        signal=signal,
        group_by=group_by,
        max_groups=max_groups,
        title=title,
        strict=strict,
    )
    return render(spec, backend=backend, ax=ax)
