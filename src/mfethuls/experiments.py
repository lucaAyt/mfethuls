from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import logging
import os

import pandas as pd

from .registry_validator import RegistryValidator


logger = logging.getLogger(__name__)


def resolve_registry_path(path: Optional[str] = None) -> str:
    """Resolve the registry path from an explicit argument or environment defaults."""

    if path:
        return os.path.abspath(path)

    registry_path = os.environ.get("PATH_TO_REGISTRY")
    if registry_path:
        return os.path.abspath(registry_path)

    raise ValueError(
        "No registry path provided. Pass a path explicitly or set PATH_TO_REGISTRY."
    )


def _infer_measurement_profile_from_text(text: Optional[str]) -> Optional[str]:
    """Infer a measurement profile from free-text description.

    This produces a raw registry profile value (not canonical).
    The same profile names are used for rheometer and DMA where the intent is
    comparable (frequency, strain, or temperature sweep).
    Canonicalization happens later in the parser layer.
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
    a human-friendly name (e.g. "CL_uv"), the instrument configuration name,
    and optional identifiers (S###, R###).

    ``experiment_id`` is a system-assigned UUID (12-char hex) set at first
    ingest via the manifest backend — it is never user-provided.

    ``raw_data_filename`` is the stem of the raw data file as the experimentalist
    named it at the instrument (e.g. "chitosan_jan15"). Defaults to ``name``
    when not declared in the registry.
    """

    name: str
    instrument_name: Optional[str]
    experiment_id: Optional[str] = None
    raw_data_filename: Optional[str] = None
    sample_id: Optional[str] = None
    run_id: Optional[str] = "R001"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.sample_id = RegistryValidator.validate_sample_id(self.sample_id)
        self.run_id = RegistryValidator.validate_run_id(self.run_id)
        if self.instrument_name is None:
            return
        self.instrument_name = str(self.instrument_name).strip().casefold()


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


def clear_experiment_registry() -> None:
    """Clear all entries from the in-memory registry.

    Called by the worker before each job so that experiments removed from the
    shared registry between runs are not carried forward as stale entries.
    """
    _EXPERIMENT_REGISTRY.clear()


@dataclass
class RegistryRowResult:
    """Outcome of parsing a single registry spreadsheet row."""

    experiment: Optional[Experiment]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def experiment_from_registry_record(rec: dict) -> RegistryRowResult:
    """Build an Experiment from a registry row without registering it."""

    errors: List[str] = []
    warnings: List[str] = []

    name = _normalize_optional_str(rec.get("name"))
    if name is None:
        errors.append("missing required field: name")
        return RegistryRowResult(experiment=None, errors=errors, warnings=warnings)

    raw_data_filename = _normalize_optional_str(rec.get("raw_data_filename")) or name

    description = _normalize_optional_str(rec.get("description"))
    explicit_measurement_profile = _normalize_optional_str(rec.get("measurement_profile"))
    sample_id = _normalize_optional_str(rec.get("sample_id"))
    raw_run_id = _normalize_optional_str(rec.get("run_id"))
    run_id = raw_run_id or "R001"
    instrument_name = _normalize_optional_str(rec.get("instrument_name"))

    measurement_profile = explicit_measurement_profile or _infer_measurement_profile_from_text(
        description
    )

    if instrument_name is None:
        warnings.append(
            "missing instrument_name; row is visible in the registry but cannot be analysed yet"
        )

    metadata: Dict[str, Any] = {}
    _known_keys = {
        "name",
        "raw_data_filename",
        "instrument_name",
        "sample_id",
        "run_id",
        "description",
        "measurement_profile",
    }
    for key, value in rec.items():
        if key in _known_keys:
            continue
        metadata[key] = value

    if description is not None:
        metadata["description"] = description
    if measurement_profile is not None:
        metadata["registry_measurement_profile"] = measurement_profile

    exp = Experiment(
        name=name,
        instrument_name=instrument_name,
        raw_data_filename=raw_data_filename,
        sample_id=sample_id,
        run_id=run_id,
        metadata=metadata,
    )
    return RegistryRowResult(experiment=exp, errors=errors, warnings=warnings)


def get_experiment(name: str) -> Experiment:
    """Retrieve an Experiment by its human-friendly name.

    Raises KeyError if the experiment is not known.
    """

    try:
        return _EXPERIMENT_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"Unknown experiment name: {name!r}") from exc


def read_tabular_content(path: str) -> pd.DataFrame:
    """Read a CSV/XLSX file into a DataFrame."""

    _, ext = os.path.splitext(path.lower())
    if ext in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    elif ext in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    return df


def load_experiment_registry(
    path: Optional[str] = None,
    *,
    check_data_paths: bool = False,
    data_root: Optional[str] = None,
) -> pd.DataFrame:
    """Load experiments from a CSV/Excel file into the in-memory registry.

    The file is expected to contain at least the following columns:

    - ``name``: human-friendly experiment name (used as lookup key, must be unique)
    - ``instrument_name``: must match an instrument ``name`` from the
      instrument configuration JSON.

    Optional columns (if present) are interpreted as follows:

    - ``raw_data_filename``: stem of the raw data file as named at the
        instrument (e.g. "chitosan_jan15"). Defaults to ``name`` when absent.
        Must be unique per ``instrument_name``.
    - ``description``: free-text description used to infer a measurement
        profile (raw registry value) when explicit measurement_profile absent
    - ``measurement_profile``: raw registry measurement profile name (e.g.
        "frequency Sweep" or "oscillatory_frequency_sweep").
        This is stored as ``registry_measurement_profile`` in Experiment.metadata.
        Canonicalization happens later in the parser layer.
    - ``sample_id``: strict sample id (e.g. S001)
    - ``run_id``: strict run id (e.g. R001), defaults to R001 when missing
    - any other columns are stored in ``Experiment.metadata``.

    The function returns the loaded DataFrame so callers can further filter or
    inspect the registry in notebooks or scripts.
    """

    # Resolve to an absolute path for clearer error messages.
    path = resolve_registry_path(path)
    df = read_tabular_content(path)

    required_cols = {"name", "instrument_name"}
    missing = required_cols.difference(df.columns)
    if missing:
        raise ValueError(
            f"Experiment registry at {path!r} is missing required columns: {sorted(missing)}"
        )

    if "raw_data_filename" not in df.columns:
        logger.warning(
            "Registry at %r has no 'raw_data_filename' column — defaulting to 'name' for each row.",
            path,
        )

    validator = RegistryValidator()
    records = df.to_dict(orient="records")

    for rec in records:
        row_result = experiment_from_registry_record(rec)
        if row_result.errors:
            logger.warning(
                "Skipping registry row %r: %s",
                rec.get("name"),
                "; ".join(row_result.errors),
            )
            continue
        if row_result.experiment is None:
            continue

        extra_errors, extra_warnings = validator.validate_experiment_details(
            row_result.experiment,
            check_data_paths=check_data_paths,
            data_root=data_root,
        )
        if extra_errors:
            logger.warning(
                "Skipping registry row %r: %s",
                rec.get("name"),
                "; ".join(extra_errors),
            )
            continue

        for message in row_result.warnings:
            logger.warning("Registry row %r: %s", rec.get("name"), message)
        for _, message in extra_warnings:
            logger.warning("Registry row %r: %s", rec.get("name"), message)

        register_experiment(row_result.experiment)

    return df
