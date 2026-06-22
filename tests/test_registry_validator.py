"""Tests for registry validator."""

import pytest
import pandas as pd

from mfethuls.experiments import Experiment
from mfethuls.registry_validator import (
    RegistryValidator,
    RegistryValidationError,
    validate_registry_dataframe,
    _check_name_uniqueness,
    _check_raw_data_filename_uniqueness,
    _check_raw_data_filename_filesystem_safe,
)
from mfethuls.factory import parse_experiment


class TestRegistryValidator:
    """Test suite for RegistryValidator."""

    def test_validate_valid_experiment(self):
        validator = RegistryValidator()
        exp = Experiment(name="test_dsc", instrument_name="dsc")
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"
        assert len(errors) == 0

    def test_validate_valid_experiment_is_case_insensitive(self):
        validator = RegistryValidator()
        exp = Experiment(name="test_dsc_upper", instrument_name="DSC")
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"

    def test_validate_unknown_instrument(self):
        validator = RegistryValidator()
        exp = Experiment(name="test_unknown", instrument_name="nonexistent_instrument")
        is_valid, errors = validator.validate_experiment(exp)
        assert not is_valid
        assert any("not found in instrument_params.json" in err for err in errors)

    def test_validate_rheometer_with_valid_profile(self):
        validator = RegistryValidator()
        exp = Experiment(
            name="test_rheometer",
            instrument_name="rheometer",
            metadata={"measurement_profile": "oscillatory_frequency_sweep"},
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"

    def test_validate_rheometer_with_profile_similarity_match(self):
        validator = RegistryValidator()
        exp = Experiment(
            name="test_rheometer_similarity",
            instrument_name="rheometer",
            metadata={"measurement_profile": "Oscillatory Frequency Sweep"},
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"

    def test_validate_rheometer_with_profile_subset_similarity_match(self):
        validator = RegistryValidator()
        exp = Experiment(
            name="test_rheometer_subset_similarity",
            instrument_name="rheometer",
            metadata={"measurement_profile": "frequency sweep"},
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"

    def test_validate_rheometer_with_invalid_profile(self):
        validator = RegistryValidator()
        exp = Experiment(
            name="test_rheometer",
            instrument_name="rheometer",
            metadata={"registry_measurement_profile": "nonexistent_profile"},
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid

    def test_validate_rheometer_rejects_non_subset_profile(self):
        validator = RegistryValidator()
        exp = Experiment(
            name="test_rheometer_non_subset",
            instrument_name="rheometer",
            metadata={"registry_measurement_profile": "frequency sweep extra"},
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid

    def test_validate_all_diagnostic(self):
        validator = RegistryValidator()
        all_valid, errors_dict = validator.validate_all()
        assert all_valid, f"Some instruments failed validation: {errors_dict}"
        assert isinstance(errors_dict, dict)

    def test_parse_experiment_fails_with_invalid_instrument(self):
        exp = Experiment(name="test_invalid", instrument_name="nonexistent_instrument")

        class MockInstrument:
            type_ = "unknown"
            model = "unknown"
            name = "nonexistent_instrument"

        with pytest.raises(RegistryValidationError):
            parse_experiment(exp, {}, MockInstrument())

    def test_list_instrument_names(self):
        validator = RegistryValidator()
        names_str = validator._list_instrument_names()
        assert "dsc" in names_str
        assert "rheometer" in names_str

    def test_list_available_parsers(self):
        validator = RegistryValidator()
        parsers_str = validator._list_available_parsers()
        assert "(" in parsers_str
        assert ")" in parsers_str

    def test_validate_sample_id(self):
        assert RegistryValidator.validate_sample_id("S010") == "S010"
        assert RegistryValidator.validate_sample_id(None) is None
        with pytest.raises(ValueError):
            RegistryValidator.validate_sample_id("S1")

    def test_validate_run_id(self):
        assert RegistryValidator.validate_run_id("R099") == "R099"
        assert RegistryValidator.validate_run_id(None) is None
        with pytest.raises(ValueError):
            RegistryValidator.validate_run_id("R1")


class TestDataframeValidations:
    """Tests for the new DataFrame-level uniqueness and safety checks."""

    def test_duplicate_name_caught(self):
        df = pd.DataFrame([
            {"name": "exp_a", "instrument_name": "dsc"},
            {"name": "exp_a", "instrument_name": "tga"},
        ])
        errors = _check_name_uniqueness(df)
        assert errors
        assert "exp_a" in errors[0]

    def test_unique_names_pass(self):
        df = pd.DataFrame([
            {"name": "exp_a", "instrument_name": "dsc"},
            {"name": "exp_b", "instrument_name": "dsc"},
        ])
        assert _check_name_uniqueness(df) == []

    def test_duplicate_raw_data_filename_per_instrument_caught(self):
        df = pd.DataFrame([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "run_jan15"},
            {"name": "exp_b", "instrument_name": "dsc", "raw_data_filename": "run_jan15"},
        ])
        errors = _check_raw_data_filename_uniqueness(df)
        assert errors
        assert "run_jan15" in errors[0]

    def test_same_filename_different_instruments_is_ok(self):
        df = pd.DataFrame([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "run_jan15"},
            {"name": "exp_b", "instrument_name": "tga", "raw_data_filename": "run_jan15"},
        ])
        assert _check_raw_data_filename_uniqueness(df) == []

    def test_unsafe_filename_characters_caught(self):
        df = pd.DataFrame([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "my file (1)"},
        ])
        errors = _check_raw_data_filename_filesystem_safe(df)
        assert errors
        assert "my file (1)" in errors[0]

    def test_safe_filename_passes(self):
        df = pd.DataFrame([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "chitosan_jan15"},
        ])
        assert _check_raw_data_filename_filesystem_safe(df) == []

    def test_validate_registry_dataframe_catches_global_errors(self):
        df = pd.DataFrame([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "run1"},
            {"name": "exp_a", "instrument_name": "tga", "raw_data_filename": "run2"},
        ])
        result = validate_registry_dataframe(df)
        first_row_errors = result["rows"][0]["errors"]
        assert any(e["field"] == "registry_global" for e in first_row_errors)
