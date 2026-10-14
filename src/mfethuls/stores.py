"""Where ingested data lives: the stores ingest, load and reconcile work with.

A :class:`Stores` bundles the manifest (experiment IDs), the dataset storage (Parquet
files), the DuckDB catalog and an optional metadata sink that receives a copy of each
catalog record. The core builds local stores (:func:`local_stores`,
:func:`open_local_stores`); other deployments build their own and pass them in.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from .manifest import FileManifestBackend, ManifestBackend
from .settings import get_settings
from .storage.backends import LocalParquetStorage
from .storage.types import DataStorageBackend, MetadataBackend


@dataclass
class Stores:
    manifest: ManifestBackend
    storage: Optional[DataStorageBackend] = None
    catalog: Any = None  # DuckDBQueryBackend; None: datasets are stored but not registered
    metadata: Optional[MetadataBackend] = None  # receives each dataset's metadata after it is stored
    cache: Optional[DataStorageBackend] = None  # where stored datasets are read from (default: storage)

    @property
    def reads_from(self) -> Optional[DataStorageBackend]:
        return self.cache or self.storage


def local_stores(*, catalog: Any = None) -> Stores:
    """The manifest file in PATH_TO_DATA and Parquet storage under PATH_TO_LOCAL_STORAGE."""

    data_root = get_settings().data_root
    if not data_root:
        raise ValueError("PATH_TO_DATA is not set: the manifest lives in the data folder.")
    return Stores(manifest=FileManifestBackend(data_root), storage=LocalParquetStorage(), catalog=catalog)


@contextmanager
def open_local_stores(*, read_only: bool = False) -> Iterator[Stores]:
    """:func:`local_stores` with the DuckDB catalog open."""

    from .storage.duckdb_backend import DuckDBQueryBackend

    with DuckDBQueryBackend(read_only=read_only) as catalog:
        yield local_stores(catalog=catalog)
