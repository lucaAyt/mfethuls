from pathlib import Path

import pandas as pd
import pytest

from mfethuls import ComparisonSet, load_experiments, load_samples
from mfethuls.comparison import ComparisonSet as ComparisonSetDirect, load_comparison_set
from mfethuls.dataset import Dataset
from mfethuls.experiments import get_experiment

EXAMPLE_REGISTRY = Path(__file__).resolve().parents[1] / "examples" / "experiments_registry.csv"


@pytest.fixture
def empty_experiment_registry(monkeypatch):
    """Start from an empty in-memory registry, as in a fresh Python session."""
    from mfethuls import experiments as experiments_module

    monkeypatch.setattr(experiments_module, "_EXPERIMENT_REGISTRY", {})


def test_load_comparison_set_to_dataframe_works(monkeypatch):
    def _fake_loader(name, use_storage=True, refresh=False, **kwargs):
        _ = use_storage, refresh, kwargs
        return {
            "exp_a": pd.DataFrame({"temperature_C": [25.0, 50.0], "heat_flow_mW": [0.1, 0.2]}),
            "exp_b": pd.DataFrame({"temperature_C": [30.0, 60.0], "heat_flow_mW": [0.3, 0.4]}),
        }[name]

    from mfethuls import comparison as comparison_module

    monkeypatch.setattr(comparison_module, "is_experiment_registered", lambda name: True)
    monkeypatch.setattr(
        comparison_module,
        "load_experiment_dataset",
        lambda name, use_storage=True, refresh=False, **kwargs: Dataset(
            data=_fake_loader(name, use_storage, refresh, **kwargs),
            metadata={"experiment_id": name, "experiment_name": f"name_{name}"},
        ),
    )

    comparison = load_comparison_set(["exp_a", "exp_b"])
    assert isinstance(comparison, ComparisonSet)
    assert isinstance(comparison, ComparisonSetDirect)

    frame = comparison.to_dataframe()
    assert set(["comparison_label", "temperature_C", "heat_flow_mW"]).issubset(frame.columns)
    assert "comparison_index" not in frame.columns
    assert frame.shape[0] == 4
    assert list(frame["comparison_label"].unique()) == ["name_exp_a", "name_exp_b"]


def test_load_experiments_is_preferred_alias(monkeypatch):
    def _fake_loader(name, use_storage=True, refresh=False, **kwargs):
        _ = use_storage, refresh, kwargs
        return Dataset(
            data=pd.DataFrame({"temperature_C": [25.0], "heat_flow_mW": [0.1]}),
            metadata={"experiment_id": name, "experiment_name": f"name_{name}"},
        )

    monkeypatch.setattr("mfethuls.comparison.is_experiment_registered", lambda name: True)
    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader)

    comparison = load_experiments(["exp_a"])
    assert isinstance(comparison, ComparisonSet)
    assert comparison.labels == ["name_exp_a"]


def test_load_samples_filters_registry_and_loads_matching_experiments(monkeypatch):
    registry = pd.DataFrame(
        [
            {"name": "exp_a", "experiment_id": "EXP001", "sample_id": "S001"},
            {"name": "exp_b", "experiment_id": "EXP002", "sample_id": "S002"},
            {"name": "exp_c", "experiment_id": "EXP003", "sample_id": "S001"},
        ]
    )

    loaded_names: list[str] = []

    from mfethuls import comparison as comparison_module

    monkeypatch.setattr(comparison_module, "load_experiment_registry", lambda registry_path=None: registry)

    def _fake_loader(name, use_storage=True, refresh=False, **kwargs):
        _ = use_storage, refresh, kwargs
        loaded_names.append(name)
        return Dataset(
            data=pd.DataFrame({"temperature_C": [25.0], "heat_flow_mW": [0.1]}),
            metadata={"experiment_id": name, "experiment_name": f"name_{name}", "sample_id": "S001"},
        )

    monkeypatch.setattr(comparison_module, "load_experiment_dataset", _fake_loader)

    comparison = load_samples("S001")

    assert isinstance(comparison, ComparisonSet)
    assert loaded_names == ["exp_a", "exp_c"]
    assert comparison.labels == ["name_exp_a", "name_exp_c"]


def test_load_experiments_loads_registry_in_fresh_session(monkeypatch, empty_experiment_registry):
    """load_experiments reads PATH_TO_REGISTRY itself, like load_samples."""
    monkeypatch.setenv("PATH_TO_REGISTRY", str(EXAMPLE_REGISTRY))

    def _fake_loader(name, use_storage=True, refresh=False, **kwargs):
        _ = use_storage, refresh, kwargs
        exp = get_experiment(name)  # raises if the registry was not loaded
        return Dataset(
            data=pd.DataFrame({"temperature_C": [25.0]}),
            metadata={"experiment_id": exp.name, "experiment_name": exp.name},
        )

    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader)

    comparison = load_experiments(["LB_dsc_001", "LB_dsc_002"])
    assert comparison.labels == ["LB_dsc_001", "LB_dsc_002"]


def test_load_experiments_unknown_name_mentions_registry(monkeypatch, empty_experiment_registry):
    monkeypatch.delenv("PATH_TO_REGISTRY", raising=False)

    with pytest.raises(KeyError, match="experiments_registry.csv"):
        load_experiments(["does_not_exist"], registry_path=str(EXAMPLE_REGISTRY))
