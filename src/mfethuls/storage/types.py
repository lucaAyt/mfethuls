"""Shared storage interfaces and metadata schema types."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TypedDict

from ..dataset import Dataset
from ..experiments import Experiment


class DataStorageBackend:
    """Abstract base class for data storage backends."""

    # Recorded in provenance and the metadata sink, e.g. "local_filesystem", "s3".
    label: str = "local_filesystem"
    is_cloud: bool = False

    def locations(self, experiment: Experiment) -> Dict[str, Optional[str]]:
        """Where the dataset's Parquet file is stored: ``{"local": path, "cloud": path}`` (None if not there)."""
        path, _ = self.dataset_paths(experiment)
        return {"local": None, "cloud": path} if self.is_cloud else {"local": path, "cloud": None}

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        raise NotImplementedError()

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        raise NotImplementedError()

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        raise NotImplementedError()

    def load_dataset(self, experiment: Experiment) -> Dataset:
        raise NotImplementedError()

    def stored_files(self) -> Dict[Tuple[str, str], List[str]]:
        """Every stored file, by ``(instrument_name, experiment_id)`` (datasets are stored per experiment)."""
        raise NotImplementedError()

    def remove_files(self, paths: List[str]) -> None:
        """Delete stored files; paths this backend does not hold are skipped."""
        raise NotImplementedError()


class MetadataBackend:
    """Abstract base class for metadata-only backends."""

    def persist_metadata(self, metadata: "DatasetMetadata") -> Optional[int]:
        raise NotImplementedError()

    def remove_experiment(self, experiment_id: str) -> int:
        """Delete everything recorded for an experiment; returns how many records there were."""
        raise NotImplementedError()


class DatasetMetadata(TypedDict, total=False):
    """The record a metadata sink (:class:`MetadataBackend`) receives for each stored dataset."""

    experiment_id: str
    sample_id: Optional[str]
    run_id: Optional[str]
    experiment_name: str
    raw_data_filename: Optional[str]

    instrument_name: str
    instrument_type: Optional[str]
    instrument_model: Optional[str]

    dataset_name: str
    storage_path: str
    local_storage_path: Optional[str]
    cloud_storage_path: Optional[str]
    storage_format: str

    rows: int
    cols: int

    schema_version: Optional[str]
    measurement_profile: Optional[str]
    schema_normalization: Optional[dict]

    mfethuls_version: Optional[str]

    provenance: dict
