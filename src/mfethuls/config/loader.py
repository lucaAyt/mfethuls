import os
import json
import logging

from collections import namedtuple
from dataclasses import replace
from typing import Any, Optional

from mfethuls.dataset import Dataset
from mfethuls.factory import (
    get_data_root_path,
    instrument_data_path_constructor,
    create_instrument,
    create_characterizer,
    parse_experiment as _parse_experiment,
)
from mfethuls.experiments import Experiment, Registry
from mfethuls.manifest import content_hash
from mfethuls.parsers.registry import reads
from mfethuls.schema_normalization import add_elapsed_time
from mfethuls.settings import get_settings
from mfethuls.storage.catalog import CatalogRecord
from mfethuls.storage.manager import StorageManager
from mfethuls.stores import Stores, local_stores

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


def ensure_registered(exp, stores: Stores, dataset: Optional[Dataset] = None) -> Optional[str]:
    """Register the stored dataset of ``exp`` in the catalog (if there is one); returns the view name."""

    record = catalog_record(exp, stores.storage, dataset)
    if record is None or stores.catalog is None:
        return None
    return stores.catalog.register_parquet(record.storage_path, record=record)


def persist_dataset(exp, dataset: Dataset, stores: Stores) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Store ``dataset`` and register it in the catalog and the metadata sink."""

    if stores.storage is None:
        return None, None, None
    manager = StorageManager(data_backend=stores.storage, metadata_backend=stores.metadata, query_backend=stores.catalog)
    parquet_path, meta_path, dataset_id = manager.save_and_persist(exp, dataset)
    if get_settings().storage_debug:
        logger.info("Saved dataset of experiment %s (metadata id %s)", exp.name, dataset_id)
    return parquet_path, meta_path, dataset_id


def _assign_experiment_id(exp, stores: Stores) -> None:
    """Assign experiment_id from the manifest (created on first ingest)."""
    exp.experiment_id = stores.manifest.get_or_create_experiment_id(
        instrument_name=exp.instrument_name,
        raw_data_filename=exp.raw_data_filename or exp.name,
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


def _parse_raw(exp, stores: Stores) -> Dataset:
    """Parse the raw data files of ``exp`` and record their content hash in the manifest."""

    raw_filename = exp.raw_data_filename or exp.name
    bundle = prepare_instruments(filters={"name": [exp.instrument_name]}, experiments=[raw_filename])
    try:
        instrument = bundle.instruments[exp.instrument_name]
        raw_dict = bundle.data_paths[exp.instrument_name]
    except KeyError as exc:
        raise KeyError(
            f"Instrument {exp.instrument_name!r} for experiment {exp.name!r} "
            f"is not present in the current instrument configuration."
        ) from exc

    files = _data_files(instrument, raw_dict.get(raw_filename, []), exp.name)
    dataset = _parse_experiment(exp, {exp.experiment_id: files}, instrument)
    if files:
        stores.manifest.record_content_hash(
            instrument_name=exp.instrument_name, raw_data_filename=raw_filename, content_hash=content_hash(files)
        )
    return dataset


def _resolve_stores(stores: Optional[Stores], use_storage: bool) -> Stores:
    stores = stores if stores is not None else local_stores()
    if not use_storage or get_settings().disable_storage:
        return replace(stores, storage=None, catalog=None, metadata=None, cache=None)
    return stores


def ingest_experiment_dataset(
    experiment_name,
    *,
    stores: Optional[Stores] = None,
    use_storage: bool = True,
    refresh: bool = False,
    registry: Optional[Registry] = None,
) -> Optional[dict[str, Any]]:
    """Parse (or reuse) and store one experiment, register it in the catalog, and report the outcome.

    The experiment is looked up in ``registry``; without one, the registry at
    ``PATH_TO_REGISTRY`` is read. ``stores`` defaults to :func:`~mfethuls.stores.local_stores`
    without a catalog; pass stores with an open catalog to register the dataset.
    """

    exp = _resolve_experiment(experiment_name, registry)
    if exp.instrument_name is None:
        logger.warning(
            "Skipping experiment %r: it is registered but has no associated instrument data yet.",
            experiment_name,
        )
        return {"status": "skipped"}

    stores = _resolve_stores(stores, use_storage)
    if stores.storage is None:
        return {"status": "skipped"}
    _assign_experiment_id(exp, stores)

    if not refresh:
        cached_dataset = get_cached_dataset(exp, stores.reads_from, experiment_name)
        if cached_dataset is not None:
            dataset_id = ensure_registered(exp, stores, cached_dataset)
            record = catalog_record(exp, stores.storage, cached_dataset)
            return {
                "status": "registered",
                "dataset_id": dataset_id,
                "storage_path": record.storage_path,
                "catalog_record": record,
            }

    dataset = _parse_raw(exp, stores)
    parquet_path, _, dataset_id = persist_dataset(exp, dataset, stores)
    if parquet_path or dataset_id:
        return {
            "status": "persisted",
            "dataset_id": dataset_id,
            "storage_path": parquet_path,
            "catalog_record": catalog_record(exp, stores.storage, dataset),
        }
    return {"status": "failed"}


def load_experiment_dataset(
    experiment_name,
    *,
    stores: Optional[Stores] = None,
    use_storage: bool = True,
    refresh: bool = False,
    registry: Optional[Registry] = None,
) -> Optional[Dataset]:
    """Load one experiment as a Dataset: from storage when it was stored before, else parsed from raw data.

    The experiment is looked up in ``registry``; without one, the registry at
    ``PATH_TO_REGISTRY`` is read. A freshly parsed dataset is stored for next time
    (unless ``use_storage`` is false). ``stores`` defaults to
    :func:`~mfethuls.stores.local_stores`.
    """

    exp = _resolve_experiment(experiment_name, registry)
    if exp.instrument_name is None:
        logger.warning(
            "Skipping experiment %r: it is registered but has no associated instrument data yet.",
            experiment_name,
        )
        return None

    stores = _resolve_stores(stores, use_storage)
    _assign_experiment_id(exp, stores)

    if stores.reads_from is not None and not refresh:
        cached_dataset = get_cached_dataset(exp, stores.reads_from, experiment_name)
        if cached_dataset is not None:
            ensure_registered(exp, stores, cached_dataset)
            return cached_dataset

    dataset = _parse_raw(exp, stores)
    persist_dataset(exp, dataset, stores)
    return dataset
