"""Display names and units for canonical columns.

Canonical column names carry their unit (``temperature_C``, ``wavenumber_cm_inv``);
see docs/reference/schema.md. Labels use Matplotlib mathtext for superscripts,
subscripts and symbols (``r"cm$^{-1}$"``); the Plotly renderer converts them with
:func:`mathtext_to_html`. Every column in ``config/schemas/*.json`` needs an
entry here, which tests/test_plotting_labels.py enforces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class ColumnLabel:
    quantity: str
    unit: Optional[str] = None
    symbol: Optional[str] = None
    # Shared axis name when several columns of the same kind are plotted together.
    group: Optional[str] = None

    @property
    def name(self) -> str:
        """Quantity and symbol, without the unit (for legend entries)."""
        return f"{self.quantity} {self.symbol}" if self.symbol else self.quantity


COLUMN_LABELS: dict[str, ColumnLabel] = {
    # Thermal analysis
    "temperature_C": ColumnLabel("Temperature", "°C"),
    "temperature_sample_C": ColumnLabel("Sample temperature", "°C"),
    "time_s": ColumnLabel("Time", "s"),
    "heat_flow_mW": ColumnLabel("Heat flow", "mW"),
    "mass_pct": ColumnLabel("Mass", "%"),
    "mass_mg": ColumnLabel("Mass", "mg"),
    "mass_loss_pct": ColumnLabel("Mass loss", "%"),
    "d_mass_dt_pct_min": ColumnLabel("Mass change rate", r"% min$^{-1}$", symbol=r"$\mathrm{d}m/\mathrm{d}t$"),
    # Spectroscopy
    "wavelength_nm": ColumnLabel("Wavelength", "nm"),
    "wavenumber_cm_inv": ColumnLabel("Wavenumber", r"cm$^{-1}$"),
    "absorbance_a_u": ColumnLabel("Absorbance", "a.u."),
    "transmittance_pct": ColumnLabel("Transmittance", "%"),
    "emission_counts": ColumnLabel("Emission intensity", "counts"),
    "intensity_a_u": ColumnLabel("Intensity", "a.u."),
    "intensity_error_a_u": ColumnLabel("Intensity error", "a.u."),
    "chemical_shift_ppm": ColumnLabel("Chemical shift", "ppm", symbol=r"$\delta$"),
    "mz": ColumnLabel(r"$m/z$"),
    "q_inv_nm": ColumnLabel("Scattering vector", r"nm$^{-1}$", symbol=r"$q$"),
    # Chromatography
    "retention_time_min": ColumnLabel("Retention time", "min"),
    "detector_response_a_u": ColumnLabel("Detector response", "a.u."),
    "detector_name": ColumnLabel("Detector"),
    # Mechanical analysis and rheology
    "frequency_hz": ColumnLabel("Frequency", "Hz"),
    "angular_frequency_rad_s": ColumnLabel("Angular frequency", r"rad s$^{-1}$", symbol=r"$\omega$"),
    "strain_pct": ColumnLabel("Strain", "%"),
    "storage_modulus_mpa": ColumnLabel("Storage modulus", "MPa", symbol=r"$E'$", group="Modulus"),
    "loss_modulus_mpa": ColumnLabel("Loss modulus", "MPa", symbol=r"$E''$", group="Modulus"),
    "storage_modulus_pa": ColumnLabel("Storage modulus", "Pa", symbol=r"$G'$", group="Modulus"),
    "loss_modulus_pa": ColumnLabel("Loss modulus", "Pa", symbol=r"$G''$", group="Modulus"),
    "tan_delta": ColumnLabel("Loss factor", symbol=r"$\tan\delta$"),
    "shear_rate_s_inv": ColumnLabel("Shear rate", r"s$^{-1}$", symbol=r"$\dot{\gamma}$"),
    "shear_stress_pa": ColumnLabel("Shear stress", "Pa", symbol=r"$\tau$"),
    "viscosity_pa_s": ColumnLabel("Viscosity", r"Pa$\cdot$s", symbol=r"$\eta$"),
    # Grouping columns
    "profile": ColumnLabel("Segment"),
}


def _format(quantity: str, unit: Optional[str]) -> str:
    return f"{quantity} ({unit})" if unit else quantity


def axis_label(column: Optional[str]) -> Optional[str]:
    """Axis title such as ``"Temperature (°C)"``; unknown columns are returned unchanged."""

    if column is None:
        return None
    entry = COLUMN_LABELS.get(column)
    return _format(entry.name, entry.unit) if entry else column


def legend_name(column: Optional[str]) -> Optional[str]:
    """Legend entry or title without the unit, such as ``"Storage modulus $E'$"``."""

    if column is None:
        return None
    entry = COLUMN_LABELS.get(column)
    return entry.name if entry else column


def shared_axis_label(columns: Sequence[str]) -> str:
    """One axis title for several columns: ``"Modulus (MPa)"`` when they share a group and unit."""

    entries = [COLUMN_LABELS.get(column) for column in columns]
    if len(columns) > 1 and all(entries):
        groups = {(entry.group, entry.unit) for entry in entries}
        if len(groups) == 1:
            group, unit = groups.pop()
            if group:
                return _format(group, unit)
    return ", ".join(axis_label(column) for column in columns)


_GREEK = {
    name: chr(code)
    for name, code in [
        ("alpha", 0x3B1), ("beta", 0x3B2), ("gamma", 0x3B3), ("delta", 0x3B4), ("epsilon", 0x3B5),
        ("eta", 0x3B7), ("theta", 0x3B8), ("lambda", 0x3BB), ("mu", 0x3BC), ("nu", 0x3BD),
        ("pi", 0x3C0), ("rho", 0x3C1), ("sigma", 0x3C3), ("tau", 0x3C4), ("phi", 0x3C6),
        ("omega", 0x3C9), ("Delta", 0x394), ("Omega", 0x3A9),
    ]
}
_COMMANDS = {**_GREEK, "cdot": "·", "times": "×", "pm": "±", "circ": "°", "degree": "°", "tan": "tan "}
_COMBINING_DOT = "\u0307"


def _command(name: str) -> str:
    return _COMMANDS.get(name, name)


def _math_to_html(math: str) -> str:
    math = re.sub(r"\\(?:mathrm|mathit|text)\{([^{}]*)\}", r"\1", math)
    math = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", math)
    math = re.sub(r"\\dot\{\\?([A-Za-z]+)\}", lambda m: _command(m.group(1)) + _COMBINING_DOT, math)
    math = math.replace("''", "″").replace("'", "′")
    math = re.sub(r"\^\{([^{}]*)\}|\^(\S)", lambda m: f"<sup>{m.group(1) or m.group(2)}</sup>", math)
    math = re.sub(r"_\{([^{}]*)\}|_(\S)", lambda m: f"<sub>{m.group(1) or m.group(2)}</sub>", math)
    math = re.sub(r"\\([A-Za-z]+) ?", lambda m: _command(m.group(1)), math)
    return math.replace(r"\,", " ").replace("\\ ", " ")


def mathtext_to_html(text: Optional[str]) -> Optional[str]:
    """Convert the mathtext parts (``$...$``) of a label to the HTML subset Plotly renders.

    ``"Wavenumber (cm$^{-1}$)"`` becomes ``"Wavenumber (cm<sup>-1</sup>)"``. Plotly only
    typesets LaTeX when a whole label is one ``$...$`` block and MathJax is loaded, so
    mixed labels are converted instead. Text without a balanced pair of ``$`` is unchanged.
    """

    if not text or text.count("$") < 2 or text.count("$") % 2:
        return text
    parts = text.split("$")
    return "".join(_math_to_html(part) if idx % 2 else part for idx, part in enumerate(parts))
