import os
import tempfile
import logging
from importlib.metadata import PackageNotFoundError, version
from unittest.mock import patch

import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls.experiments import Experiment
from mfethuls.experiments import get_experiment, load_experiment_registry
from mfethuls.factory import parse_experiment
from mfethuls.config.loader import load_experiment_dataset
from mfethuls.storage import (
    dataset_in_storage,
    load_dataset_from_storage,
    save_dataset_to_storage,
)

_FAKE_EXPERIMENT_ID = "abc123def456"


def _write_registry(tmpdir: str) -> str:
    path = os.path.join(tmpdir, "experiments_test.csv")
    df = pd.DataFrame(
        [
            {
                "name": "dsc_test_1",
                "instrument_name": "dsc_mettler_toledo",
                "raw_data_filename": "dsc_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "dsc_test_2",
                "instrument_name": "dsc_mettler_toledo",
                "raw_data_filename": "dsc_test_2_data",
                "sample_id": "S002",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "dsc_test_3",
                "instrument_name": "dsc_perkin_elmer",
                "raw_data_filename": "dsc_test_3_data",
                "sample_id": "S003",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "rheometer_test_1",
                "instrument_name": "rheometer",
                "raw_data_filename": "rheometer_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "description": "Oscillatory frequency sweep rheology run",
                "status": "to_analyse",
            },
            {
                "name": "sec_test_1",
                "instrument_name": "sec",
                "raw_data_filename": "sec_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "ms_test_1",
                "instrument_name": "ms",
                "raw_data_filename": "ms_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "saxs_test_1",
                "instrument_name": "saxs",
                "raw_data_filename": "saxs_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "tga_test_1",
                "instrument_name": "tga",
                "raw_data_filename": "tga_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "ftir_test_1",
                "instrument_name": "ftir",
                "raw_data_filename": "ftir_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
            {
                "name": "dma_test_1",
                "instrument_name": "dma",
                "raw_data_filename": "dma_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "description": "DMA temperature sweep run",
                "status": "to_analyse",
            },
            {
                "name": "uv_vis_test_1",
                "instrument_name": "uv_vis",
                "raw_data_filename": "uv_vis_test_1_data",
                "sample_id": "S001",
                "run_id": "R001",
                "status": "to_analyse",
            },
        ]
    )
    df.to_csv(path, index=False)
    return path


def test_load_experiment_registry_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)
        df_registry = load_experiment_registry(registry_path)

        assert "name" in df_registry.columns
        assert "raw_data_filename" in df_registry.columns
        expected_names = {
            "dsc_test_1", "dsc_test_2", "dsc_test_3",
            "rheometer_test_1", "sec_test_1", "ms_test_1",
            "saxs_test_1", "tga_test_1", "ftir_test_1",
            "dma_test_1", "uv_vis_test_1",
        }
        assert set(df_registry["name"]) == expected_names


def test_load_experiment_registry_defaults_from_path_to_registry(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)
        default_registry_path = os.path.join(tmpdir, "experiment_registry.csv")
        os.replace(registry_path, default_registry_path)

        monkeypatch.setenv("PATH_TO_REGISTRY", default_registry_path)
        monkeypatch.setenv("PATH_TO_DATA", "ignored-for-registry-default")

        df_registry = load_experiment_registry()

        assert "name" in df_registry.columns
        assert "dsc_test_1" in set(df_registry["name"])


def test_load_experiment_registry_infers_measurement_profile_from_description():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)
        load_experiment_registry(registry_path)

        exp = get_experiment("rheometer_test_1")
        assert exp.metadata.get("description") == "Oscillatory frequency sweep rheology run"
        assert exp.metadata.get("registry_measurement_profile") == "oscillatory_frequency_sweep"
        assert "measurement_profile" not in exp.metadata
        assert exp.metadata.get("measurement_profile") is None


def test_load_experiment_registry_infers_dma_measurement_profile_from_description():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = _write_registry(tmpdir)
        load_experiment_registry(registry_path)

        exp = get_experiment("dma_test_1")
        assert exp.metadata.get("description") == "DMA temperature sweep run"
        assert exp.metadata.get("registry_measurement_profile") == "oscillatory_temperature_sweep"
        assert "measurement_profile" not in exp.metadata


def test_load_experiment_registry_explicit_measurement_profile_trumps_inference():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = os.path.join(tmpdir, "experiments_profile_priority.csv")
        pd.DataFrame(
            [
                {
                    "name": "dma_profile_priority",
                    "instrument_name": "dma",
                    "raw_data_filename": "dma_profile_priority_data",
                    "sample_id": "S001",
                    "run_id": "R001",
                    "description": "temperature sweep run",
                    "measurement_profile": "oscillatory_frequency_sweep",
                }
            ]
        ).to_csv(registry_path, index=False)

        load_experiment_registry(registry_path)
        exp = get_experiment("dma_profile_priority")
        assert exp.metadata.get("registry_measurement_profile") == "oscillatory_frequency_sweep"
        assert "measurement_profile" not in exp.metadata


def test_load_experiment_dataset_returns_dataset_even_when_missing_files(monkeypatch):
    """High-level check that load_experiment_dataset returns a Dataset or raises filesystem errors."""

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("PATH_TO_DATA", tmpdir)
        registry_path = _write_registry(tmpdir)
        df_registry = load_experiment_registry(registry_path)

        for row in df_registry.itertuples(index=False):
            name = row.name
            with patch(
                "mfethuls.config.loader._assign_experiment_id",
                side_effect=lambda exp, db_url: setattr(exp, "experiment_id", _FAKE_EXPERIMENT_ID) or None,
            ):
                try:
                    ds = load_experiment_dataset(name)
                except Exception as exc:
                    assert isinstance(exc, (KeyError, FileNotFoundError, OSError))
                else:
                    assert isinstance(ds, Dataset)


def test_dataset_storage_roundtrip_uses_temp_folder(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", tmpdir)

        exp = Experiment(
            name="test_exp_storage",
            experiment_id="abc123def456",
            instrument_name="dummy_instrument",
            raw_data_filename="test_exp_storage",
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


def test_load_experiment_registry_normalizes_instrument_name_case():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = os.path.join(tmpdir, "experiments_case_test.csv")
        pd.DataFrame(
            [
                {
                    "name": "case_test_1",
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


def test_load_experiment_registry_raw_data_filename_defaults_to_name(caplog):
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = os.path.join(tmpdir, "experiments_no_filename.csv")
        pd.DataFrame(
            [
                {
                    "name": "exp_no_filename",
                    "instrument_name": "dsc_mettler_toledo",
                    "sample_id": "S001",
                    "run_id": "R001",
                }
            ]
        ).to_csv(registry_path, index=False)

        with caplog.at_level(logging.WARNING):
            load_experiment_registry(registry_path)

        exp = get_experiment("exp_no_filename")
        assert exp.raw_data_filename == "exp_no_filename"
        assert any("raw_data_filename" in m for m in caplog.messages)


def test_parse_experiment_applies_characterizer_for_dataset_parser_output():
    class _FakeParser:
        def parse(self, dict_paths, **kwargs):
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
        experiment_id="abc123def456",
        instrument_name="dsc_mettler_toledo",
        sample_id="S001",
        run_id="R001",
    )

    ds = parse_experiment(exp, dict_data_paths={}, instrument=_FakeInstrument())
    assert isinstance(ds, Dataset)
    assert "profile" in ds.data.columns
    assert ds.metadata.get("characterization", {}).get("applied") is True
    assert ds.metadata.get("characterization", {}).get("name") == "_FakeCharacterizer"
