"""Storage: local Parquet datasets, the DuckDB catalog and the storage interfaces."""

from .backends import LocalParquetStorage
from .config import _get_duckdb_path, catalog_path
from .duckdb_backend import DuckDBQueryBackend, duckdb, duckdb_session
from .manager import StorageManager
from .notebook import get_dataset, list_datasets
from .types import DataStorageBackend, DatasetMetadata, MetadataBackend

__all__ = [
    "LocalParquetStorage",
    "_get_duckdb_path",
    "catalog_path",
    "DuckDBQueryBackend",
    "duckdb",
    "duckdb_session",
    "StorageManager",
    "get_dataset",
    "list_datasets",
    "DataStorageBackend",
    "DatasetMetadata",
    "MetadataBackend",
]
