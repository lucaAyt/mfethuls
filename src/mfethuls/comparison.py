from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence, TYPE_CHECKING

import pandas as pd

from .config.loader import load_experiment_dataset
from .experiments import Experiment, Registry
from .dataset import Dataset

if TYPE_CHECKING:
    from .stores import Stores


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


def _load_comparison(
    experiments: Sequence[Experiment],
    registry: Registry,
    *,
    use_storage: bool = True,
    refresh: bool = False,
    stores: "Stores | None" = None,
) -> ComparisonSet:
    datasets: list[Dataset] = []
    labels: list[str] = []

    for idx, exp in enumerate(experiments):
        dataset = load_experiment_dataset(
            exp.name,
            use_storage=use_storage,
            refresh=refresh,
            stores=stores,
            registry=registry,
        )
        if dataset is None:
            logger.warning("Not loading experiment %r because no dataset is associated with it.", exp.name)
            continue
        datasets.append(dataset)
        labels.append(_label_for_dataset(dataset, idx))

    return ComparisonSet(datasets=datasets, labels=labels)


def load_experiments(
    experiment_names: Sequence[str],
    *,
    registry: Registry | None = None,
    registry_path: str | None = None,
    use_storage: bool = True,
    refresh: bool = False,
    stores: "Stores | None" = None,
) -> ComparisonSet:
    """Load multiple experiments into a comparison set for inspection or plotting.

    Experiments are looked up in ``registry``. Without one, the registry file at
    ``registry_path`` (default ``PATH_TO_REGISTRY``) is read on each call, so
    edits to it are always picked up.

    ``stores`` defaults to the local stores (see :mod:`mfethuls.stores`).
    """

    names = [str(name) for name in experiment_names]
    if not names:
        raise ValueError("load_experiments requires at least one experiment name.")
    registry = registry if registry is not None else Registry.load(registry_path)

    unknown = [name for name in names if name not in registry]
    if unknown:
        where = f" at {registry.path!r}" if registry.path else ""
        raise KeyError(
            f"Unknown experiment name(s): {unknown}. They are not in the registry{where}, "
            "or their rows were skipped as invalid (see Registry.problems)."
        )

    return _load_comparison(
        [registry.get(name) for name in names],
        registry,
        use_storage=use_storage,
        refresh=refresh,
        stores=stores,
    )


def load_samples(
    sample_ids: Sequence[str] | str,
    *,
    registry: Registry | None = None,
    registry_path: str | None = None,
    use_storage: bool = True,
    refresh: bool = False,
    stores: "Stores | None" = None,
) -> ComparisonSet:
    """Load all experiments of one or more sample ids into a comparison set.

    The registry is used as in :func:`load_experiments`.
    """

    if isinstance(sample_ids, str):
        requested_sample_ids = [sample_ids]
    else:
        requested_sample_ids = [str(sample_id) for sample_id in sample_ids]

    requested_sample_ids = [sample_id.strip() for sample_id in requested_sample_ids if str(sample_id).strip()]
    if not requested_sample_ids:
        raise ValueError("load_samples requires at least one sample id.")

    registry = registry if registry is not None else Registry.load(registry_path)
    experiments = registry.for_samples(requested_sample_ids)
    if not experiments:
        raise ValueError(f"No experiments found for sample id(s): {requested_sample_ids}")

    return _load_comparison(
        experiments,
        registry,
        use_storage=use_storage,
        refresh=refresh,
        stores=stores,
    )
