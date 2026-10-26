"""Physical quantities, their standard column names and unit conversions.

An instrument definition maps each source column to a *quantity* and the *unit*
the instrument writes, for example ``Weight [g]`` → ``mass`` in ``g``. mfethuls
stores it under the quantity's standard column (``mass_mg``) in the standard
unit, so data from different instruments can be compared.

Units are case sensitive (``MPa`` is not ``mPa``). ``µ``/``μ`` may be written
``u``, ``°`` may be left out and spaces are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

import pandas as pd

# A conversion into the standard unit: standard = value * factor + offset.
Conversion = Tuple[float, float]


@dataclass(frozen=True)
class Quantity:
    name: str
    label: str
    column: str
    unit: str
    # Other accepted units: unit -> (factor, offset) into ``unit``.
    units: Mapping[str, Conversion] = field(default_factory=dict)
    # Instrument types storing this quantity in another standard unit:
    # type -> (column, unit). The other unit must be one of ``units``.
    by_type: Mapping[str, Tuple[str, str]] = field(default_factory=dict)
    # Units that cannot be converted into ``unit`` (strain in mm, not %): each family is
    # stored in its own column, (column, unit, other units -> conversion into that unit).
    families: Tuple[Tuple[str, str, Mapping[str, Conversion]], ...] = ()

    def family(self, unit: Optional[str]) -> Optional[Tuple[str, str, Mapping[str, Conversion]]]:
        """The extra unit family ``unit`` belongs to, or None (the quantity's own units)."""
        if unit is None:
            return None
        wanted = normalize_unit(unit)
        return next((f for f in self.families
                     if wanted in {normalize_unit(u) for u in (f[1], *f[2])}), None)

    def target(self, instrument_type: Optional[str] = None, unit: Optional[str] = None) -> Tuple[str, str]:
        """``(column, unit)`` the quantity is stored as for ``instrument_type`` and the file's ``unit``."""
        family = self.family(unit)
        if family is not None:
            return family[0], family[1]
        return self.by_type.get(str(instrument_type or ""), (self.column, self.unit))

    def columns(self) -> Tuple[str, ...]:
        """Every column the quantity may be stored in."""
        return (self.column, *(c for c, _ in self.by_type.values()), *(f[0] for f in self.families))

    def unit_names(self) -> Tuple[str, ...]:
        return (self.unit, *self.units, *(u for f in self.families for u in (f[1], *f[2])))


_MASS = {"g": (1000.0, 0.0), "ug": (0.001, 0.0), "kg": (1e6, 0.0)}
_TIME = {"min": (60.0, 0.0), "h": (3600.0, 0.0), "ms": (0.001, 0.0)}
_PRESSURE = {"MPa": (1e6, 0.0), "kPa": (1000.0, 0.0), "GPa": (1e9, 0.0)}
_AU = {"a.u.": (1.0, 0.0), "AU": (1.0, 0.0), "": (1.0, 0.0)}


def _quantities(*items: Quantity) -> Dict[str, Quantity]:
    return {q.name: q for q in items}


QUANTITIES: Dict[str, Quantity] = _quantities(
    Quantity("temperature", "Temperature", "temperature_C", "°C",
             {"K": (1.0, -273.15), "°F": (5 / 9, -160 / 9)}),
    Quantity("sample_temperature", "Sample temperature", "temperature_sample_C", "°C",
             {"K": (1.0, -273.15), "°F": (5 / 9, -160 / 9)}),
    Quantity("time", "Time", "time_s", "s", _TIME),
    Quantity("retention_time", "Retention time", "retention_time_min", "min",
             {"s": (1 / 60, 0.0), "h": (60.0, 0.0)}),
    Quantity("mass", "Mass", "mass_mg", "mg", _MASS),
    Quantity("mass_pct", "Mass", "mass_pct", "%"),
    Quantity("mass_loss", "Mass loss", "mass_loss_pct", "%"),
    Quantity("mass_loss_rate", "Mass loss rate (DTG)", "d_mass_dt_pct_min", "%/min",
             {"%/s": (60.0, 0.0)}),
    Quantity("heat_flow", "Heat flow", "heat_flow_mW", "mW", {"W": (1000.0, 0.0), "uW": (0.001, 0.0)}),
    Quantity("specific_heat_flow", "Heat flow per sample mass", "heat_flow_W_g", "W/g",
             {"Wg^-1": (1.0, 0.0), "mW/mg": (1.0, 0.0), "mW/g": (0.001, 0.0), "W/kg": (0.001, 0.0)}),
    Quantity("wavenumber", "Wavenumber", "wavenumber_cm_inv", "cm-1"),
    Quantity("wavelength", "Wavelength", "wavelength_nm", "nm", {"um": (1000.0, 0.0), "Å": (0.1, 0.0)}),
    Quantity("absorbance", "Absorbance", "absorbance_a_u", "a.u.", _AU),
    Quantity("transmittance", "Transmittance", "transmittance_pct", "%", {"fraction": (100.0, 0.0)}),
    Quantity("emission", "Emission", "emission_counts", "counts"),
    Quantity("intensity", "Intensity", "intensity_a_u", "a.u.", _AU),
    Quantity("intensity_error", "Intensity error", "intensity_error_a_u", "a.u.", _AU),
    Quantity("detector_response", "Detector response", "detector_response_a_u", "a.u.", _AU),
    Quantity("chemical_shift", "Chemical shift", "chemical_shift_ppm", "ppm"),
    Quantity("mz", "m/z", "mz", "m/z", {"": (1.0, 0.0), "Th": (1.0, 0.0)}),
    Quantity("q", "Scattering vector q", "q_inv_nm", "nm-1", {"Å-1": (10.0, 0.0)}),
    Quantity("frequency", "Frequency", "frequency_hz", "Hz", {"kHz": (1000.0, 0.0)}),
    Quantity("angular_frequency", "Angular frequency", "angular_frequency_rad_s", "rad/s"),
    # Relative strain (rheology, DMA) in %, or a strain written as a length (tensile testers: mm).
    # "1" is a plain ratio (Anton Paar "Strain [1]": 0.01 is 1 %).
    Quantity("strain", "Strain", "strain_pct", "%", {"fraction": (100.0, 0.0), "1": (100.0, 0.0)},
             families=(("strain_mm", "mm", {"um": (0.001, 0.0), "cm": (10.0, 0.0), "m": (1000.0, 0.0)}),)),
    Quantity("storage_modulus", "Storage modulus", "storage_modulus_pa", "Pa", _PRESSURE,
             by_type={"dma": ("storage_modulus_mpa", "MPa")}),
    Quantity("loss_modulus", "Loss modulus", "loss_modulus_pa", "Pa", _PRESSURE,
             by_type={"dma": ("loss_modulus_mpa", "MPa")}),
    Quantity("tan_delta", "tan δ", "tan_delta", "", {"1": (1.0, 0.0)}),
    Quantity("shear_rate", "Shear rate", "shear_rate_s_inv", "s-1"),
    # Rheology in Pa; mechanical testing (tensile, lap shear) in MPa, as is the convention.
    Quantity("shear_stress", "Shear stress", "shear_stress_pa", "Pa", _PRESSURE,
             by_type={"tensile": ("shear_stress_mpa", "MPa")}),
    Quantity("viscosity", "Viscosity", "viscosity_pa_s", "Pa s", {"mPa s": (0.001, 0.0)}),
    # Normal (tensile, compressive) stress; MPa for mechanical testing, as is the convention.
    Quantity("stress", "Stress", "stress_pa", "Pa", _PRESSURE, by_type={"tensile": ("stress_mpa", "MPa")}),
    Quantity("displacement", "Displacement", "displacement_mm", "mm",
             {"um": (0.001, 0.0), "cm": (10.0, 0.0), "m": (1000.0, 0.0)}),
    Quantity("force", "Force", "force_N", "N", {"kN": (1000.0, 0.0), "mN": (0.001, 0.0)}),
)


def normalize_unit(unit: Optional[str]) -> str:
    """Spelling-tolerant form of a unit, used to compare units (case kept)."""
    text = str(unit or "").strip()
    for old, new in (("µ", "u"), ("μ", "u"), ("°", ""), ("·", ""), ("*", ""), (" ", ""),
                     ("^", ""), ("⁻¹", "-1"), ("1/", "inv"), ("deg", "")):
        text = text.replace(old, new)
    if text.endswith("-1") and not text.startswith("inv"):
        text = "inv" + text[:-2]
    return text


def _factor_into(quantity: Quantity, unit: str) -> Optional[Conversion]:
    """Conversion of ``unit`` into the quantity's default standard unit."""
    wanted = normalize_unit(unit)
    if wanted == normalize_unit(quantity.unit):
        return (1.0, 0.0)
    for name, conversion in quantity.units.items():
        if wanted == normalize_unit(name):
            return conversion
    return None


def conversion(quantity: Quantity, unit: Optional[str], instrument_type: Optional[str] = None) -> Conversion:
    """``(factor, offset)`` turning values in ``unit`` into the stored unit.

    Raises ``ValueError`` naming the accepted units when ``unit`` is unknown.
    """
    family = quantity.family(unit)
    if family is not None:
        # A unit family of its own (strain in mm): converted within it, never into %.
        wanted = normalize_unit(unit)
        if wanted == normalize_unit(family[1]):
            return (1.0, 0.0)
        return next(c for u, c in family[2].items() if normalize_unit(u) == wanted)
    _, stored_unit = quantity.target(instrument_type)
    source = _factor_into(quantity, quantity.unit if unit is None else unit)
    stored = _factor_into(quantity, stored_unit)
    if source is None:
        accepted = ", ".join(repr(u) for u in quantity.unit_names())
        raise ValueError(f"Unknown unit {unit!r} for {quantity.name}; use one of {accepted}.")
    # value -> default standard unit -> stored unit (stored = default * f2 + o2, inverted).
    (f1, o1), (f2, o2) = source, stored
    return (f1 / f2, (o1 - o2) / f2)


def convert(values: pd.Series, factor: float, offset: float) -> pd.Series:
    if factor == 1.0 and offset == 0.0:
        return values
    return values * factor + offset


# Values outside these ranges (in the stored unit) are almost always a wrong unit or a
# wrong column; they are warned about, never refused.
PLAUSIBLE: Dict[str, Tuple[float, float]] = {
    "temperature": (-273.15, 3000.0),
    "sample_temperature": (-273.15, 3000.0),
    "retention_time": (0.0, 1000.0),
    "mass": (-50.0, 5000.0),
    "mass_pct": (-10.0, 200.0),
    "mass_loss": (-100.0, 200.0),
    "heat_flow": (-10000.0, 10000.0),
    "specific_heat_flow": (-1000.0, 1000.0),
    "wavenumber": (1.0, 50000.0),
    "wavelength": (100.0, 30000.0),
    "absorbance": (-2.0, 10.0),
    "transmittance": (-10.0, 200.0),
    "chemical_shift": (-100.0, 300.0),
    "mz": (0.0, 1e7),
    "q": (0.0, 1000.0),
    "frequency": (0.0, 1e10),
    "angular_frequency": (0.0, 1e10),
    "tan_delta": (-100.0, 1e4),
}


def range_warnings(df: pd.DataFrame, instrument_type: Optional[str] = None) -> List[str]:
    """Stored quantity columns whose values fall outside :data:`PLAUSIBLE`."""
    warnings = []
    for column, quantity in standard_columns(instrument_type).items():
        bounds = PLAUSIBLE.get(quantity.name)
        if bounds is None or column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if values.empty:
            continue
        low, high = float(values.min()), float(values.max())
        if low < bounds[0] or high > bounds[1]:
            unit = quantity.target(instrument_type)[1]
            warnings.append(
                f"{quantity.label} ({column}) goes from {low:.4g} to {high:.4g} {unit}, outside the usual "
                f"{bounds[0]:g} to {bounds[1]:g} {unit}. Is the unit in the file right?"
            )
    return warnings


def standard_columns(instrument_type: Optional[str] = None) -> Dict[str, Quantity]:
    """Stored column name -> quantity, for ``instrument_type``."""
    out = {q.target(instrument_type)[0]: q for q in QUANTITIES.values()}
    for q in QUANTITIES.values():
        for column, *_ in q.families:
            out.setdefault(column, q)
    return out
