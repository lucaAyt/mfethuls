"""Composition layer for storage, metadata, and query backends."""

from __future__ import annotations

from typing import Optional, Tuple

from ..dataset import Dataset
from ..experiments import Experiment
from .backends import LocalParquetStorage
from .catalog import CatalogRecord
from .config import _dataset_basename, _get_package_version
from .provenance import _build_provenance_metadata
from .types import DataStorageBackend, DatasetMetadata, MetadataBackend
from .duckdb_backend import DuckDBQueryBackend


def _prepare_registration_metadata(
    record: CatalogRecord,
    experiment: Experiment,
    dataset: Dataset,
    meta_path: str,
    storage_backend: str,
    local_storage_path: Optional[str] = None,
    cloud_storage_path: Optional[str] = None,
) -> DatasetMetadata:
    """The metadata-sink record: the catalog record plus storage and provenance details."""

    metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}
    provenance = _build_provenance_metadata(
        experiment,
        dataset,
        record.storage_path,
        meta_path,
        storage_backend=storage_backend,
    )

    return DatasetMetadata(
        experiment_id=record.experiment_id,
        sample_id=record.sample_id,
        run_id=record.run_id,
        experiment_name=record.experiment_name,
        raw_data_filename=record.raw_data_filename,
        instrument_name=record.instrument_name,
        instrument_type=record.instrument_type,
        instrument_model=record.instrument_model,
        dataset_name=_dataset_basename(experiment),
        storage_path=record.storage_path,
        local_storage_path=local_storage_path,
        cloud_storage_path=cloud_storage_path,
        storage_format="parquet",
        rows=record.rows,
        cols=int(dataset.data.shape[1]),
        schema_version=metadata.get("schema_version"),
        measurement_profile=record.measurement_profile,
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
        locations = self.data_backend.locations(experiment)

        # One record feeds both the DuckDB catalog and the metadata sink.
        record = CatalogRecord.build(
            experiment,
            parquet_path,
            dataset_metadata=dataset.metadata if isinstance(dataset.metadata, dict) else None,
            rows=int(dataset.data.shape[0]),
        )

        dataset_id: Optional[int] = None
        if self.metadata_backend is not None:
            metadata = _prepare_registration_metadata(
                record,
                experiment,
                dataset,
                meta_path,
                storage_backend=self.data_backend.label,
                local_storage_path=locations.get("local"),
                cloud_storage_path=locations.get("cloud"),
            )
            dataset_id = self.metadata_backend.persist_metadata(metadata)
        if self.query_backend is not None:
            self.query_backend.register_parquet(parquet_path, record=record)
        return parquet_path, meta_path, dataset_id
