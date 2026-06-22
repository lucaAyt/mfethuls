"""Shared storage interfaces and metadata schema types."""

from __future__ import annotations

from typing import Optional, Tuple, TypedDict

from ..dataset import Dataset
from ..experiments import Experiment


class DataStorageBackend:
    """Abstract base class for data storage backends."""

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        raise NotImplementedError()

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        raise NotImplementedError()

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        raise NotImplementedError()

    def load_dataset(self, experiment: Experiment) -> Dataset:
        raise NotImplementedError()


class MetadataBackend:
    """Abstract base class for metadata-only backends."""

    def persist_metadata(self, metadata: "DatasetMetadata") -> Optional[int]:
        raise NotImplementedError()


class DatasetMetadata(TypedDict, total=False):
    """Unified metadata schema for both local and Postgres storage."""

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
