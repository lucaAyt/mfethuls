from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import logging
import os

import pandas as pd

from .ids import validate_experiment_id, validate_run_id, validate_sample_id


logger = logging.getLogger(__name__)


def _infer_measurement_profile_from_text(text: Optional[str]) -> Optional[str]:
    """Infer a measurement profile from free-text description.

    The same profile names are used for rheometer and DMA where the intent is
    comparable (frequency, strain, or temperature sweep).
    """

    if text is None:
        return None

    value = str(text).strip().lower()
    if not value:
        return None

    if any(token in value for token in ("freq", "frequency", "oscill")):
        return "oscillatory_frequency_sweep"
    if any(token in value for token in ("temp", "temperature")):
        return "oscillatory_temperature_sweep"
    if any(token in value for token in ("strain", "amplitude")):
        return "oscillatory_strain_sweep"
    if any(token in value for token in ("flow", "viscos", "shear")):
        return "flow_curve"

    return None


@dataclass
class Experiment:
    """Represents a single experiment definition.

    This is an abstract description, not the raw data itself. It ties together
    a human-friendly name (e.g. "CL_uv"), strict identifiers (EXP###, S###,
    R###) and the instrument configuration name used in mfethuls.
    """

    name: str
    experiment_id: str
    instrument_name: str
    sample_id: Optional[str] = None
    run_id: Optional[str] = "R001"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.experiment_id = validate_experiment_id(self.experiment_id)
        self.sample_id = validate_sample_id(self.sample_id)
        self.run_id = validate_run_id(self.run_id)


# Minimal in-memory registry placeholder.
# In the future this can be backed by JSON/CSV or a database.
_EXPERIMENT_REGISTRY: Dict[str, Experiment] = {}


def _normalize_optional_str(value: Any) -> Optional[str]:
    """Normalize optional text fields coming from pandas records.

    Treats NaN / empty strings as ``None`` and returns a stripped string
    otherwise.
    """

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def register_experiment(exp: Experiment) -> None:
    """Register an experiment in the in-memory registry.

    For now, this is primarily useful for interactive sessions and tests.
    A file- or DB-backed registry can be added later.
    """

    _EXPERIMENT_REGISTRY[exp.name] = exp


def get_experiment(name: str) -> Experiment:
    """Retrieve an Experiment by its human-friendly name.

    Raises KeyError if the experiment is not known.
    """

    try:
        return _EXPERIMENT_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"Unknown experiment name: {name!r}") from exc


def load_experiment_registry(path: str) -> pd.DataFrame:
    """Load experiments from a CSV/Excel file into the in-memory registry.

    The file is expected to contain at least the following columns:

    - ``name``: human-friendly experiment name (used as lookup key)
    - ``experiment_id``: strict id (e.g. EXP001)
    - ``instrument_name``: must match an instrument ``name`` from the
      instrument configuration JSON.

        Optional columns (if present) are interpreted as follows:

        - ``description``: free-text description used to infer a measurement
            profile when available
        - ``measurement_profile``: canonical rheology profile name, e.g.
            ``oscillatory_frequency_sweep``
    - ``sample_id``: strict sample id (e.g. S001)
    - ``run_id``: strict run id (e.g. R001), defaults to R001 when missing
        - ``test_type``: deprecated filename-derived test type; used only as a
            fallback for profile inference if no description/profile is provided
    - any other columns are stored in ``Experiment.metadata``.

    The function returns the loaded DataFrame so callers can further filter or
    inspect the registry in notebooks or scripts.
    """

    # Resolve to an absolute path for clearer error messages.
    path = os.path.abspath(path)

    _, ext = os.path.splitext(path.lower())
    if ext in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)

    required_cols = {"name", "experiment_id", "instrument_name"}
    missing = required_cols.difference(df.columns)
    if missing:
        raise ValueError(
            f"Experiment registry at {path!r} is missing required columns: {sorted(missing)}"
        )

    records = df.to_dict(orient="records")

    for rec in records:
        name = rec.get("name")
        experiment_id = rec.get("experiment_id")
        description = _normalize_optional_str(rec.get("description"))
        explicit_measurement_profile = _normalize_optional_str(rec.get("measurement_profile"))
        legacy_test_type = _normalize_optional_str(rec.get("test_type"))

        # Normalise optional identifiers so that empty cells / NaN from
        # Excel/CSV are treated as missing.
        sample_id = _normalize_optional_str(rec.get("sample_id"))

        raw_run_id = _normalize_optional_str(rec.get("run_id"))
        run_id = raw_run_id or "R001"

        # Instrument name is required *per experiment* for analysis. Allow the
        # column to exist but individual rows may be empty/NaN to represent an
        # experiment that has not (yet) been analysed on an instrument.
        instrument_name = _normalize_optional_str(rec.get("instrument_name"))

        measurement_profile = explicit_measurement_profile or _infer_measurement_profile_from_text(description)
        if measurement_profile is None and legacy_test_type:
            measurement_profile = _infer_measurement_profile_from_text(legacy_test_type)
            if measurement_profile:
                logger.warning(
                    "Experiment %r is using deprecated test_type %r from the registry to infer measurement_profile %r; "
                    "please add an explicit measurement_profile or description column instead.",
                    name,
                    legacy_test_type,
                    measurement_profile,
                )

        if instrument_name is None:
            # Do not register this experiment for analysis; it cannot be
            # resolved by load_experiment_dataset. Emit a warning so users
            # understand why it is skipped.
            logger.warning(
                "Skipping experiment %r (id %r): no instrument_name provided in registry; "
                "experiment cannot be analysed.",
                name,
                experiment_id,
            )
            continue

        # Everything else becomes metadata.
        metadata: Dict[str, Any] = {}
        for key, value in rec.items():
            if key in {
                "name",
                "experiment_id",
                "instrument_name",
                "sample_id",
                "run_id",
                "description",
                "measurement_profile",
            }:
                continue
            metadata[key] = value

        if description is not None:
            metadata["description"] = description
        if measurement_profile is not None:
            metadata["measurement_profile"] = measurement_profile
        if legacy_test_type is not None:
            metadata["test_type"] = legacy_test_type

        exp = Experiment(
            name=name,
            experiment_id=str(experiment_id),
            instrument_name=str(instrument_name),
            sample_id=sample_id,
            run_id=run_id,
            metadata=metadata,
        )
        register_experiment(exp)

    return df
