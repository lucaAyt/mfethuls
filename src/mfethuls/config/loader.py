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
from mfethuls.experiments import Experiment, Registry
from mfethuls.storage import (
    AzureBlobParquetStorage,
    CombinedStorageBackend,
    get_postgres_db_url,
    LocalParquetStorage,
    PostgresMetadataBackend,
    S3ParquetStorage,
    StorageManager,
)
from mfethuls.storage.catalog import CatalogRecord
from mfethuls.config.mode import is_service_mode
from mfethuls.manifest import content_hash, get_manifest_backend
from mfethuls.parsers.registry import reads
from mfethuls.schema_normalization import add_elapsed_time
from mfethuls.settings import get_settings

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
        folder_name = entry["folder_name"]  # required; see tests/test_instrument_config.py
        characterizer = None

        if "characterizer" in entry:
            characterizer = create_characterizer(type_, entry["characterizer"])

        data_path = get_data_root_path(folder_name)
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

    if get_settings().metadata_db_enabled:
        return get_postgres_db_url()

    return None


# Identifier columns parsers write into every data row.
_ID_COLUMNS = ("experiment_id", "sample_id", "run_id")


def apply_registry_fields(dataset: Dataset, exp: Experiment) -> Dataset:
    """Overwrite the descriptive fields stored at ingest with the registry's current values.

    The registry owns names, sample/run ids, description and extra columns; the
    stored metadata is a snapshot from ingest time. Registry values win in
    ``dataset.metadata`` and in the id columns of the data.
    """

    current = {
        "experiment_name": exp.name,
        "experiment_id": exp.experiment_id,
        "sample_id": exp.sample_id,
        "run_id": exp.run_id,
        "instrument_name": exp.instrument_name,
        "raw_data_filename": exp.raw_data_filename,
        **exp.metadata,
    }
    dataset.metadata.update(current)
    for column in _ID_COLUMNS:
        if column in dataset.data.columns and current[column] is not None:
            dataset.data[column] = current[column]
    return dataset


def _resolve_experiment(experiment_name: str, registry: Optional[Registry]) -> Experiment:
    return (registry if registry is not None else Registry.load()).get(experiment_name)


def get_cached_dataset(exp, cache_backend, experiment_name: str) -> Optional[Dataset]:
    if cache_backend is None:
        return None

    if cache_backend.dataset_in_storage(exp):
        if get_settings().storage_debug:
            logger.warning(
                "Loading Dataset for experiment %s from storage cache in %s",
                experiment_name,
                cache_backend.__class__.__name__,
            )
        dataset = cache_backend.load_dataset(exp)
        # Datasets stored before time_s was derived during normalization.
        dataset.data = add_elapsed_time(dataset.data)
        apply_registry_fields(dataset, exp)
        return dataset

    return None


def catalog_record(exp, data_backend, dataset: Optional[Dataset] = None) -> Optional[CatalogRecord]:
    """The catalog row for ``exp`` as stored by ``data_backend``."""

    if data_backend is None:
        return None
    parquet_path, _ = data_backend.dataset_paths(exp)
    return CatalogRecord.build(
        exp,
        parquet_path,
        dataset_metadata=dataset.metadata if dataset is not None else None,
        rows=len(dataset.data) if dataset is not None else None,
    )


def ensure_registered(
    exp, data_backend, query_backend: "DuckDBQueryBackend | None", dataset: Optional[Dataset] = None
) -> Optional[str]:
    record = catalog_record(exp, data_backend, dataset)
    if record is None or query_backend is None:
        return None
    return query_backend.register_parquet(record.storage_path, record=record)


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
    if get_settings().storage_debug:
        logger.info("Saved Dataset for experiment %s to storage backend", experiment_name)
        if dataset_id:
            logger.info(
                "Persisted dataset metadata for experiment %s in Postgres (dataset_id=%s)",
                experiment_name,
                dataset_id,
            )
    return parquet_path, meta_path, dataset_id


def _manifest_backend(db_url: Optional[str]):
    return get_manifest_backend(data_root=get_settings().data_root, db_url=_resolve_metadata_db_url(db_url))


def _assign_experiment_id(exp, db_url: Optional[str]) -> None:
    """Assign experiment_id from the manifest backend (creates on first ingest)."""
    backend = _manifest_backend(db_url)
    raw_filename = exp.raw_data_filename or exp.name
    exp.experiment_id = backend.get_or_create_experiment_id(
        instrument_name=exp.instrument_name,
        raw_data_filename=raw_filename,
        experiment_name=exp.name,
    )


def _data_files(instrument, files: list[str], experiment_name: str) -> list[str]:
    """The files the instrument's parser reads; others next to the data (plots, notes) are skipped."""
    data = [f for f in files if reads(instrument.parser, f)]
    skipped = [os.path.basename(f) for f in files if f not in data]
    if skipped:
        logger.warning("Experiment %r: not reading %s (not data for %s).",
                       experiment_name, ", ".join(skipped), instrument.name)
    return data


def _record_content_hash(exp, raw_filename: str, files: list[str], db_url: Optional[str]) -> None:
    """Store the hash of the raw files just parsed on the experiment's manifest entry."""
    if files:
        _manifest_backend(db_url).record_content_hash(
            instrument_name=exp.instrument_name,
            raw_data_filename=raw_filename,
            content_hash=content_hash(files),
        )


def ingest_experiment_dataset(
    experiment_name,
    use_storage: bool = True,
    refresh: bool = False,
    storage_mode: str = "local",
    cloud_provider: Optional[str] = None,
    db_url: Optional[str] = None,
    query_backend: "DuckDBQueryBackend | None" = None,
    registry: Optional[Registry] = None,
) -> Optional[dict[str, Any]]:
    """Parse (or reuse) and store one experiment, register it in the catalog, and report the outcome.

    The experiment is looked up in ``registry``; without one, the registry at
    ``PATH_TO_REGISTRY`` is read.
    """

    exp = _resolve_experiment(experiment_name, registry)

    if exp.instrument_name is None:
        logger.warning(
            "Skipping experiment %r: it is registered but has no associated instrument data yet.",
            experiment_name,
        )
        return {"status": "skipped"}

    effective_use_storage = use_storage and not get_settings().disable_storage
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
            dataset_id = ensure_registered(exp, data_backend, query_backend, cached_dataset)
            record = catalog_record(exp, data_backend, cached_dataset)
            return {
                "status": "registered",
                "dataset_id": dataset_id,
                "storage_path": record.storage_path,
                "catalog_record": record,
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
    dict_data_paths = {exp.experiment_id: _data_files(instrument, raw_dict.get(raw_filename, []), experiment_name)}

    dataset = _parse_experiment(exp, dict_data_paths, instrument)
    _record_content_hash(exp, raw_filename, dict_data_paths[exp.experiment_id], db_url)
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
            "catalog_record": catalog_record(exp, data_backend, dataset),
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
    registry: Optional[Registry] = None,
) -> Optional[Dataset]:
    """Load and parse data for a given experiment name into a Dataset.

    The experiment is looked up in ``registry``; without one, the registry at
    ``PATH_TO_REGISTRY`` is read.

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

    exp = _resolve_experiment(experiment_name, registry)

    if exp.instrument_name is None:
        logger.warning(
            "Skipping experiment %r: it is registered but has no associated instrument data yet.",
            experiment_name,
        )
        return None

    _assign_experiment_id(exp, db_url)

    # Allow a global switch to disable storage via environment for debugging.
    effective_use_storage = use_storage and not get_settings().disable_storage

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
            ensure_registered(exp, data_backend, query_backend, cached_dataset)
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

    dict_data_paths = {exp.experiment_id: _data_files(instrument, raw_dict.get(raw_filename, []), experiment_name)}

    # Delegate parsing + Dataset construction to the factory helper.
    dataset = _parse_experiment(exp, dict_data_paths, instrument)
    _record_content_hash(exp, raw_filename, dict_data_paths[exp.experiment_id], db_url)

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
