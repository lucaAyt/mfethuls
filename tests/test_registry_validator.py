"""Tests for registry validator."""

import pytest

from mfethuls.experiments import Experiment
from mfethuls.registry_validator import (
    RegistryValidator,
    RegistryValidationError,
)
from mfethuls.factory import parse_experiment


class TestRegistryValidator:
    """Test suite for RegistryValidator."""

    def test_validate_valid_experiment(self):
        """Validator should accept a valid experiment with known instrument."""
        validator = RegistryValidator()
        exp = Experiment(
            name="test_dsc",
            experiment_id="EXP001",
            instrument_name="dsc",
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"
        assert len(errors) == 0

    def test_validate_unknown_instrument(self):
        """Validator should reject experiment with unknown instrument."""
        validator = RegistryValidator()
        exp = Experiment(
            name="test_unknown",
            experiment_id="EXP001",
            instrument_name="nonexistent_instrument",
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert not is_valid
        assert any("not found in instrument_params.json" in err for err in errors)

    def test_validate_rheometer_with_valid_profile(self):
        """Validator should accept rheometer with a known measurement profile."""
        validator = RegistryValidator()
        exp = Experiment(
            name="test_rheometer",
            experiment_id="EXP002",
            instrument_name="rheometer",
            metadata={"measurement_profile": "oscillatory_frequency_sweep"},
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"

    def test_validate_rheometer_with_invalid_profile(self):
        """Validator should reject rheometer with unknown measurement profile."""
        validator = RegistryValidator()
        exp = Experiment(
            name="test_rheometer",
            experiment_id="EXP002",
            instrument_name="rheometer",
            metadata={"measurement_profile": "nonexistent_profile"},
        )
        is_valid, errors = validator.validate_experiment(exp)
        assert not is_valid
        assert any("Unknown measurement_profile" in err for err in errors)

    def test_validate_all_diagnostic(self):
        """Validator.validate_all() should produce a diagnostic report."""
        validator = RegistryValidator()
        all_valid, errors_dict = validator.validate_all()
        # At minimum, we expect all configured instruments to be valid
        # (since the config should be self-consistent)
        assert all_valid, f"Some instruments failed validation: {errors_dict}"
        assert isinstance(errors_dict, dict)

    def test_parse_experiment_fails_with_invalid_instrument(self):
        """parse_experiment should raise RegistryValidationError for invalid setup."""
        exp = Experiment(
            name="test_invalid",
            experiment_id="EXP003",
            instrument_name="nonexistent_instrument",
        )
        # Create a minimal mock instrument for the call
        class MockInstrument:
            type_ = "unknown"
            model = "unknown"
            name = "nonexistent_instrument"

        with pytest.raises(RegistryValidationError):
            parse_experiment(exp, {}, MockInstrument())

    def test_list_instrument_names(self):
        """Validator should list available instrument names."""
        validator = RegistryValidator()
        names_str = validator._list_instrument_names()
        # Should contain at least the known test instruments
        assert "dsc" in names_str
        assert "rheometer" in names_str
        assert len(names_str) > 0

    def test_list_available_parsers(self):
        """Validator should list available registered parsers."""
        validator = RegistryValidator()
        parsers_str = validator._list_available_parsers()
        # Should contain at least some (type, model) pairs
        assert "(" in parsers_str
        assert ")" in parsers_str
        assert len(parsers_str) > 0

    def test_validate_id_methods(self):
        """RegistryValidator should validate canonical experiment/sample/run ids."""

        assert RegistryValidator.validate_experiment_id("EXP001") == "EXP001"
        assert RegistryValidator.validate_sample_id("S010") == "S010"
        assert RegistryValidator.validate_run_id("R099") == "R099"
        assert RegistryValidator.validate_sample_id(None) is None
        assert RegistryValidator.validate_run_id(None) is None

        with pytest.raises(ValueError):
            RegistryValidator.validate_experiment_id("EXP1")
        with pytest.raises(ValueError):
            RegistryValidator.validate_sample_id("S1")
        with pytest.raises(ValueError):
            RegistryValidator.validate_run_id("R1")

    def test_next_code_method(self):
        """RegistryValidator.next_code should increment prefix-matching sequences."""

        assert RegistryValidator.next_code("S", ["S001", "S002"]) == "S003"
        assert RegistryValidator.next_code("R", []) == "R001"
