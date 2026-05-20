import os
import json
import logging

from collections import namedtuple
from typing import Optional, TYPE_CHECKING

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
    LocalParquetStorage,
    PostgresMetadataBackend,
    S3ParquetStorage,
    StorageManager,
)

if TYPE_CHECKING:
    from mfethuls.storage import DuckDBQueryBackend

logger = logging.getLogger(__name__)

# Load config
instrument_config_path = os.path.join(os.path.dirname(__file__), 'config', 'instrument_params.json')
with open(instrument_config_path, encoding='utf8') as f:
    config = json.load(f)
    for entry in config:
        if isinstance(entry.get("name"), str):
            entry["name"] = entry["name"].strip().casefold()

InstrumentBundle = namedtuple("InstrumentBundle", ["instruments", "data_paths"])


def prepare_instruments(filters=None, experiments=None):
    instruments = {}
    dict_data_paths = {}

    for entry in filter_entries(filters):
        type_ = entry["type"]
        model = entry["model"]
        name = entry["name"]
        exps = entry["experiments"] if not experiments else experiments
        characterizer = None

        if "characterizer" in entry:
            characterizer = create_characterizer(type_, entry["characterizer"])

        data_root = get_data_root_path(entry)
        instr = create_instrument(type_, name, model, characterizer, data_root)
        instruments[name] = instr

        # Load data paths assoc. with instrument and experiments specified
        dict_data_paths[name] = instrument_data_path_constructor(data_root, exps)

    return InstrumentBundle(instruments, dict_data_paths)


def filter_entries(filters):
    if not filters:
        return config
    return [
        entry for entry in config
        if any(entry.get(k) in v for k, v in filters.items() if k in entry)
    ]


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
    """

    exp = get_experiment(experiment_name)

    if exp.instrument_name is None:
        logger.warning(
            "Skipping experiment %r: it is registered but has no associated instrument data yet.",
            experiment_name,
        )
        return None

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
    if effective_use_storage and not refresh and cache_backend is not None:
        try:
            if cache_backend.dataset_in_storage(exp):
                if os.environ.get("MFETHULS_STORAGE_DEBUG"):
                    logger.info("Loading Dataset for experiment %s from storage cache", experiment_name)
                return cache_backend.load_dataset(exp)
        except Exception:  # noqa: BLE001
            # Best-effort cache: fall back to parsing on any storage issue.
            if os.environ.get("MFETHULS_STORAGE_DEBUG"):
                logger.exception("Falling back to fresh parse for experiment %s due to storage error", experiment_name)

    # Restrict to the instrument associated with this experiment.
    filters = {"name": [exp.instrument_name]}
    bundle = prepare_instruments(filters=filters, experiments=[exp.experiment_id])

    try:
        instrument = bundle.instruments[exp.instrument_name]
        dict_data_paths = bundle.data_paths[exp.instrument_name]
    except KeyError as exc:
        raise KeyError(
            f"Instrument {exp.instrument_name!r} for experiment {experiment_name!r} "
            f"is not present in the current instrument configuration."
        ) from exc

    # Delegate parsing + Dataset construction to the factory helper.
    dataset = _parse_experiment(exp, dict_data_paths, instrument)

    # Persist to local storage for future fast loading, and optionally persist
    # metadata to Postgres via StorageManager. Never fail the call if
    # persistence itself has issues.
    parquet_path = None
    meta_path = None
    if effective_use_storage:
        try:
            metadata_backend = PostgresMetadataBackend(db_url) if db_url else None
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
        except Exception:  # noqa: BLE001
            if os.environ.get("MFETHULS_STORAGE_DEBUG"):
                logger.exception("Failed to save/persist Dataset for experiment %s", experiment_name)

    return dataset


def _build_data_backend(storage_mode: str, cloud_provider: Optional[str]) -> "LocalParquetStorage | S3ParquetStorage | AzureBlobParquetStorage | CombinedStorageBackend":
    mode = (storage_mode or "local").strip().lower()
    if mode not in {"local", "cloud", "both"}:
        raise ValueError("storage_mode must be one of: local, cloud, both")

    if mode == "local":
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
