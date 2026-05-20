from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence, TYPE_CHECKING

import pandas as pd

from .config_loader import load_experiment_dataset
from .experiments import load_experiment_registry
from .dataset import Dataset

if TYPE_CHECKING:
    from .storage import DuckDBQueryBackend


logger = logging.getLogger(__name__)


@dataclass
class ComparisonSet:
    datasets: list[Dataset]
    labels: list[str]

    def to_dataframe(self) -> pd.DataFrame:
        """Combine the comparison set into a single DataFrame for exploration."""

        frames: list[pd.DataFrame] = []
        for dataset, label in zip(self.datasets, self.labels):
            frame = dataset.data.copy()
            frame.insert(0, "comparison_label", label)

            metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}
            for column in (
                "experiment_name",
                "experiment_id",
                "sample_id",
                "run_id",
                "instrument_name",
                "instrument_type",
                "measurement_profile",
            ):
                value = metadata.get(column)
                if column not in frame.columns and value is not None:
                    frame[column] = value

            frames.append(frame)

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)


def _label_for_dataset(dataset: Dataset, index: int) -> str:
    metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}

    experiment_name = metadata.get("experiment_name")
    if experiment_name:
        return str(experiment_name)

    experiment_id = dataset.experiment_id
    if experiment_id:
        return str(experiment_id)

    return f"dataset_{index + 1}"


def load_comparison_set(
    experiment_names: Sequence[str],
    *,
    use_storage: bool = True,
    refresh: bool = False,
    storage_mode: str = "local",
    cloud_provider: str | None = None,
    query_backend: "DuckDBQueryBackend | None" = None,
) -> ComparisonSet:
    """Compatibility wrapper for load_experiments."""

    return load_experiments(
        experiment_names,
        use_storage=use_storage,
        refresh=refresh,
        storage_mode=storage_mode,
        cloud_provider=cloud_provider,
        query_backend=query_backend,
    )


def _load_comparison_from_names(
    experiment_names: Sequence[str],
    *,
    use_storage: bool = True,
    refresh: bool = False,
    storage_mode: str = "local",
    cloud_provider: str | None = None,
    db_url: str | None = None,
    query_backend: "DuckDBQueryBackend | None" = None,
) -> ComparisonSet:
    names = [str(name) for name in experiment_names]
    if not names:
        raise ValueError("load_experiments requires at least one experiment name.")

    datasets: list[Dataset] = []
    labels: list[str] = []

    for idx, name in enumerate(names):
        dataset = load_experiment_dataset(
            name,
            use_storage=use_storage,
            refresh=refresh,
            storage_mode=storage_mode,
            cloud_provider=cloud_provider,
            db_url=db_url,
            query_backend=query_backend,
        )
        if dataset is None:
            logger.warning("Not loading experiment %r because no dataset is associated with it.", name)
            continue
        datasets.append(dataset)
        labels.append(_label_for_dataset(dataset, idx))

    return ComparisonSet(datasets=datasets, labels=labels)


def load_experiments(
    experiment_names: Sequence[str],
    *,
    use_storage: bool = True,
    refresh: bool = False,
    storage_mode: str = "local",
    cloud_provider: str | None = None,
    db_url: str | None = None,
    query_backend: "DuckDBQueryBackend | None" = None,
) -> ComparisonSet:
    """Load multiple experiments into a comparison set for inspection or plotting.

    If db_url is provided, dataset metadata will be registered in the specified
    Postgres database after local storage save.
    """
    return _load_comparison_from_names(
        experiment_names,
        use_storage=use_storage,
        refresh=refresh,
        storage_mode=storage_mode,
        cloud_provider=cloud_provider,
        db_url=db_url,
        query_backend=query_backend,
    )


def load_samples(
    sample_ids: Sequence[str] | str,
    *,
    registry_path: str | None = None,
    use_storage: bool = True,
    refresh: bool = False,
    storage_mode: str = "local",
    cloud_provider: str | None = None,
    query_backend: "DuckDBQueryBackend | None" = None,
) -> ComparisonSet:
    """Load all experiments associated with one or more sample ids into a comparison set."""

    if isinstance(sample_ids, str):
        requested_sample_ids = [sample_ids]
    else:
        requested_sample_ids = [str(sample_id) for sample_id in sample_ids]

    requested_sample_ids = [sample_id.strip() for sample_id in requested_sample_ids if str(sample_id).strip()]
    if not requested_sample_ids:
        raise ValueError("load_samples requires at least one sample id.")

    registry = load_experiment_registry(registry_path)
    if "sample_id" not in registry.columns:
        raise ValueError("Experiment registry does not include a sample_id column.")

    selected = registry[registry["sample_id"].astype(str).isin(requested_sample_ids)]
    experiment_names = [str(name) for name in selected["name"].tolist() if str(name).strip()]

    if not experiment_names:
        raise ValueError(f"No experiments found for sample id(s): {requested_sample_ids}")

    return _load_comparison_from_names(
        experiment_names,
        use_storage=use_storage,
        refresh=refresh,
        storage_mode=storage_mode,
        cloud_provider=cloud_provider,
        query_backend=query_backend,
    )