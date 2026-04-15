from __future__ import annotations

import json
import os
from typing import Tuple

import pandas as pd

from .dataset import Dataset
from .experiments import Experiment


def _get_storage_root() -> str:
    """Return the root folder for stored datasets.

    Resolution order (first non-empty wins):

    - ``PATH_TO_LOCAL_STORAGE`` env var
    - ``PATH_TO_STORAGE`` env var (legacy name)
    - ``MFETHULS_STORAGE_ROOT`` env var
    - ``PATH_TO_DATA`` env var + ``_storage`` subfolder
    - current working directory + ``.mfethuls_storage``

    The directory is created if it does not exist.
    """

    for key in ("PATH_TO_LOCAL_STORAGE", "PATH_TO_STORAGE", "MFETHULS_STORAGE_ROOT"):
        value = os.environ.get(key)
        if value:
            root = os.path.abspath(value)
            os.makedirs(root, exist_ok=True)
            return root

    data_root = os.environ.get("PATH_TO_DATA")
    if data_root:
        root = os.path.abspath(os.path.join(data_root, "_storage"))
    else:
        root = os.path.abspath(os.path.join(os.getcwd(), ".mfethuls_storage"))

    os.makedirs(root, exist_ok=True)
    return root


def _dataset_basename(experiment: Experiment) -> str:
    """Construct a stable base filename for a dataset.

    By default this uses ``experiment_id[_sample_id][_run_id]`` so that
    multiple samples or runs of the same experiment can be stored
    side-by-side without clashing.
    """

    parts = [experiment.experiment_id]
    if experiment.sample_id:
        parts.append(experiment.sample_id)
    if experiment.run_id:
        parts.append(experiment.run_id)
    return "_".join(parts)


def dataset_paths(experiment: Experiment) -> Tuple[str, str]:
    """Return (parquet_path, metadata_path) for a given experiment."""

    root = _get_storage_root()
    instrument_dir = os.path.join(root, experiment.instrument_name)
    os.makedirs(instrument_dir, exist_ok=True)

    base = _dataset_basename(experiment)
    parquet_path = os.path.join(instrument_dir, f"{base}.parquet")
    meta_path = os.path.join(instrument_dir, f"{base}.metadata.json")
    return parquet_path, meta_path


def dataset_in_storage(experiment: Experiment) -> bool:
    """Return True if a stored dataset exists for this experiment."""

    parquet_path, _ = dataset_paths(experiment)
    return os.path.exists(parquet_path)


def _json_default(value):  # pragma: no cover - simple fallback helper
    """Best-effort JSON serialisation for metadata.

    Falls back to ``str(value)`` for objects that the standard JSON encoder
    cannot handle (e.g. numpy scalars).
    """

    try:
        import numpy as np  # type: ignore[import]

        if isinstance(value, (np.generic,)):
            return value.item()
    except Exception:  # noqa: BLE001
        # numpy is optional; ignore import or other errors
        pass

    return str(value)


def save_dataset_to_storage(experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
    """Persist a Dataset for the given experiment to local storage.

    Returns the paths to the parquet and metadata files.
    """

    parquet_path, meta_path = dataset_paths(experiment)
    # Do not store the index by default; it can be reconstructed.
    dataset.data.to_parquet(parquet_path, index=False)

    with open(meta_path, "w", encoding="utf8") as f:
        json.dump(dataset.metadata, f, default=_json_default)

    return parquet_path, meta_path


def load_dataset_from_storage(experiment: Experiment) -> Dataset:
    """Load a Dataset for the given experiment from local storage.

    Raises FileNotFoundError if the parquet file is missing.
    """

    parquet_path, meta_path = dataset_paths(experiment)

    if not os.path.exists(parquet_path):
        raise FileNotFoundError(f"No stored dataset found at {parquet_path!r}")

    data = pd.read_parquet(parquet_path)

    metadata = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf8") as f:
            metadata = json.load(f)

    # Ensure core identifiers are present otherwise insert default in metadata for convenience.
    metadata.setdefault("experiment_id", experiment.experiment_id)
    metadata.setdefault("sample_id", experiment.sample_id)
    metadata.setdefault("run_id", experiment.run_id)
    metadata.setdefault("instrument_name", experiment.instrument_name)

    return Dataset(data=data, metadata=metadata)
