from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import pandas as pd

try:
    from sqlalchemy import create_engine, MetaData, text
    from sqlalchemy.exc import SQLAlchemyError
except Exception:  # pragma: no cover - optional dependency
    create_engine = None  # type: ignore

from .dataset import Dataset
from .experiments import Experiment


class StorageBackend:
    """Abstract base class for storage backends.

    Defines the interface that all storage implementations must follow.
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

    # Full audit trail (provenance is the rich metadata blob)
    provenance: Dict[str, Any]  # JSONB in Postgres


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

    # First priority: explicit full URL
    db_url = os.environ.get("MFETHULS_POSTGRES_URL")
    if db_url:
        return db_url

    # Second priority: construct from components
    user = os.environ.get("MFETHULS_POSTGRES_USER")
    password = os.environ.get("MFETHULS_POSTGRES_PASSWORD")
    host = os.environ.get("MFETHULS_POSTGRES_HOST", "localhost")
    port = os.environ.get("MFETHULS_POSTGRES_PORT", "5432")
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


class LocalParquetStorage(StorageBackend):
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
        )

        with open(meta_path, "w", encoding="utf8") as f:
            json.dump(metadata_to_store, f, default=_json_default)

        return parquet_path, meta_path

    def prepare_registration_metadata(
        self, experiment: Experiment, dataset: Dataset, parquet_path: str, meta_path: str
    ) -> DatasetMetadata:
        """Prepare metadata for Postgres registration using unified schema.

        This bridges the format written to disk with what PostgresMetadataBackend expects.
        Extracts all query-relevant fields following the DatasetMetadata schema.

        Args:
            experiment: The experiment object.
            dataset: The dataset object.
            parquet_path: Path to the saved parquet file.
            meta_path: Path to the saved metadata JSON file.

        Returns:
            A DatasetMetadata dict ready for PostgresMetadataBackend.register_dataset().
        """

        metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}
        provenance = _build_provenance_metadata(experiment, dataset, parquet_path, meta_path)

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
            # Full audit trail
            provenance=provenance,
        )

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


def dataset_paths(experiment: Experiment) -> Tuple[str, str]:
    """Return the storage paths for an experiment.

    This wrapper preserves the historical API while delegating to
    ``LocalParquetStorage``.
    """

    return LocalParquetStorage().dataset_paths(experiment)


def dataset_in_storage(experiment: Experiment) -> bool:
    """Return True if a stored dataset exists for this experiment."""

    return LocalParquetStorage().dataset_in_storage(experiment)


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


def _extract_source_files(dataset: Dataset, metadata: Dict[str, Any]) -> List[str]:
    """Extract a stable list of source files from metadata or data columns."""

    metadata_sources = metadata.get("source_files")
    if isinstance(metadata_sources, list):
        return sorted({str(item) for item in metadata_sources if item is not None and str(item).strip()})

    if "source_file" in dataset.data.columns:
        series = dataset.data["source_file"].dropna().astype(str)
        return sorted({value for value in series if value.strip()})

    return []


def _build_provenance_metadata(
    experiment: Experiment,
    dataset: Dataset,
    parquet_path: str,
    meta_path: str,
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
            "backend": "local_filesystem",
            "format": {"data": "parquet", "metadata": "json"},
            "parquet_path": parquet_path,
            "metadata_path": meta_path,
        },
        "dataset": {
            "row_count": int(dataset.data.shape[0]),
            "column_count": int(dataset.data.shape[1]),
            "columns": [str(column) for column in dataset.data.columns],
        },
        "instrument": {
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


def prepare_registration_metadata_for_postgres(
    experiment: Experiment, dataset: Dataset, parquet_path: str, meta_path: str
) -> Dict[str, Any]:
    """Prepare metadata for Postgres registration after saving to local storage.

    This is a convenience wrapper that bridges LocalParquetStorage and PostgresMetadataBackend.
    Use this right after save_dataset_to_storage() to get a dict ready for register_dataset().

    Example:
        parquet_path, meta_path = save_dataset_to_storage(exp, dataset)
        metadata = prepare_registration_metadata_for_postgres(exp, dataset, parquet_path, meta_path)
        postgres_backend.register_dataset(metadata)

    Args:
        experiment: The experiment object.
        dataset: The dataset object.
        parquet_path: Path returned by save_dataset_to_storage().
        meta_path: Metadata path returned by save_dataset_to_storage().

    Returns:
        A dict ready for PostgresMetadataBackend.register_dataset().
    """

    return LocalParquetStorage().prepare_registration_metadata(experiment, dataset, parquet_path, meta_path)


class PostgresMetadataBackend(StorageBackend):
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

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        """Not implemented for Postgres backend; use LocalParquetStorage for paths."""
        raise NotImplementedError("PostgresMetadataBackend does not manage file paths. Use LocalParquetStorage.")

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        """Not implemented for Postgres backend."""
        raise NotImplementedError("PostgresMetadataBackend does not check file existence. Use LocalParquetStorage.")

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        """Not implemented for Postgres backend; use LocalParquetStorage for save."""
        raise NotImplementedError("PostgresMetadataBackend does not write parquet files. Use LocalParquetStorage.")

    def load_dataset(self, experiment: Experiment) -> Dataset:
        """Not implemented for Postgres backend; use LocalParquetStorage for load."""
        raise NotImplementedError("PostgresMetadataBackend does not read parquet files. Use LocalParquetStorage.")

    def register_dataset(self, metadata: DatasetMetadata) -> Optional[int]:
        """Register a dataset's metadata in Postgres using unified schema.

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
            "rows, cols, schema_version, measurement_profile, schema_normalization, provenance"
            ") VALUES ("
            ":experiment_id, :sample_id, :run_id, :experiment_name, "
            ":instrument_name, :instrument_type, :instrument_model, "
            ":dataset_name, :storage_path, :storage_format, "
            ":rows, :cols, :schema_version, :measurement_profile, :schema_normalization, :provenance"
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
