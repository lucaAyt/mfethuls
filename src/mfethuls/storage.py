"""Storage layer: data + metadata handling for mfethuls.

This module separates concerns into:
- DataStorageBackend: manages bulk dataset files (Parquet, S3, etc.)
- MetadataBackend: manages searchable metadata (Postgres, etc.)
- StorageManager: composes data and metadata backends for common flows

Organization (sections present in-file):
1. Abstract Base Classes & Type Definitions
2. Configuration & Environment Utilities
3. Local Parquet Storage Implementation
4. Provenance & Metadata Helpers
5. Postgres Metadata Backend
6. DuckDB Query Backend
7. Storage Manager (Composition Layer)
8. Public Module Wrappers (for notebooks)
"""

from __future__ import annotations

import io
import json
import os
import re
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import pandas as pd

try:
    import duckdb  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    duckdb = None  # type: ignore

try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
    from botocore.config import Config  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    boto3 = None  # type: ignore
    ClientError = None  # type: ignore
    Config = None  # type: ignore

try:
    from azure.storage.blob import BlobServiceClient  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BlobServiceClient = None  # type: ignore

try:
    from sqlalchemy import create_engine, MetaData, text
    from sqlalchemy.exc import SQLAlchemyError
except Exception:  # pragma: no cover - optional dependency
    create_engine = None  # type: ignore

from .dataset import Dataset
from .experiments import Experiment


# Note: older monolithic `StorageBackend` was split into `DataStorageBackend`
# and `MetadataBackend` to clearly separate file storage from metadata APIs.


class DataStorageBackend:
    """Abstract base class for data storage backends.

    This interface covers backends that manage bulk dataset files (Parquet,
    S3 objects, DuckDB tables, etc.). It intentionally excludes metadata-only
    operations which belong on :class:`MetadataBackend`.
    """

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        """Return (parquet_path, metadata_path) for an experiment."""
        raise NotImplementedError()

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        """Check if a dataset exists in storage for the given experiment."""
        raise NotImplementedError()

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        """Persist a dataset. Returns (parquet_path, metadata_path)."""
        raise NotImplementedError()

    def load_dataset(self, experiment: Experiment) -> Dataset:
        """Load a dataset from storage."""
        raise NotImplementedError()


class MetadataBackend:
    """Abstract base class for metadata-only backends.

    Implementations store searchable metadata (for example Postgres). This
    interface intentionally focuses on metadata operations and does not touch
    raw dataset files.
    """

    def persist_metadata(self, metadata: DatasetMetadata) -> Optional[int]:
        """Persist dataset metadata and return the inserted dataset id if any."""
        raise NotImplementedError()


class DatasetMetadata(TypedDict, total=False):
    """Unified metadata schema for both local and Postgres storage.

    Used by LocalParquetStorage and PostgresMetadataBackend to ensure
    consistent metadata handling. All query-relevant fields are defined here.

    See docs/database_integration.md for schema design rationale.
    """

    # Core identifiers (indexed for filtering)
    experiment_id: str
    sample_id: Optional[str]
    run_id: Optional[str]
    experiment_name: str

    # Instrument info (indexed for filtering by instrument type, model, etc.)
    instrument_name: str
    instrument_type: Optional[str]
    instrument_model: Optional[str]

    # Data storage info
    dataset_name: str
    storage_path: str
    storage_format: str  # Default: 'parquet'

    # Data shape (useful for filtering by dataset size)
    rows: int
    cols: int

    # Processing metadata (extracted from provenance for easier querying)
    schema_version: Optional[str]
    measurement_profile: Optional[str]
    schema_normalization: Optional[Dict[str, Any]]  # JSONB in Postgres
    
    # Package version (explicit for easy querying)
    mfethuls_version: Optional[str]

    # Full audit trail (provenance is the rich metadata blob)
    provenance: Dict[str, Any]  # JSONB in Postgres


# ======================================================================
# SECTION 2: Configuration & Environment Utilities
# ======================================================================


def _get_package_version() -> str:
    """Return installed package version for provenance metadata."""

    try:
        return str(version("mfethuls"))
    except PackageNotFoundError:
        return "unknown"


def _get_storage_root() -> str:
    """Return the root folder for stored datasets.

    Resolution order (first non-empty wins):
    - ``PATH_TO_LOCAL_STORAGE`` env var
    - ``PATH_TO_STORAGE`` env var (legacy name)
    - ``MFETHULS_STORAGE_ROOT`` env var
    - ``PATH_TO_DATA`` env var + ``_storage`` subfolder
    - current working directory + ``.mfethuls_storage``
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


def _get_duckdb_path() -> str:
    """Return the DuckDB file path for local query storage.

    Resolution order (first non-empty wins):
    - ``MFETHULS_DUCKDB_PATH`` env var
    - ``<storage_root>/mfethuls.duckdb``
    """

    path = os.environ.get("MFETHULS_DUCKDB_PATH")
    if path:
        return os.path.abspath(path)

    return os.path.join(_get_storage_root(), "mfethuls.duckdb")


def _normalize_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ""
    return prefix.strip("/")


def _join_storage_key(*parts: Optional[str]) -> str:
    cleaned = [part.strip("/") for part in parts if part and part.strip("/")]
    return "/".join(cleaned)


def _get_s3_config() -> Dict[str, Optional[str]]:
    return {
        "bucket": os.environ.get("MFETHULS_S3_BUCKET"),
        "prefix": _normalize_prefix(os.environ.get("MFETHULS_S3_PREFIX")),
        "region": os.environ.get("MFETHULS_S3_REGION"),
        "endpoint": os.environ.get("MFETHULS_S3_ENDPOINT"),
    }

def _construct_s3_endpoint_url() -> Optional[str]:
    config = _get_s3_config()
    return f"https://{config['bucket']}.{config['region']}.{config['endpoint']}"


def _get_azure_blob_config() -> Dict[str, Optional[str]]:
    return {
        "connection_string": os.environ.get("MFETHULS_AZURE_CONNECTION_STRING"),
        "account": os.environ.get("MFETHULS_AZURE_ACCOUNT"),
        "container": os.environ.get("MFETHULS_AZURE_CONTAINER"),
        "prefix": _normalize_prefix(os.environ.get("MFETHULS_AZURE_PREFIX")),
        "key": os.environ.get("MFETHULS_AZURE_KEY"),
        "sas_token": os.environ.get("MFETHULS_AZURE_SAS_TOKEN"),
    }


# ======================================================================
# SECTION 3: Local Parquet Storage Implementation
# ======================================================================


def get_postgres_db_url() -> Optional[str]:
    """Load Postgres database URL from environment.

    Resolution order:
    1. ``MFETHULS_POSTGRES_URL`` if set (backward compatibility)
    2. Construct from individual components:
       - MFETHULS_POSTGRES_USER (required)
       - MFETHULS_POSTGRES_PASSWORD (required)
       - MFETHULS_POSTGRES_HOST (default: localhost)
       - MFETHULS_POSTGRES_PORT (default: 5432)
       - MFETHULS_POSTGRES_DB (required)
    3. Returns None if disabled or not fully configured

    Environment variables:
    - MFETHULS_POSTGRES_ENABLED: Set to 'true', '1', 'yes' to enable (default: false)
    - MFETHULS_POSTGRES_URL: Full connection string (optional, overrides component vars)
    - MFETHULS_POSTGRES_USER: Database user
    - MFETHULS_POSTGRES_PASSWORD: Database password
    - MFETHULS_POSTGRES_HOST: Database host (default: localhost)
    - MFETHULS_POSTGRES_PORT: Database port (default: 5432)
    - MFETHULS_POSTGRES_DB: Database name

    Example .env entries:

    Option 1 - Full URL:
        MFETHULS_POSTGRES_ENABLED=true
        MFETHULS_POSTGRES_URL=postgresql://mfethuls:testpass@localhost:5432/mfethuls

    Option 2 - Components (more flexible):
        MFETHULS_POSTGRES_ENABLED=true
        MFETHULS_POSTGRES_USER=mfethuls
        MFETHULS_POSTGRES_PASSWORD=testpass
        MFETHULS_POSTGRES_DB=mfethuls
        MFETHULS_POSTGRES_PORT=5432
        MFETHULS_POSTGRES_HOST=localhost

    Returns:
        The Postgres connection URL if enabled, or None otherwise.
    """

    enabled = os.environ.get("MFETHULS_POSTGRES_ENABLED", "").lower()
    if enabled not in {"1", "true", "yes"}:
        return None

    # Construct URL from .env components
    user = os.environ.get("MFETHULS_POSTGRES_USER")
    password = os.environ.get("MFETHULS_POSTGRES_PASSWORD")
    host = os.environ.get("MFETHULS_POSTGRES_HOST", "localhost")
    port = os.environ.get("MFETHULS_POSTGRES_PORT")
    database = os.environ.get("MFETHULS_POSTGRES_DB")

    if not (user and password and database):
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            "MFETHULS_POSTGRES_ENABLED is true but required credentials are missing. "
            "Provide either MFETHULS_POSTGRES_URL or all of: "
            "MFETHULS_POSTGRES_USER, MFETHULS_POSTGRES_PASSWORD, MFETHULS_POSTGRES_DB. "
            "Postgres registration disabled."
        )
        return None

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


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


 
class LocalParquetStorage(DataStorageBackend):
    """Local filesystem storage for datasets and metadata.

    The on-disk layout is intentionally simple and readable:

    - ``<root>/<instrument_name>/<experiment_id>/<dataset_base>.parquet``
    - ``<root>/<instrument_name>/<experiment_id>/<dataset_base>.metadata.json``

    This keeps related files together, makes manual inspection easy, and gives
    us a clean contract for later Postgres-backed indexing.
    """

    def __init__(self, root: str | None = None) -> None:
        self.root = os.path.abspath(root or _get_storage_root())
        os.makedirs(self.root, exist_ok=True)

    def _experiment_dir(self, experiment: Experiment) -> str:
        instrument_dir = os.path.join(self.root, experiment.instrument_name)
        experiment_dir = os.path.join(instrument_dir, experiment.experiment_id)
        os.makedirs(experiment_dir, exist_ok=True)
        return experiment_dir

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        """Return the parquet and metadata paths for an experiment."""

        experiment_dir = self._experiment_dir(experiment)
        base = _dataset_basename(experiment)
        parquet_path = os.path.join(experiment_dir, f"{base}.parquet")
        meta_path = os.path.join(experiment_dir, f"{base}.metadata.json")
        return parquet_path, meta_path

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        parquet_path, _ = self.dataset_paths(experiment)
        return os.path.exists(parquet_path)

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        """Persist a dataset as Parquet plus JSON metadata.

        Returns the ``(parquet_path, metadata_path)`` tuple.
        """

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

        with open(meta_path, "w", encoding="utf8") as f:
            json.dump(metadata_to_store, f, default=_json_default)

        return parquet_path, meta_path

    def load_dataset(self, experiment: Experiment) -> Dataset:
        """Load a dataset previously saved with :meth:`save_dataset`."""

        parquet_path, meta_path = self.dataset_paths(experiment)
        if not os.path.exists(parquet_path):
            raise FileNotFoundError(f"No stored dataset found at {parquet_path!r}")

        data = pd.read_parquet(parquet_path)

        metadata: Dict[str, Any] = {}
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf8") as f:
                metadata = json.load(f)

        metadata.setdefault("experiment_id", experiment.experiment_id)
        metadata.setdefault("sample_id", experiment.sample_id)
        metadata.setdefault("run_id", experiment.run_id)
        metadata.setdefault("instrument_name", experiment.instrument_name)

        return Dataset(data=data, metadata=metadata)


class S3ParquetStorage(DataStorageBackend):
    """S3-backed storage for datasets and metadata JSON files."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: Optional[str] = None,
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        client: Any = None,
    ) -> None:
        if boto3 is None or ClientError is None:
            raise RuntimeError("boto3 is required for S3ParquetStorage. Install boto3.")

        config = _get_s3_config()
        self.bucket = bucket or config.get("bucket")
        self.prefix = _normalize_prefix(prefix or config.get("prefix"))
        self.region = region or config.get("region")
        self.endpoint_url = endpoint_url or _construct_s3_endpoint_url()

        if not self.bucket:
            raise ValueError("S3 bucket is required. Set MFETHULS_S3_BUCKET or pass bucket.")

        # Allow an explicit client (useful for mocking), or a session which
        # will be used to create a client. If neither is provided, fall back
        # to the default boto3.client. Endpoint support enables S3-compatible
        # services (DigitalOcean Spaces, MinIO, etc.).
        self.client = client or boto3.client("s3", 
                                             region_name=self.region,
                                             endpoint_url=self.endpoint_url,
                                             aws_access_key_id=os.environ.get("MFETHULS_S3_ACCESS_KEY"),
                                             aws_secret_access_key=os.environ.get("MFETHULS_S3_SECRET_KEY"),
                                             config=Config(signature_version="s3v4"))

    def _s3_key(self, experiment: Experiment, suffix: str) -> str:
        base = _dataset_basename(experiment)
        filename = f"{base}{suffix}"
        return _join_storage_key(self.prefix, experiment.instrument_name, experiment.experiment_id, filename)

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        parquet_key = self._s3_key(experiment, ".parquet")
        meta_key = self._s3_key(experiment, ".metadata.json")
        parquet_path = f"s3://{self.bucket}/{parquet_key}"
        meta_path = f"s3://{self.bucket}/{meta_key}"
        return parquet_path, meta_path

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        parquet_key = self._s3_key(experiment, ".parquet")
        try:
            self.client.head_object(Bucket=self.bucket, Key=parquet_key)
            return True
        except ClientError:
            return False

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        parquet_key = self._s3_key(experiment, ".parquet")
        meta_key = self._s3_key(experiment, ".metadata.json")
        parquet_path, meta_path = self.dataset_paths(experiment)

        parquet_buffer = io.BytesIO()
        dataset.data.to_parquet(parquet_buffer, index=False)
        parquet_buffer.seek(0)
        self.client.put_object(Bucket=self.bucket, Key=parquet_key, Body=parquet_buffer.getvalue())

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
            storage_backend="s3",
        )

        meta_body = json.dumps(metadata_to_store, default=_json_default).encode("utf8")
        self.client.put_object(
            Bucket=self.bucket,
            Key=meta_key,
            Body=meta_body,
            ContentType="application/json",
        )

        return parquet_path, meta_path

    def load_dataset(self, experiment: Experiment) -> Dataset:
        parquet_key = self._s3_key(experiment, ".parquet")
        meta_key = self._s3_key(experiment, ".metadata.json")

        try:
            parquet_obj = self.client.get_object(Bucket=self.bucket, Key=parquet_key)
        except ClientError as exc:
            raise FileNotFoundError(f"No stored dataset found at s3://{self.bucket}/{parquet_key}") from exc

        parquet_bytes = parquet_obj["Body"].read()
        data = pd.read_parquet(io.BytesIO(parquet_bytes))

        metadata: Dict[str, Any] = {}
        try:
            meta_obj = self.client.get_object(Bucket=self.bucket, Key=meta_key)
            metadata = json.loads(meta_obj["Body"].read().decode("utf8"))
        except ClientError:
            metadata = {}

        metadata.setdefault("experiment_id", experiment.experiment_id)
        metadata.setdefault("sample_id", experiment.sample_id)
        metadata.setdefault("run_id", experiment.run_id)
        metadata.setdefault("instrument_name", experiment.instrument_name)

        return Dataset(data=data, metadata=metadata)


class AzureBlobParquetStorage(DataStorageBackend):
    """Azure Blob storage backend for datasets and metadata JSON files."""

    def __init__(
        self,
        account: Optional[str] = None,
        container: Optional[str] = None,
        prefix: Optional[str] = None,
        connection_string: Optional[str] = None,
        credential: Optional[str] = None,
        service_client: Any = None,
    ) -> None:
        if BlobServiceClient is None:
            raise RuntimeError(
                "azure-storage-blob is required for AzureBlobParquetStorage. Install azure-storage-blob."
            )

        config = _get_azure_blob_config()
        self.connection_string = connection_string or config.get("connection_string")
        self.account = account or config.get("account")
        self.container = container or config.get("container")
        self.prefix = _normalize_prefix(prefix or config.get("prefix"))
        self.credential = credential or config.get("key") or config.get("sas_token")

        if not self.container:
            raise ValueError("Azure container is required. Set MFETHULS_AZURE_CONTAINER or pass container.")

        if service_client is not None:
            self.service_client = service_client
        elif self.connection_string:
            self.service_client = BlobServiceClient.from_connection_string(self.connection_string)
        else:
            if not self.account:
                raise ValueError(
                    "Azure account is required. Set MFETHULS_AZURE_ACCOUNT or MFETHULS_AZURE_CONNECTION_STRING."
                )
            account_url = f"https://{self.account}.blob.core.windows.net"
            self.service_client = BlobServiceClient(account_url=account_url, credential=self.credential)

        self.container_client = self.service_client.get_container_client(self.container)

    def _blob_key(self, experiment: Experiment, suffix: str) -> str:
        base = _dataset_basename(experiment)
        filename = f"{base}{suffix}"
        return _join_storage_key(self.prefix, experiment.instrument_name, experiment.experiment_id, filename)

    def _blob_url(self, blob_key: str) -> str:
        account_name = self.account or self.service_client.account_name
        return f"https://{account_name}.blob.core.windows.net/{self.container}/{blob_key}"

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        parquet_key = self._blob_key(experiment, ".parquet")
        meta_key = self._blob_key(experiment, ".metadata.json")
        parquet_path = self._blob_url(parquet_key)
        meta_path = self._blob_url(meta_key)
        return parquet_path, meta_path

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        parquet_key = self._blob_key(experiment, ".parquet")
        blob_client = self.container_client.get_blob_client(parquet_key)
        try:
            blob_client.get_blob_properties()
            return True
        except Exception:
            return False

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        parquet_key = self._blob_key(experiment, ".parquet")
        meta_key = self._blob_key(experiment, ".metadata.json")
        parquet_path, meta_path = self.dataset_paths(experiment)

        parquet_buffer = io.BytesIO()
        dataset.data.to_parquet(parquet_buffer, index=False)
        parquet_buffer.seek(0)

        parquet_client = self.container_client.get_blob_client(parquet_key)
        parquet_client.upload_blob(parquet_buffer.getvalue(), overwrite=True)

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
            storage_backend="azure_blob",
        )

        meta_body = json.dumps(metadata_to_store, default=_json_default).encode("utf8")
        meta_client = self.container_client.get_blob_client(meta_key)
        meta_client.upload_blob(meta_body, overwrite=True)

        return parquet_path, meta_path

    def load_dataset(self, experiment: Experiment) -> Dataset:
        parquet_key = self._blob_key(experiment, ".parquet")
        meta_key = self._blob_key(experiment, ".metadata.json")

        parquet_client = self.container_client.get_blob_client(parquet_key)
        try:
            parquet_bytes = parquet_client.download_blob().readall()
        except Exception as exc:
            raise FileNotFoundError(f"No stored dataset found at {self._blob_url(parquet_key)}") from exc

        data = pd.read_parquet(io.BytesIO(parquet_bytes))

        metadata: Dict[str, Any] = {}
        meta_client = self.container_client.get_blob_client(meta_key)
        try:
            metadata = json.loads(meta_client.download_blob().readall().decode("utf8"))
        except Exception:
            metadata = {}

        metadata.setdefault("experiment_id", experiment.experiment_id)
        metadata.setdefault("sample_id", experiment.sample_id)
        metadata.setdefault("run_id", experiment.run_id)
        metadata.setdefault("instrument_name", experiment.instrument_name)

        return Dataset(data=data, metadata=metadata)


class CombinedStorageBackend(DataStorageBackend):
    """Persist datasets to multiple backends while using one as canonical."""

    def __init__(self, primary: DataStorageBackend, secondary: DataStorageBackend) -> None:
        self.primary = primary
        self.secondary = secondary

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        return self.primary.dataset_paths(experiment)

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        return self.primary.dataset_in_storage(experiment)

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        paths = self.primary.save_dataset(experiment, dataset)
        try:
            self.secondary.save_dataset(experiment, dataset)
        except Exception:
            pass
        return paths

    def load_dataset(self, experiment: Experiment) -> Dataset:
        return self.primary.load_dataset(experiment)


    # ======================================================================
    # SECTION 4: Provenance & Metadata Helpers
    # ======================================================================


def dataset_paths(experiment: Experiment) -> Tuple[str, str]:
    """Return the storage paths for an experiment.

    This wrapper preserves the historical API while delegating to
    ``LocalParquetStorage``.
    """

    return LocalParquetStorage().dataset_paths(experiment)


def dataset_in_storage(experiment: Experiment) -> bool:
    """Return True if a stored dataset exists for this experiment."""

    return LocalParquetStorage().dataset_in_storage(experiment)


def save_dataset_to_storage(experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
    """Persist a Dataset for the given experiment to local storage.

    Returns the paths to the parquet and metadata files.
    """

    return LocalParquetStorage().save_dataset(experiment, dataset)


def load_dataset_from_storage(experiment: Experiment) -> Dataset:
    """Load a Dataset for the given experiment from local storage.

    Raises FileNotFoundError if the parquet file is missing.
    """

    return LocalParquetStorage().load_dataset(experiment)


def _json_default(value):  # pragma: no cover - simple fallback helper
    """Best-effort JSON serialisation for metadata.

    Falls back to ``str(value)`` for objects that the standard JSON encoder
    cannot handle (e.g. numpy scalars).
    """

    try:
        import numpy as np  # type: ignore[import]

        if isinstance(value, (np.generic,)):
            return value.item()
    except Exception:
        pass

    return str(value)


# TODO: Check if the source file metadata param is of any use
def _extract_source_files(dataset: Dataset, metadata: Dict[str, Any]) -> List[str]:
    """Extract a stable list of source files from metadata or data columns."""

    metadata_sources = metadata.get("source_files")
    if isinstance(metadata_sources, list):
        return sorted({str(item) for item in metadata_sources if item is not None and str(item).strip()})

    if "source_file" in dataset.data.columns:
        series = dataset.data["source_file"].dropna().astype(str)
        return sorted({value for value in series if value.strip()})

    return []


#TODO: Not sure if it is worth having all this redundancy in provenance. 
# Perhaps we can clean this up
def _build_provenance_metadata(
    experiment: Experiment,
    dataset: Dataset,
    parquet_path: str,
    meta_path: str,
    storage_backend: str = "local_filesystem",
) -> Dict[str, Any]:
    """Build provenance metadata block for persisted datasets."""

    metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}
    schema_report = metadata.get("schema_normalization")
    if not isinstance(schema_report, dict):
        schema_report = {}

    source_files = _extract_source_files(dataset, metadata)

    instrument_type = metadata.get("instrument_type")
    instrument_model = metadata.get("instrument_model")
    parser_key = None
    if instrument_type and instrument_model:
        parser_key = f"{instrument_type}:{instrument_model}"

    warnings = schema_report.get("warnings", [])
    missing_required_columns = schema_report.get("missing_required_columns", [])
    if not isinstance(warnings, list):
        warnings = []
    if not isinstance(missing_required_columns, list):
        missing_required_columns = []

    return {
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "mfethuls_version": _get_package_version(),
        "storage": {
            "backend": storage_backend,
            "format": {"data": "parquet", "metadata": "json"},
            "parquet_path": parquet_path,
            "metadata_path": meta_path,
            "instrument_name": experiment.instrument_name,
            "instrument_type": instrument_type,
            "instrument_model": instrument_model,
            "parser_key": parser_key,
        },
        "schema": {
            "schema_version": metadata.get("schema_version"),
            "schema_applied": schema_report.get("schema_applied"),
            "warning_count": len(warnings),
            "warnings": warnings,
            "missing_required_columns": missing_required_columns,
        },
        "source": {
            "source_files": source_files,
            "source_file_count": len(source_files),
        },
    }


def _get_storage_backend_label(data_backend: DataStorageBackend) -> str:
    if isinstance(data_backend, CombinedStorageBackend):
        return _get_storage_backend_label(data_backend.primary)
    if isinstance(data_backend, S3ParquetStorage):
        return "s3"
    if isinstance(data_backend, AzureBlobParquetStorage):
        return "azure_blob"
    return "local_filesystem"


def _prepare_registration_metadata(
    experiment: Experiment,
    dataset: Dataset,
    parquet_path: str,
    meta_path: str,
    storage_backend: str,
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
        # Core identifiers
        experiment_id=experiment.experiment_id,
        sample_id=experiment.sample_id,
        run_id=experiment.run_id,
        experiment_name=experiment.name,
        # Instrument info
        instrument_name=experiment.instrument_name,
        instrument_type=metadata.get("instrument_type"),
        instrument_model=metadata.get("instrument_model"),
        # Storage
        dataset_name=_dataset_basename(experiment),
        storage_path=parquet_path,
        storage_format="parquet",
        # Data shape
        rows=int(dataset.data.shape[0]),
        cols=int(dataset.data.shape[1]),
        # Processing metadata
        schema_version=metadata.get("schema_version"),
        measurement_profile=metadata.get("measurement_profile"),
        schema_normalization=metadata.get("schema_normalization"),
        # Package version
        mfethuls_version=_get_package_version(),
        # Full audit trail
        provenance=provenance,
    )


# ======================================================================
# SECTION 5: Postgres Metadata Backend
# ======================================================================


class PostgresMetadataBackend(MetadataBackend):
    """Postgres-backed metadata storage using SQLAlchemy.

    This backend focuses on metadata registration (experiments, datasets).
    It pairs with a separate data storage layer (LocalParquetStorage, S3, etc.).

    SQLAlchemy is optional; users without it can use LocalParquetStorage alone.
    """

    def __init__(self, db_url: str) -> None:
        if create_engine is None:
            raise RuntimeError("SQLAlchemy is required for PostgresMetadataBackend. Install sqlalchemy and psycopg2-binary.")
        self.engine = create_engine(db_url)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        create_experiments = """
        CREATE TABLE IF NOT EXISTS experiments (
            id SERIAL PRIMARY KEY,
            name TEXT,
            experiment_id TEXT UNIQUE,
            instrument_name TEXT,
            instrument_type TEXT,
            sample_id TEXT,
            status TEXT,
            registry_measurement_profile TEXT,
            raw_registry_row JSONB,
            registered_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        """

        create_datasets = """
        CREATE TABLE IF NOT EXISTS datasets (
            id SERIAL PRIMARY KEY,
            
            -- Core identifiers (indexed for filtering)
            experiment_id TEXT NOT NULL,
            sample_id TEXT,
            run_id TEXT,
            experiment_name TEXT,
            
            -- Instrument info (indexed for filtering)
            instrument_name TEXT NOT NULL,
            instrument_type TEXT,
            instrument_model TEXT,
            
            -- Data storage info
            dataset_name TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            storage_format TEXT DEFAULT 'parquet',
            
            -- Data shape
            rows INTEGER,
            cols INTEGER,
            
            -- Processing metadata
            schema_version TEXT,
            measurement_profile TEXT,
            mfethuls_version TEXT,
            schema_normalization JSONB,
            
            -- Full audit trail (rich provenance metadata)
            provenance JSONB,
            
            -- Timestamps
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        """

        with self.engine.connect() as conn:
            conn.execute(text(create_experiments))
            conn.execute(text(create_datasets))
            conn.commit()

    def persist_metadata(self, metadata: DatasetMetadata) -> Optional[int]:
        """Persist a dataset's metadata in Postgres using unified schema.

        Follows the DatasetMetadata schema for consistency across backends.

        Args:
            metadata: A DatasetMetadata dict with all query-relevant fields.

        Returns:
            The dataset id if successfully inserted, or None on failure.
        """
        insert_sql = text(
            "INSERT INTO datasets ("
            "experiment_id, sample_id, run_id, experiment_name, "
            "instrument_name, instrument_type, instrument_model, "
            "dataset_name, storage_path, storage_format, "
            "rows, cols, schema_version, measurement_profile, mfethuls_version, schema_normalization, provenance"
            ") VALUES ("
            ":experiment_id, :sample_id, :run_id, :experiment_name, "
            ":instrument_name, :instrument_type, :instrument_model, "
            ":dataset_name, :storage_path, :storage_format, "
            ":rows, :cols, :schema_version, :measurement_profile, :mfethuls_version, :schema_normalization, :provenance"
            ") RETURNING id;"
        )

        # Convert dict fields to JSON strings for JSONB columns
        schema_norm = metadata.get("schema_normalization")
        provenance = metadata.get("provenance")

        params = {
            "experiment_id": metadata.get("experiment_id"),
            "sample_id": metadata.get("sample_id"),
            "run_id": metadata.get("run_id"),
            "experiment_name": metadata.get("experiment_name"),
            "instrument_name": metadata.get("instrument_name"),
            "instrument_type": metadata.get("instrument_type"),
            "instrument_model": metadata.get("instrument_model"),
            "dataset_name": metadata.get("dataset_name"),
            "storage_path": metadata.get("storage_path"),
            "storage_format": metadata.get("storage_format", "parquet"),
            "rows": metadata.get("rows"),
            "cols": metadata.get("cols"),
            "schema_version": metadata.get("schema_version"),
            "measurement_profile": metadata.get("measurement_profile"),
            "schema_normalization": json.dumps(schema_norm) if isinstance(schema_norm, dict) else schema_norm,
            "provenance": json.dumps(provenance) if isinstance(provenance, dict) else provenance,
            "mfethuls_version": metadata.get("mfethuls_version") or _get_package_version(),
        }
        try:
            with self.engine.connect() as conn:
                res = conn.execute(insert_sql, params)
                conn.commit()
                row = res.fetchone()
                if row is not None:
                    return int(row[0])
        except SQLAlchemyError:
            raise
        return None

    def list_datasets(self, limit: int = 100, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Return a list of dataset rows matching optional filters.

        Supported filter keys: `instrument_name`, `instrument_type`,
        `schema_version`, `mfethuls_version`, `experiment_id`, `measurement_profile`.
        """
        filters = filters or {}
        where_clauses: List[str] = []
        params: Dict[str, Any] = {"limit": limit}

        allowed = (
            "instrument_name",
            "instrument_type",
            "schema_version",
            "mfethuls_version",
            "experiment_id",
            "measurement_profile",
        )
        for key in allowed:
            if key in filters and filters[key] is not None:
                where_clauses.append(f"{key} = :{key}")
                params[key] = filters[key]

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql = f"SELECT * FROM datasets {where_sql} ORDER BY created_at DESC LIMIT :limit"

        with self.engine.connect() as conn:
            res = conn.execute(text(sql), params)
            try:
                rows = [dict(r) for r in res.mappings().all()]
            except Exception:
                rows = [dict(r._mapping) for r in res.fetchall()]
        return rows

    def get_dataset_by_id(self, dataset_id: int) -> Optional[Dict[str, Any]]:
        """Return a single dataset row by `id`, or None if not found."""
        sql = "SELECT * FROM datasets WHERE id = :id LIMIT 1"
        with self.engine.connect() as conn:
            res = conn.execute(text(sql), {"id": dataset_id})
            try:
                row = res.mappings().first()
            except Exception:
                fetched = res.fetchone()
                row = dict(fetched._mapping) if fetched is not None else None
        return dict(row) if row is not None else None


# ======================================================================
# SECTION 6: DuckDB Query Backend
# ======================================================================


class DuckDBQueryBackend:
    """DuckDB-backed query backend for Parquet datasets.

    This backend registers Parquet files as DuckDB views for ad-hoc SQL
    queries. It keeps a small registry table so datasets can be listed
    and re-used across sessions.
    """

    def __init__(self, db_path: Optional[str] = None, read_only: bool = False) -> None:
        if duckdb is None:
            raise RuntimeError("duckdb is required for DuckDBQueryBackend. Install duckdb.")

        resolved = db_path or _get_duckdb_path()
        self.db_path = resolved if resolved == ":memory:" else os.path.abspath(resolved)
        self.read_only = read_only
        self._conn = duckdb.connect(self.db_path, read_only=read_only)
        self._ensure_registry()
        self._rehydrate_views()

    def _ensure_registry(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_registry (
                table_name TEXT PRIMARY KEY,
                storage_path TEXT NOT NULL,
                registered_at TIMESTAMP DEFAULT now()
            );
            """
        )

    def _rehydrate_views(self) -> None:
        rows = self._conn.execute(
            "SELECT table_name, storage_path FROM dataset_registry;"
        ).fetchall()
        for table_name, storage_path in rows:
            try:
                relation = self._conn.from_parquet(storage_path)
                try:
                    self._conn.unregister(table_name)
                except Exception:
                    pass
                self._conn.register(table_name, relation)
            except Exception:
                continue

    @staticmethod
    def _sanitize_table_name(name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
        return safe or "dataset"

    def register_parquet(self, storage_path: str, table_name: Optional[str] = None, overwrite: bool = True) -> str:
        """Register a Parquet file as a DuckDB view.

        Args:
            storage_path: Local path or URI to the Parquet file.
            table_name: Optional table/view name. If omitted, derived from path.
            overwrite: When True, replace any existing view of the same name.

        Returns:
            The DuckDB view name created or replaced.
        """

        inferred = table_name or os.path.splitext(os.path.basename(storage_path))[0]
        view_name = self._sanitize_table_name(inferred)
        relation = self._conn.from_parquet(storage_path)
        if overwrite:
            try:
                self._conn.unregister(view_name)
            except Exception:
                pass
        self._conn.register(view_name, relation)
        self._conn.execute(
            """
            INSERT INTO dataset_registry (table_name, storage_path)
            VALUES (?, ?)
            ON CONFLICT(table_name)
            DO UPDATE SET storage_path = excluded.storage_path, registered_at = now();
            """,
            [view_name, storage_path],
        )
        return view_name

    def list_registered(self) -> List[Dict[str, Any]]:
        """Return the list of registered datasets."""

        res = self._conn.execute(
            "SELECT table_name, storage_path, registered_at FROM dataset_registry ORDER BY registered_at DESC;"
        )
        rows = res.fetchall()
        return [
            {
                "table_name": row[0],
                "storage_path": row[1],
                "registered_at": row[2],
            }
            for row in rows
        ]

    def query(self, sql: str) -> pd.DataFrame:
        """Run a SQL query and return results as a DataFrame."""

        return self._conn.execute(sql).fetch_df()

    def get_sqlalchemy_url(self) -> str:
        """Return a SQLAlchemy-compatible DuckDB URL."""

        if self.db_path == ":memory:":
            return "duckdb:///:memory:"
        path = self.db_path.replace("\\", "/")
        return f"duckdb:///{path}"

    def close(self) -> None:
        """Close the underlying DuckDB connection."""

        self._conn.close()


    # ======================================================================
    # SECTION 7: Storage Manager (Composition Layer)
    # ======================================================================


class StorageManager:
    """Compose data, metadata, and optional query backends.

    This helper centralises the common workflow: save dataset files with a
    data backend (local Parquet, S3, etc.), optionally persist metadata with
    a metadata backend (Postgres, etc.), and optionally register files with
    a query backend (DuckDB).
    """

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
        """Save dataset to the data backend and optionally persist metadata.

        Returns a tuple: (parquet_path, meta_path, dataset_id_or_None).
        """
        parquet_path, meta_path = self.data_backend.save_dataset(experiment, dataset)
        dataset_id: Optional[int] = None
        if self.metadata_backend is not None:
            storage_backend = _get_storage_backend_label(self.data_backend)
            metadata = _prepare_registration_metadata(
                experiment,
                dataset,
                parquet_path,
                meta_path,
                storage_backend=storage_backend,
            )
            dataset_id = self.metadata_backend.persist_metadata(metadata)
        if self.query_backend is not None:
            self.query_backend.register_parquet(
                parquet_path,
                table_name=_dataset_basename(experiment),
            )
        return parquet_path, meta_path, dataset_id


    # ======================================================================
    # SECTION 8: Public Module Wrappers (for Notebooks)
    # ======================================================================


def list_datasets(db_url: str, limit: int = 100, filters: Optional[Dict[str, Any]] = None) -> "pd.DataFrame":
    """Convenience wrapper for notebooks: return datasets as a pandas DataFrame.

    Args:
        db_url: Postgres connection URL.
        limit: Maximum number of rows to return.
        filters: Optional dict of filters (see ``PostgresMetadataBackend.list_datasets``).

    Returns:
        A `pandas.DataFrame` with dataset rows (empty if none or if db_url is falsy).
    """
    if not db_url:
        return pd.DataFrame()
    backend = PostgresMetadataBackend(db_url)
    rows = backend.list_datasets(limit=limit, filters=filters)
    return pd.DataFrame(rows)


def get_dataset(db_url: str, dataset_id: int) -> Optional["pd.Series"]:
    """Convenience wrapper for notebooks: return a single dataset as a Series.

    Args:
        db_url: Postgres connection URL.
        dataset_id: Numeric id of the dataset row.

    Returns:
        A `pandas.Series` or `None` if not found.
    """
    if not db_url:
        return None
    backend = PostgresMetadataBackend(db_url)
    row = backend.get_dataset_by_id(dataset_id)
    if row is None:
        return None
    return pd.Series(row)
