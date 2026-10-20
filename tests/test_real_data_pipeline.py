"""End-to-end ingest of the onboarding examples in ``examples/``.

The examples are copied to a temporary folder first, because ingest writes a
manifest into the data folder and parquet/DuckDB files into storage.
"""

import shutil

import pandas as pd
import pytest

from mfethuls.config.loader import load_experiment_dataset
from mfethuls.experiments import Registry
from mfethuls.instruments.configured import definition_for
from mfethuls.manifest import FileManifestBackend

from mfethuls.examples import EXAMPLES_DIR
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
    monkeypatch.delenv("MFETHULS_DUCKDB_PATH", raising=False)
    return data_root, registry_path, local_storage


def test_examples_registry_loads(examples_config):
    """Every example row is valid and registered."""

    _, registry_path, _ = examples_config
    registry = Registry.load(str(registry_path))

    assert {"name", "instrument_name", "raw_data_filename"}.issubset(registry.frame.columns)
    assert registry.names == EXAMPLE_NAMES
    assert not [problem for problem in registry.problems if problem.skipped]


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

    # The manifest entry records the hash of the raw files that were parsed.
    data_root = examples_config[0]
    (entry,) = [m for m in FileManifestBackend(str(data_root)).all_mappings() if m["experiment_id"] == ds.experiment_id]
    assert entry["content_hash"]


@pytest.mark.parametrize("instrument", ["dsc", "tga", "ftir"])
def test_examples_in_shared_folder_get_their_own_data(examples_config, instrument):
    """poly1 and poly2 share an instrument folder but must not share data."""

    ds1 = load_experiment_dataset(f"LB_{instrument}_001", use_storage=False)
    ds2 = load_experiment_dataset(f"LB_{instrument}_002", use_storage=False)

    numeric1 = ds1.data.select_dtypes("number").reset_index(drop=True)
    numeric2 = ds2.data.select_dtypes("number").reset_index(drop=True)
    assert not numeric1.equals(numeric2)


def test_files_next_to_the_data_are_not_read_or_hashed(examples_config, caplog):
    """A plot saved next to the raw data is skipped at ingest and does not change the hash."""

    data_root, _, _ = examples_config
    name = EXAMPLE_NAMES[0]
    first = load_experiment_dataset(name, use_storage=True, refresh=True)
    (entry,) = [m for m in FileManifestBackend(str(data_root)).all_mappings() if m["experiment_id"] == first.experiment_id]

    raw = entry["raw_data_filename"]
    # In the experiment's instrument folder: other instruments' folders have files of the same name
    # (TGA/poly1.txt next to DSC/poly1.txt), and rglob's order differs between systems.
    folder = data_root / definition_for(entry["instrument_name"], str(data_root)).folder_name
    (data_file,) = [p for p in sorted(folder.rglob(f"{raw}*")) if p.is_file() and p.suffix != ".parquet"][:1]
    (data_file.parent / f"{raw}.svg").write_text("<svg/>", encoding="utf8")

    with caplog.at_level("WARNING", logger="mfethuls.config.loader"):
        again = load_experiment_dataset(name, use_storage=True, refresh=True)
    (after,) = [m for m in FileManifestBackend(str(data_root)).all_mappings() if m["experiment_id"] == first.experiment_id]

    assert len(again.data) == len(first.data)
    assert after["content_hash"] == entry["content_hash"]
    assert f"{raw}.svg" in caplog.text
