"""Which quantity a DMA or rheometer run swept, read from the data.

A run holds one quantity fixed and changes another: a temperature sweep at 1 Hz, a
frequency sweep at 25 °C. Nothing needs to be declared: the swept quantity is the
one whose values span a real range. Small drifts (a temperature creeping by 2 °C,
a strain held at 1 % ± 0.01) do not count.
"""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

# Swept when the values span more than this fraction of their size.
SWEPT_SPAN = 0.05

# The name of the sweep along each axis, for titles.
SWEEP_NAMES = {
    "temperature_C": "temperature sweep",
    "frequency_hz": "frequency sweep",
    "angular_frequency_rad_s": "frequency sweep",
    "strain_pct": "strain sweep",
    "shear_rate_s_inv": "flow curve",
    "time_s": "time sweep",
}


def is_swept(values: pd.Series, column: str) -> bool:
    """True when ``values`` change by more than :data:`SWEPT_SPAN` of their size.

    Temperatures are compared in kelvin, so a drift of a few degrees near 0 °C is
    not a sweep.
    """
    values = pd.to_numeric(values, errors="coerce").dropna()
    if len(values) < 2:
        return False
    if column == "temperature_C":
        values = values + 273.15
    size = max(abs(values.max()), abs(values.min()))
    return size > 0 and (values.max() - values.min()) / size > SWEPT_SPAN


def sweep_axis(data: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    """The first of ``candidates`` that was swept; else time, if the data has it; else None."""
    candidates = [c for c in candidates if c in data.columns]
    for column in candidates:
        if column != "time_s" and is_swept(data[column], column):
            return column
    return "time_s" if "time_s" in candidates else None
