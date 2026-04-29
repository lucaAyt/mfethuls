from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from .config_loader import load_experiment_dataset
from .dataset import Dataset


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
) -> ComparisonSet:
    """Compatibility wrapper for load_experiments."""

    return load_experiments(experiment_names, use_storage=use_storage, refresh=refresh)


def load_experiments(
    experiment_names: Sequence[str],
    *,
    use_storage: bool = True,
    refresh: bool = False,
) -> ComparisonSet:
    """Load multiple experiments into a comparison set for inspection or plotting."""

    names = [str(name) for name in experiment_names]
    if not names:
        raise ValueError("load_experiments requires at least one experiment name.")

    datasets: list[Dataset] = []
    labels: list[str] = []

    for idx, name in enumerate(names):
        dataset = load_experiment_dataset(name, use_storage=use_storage, refresh=refresh)
        datasets.append(dataset)
        labels.append(_label_for_dataset(dataset, idx))

    return ComparisonSet(datasets=datasets, labels=labels)