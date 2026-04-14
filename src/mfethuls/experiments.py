from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import os

import pandas as pd

from .ids import validate_experiment_id, validate_run_id, validate_sample_id


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

    - ``sample_id``: strict sample id (e.g. S001)
    - ``run_id``: strict run id (e.g. R001), defaults to R001 when missing
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
        instrument_name = rec.get("instrument_name")

        sample_id = rec.get("sample_id")
        run_id = rec.get("run_id") or "R001"

        # Everything else becomes metadata.
        metadata: Dict[str, Any] = {}
        for key, value in rec.items():
            if key in {"name", "experiment_id", "instrument_name", "sample_id", "run_id"}:
                continue
            metadata[key] = value

        exp = Experiment(
            name=name,
            experiment_id=str(experiment_id),
            instrument_name=str(instrument_name),
            sample_id=str(sample_id) if sample_id is not None else None,
            run_id=str(run_id) if run_id is not None else None,
            metadata=metadata,
        )
        register_experiment(exp)

    return df
