"""Composition layer for storage, metadata, and query backends."""

from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from ..experiments import Experiment
from .backends import AzureBlobParquetStorage, CombinedStorageBackend, LocalParquetStorage, S3ParquetStorage
from .config import _dataset_basename, _view_basename, _get_package_version
from .provenance import _build_provenance_metadata
from .types import DataStorageBackend, DatasetMetadata, MetadataBackend
from .duckdb_backend import DuckDBQueryBackend


def _get_storage_backend_label(data_backend: DataStorageBackend) -> str:
    if isinstance(data_backend, CombinedStorageBackend):
        return _get_storage_backend_label(data_backend.primary)
    if isinstance(data_backend, S3ParquetStorage):
        return "s3"
    if isinstance(data_backend, AzureBlobParquetStorage):
        return "azure_blob"
    return "local_filesystem"


def _is_cloud_backend(data_backend: DataStorageBackend) -> bool:
    return isinstance(data_backend, (S3ParquetStorage, AzureBlobParquetStorage))


def _prepare_registration_metadata(
    experiment: Experiment,
    dataset: Dataset,
    parquet_path: str,
    meta_path: str,
    storage_backend: str,
    local_storage_path: Optional[str] = None,
    cloud_storage_path: Optional[str] = None,
) -> DatasetMetadata:
    metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}
    provenance = _build_provenance_metadata(
        experiment,
        dataset,
        parquet_path,
        meta_path,
        storage_backend=storage_backend,
    )

    return DatasetMetadata(
        experiment_id=experiment.experiment_id,
        sample_id=experiment.sample_id,
        run_id=experiment.run_id,
        experiment_name=experiment.name,
        raw_data_filename=experiment.raw_data_filename,
        instrument_name=experiment.instrument_name,
        instrument_type=metadata.get("instrument_type"),
        instrument_model=metadata.get("instrument_model"),
        dataset_name=_dataset_basename(experiment),
        storage_path=parquet_path,
        local_storage_path=local_storage_path,
        cloud_storage_path=cloud_storage_path,
        storage_format="parquet",
        rows=int(dataset.data.shape[0]),
        cols=int(dataset.data.shape[1]),
        schema_version=metadata.get("schema_version"),
        measurement_profile=metadata.get("measurement_profile"),
        schema_normalization=metadata.get("schema_normalization"),
        mfethuls_version=metadata.get("mfethuls_version") or _get_package_version(),
        provenance=provenance,
    )


class StorageManager:
    """Compose data, metadata, and optional query backends."""

    def __init__(
        self,
        data_backend: Optional[DataStorageBackend] = None,
        metadata_backend: Optional[MetadataBackend] = None,
        query_backend: Optional[DuckDBQueryBackend] = None,
    ) -> None:
        self.data_backend = data_backend or LocalParquetStorage()
        self.metadata_backend = metadata_backend
        self.query_backend = query_backend

    def save_and_persist(
        self, experiment: Experiment, dataset: Dataset
    ) -> Tuple[str, str, Optional[int]]:
        parquet_path, meta_path = self.data_backend.save_dataset(experiment, dataset)
        local_storage_path: Optional[str] = None
        cloud_storage_path: Optional[str] = None

        if isinstance(self.data_backend, CombinedStorageBackend):
            primary_path, _ = self.data_backend.primary.dataset_paths(experiment)
            secondary_path, _ = self.data_backend.secondary.dataset_paths(experiment)
            if _is_cloud_backend(self.data_backend.primary):
                cloud_storage_path = primary_path
            else:
                local_storage_path = primary_path
            if _is_cloud_backend(self.data_backend.secondary):
                cloud_storage_path = secondary_path
            else:
                local_storage_path = secondary_path
        elif _is_cloud_backend(self.data_backend):
            cloud_storage_path = parquet_path
        else:
            local_storage_path = parquet_path

        dataset_id: Optional[int] = None
        if self.metadata_backend is not None:
            storage_backend = _get_storage_backend_label(self.data_backend)
            metadata = _prepare_registration_metadata(
                experiment,
                dataset,
                parquet_path,
                meta_path,
                storage_backend=storage_backend,
                local_storage_path=local_storage_path,
                cloud_storage_path=cloud_storage_path,
            )
            dataset_id = self.metadata_backend.persist_metadata(metadata)
        if self.query_backend is not None:
            self.query_backend.register_parquet(
                parquet_path,
                table_name=_view_basename(experiment),
                experiment_name=experiment.name,
                raw_data_filename=experiment.raw_data_filename,
            )
        return parquet_path, meta_path, dataset_id
