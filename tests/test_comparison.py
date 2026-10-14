from pathlib import Path

import pandas as pd
import pytest

from mfethuls import ComparisonSet, Registry, load_experiments, load_samples
from mfethuls.comparison import ComparisonSet as ComparisonSetDirect
from mfethuls.dataset import Dataset

EXAMPLE_REGISTRY = Path(__file__).resolve().parents[1] / "examples" / "experiments_registry.csv"


def _registry(*rows: tuple[str, str]) -> Registry:
    """A registry of DSC experiments from (name, sample_id) pairs."""
    return Registry.from_frame(
        pd.DataFrame([{"name": name, "instrument_name": "dsc", "sample_id": sample} for name, sample in rows])
    )


def _fake_loader(loaded: list[str] | None = None, frames: dict | None = None):
    def loader(name, use_storage=True, refresh=False, registry=None, **kwargs):
        if loaded is not None:
            loaded.append(name)
        data = (frames or {}).get(name, pd.DataFrame({"temperature_C": [25.0], "heat_flow_mW": [0.1]}))
        exp = registry.get(name)  # raises if the experiment is not in the registry passed on
        return Dataset(data=data, metadata={"experiment_id": exp.name, "experiment_name": f"name_{exp.name}"})

    return loader


def test_load_experiments_to_dataframe_works(monkeypatch):
    frames = {
        "exp_a": pd.DataFrame({"temperature_C": [25.0, 50.0], "heat_flow_mW": [0.1, 0.2]}),
        "exp_b": pd.DataFrame({"temperature_C": [30.0, 60.0], "heat_flow_mW": [0.3, 0.4]}),
    }
    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader(frames=frames))

    comparison = load_experiments(["exp_a", "exp_b"], registry=_registry(("exp_a", "S001"), ("exp_b", "S002")))
    assert isinstance(comparison, ComparisonSet)
    assert isinstance(comparison, ComparisonSetDirect)

    frame = comparison.to_dataframe()
    assert {"comparison_label", "temperature_C", "heat_flow_mW"}.issubset(frame.columns)
    assert "comparison_index" not in frame.columns
    assert frame.shape[0] == 4
    assert list(frame["comparison_label"].unique()) == ["name_exp_a", "name_exp_b"]


def test_load_samples_loads_matching_experiments_in_registry_order(monkeypatch):
    loaded: list[str] = []
    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader(loaded))

    registry = _registry(("exp_a", "S001"), ("exp_b", "S002"), ("exp_c", "S001"))
    comparison = load_samples("S001", registry=registry)

    assert loaded == ["exp_a", "exp_c"]
    assert comparison.labels == ["name_exp_a", "name_exp_c"]


def test_load_samples_without_matches_raises():
    with pytest.raises(ValueError, match="S999"):
        load_samples("S999", registry=_registry(("exp_a", "S001")))


def test_load_experiments_reads_registry_file_when_none_given(monkeypatch):
    """Without a registry, load_experiments reads PATH_TO_REGISTRY itself."""
    monkeypatch.setenv("PATH_TO_REGISTRY", str(EXAMPLE_REGISTRY))
    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader())

    comparison = load_experiments(["LB_dsc_001", "LB_dsc_002"])
    assert comparison.labels == ["name_LB_dsc_001", "name_LB_dsc_002"]


def test_load_experiments_reads_edits_to_the_registry_file(monkeypatch, tmp_path):
    """Nothing is cached between calls, so a renamed row is picked up immediately."""
    path = tmp_path / "registry.csv"
    pd.DataFrame([{"name": "exp_a", "instrument_name": "dsc"}]).to_csv(path, index=False)
    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader())

    assert load_experiments(["exp_a"], registry_path=str(path)).labels == ["name_exp_a"]

    pd.DataFrame([{"name": "exp_b", "instrument_name": "dsc"}]).to_csv(path, index=False)
    assert load_experiments(["exp_b"], registry_path=str(path)).labels == ["name_exp_b"]


def test_load_experiments_unknown_name_mentions_registry():
    with pytest.raises(KeyError, match="experiments_registry.csv"):
        load_experiments(["does_not_exist"], registry_path=str(EXAMPLE_REGISTRY))
