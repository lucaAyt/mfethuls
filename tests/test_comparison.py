import pandas as pd

from mfethuls import ComparisonSet, load_experiments
from mfethuls.comparison import ComparisonSet as ComparisonSetDirect, load_comparison_set
from mfethuls.dataset import Dataset


def test_load_comparison_set_to_dataframe_works(monkeypatch):
    def _fake_loader(name, use_storage=True, refresh=False):
        _ = use_storage, refresh
        return {
            "exp_a": pd.DataFrame({"temperature_C": [25.0, 50.0], "heat_flow_mW": [0.1, 0.2]}),
            "exp_b": pd.DataFrame({"temperature_C": [30.0, 60.0], "heat_flow_mW": [0.3, 0.4]}),
        }[name]

    from mfethuls import comparison as comparison_module

    monkeypatch.setattr(
        comparison_module,
        "load_experiment_dataset",
        lambda name, use_storage=True, refresh=False: Dataset(
            data=_fake_loader(name, use_storage, refresh),
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
    def _fake_loader(name, use_storage=True, refresh=False):
        _ = use_storage, refresh
        return Dataset(
            data=pd.DataFrame({"temperature_C": [25.0], "heat_flow_mW": [0.1]}),
            metadata={"experiment_id": name, "experiment_name": f"name_{name}"},
        )

    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader)

    comparison = load_experiments(["exp_a"])
    assert isinstance(comparison, ComparisonSet)
    assert comparison.labels == ["name_exp_a"]
