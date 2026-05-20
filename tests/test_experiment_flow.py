import os
import tempfile
import logging
from importlib.metadata import PackageNotFoundError, version

import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls.experiments import Experiment
from mfethuls.experiments import get_experiment, load_experiment_registry
from mfethuls.factory import parse_experiment
from mfethuls.config_loader import load_experiment_dataset
from mfethuls.storage import (
    dataset_in_storage,
    load_dataset_from_storage,
    save_dataset_to_storage,
)


def _write_registry(tmpdir: str) -> str:
    """Create a minimal experiment registry CSV for tests.

    This uses a dummy experiment that can be resolved by the library. The
    actual data files do not need to exist for the purposes of testing the
    registry loading and high-level wiring; parsing errors are caught
    explicitly in tests that expect failure.
    """

    path = os.path.join(tmpdir, "experiments_test.csv")
    df = pd.DataFrame(
        [
            {
                "name": "dsc_test_1",
                "experiment_id": "EXP001",
                "instrument_name": "dsc_mettler_toledo",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "dsc_test_2",
                "experiment_id": "EXP002",
                "instrument_name": "dsc_mettler_toledo",
                "sample_id": "S002",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "dsc_test_3",
                "experiment_id": "EXP003",
                "instrument_name": "dsc_perkin_elmer",
                "sample_id": "S003",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "rheometer_test_1",
                "experiment_id": "EXP004",
                "instrument_name": "rheometer",
                "sample_id": "S001",
                "run_id": "R001",
                "description": "Oscillatory frequency sweep rheology run",
                "status": "to_analyse",
            },
            {
                "name": "sec_test_1",
                "experiment_id": "EXP005",
                "instrument_name": "sec",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "ms_test_1",
                "experiment_id": "EXP006",
                "instrument_name": "ms",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "saxs_test_1",
                "experiment_id": "EXP007",
                "instrument_name": "saxs",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "tga_test_1",
                "experiment_id": "EXP008",
                "instrument_name": "tga",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "ftir_test_1",
                "experiment_id": "EXP009",
                "instrument_name": "ftir",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "dma_test_1",
                "experiment_id": "EXP010",
                "instrument_name": "dma",
                "sample_id": "S001",
                "run_id": "R001",
                "description": "DMA temperature sweep run",
                "status": "to_analyse",
            },
            {
                "name": "uv_vis_test_1",
                "experiment_id": "EXP011",
                "instrument_name": "uv_vis",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            }
        ]
    )
    df.to_csv(path, index=False)
    return path


def test_load_experiment_registry_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)

        df_registry = load_experiment_registry(registry_path)

        assert "name" in df_registry.columns
        assert "experiment_id" in df_registry.columns
        # Check that all expected experiment_ids are present
        expected_ids = {
            "EXP001",
            "EXP002",
            "EXP003",
            "EXP004",
            "EXP005",
            "EXP006",
            "EXP007",
            "EXP008",
            "EXP009",
            "EXP010",
            "EXP011",
        }
        assert set(df_registry["experiment_id"]) == expected_ids


def test_load_experiment_registry_defaults_from_path_to_registry(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)
        default_registry_path = os.path.join(tmpdir, "experiment_registry.csv")
        os.replace(registry_path, default_registry_path)

        monkeypatch.setenv("PATH_TO_REGISTRY", default_registry_path)
        monkeypatch.setenv("PATH_TO_DATA", "ignored-for-registry-default")

        df_registry = load_experiment_registry()

        assert "name" in df_registry.columns
        assert set(df_registry["experiment_id"]) >= {"EXP001", "EXP011"}


def test_load_experiment_registry_infers_measurement_profile_from_description():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)
        load_experiment_registry(registry_path)

        exp = get_experiment("rheometer_test_1")
        assert exp.metadata.get("description") == "Oscillatory frequency sweep rheology run"
        # Registry layer creates raw registry_measurement_profile only
        assert exp.metadata.get("registry_measurement_profile") == "oscillatory_frequency_sweep"
        # measurement_profile should not exist until parser runs
        assert "measurement_profile" not in exp.metadata
        assert exp.metadata.get("measurement_profile") is None


def test_load_experiment_registry_infers_dma_measurement_profile_from_description():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)
        load_experiment_registry(registry_path)

        exp = get_experiment("dma_test_1")
        assert exp.metadata.get("description") == "DMA temperature sweep run"
        # Registry layer creates raw registry_measurement_profile only
        assert exp.metadata.get("registry_measurement_profile") == "oscillatory_temperature_sweep"
        # measurement_profile should not exist until parser runs
        assert "measurement_profile" not in exp.metadata
        assert exp.metadata.get("measurement_profile") is None


def test_load_experiment_registry_explicit_measurement_profile_trumps_inference():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = os.path.join(tmpdir, "experiments_profile_priority.csv")
        pd.DataFrame(
            [
                {
                    "name": "dma_profile_priority",
                    "experiment_id": "EXP099",
                    "instrument_name": "dma",
                    "sample_id": "S001",
                    "run_id": "R001",
                    "description": "temperature sweep run",
                    "measurement_profile": "oscillatory_frequency_sweep",
                }
            ]
        ).to_csv(registry_path, index=False)

        load_experiment_registry(registry_path)
        exp = get_experiment("dma_profile_priority")
        # Registry layer creates raw registry_measurement_profile only
        assert exp.metadata.get("registry_measurement_profile") == "oscillatory_frequency_sweep"
        # measurement_profile should not exist until parser runs
        assert "measurement_profile" not in exp.metadata
        assert exp.metadata.get("measurement_profile") is None


def test_load_experiment_dataset_returns_dataset_even_when_missing_files():
    """High-level check that load_experiment_dataset returns a Dataset.

    This test intentionally does not depend on actual instrument data files
    being present. Instead, it asserts that the function returns either a
    Dataset or raises a KeyError/IO-related error when paths are missing,
    without crashing in unexpected ways.
    """

    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)
        df_registry = load_experiment_registry(registry_path)

        # For each experiment in the registry, either obtain a Dataset or
        # get a reasonable filesystem-related error (e.g. missing data).
        for row in df_registry.itertuples(index=False):
            name = row.name
            expected_experiment_id = row.experiment_id

            try:
                print(f'Loading dataset for {name}')
                ds = load_experiment_dataset(name)
                print(f'Loaded dataset for {ds.experiment_id}: {ds.data.head(5)}')
            except Exception as exc:  # noqa: BLE001
                assert isinstance(exc, (KeyError, FileNotFoundError, OSError))
            else:
                assert isinstance(ds, Dataset)
                assert ds.experiment_id == expected_experiment_id


def test_dataset_storage_roundtrip_uses_temp_folder(monkeypatch):
    """Basic roundtrip test for the local Dataset storage helper.

    This test does not depend on any real instrument data. It verifies that
    a Dataset can be saved to and loaded from the configured storage
    location, and that the storage paths live under the expected root.
    """

    with tempfile.TemporaryDirectory() as tmpdir:
        # Ensure storage writes into our temporary directory.
        monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", tmpdir)

        from mfethuls.experiments import Experiment

        exp = Experiment(
            name="test_exp_storage",
            experiment_id="EXP999",
            instrument_name="dummy_instrument",
            sample_id="S001",
            run_id="R001",
        )

        df = pd.DataFrame({"a": [1, 2, 3], "source_file": ["run1.txt", "run1.txt", "run2.txt"]})
        ds = Dataset(
            data=df,
            metadata={
                "key": "value",
                "instrument_type": "uv_vis",
                "instrument_model": "flame",
                "schema_version": "1.0",
                "schema_normalization": {
                    "schema_applied": True,
                    "warnings": ["sample warning"],
                    "missing_required_columns": [],
                },
            },
        )

        parquet_path, meta_path = save_dataset_to_storage(exp, ds)

        assert os.path.commonpath([tmpdir, parquet_path]) == os.path.abspath(tmpdir)
        assert os.path.exists(parquet_path)
        assert os.path.exists(meta_path)
        assert dataset_in_storage(exp)

        loaded = load_dataset_from_storage(exp)
        assert isinstance(loaded, Dataset)
        assert loaded.data.equals(df)
        assert loaded.metadata.get("key") == "value"
        assert "provenance" in loaded.metadata

        provenance = loaded.metadata["provenance"]
        assert provenance["storage"]["backend"] == "local_filesystem"
        assert provenance["storage"]["format"]["data"] == "parquet"
        assert "mfethuls_version" in provenance
        try:
            expected_version = version("mfethuls")
        except PackageNotFoundError:
            expected_version = "unknown"
        assert provenance["mfethuls_version"] == expected_version
        assert provenance["schema"]["schema_version"] == "1.0"
        assert provenance["schema"]["warning_count"] == 1
        assert provenance["source"]["source_file_count"] == 2
        assert provenance["source"]["source_files"] == ["run1.txt", "run2.txt"]
        assert "dataset" not in provenance
        assert "instrument" not in provenance


def test_load_experiment_registry_normalizes_instrument_name_case():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = os.path.join(tmpdir, "experiments_case_test.csv")
        pd.DataFrame(
            [
                {
                    "name": "case_test_1",
                    "experiment_id": "EXP012",
                    "instrument_name": "DSC_METTLER_TOLEDO",
                    "sample_id": "S001",
                    "run_id": "R001",
                }
            ]
        ).to_csv(registry_path, index=False)

        load_experiment_registry(registry_path)
        exp = get_experiment("case_test_1")
        assert exp.instrument_name == "dsc_mettler_toledo"


def test_load_experiment_registry_keeps_placeholder_experiments_without_instrument_data(caplog):
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = os.path.join(tmpdir, "experiments_placeholder_test.csv")
        pd.DataFrame(
            [
                {
                    "name": "placeholder_exp",
                    "experiment_id": "EXP013",
                    "instrument_name": None,
                    "sample_id": "S001",
                    "run_id": "R001",
                    "status": "registered_only",
                }
            ]
        ).to_csv(registry_path, index=False)

        load_experiment_registry(registry_path)

        exp = get_experiment("placeholder_exp")
        assert exp.instrument_name is None
        assert exp.metadata.get("status") == "registered_only"

        with caplog.at_level(logging.WARNING):
            result = load_experiment_dataset("placeholder_exp")

        assert result is None
        assert any("has no associated instrument data yet" in message for message in caplog.messages)


def test_load_experiment_registry_skips_invalid_experiment_ids(caplog):
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = os.path.join(tmpdir, "experiments_invalid_id_test.csv")
        pd.DataFrame(
            [
                {
                    "name": "bad_exp",
                    "experiment_id": "EXP1",
                    "instrument_name": "sec",
                    "sample_id": "S001",
                    "run_id": "R001",
                },
                {
                    "name": "good_placeholder_exp",
                    "experiment_id": "EXP014",
                    "instrument_name": None,
                    "sample_id": "S002",
                    "run_id": "R001",
                    "status": "registered_only",
                },
            ]
        ).to_csv(registry_path, index=False)

        with caplog.at_level(logging.WARNING):
            load_experiment_registry(registry_path)

        assert any("Skipping registry row 'bad_exp'" in message for message in caplog.messages)

        with pytest.raises(KeyError):
            get_experiment("bad_exp")

        placeholder = get_experiment("good_placeholder_exp")
        assert placeholder.experiment_id == "EXP014"
        assert placeholder.instrument_name is None


def test_parse_experiment_applies_characterizer_for_dataset_parser_output():
    class _FakeParser:
        def parse(self, dict_paths, **kwargs):
            _ = dict_paths, kwargs
            return Dataset(
                data=pd.DataFrame(
                    {
                        "temperature_C": [25.0, 50.0, 75.0],
                        "heat_flow_mW": [0.1, 0.4, 0.2],
                    }
                ),
                metadata={"schema_version": "1.0"},
            )

    class _FakeCharacterizer:
        def characterize(self, df):
            return df.assign(profile="Heating")

    class _FakeInstrument:
        type_ = "dsc"
        model = "mettler_toledo"
        name = "dsc_mettler_toledo"
        parser = _FakeParser()
        characterizer = _FakeCharacterizer()

    exp = Experiment(
        name="dsc_char_test",
        experiment_id="EXP123",
        instrument_name="dsc_mettler_toledo",
        sample_id="S001",
        run_id="R001",
    )

    ds = parse_experiment(exp, dict_data_paths={}, instrument=_FakeInstrument())
    assert isinstance(ds, Dataset)
    assert "profile" in ds.data.columns
    assert ds.metadata.get("characterization", {}).get("applied") is True
    assert ds.metadata.get("characterization", {}).get("name") == "_FakeCharacterizer"
