"""End-to-end ingest of the onboarding examples in ``examples/``.

The examples are copied to a temporary folder first, because ingest writes a
manifest into the data folder and parquet/DuckDB files into storage.
"""

import shutil
from pathlib import Path

import pandas as pd
import pytest

from mfethuls import experiments as experiments_module
from mfethuls.config.loader import load_experiment_dataset
from mfethuls.experiments import load_experiment_registry

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
EXAMPLE_NAMES = pd.read_csv(EXAMPLES_DIR / "experiments_registry.csv")["name"].tolist()


@pytest.fixture()
def examples_config(tmp_path, monkeypatch):
    """Point mfethuls at a temporary copy of examples/, independent of .env."""

    examples = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, examples)
    data_root = examples / "data"
    registry_path = examples / "experiments_registry.csv"
    local_storage = tmp_path / "storage"

    monkeypatch.setenv("PATH_TO_DATA", str(data_root))
    monkeypatch.setenv("PATH_TO_REGISTRY", str(registry_path))
    monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", str(local_storage))
    monkeypatch.setenv("MFETHULS_MODE", "local")
    monkeypatch.setenv("MFETHULS_DISABLE_STORAGE", "0")
    monkeypatch.delenv("MFETHULS_DUCKDB_PATH", raising=False)
    monkeypatch.setattr(experiments_module, "_EXPERIMENT_REGISTRY", {})

    load_experiment_registry(str(registry_path))
    return data_root, registry_path, local_storage


def test_examples_registry_loads(examples_config):
    """Every example row is valid and registered."""

    _, registry_path, _ = examples_config
    df_registry = load_experiment_registry(str(registry_path))

    assert {"name", "instrument_name", "raw_data_filename"}.issubset(df_registry.columns)
    assert all(experiments_module.is_experiment_registered(name) for name in EXAMPLE_NAMES)


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_examples_parse_and_cache_pipeline(examples_config, name):
    """Each example parses from raw data, is stored, and loads back from the cache."""

    _, _, local_storage = examples_config

    ds = load_experiment_dataset(name, use_storage=True, refresh=True)
    assert ds is not None
    assert ds.experiment_id is not None
    assert not ds.data.empty

    ds_cached = load_experiment_dataset(name, use_storage=True, refresh=False)
    assert ds_cached.experiment_id == ds.experiment_id
    assert len(ds_cached.data) == len(ds.data)

    assert local_storage.exists()


@pytest.mark.parametrize("instrument", ["dsc", "tga", "ftir"])
def test_examples_in_shared_folder_get_their_own_data(examples_config, instrument):
    """poly1 and poly2 share an instrument folder but must not share data."""

    ds1 = load_experiment_dataset(f"LB_{instrument}_001", use_storage=False)
    ds2 = load_experiment_dataset(f"LB_{instrument}_002", use_storage=False)

    numeric1 = ds1.data.select_dtypes("number").reset_index(drop=True)
    numeric2 = ds2.data.select_dtypes("number").reset_index(drop=True)
    assert not numeric1.equals(numeric2)
