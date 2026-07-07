import os
import json
import logging

from collections import namedtuple
from typing import Any, Optional, TYPE_CHECKING

from mfethuls.dataset import Dataset
from mfethuls.factory import (
    get_data_root_path,
    instrument_data_path_constructor,
    create_instrument,
    create_characterizer,
    parse_experiment as _parse_experiment,
)
from mfethuls.experiments import get_experiment
from mfethuls.storage import (
    AzureBlobParquetStorage,
    CombinedStorageBackend,
    get_postgres_db_url,
    LocalParquetStorage,
    PostgresMetadataBackend,
    S3ParquetStorage,
    StorageManager,
)
from mfethuls.storage.config import _view_basename
from mfethuls.config.mode import is_service_mode
from mfethuls.manifest import get_manifest_backend

if TYPE_CHECKING:
    from mfethuls.storage import DuckDBQueryBackend

logger = logging.getLogger(__name__)

# Load config
instrument_config_path = os.path.join(os.path.dirname(__file__), "instrument_params.json")
with open(instrument_config_path, encoding="utf8") as f:
    config = json.load(f)
    for entry in config:
        if isinstance(entry.get("name"), str):
            entry["name"] = entry["name"].strip().casefold()

InstrumentBundle = namedtuple("InstrumentBundle", ["instruments", "data_paths"])


def prepare_instruments(filters=None, experiments=None):
    instruments = {}
    dict_data_paths = {}

    for entry in filter_entries(filters):
        type_ = entry.get("type")
        model = entry.get("model")
        name = entry.get("name")
        folder_name = entry.get("folder_name")
        characterizer = None

        if "characterizer" in entry:
            characterizer = create_characterizer(type_, entry["characterizer"])

        data_path = get_data_root_path(folder_name, type_)
        instr = create_instrument(type_, name, model, characterizer, data_path)
        instruments[name] = instr

        # Load data paths assoc. with instrument and experiments specified
        dict_data_paths[name] = instrument_data_path_constructor(data_path, experiments)

    return InstrumentBundle(instruments, dict_data_paths)


def filter_entries(filters):
    if not filters:
        return config
    return [
        entry for entry in config
        if any(entry.get(k) in v for k, v in filters.items() if k in entry)
    ]


def _resolve_metadata_db_url(db_url: Optional[str]) -> Optional[str]:
    if not is_service_mode():
        return None
    if db_url:
        return db_url

    metadata_db_enabled_env = os.environ.get("MFETHULS_METADATA_DB_ENABLED", "").lower()
    if metadata_db_enabled_env in {"1", "true", "yes"}:
        return get_postgres_db_url()

    return None


def get_cached_dataset(exp, cache_backend, experiment_name: str) -> Optional[Dataset]:
    if cache_backend is None:
        return None

    if cache_backend.dataset_in_storage(exp):
        if os.environ.get("MFETHULS_STORAGE_DEBUG"):
            logger.warning(
                "Loading Dataset for experiment %s from storage cache in %s",
                experiment_name,
                cache_backend.__class__.__name__,
            )
        return cache_backend.load_dataset(exp)

    return None


def ensure_registered(exp, data_backend, query_backend: "DuckDBQueryBackend | None") -> Optional[str]:
    if data_backend is None or query_backend is None:
        return None

    parquet_path, _ = data_backend.dataset_paths(exp)
    return query_backend.register_parquet(
        parquet_path,
        table_name=_view_basename(exp),
        experiment_name=exp.name,
        raw_data_filename=exp.raw_data_filename,
    )


def persist_dataset(
    exp,
    dataset: Dataset,
    data_backend,
    db_url: Optional[str],
    query_backend: "DuckDBQueryBackend | None",
    experiment_name: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if data_backend is None:
        return None, None, None

    resolved_db_url = _resolve_metadata_db_url(db_url)
    metadata_backend = PostgresMetadataBackend(resolved_db_url) if resolved_db_url else None
    manager = StorageManager(
        data_backend=data_backend,
        metadata_backend=metadata_backend,
        query_backend=query_backend,
    )
    parquet_path, meta_path, dataset_id = manager.save_and_persist(exp, dataset)
    if os.environ.get("MFETHULS_STORAGE_DEBUG"):
        logger.info("Saved Dataset for experiment %s to storage backend", experiment_name)
        if dataset_id:
            logger.info(
                "Persisted dataset metadata for experiment %s in Postgres (dataset_id=%s)",
                experiment_name,
                dataset_id,
            )
    return parquet_path, meta_path, dataset_id


def _assign_experiment_id(exp, db_url: Optional[str]) -> None:
    """Assign experiment_id from the manifest backend (creates on first ingest)."""
    data_root = os.environ.get("PATH_TO_DATA")
    resolved_db_url = _resolve_metadata_db_url(db_url)
    backend = get_manifest_backend(data_root=data_root, db_url=resolved_db_url)
    raw_filename = exp.raw_data_filename or exp.name
    exp.experiment_id = backend.get_or_create_experiment_id(
        instrument_name=exp.instrument_name,
        raw_data_filename=raw_filename,
        experiment_name=exp.name,
    )


def ingest_experiment_dataset(
    experiment_name,
    use_storage: bool = True,
    refresh: bool = False,
    storage_mode: str = "local",
    cloud_provider: Optional[str] = None,
    db_url: Optional[str] = None,
    query_backend: "DuckDBQueryBackend | None" = None,
) -> Optional[dict[str, Any]]:
    exp = get_experiment(experiment_name)

    if exp.instrument_name is None:
        logger.warning(
            "Skipping experiment %r: it is registered but has no associated instrument data yet.",
            experiment_name,
        )
        return {"status": "skipped"}

    disable_storage_env = os.environ.get("MFETHULS_DISABLE_STORAGE", "").lower()
    effective_use_storage = use_storage and disable_storage_env not in {"1", "true", "yes"}
    if not effective_use_storage:
        return {"status": "skipped"}

    # Ensure Postgres schema exists before any operation that touches the DB.
    # PostgresManifestBackend (used by _assign_experiment_id) writes to the
    # experiments table, which is created by PostgresMetadataBackend._ensure_tables().
    # On a fresh deployment the table won't exist until we initialise it here.
    resolved_db_url = _resolve_metadata_db_url(db_url)
    if resolved_db_url:
        PostgresMetadataBackend(resolved_db_url)

    _assign_experiment_id(exp, db_url)

    data_backend = _build_data_backend(storage_mode, cloud_provider)
    cache_backend = data_backend
    if (storage_mode or "").strip().lower() == "both":
        cache_backend = LocalParquetStorage()

    if not refresh:
        cached_dataset = get_cached_dataset(exp, cache_backend, experiment_name)
        if cached_dataset is not None:
            dataset_id = ensure_registered(exp, data_backend, query_backend)
            parquet_path, _ = data_backend.dataset_paths(exp)
            return {
                "status": "registered",
                "dataset_id": dataset_id,
                "storage_path": parquet_path,
            }

    raw_filename = exp.raw_data_filename or exp.name
    filters = {"name": [exp.instrument_name]}
    bundle = prepare_instruments(filters=filters, experiments=[raw_filename])

    try:
        instrument = bundle.instruments[exp.instrument_name]
        raw_dict = bundle.data_paths[exp.instrument_name]
    except KeyError as exc:
        raise KeyError(
            f"Instrument {exp.instrument_name!r} for experiment {experiment_name!r} "
            f"is not present in the current instrument configuration."
        ) from exc

    # Remap from {raw_data_filename: files} → {experiment_id: files} for parsers
    dict_data_paths = {exp.experiment_id: raw_dict.get(raw_filename, [])}

    dataset = _parse_experiment(exp, dict_data_paths, instrument)
    parquet_path, _, dataset_id = persist_dataset(
        exp,
        dataset,
        data_backend,
        db_url,
        query_backend,
        experiment_name,
    )
    if parquet_path or dataset_id:
        return {
            "status": "persisted",
            "dataset_id": dataset_id,
            "storage_path": parquet_path,
        }
    return {"status": "failed"}


def load_experiment_dataset(
    experiment_name,
    use_storage: bool = True,
    refresh: bool = False,
    storage_mode: str = "local",
    cloud_provider: Optional[str] = None,
    db_url: Optional[str] = None,
    query_backend: "DuckDBQueryBackend | None" = None,
) -> Optional[Dataset]:
    """Load and parse data for a given experiment name into a Dataset.

    This is a high-level helper that ties together the Experiment registry,
    instrument configuration, and the existing parser machinery. It keeps the
    current prepare_instruments behaviour intact while offering a simpler
    interface for users who only know the experiment name.

    If db_url is provided, the dataset metadata will also be registered in the
    specified Postgres database after successful storage save.

    When `db_url` is not provided, metadata persistence can be enabled via the
    `MFETHULS_METADATA_DB_ENABLED` env var (`1`/`true`/`yes`). In that mode,
    the DB URL is resolved from Postgres env settings via `get_postgres_db_url`.
    """

    exp = get_experiment(experiment_name)

    if exp.instrument_name is None:
        logger.warning(
            "Skipping experiment %r: it is registered but has no associated instrument data yet.",
            experiment_name,
        )
        return None

    _assign_experiment_id(exp, db_url)

    # Allow a global switch to disable storage via environment for debugging.
    disable_storage_env = os.environ.get("MFETHULS_DISABLE_STORAGE", "").lower()
    effective_use_storage = use_storage and disable_storage_env not in {"1", "true", "yes"}

    data_backend = None
    if effective_use_storage:
        data_backend = _build_data_backend(storage_mode, cloud_provider)

    cache_backend = data_backend
    if effective_use_storage and (storage_mode or "").strip().lower() == "both":
        cache_backend = LocalParquetStorage()

    # If requested, try to serve from storage cache first.
    if effective_use_storage and not refresh:
        cached_dataset = get_cached_dataset(exp, cache_backend, experiment_name)
        if cached_dataset is not None:
            ensure_registered(exp, data_backend, query_backend)
            return cached_dataset

    raw_filename = exp.raw_data_filename or exp.name
    filters = {"name": [exp.instrument_name]}
    bundle = prepare_instruments(filters=filters, experiments=[raw_filename])

    try:
        instrument = bundle.instruments[exp.instrument_name]
        raw_dict = bundle.data_paths[exp.instrument_name]
    except KeyError as exc:
        raise KeyError(
            f"Instrument {exp.instrument_name!r} for experiment {experiment_name!r} "
            f"is not present in the current instrument configuration."
        ) from exc

    dict_data_paths = {exp.experiment_id: raw_dict.get(raw_filename, [])}

    # Delegate parsing + Dataset construction to the factory helper.
    dataset = _parse_experiment(exp, dict_data_paths, instrument)

    # Persist to local storage for future fast loading, and optionally persist
    # metadata to Postgres via StorageManager. Never fail the call if
    # persistence itself has issues.
    if effective_use_storage:
        persist_dataset(
            exp,
            dataset,
            data_backend,
            db_url,
            query_backend,
            experiment_name,
        )

    return dataset


def _build_data_backend(storage_mode: str, cloud_provider: Optional[str]) -> "LocalParquetStorage | S3ParquetStorage | AzureBlobParquetStorage | CombinedStorageBackend":
    mode = (storage_mode or "local").strip().lower()
    if mode not in {"local", "cloud", "both"}:
        raise ValueError("storage_mode must be one of: local, cloud, both")

    if mode in {"cloud", "both"} and not is_service_mode():
        raise ValueError("cloud storage is only available in service mode")

    if mode == "local":
        #TODO: Check if this log is outputting
        logger.info("Using LocalParquetStorage as data backend")
        return LocalParquetStorage()

    provider = (cloud_provider or "").strip().lower()
    if provider in {"s3", "aws"}:
        cloud_backend = S3ParquetStorage()
    elif provider in {"azure", "azure_blob", "blob", "azureblob"}:
        cloud_backend = AzureBlobParquetStorage()
    else:
        raise ValueError("cloud_provider must be set to 's3' or 'azure' when storage_mode is cloud or both")

    if mode == "cloud":
        return cloud_backend

    return CombinedStorageBackend(primary=cloud_backend, secondary=LocalParquetStorage())
