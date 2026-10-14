"""Local Parquet storage for datasets and their metadata."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

import pandas as pd

from ..dataset import Dataset
from ..experiments import Experiment
from .config import _dataset_basename, _get_storage_root
from .provenance import _build_provenance_metadata, _json_default
from .types import DataStorageBackend


class LocalParquetStorage(DataStorageBackend):
    """Local filesystem storage for datasets and metadata."""

    def __init__(self, root: str | None = None) -> None:
        self.root = os.path.abspath(root or _get_storage_root())
        os.makedirs(self.root, exist_ok=True)

    def _experiment_dir(self, experiment: Experiment) -> str:
        instrument_dir = os.path.join(self.root, experiment.instrument_name)
        experiment_dir = os.path.join(instrument_dir, experiment.experiment_id)
        os.makedirs(experiment_dir, exist_ok=True)
        return experiment_dir

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        experiment_dir = self._experiment_dir(experiment)
        base = _dataset_basename(experiment)
        parquet_path = os.path.join(experiment_dir, f"{base}.parquet")
        meta_path = os.path.join(experiment_dir, f"{base}.metadata.json")
        return parquet_path, meta_path

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        parquet_path, _ = self.dataset_paths(experiment)
        return os.path.exists(parquet_path)

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        parquet_path, meta_path = self.dataset_paths(experiment)
        dataset.data.to_parquet(parquet_path, index=False)

        metadata_to_store = dict(dataset.metadata)
        metadata_to_store.setdefault("experiment_id", experiment.experiment_id)
        metadata_to_store.setdefault("sample_id", experiment.sample_id)
        metadata_to_store.setdefault("run_id", experiment.run_id)
        metadata_to_store.setdefault("instrument_name", experiment.instrument_name)
        metadata_to_store["provenance"] = _build_provenance_metadata(
            experiment,
            dataset,
            parquet_path,
            meta_path,
            storage_backend="local_filesystem",
        )

        with open(meta_path, "w", encoding="utf8") as handle:
            json.dump(metadata_to_store, handle, default=_json_default)

        return parquet_path, meta_path

    def load_dataset(self, experiment: Experiment) -> Dataset:
        parquet_path, meta_path = self.dataset_paths(experiment)
        if not os.path.exists(parquet_path):
            raise FileNotFoundError(f"No stored dataset found at {parquet_path!r}")

        data = pd.read_parquet(parquet_path)

        metadata: Dict[str, Any] = {}
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf8") as handle:
                metadata = json.load(handle)

        metadata.setdefault("experiment_id", experiment.experiment_id)
        metadata.setdefault("sample_id", experiment.sample_id)
        metadata.setdefault("run_id", experiment.run_id)
        metadata.setdefault("instrument_name", experiment.instrument_name)

        return Dataset(data=data, metadata=metadata)

    def stored_files(self) -> Dict[Tuple[str, str], List[str]]:
        found: Dict[Tuple[str, str], List[str]] = {}
        for instrument in sorted(os.listdir(self.root)):
            instrument_dir = os.path.join(self.root, instrument)
            if not os.path.isdir(instrument_dir):
                continue
            for experiment_id in sorted(os.listdir(instrument_dir)):
                experiment_dir = os.path.join(instrument_dir, experiment_id)
                if os.path.isdir(experiment_dir):
                    found[(instrument, experiment_id)] = sorted(
                        os.path.join(experiment_dir, name) for name in os.listdir(experiment_dir)
                    )
        return found

    def remove_files(self, paths: List[str]) -> None:
        for path in paths:
            path = os.path.abspath(path)
            if os.path.commonpath([path, self.root]) != self.root or not os.path.isfile(path):
                continue
            os.remove(path)
            experiment_dir = os.path.dirname(path)
            if not os.listdir(experiment_dir):
                os.rmdir(experiment_dir)
