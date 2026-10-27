"""NMR spectra: chemical shift (high to low) against intensity, one panel per nucleus.

1H and 13C spectra (often expno 1 and 2 of one Bruker dataset) cover very different
ppm ranges, so a dataset or comparison holding several nuclei gets one panel per
nucleus, its x-axis naming the nucleus.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

import pandas as pd

from ..dataset import Dataset
from .backend import Backend, render
from .core import _default_title, _require_columns, _single_signal_spec
from .spec import PlotSpec

NUCLEUS_COLUMN = "nucleus"


def nuclei(dataset: Dataset) -> List[str]:
    """The dataset's nuclei, lightest first (1H, 13C, 19F, ...); empty without a nucleus column."""
    if NUCLEUS_COLUMN not in dataset.data.columns:
        return []
    return sort_nuclei(str(n) for n in dataset.data[NUCLEUS_COLUMN].dropna().unique())


def sort_nuclei(names) -> List[str]:
    """Nuclei by mass number (1H before 13C), whatever order the expno folders have."""
    def key(name: str):
        match = re.match(r"(\d+)", name)
        return (int(match.group(1)) if match else 10_000, name)
    return sorted(set(names), key=key)


def split_by_nucleus(dataset: Dataset) -> List[Tuple[str, Dataset]]:
    """One dataset per nucleus, with the same metadata."""
    column = dataset.data[NUCLEUS_COLUMN].astype(str)
    return [(nucleus, Dataset(data=dataset.data[column == nucleus].reset_index(drop=True),
                              metadata=dataset.metadata))
            for nucleus in nuclei(dataset)]


def nucleus_axis_label(nucleus: Optional[str]) -> str:
    """``$^{13}$C chemical shift (ppm)``; the plain label without a nucleus."""
    if not nucleus:
        return "Chemical shift (ppm)"
    match = re.fullmatch(r"(\d+)([A-Za-z]+)", nucleus)
    name = f"$^{{{match.group(1)}}}${match.group(2)}" if match else nucleus
    return f"{name} chemical shift (ppm)"


def spectrum_column(data: pd.DataFrame, max_groups: int = 20) -> Optional[str]:
    """The column telling the spectra apart, one line each: ``dataset`` when it names each one
    (``LUB437_000``), else ``source_file`` (``1/pdata/1``); for more than ``max_groups`` spectra,
    ``time_s`` (a colour scale). None for a single spectrum.

    Each spectrum has its own chemical shifts, so the rows of two never share an x value and the
    usual grouping by repeated x values would draw them as one line.
    """
    if "source_file" not in data.columns:
        return None
    spectra = data["source_file"].nunique()
    if spectra < 2:
        return None
    if spectra > max_groups and "time_s" in data.columns and data["time_s"].nunique() == spectra:
        return "time_s"
    if "dataset" in data.columns and data["dataset"].nunique() == spectra:
        return "dataset"
    return "source_file"


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

    def spec_for(part: Dataset, nucleus: Optional[str]) -> PlotSpec:
        spec = _single_signal_spec(
            part,
            x_column=x_column,
            y_column=signal,
            group_by=group_by or spectrum_column(part.data, max_groups),
            max_groups=max_groups,
            color="#8c564b",
            title=title or _default_title(dataset, "NMR"),
            # NMR spectra are shown from high to low chemical shift.
            x_reversed=True,
        )
        spec.panel.xlabel = nucleus_axis_label(nucleus)
        return spec

    found = nuclei(dataset)
    if len(found) <= 1:
        return spec_for(dataset, found[0] if found else None)
    panels = []
    for nucleus, part in split_by_nucleus(dataset):
        panel = spec_for(part, nucleus).panel
        panel.title = None
        panels.append(panel)
    return PlotSpec(panels, layout="facet", title=title or _default_title(dataset, "NMR"))


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
