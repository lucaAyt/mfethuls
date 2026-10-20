"""Tests for registry validator."""

import pytest
import pandas as pd

from mfethuls.experiments import Experiment
from mfethuls.registry_validator import (
    RegistryValidator,
    RegistryValidationError,
    validate_registry_dataframe,
)
from mfethuls.factory import parse_experiment


class TestRegistryValidator:
    """Test suite for RegistryValidator."""

    def test_validate_valid_experiment(self):
        validator = RegistryValidator()
        exp = Experiment(name="test_dsc", instrument_name="dsc_mettler_toledo_v0")
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"
        assert len(errors) == 0

    def test_validate_valid_experiment_is_case_insensitive(self):
        validator = RegistryValidator()
        exp = Experiment(name="test_dsc_upper", instrument_name="DSC_Mettler_Toledo_V1")
        is_valid, errors = validator.validate_experiment(exp)
        assert is_valid, f"Validation failed with errors: {errors}"

    def test_validate_unknown_instrument(self):
        validator = RegistryValidator()
        exp = Experiment(name="test_unknown", instrument_name="nonexistent_instrument")
        is_valid, errors = validator.validate_experiment(exp)
        assert not is_valid
        assert any("is not a known instrument" in err for err in errors)

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

    def test_a_renamed_instrument_names_its_new_name(self):
        exp = Experiment(name="old_dsc", instrument_name="dsc", sample_id="S001")
        is_valid, errors = RegistryValidator().validate_experiment(exp)
        assert not is_valid
        assert "renamed to 'dsc_mettler_toledo_v0'" in errors[0]

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


def _errors_by_row(rows: list[dict]) -> list[list[str]]:
    result = validate_registry_dataframe(pd.DataFrame(rows))
    return [[error["message"] for error in row["errors"]] for row in result["rows"]]


class TestTableValidations:
    """Problems that need the whole table, reported on the rows involved."""

    def test_duplicate_name_is_reported_on_each_row_using_it(self):
        errors = _errors_by_row([
            {"name": "exp_b", "instrument_name": "dsc_mettler_toledo_v0"},
            {"name": "exp_a", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": "run1"},
            {"name": "exp_a", "instrument_name": "tga", "raw_data_filename": "run2"},
        ])
        assert errors[0] == []
        assert all(any("'exp_a' is used by more than one row" in m for m in row) for row in errors[1:])

    def test_unique_names_pass(self):
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc_mettler_toledo_v0"},
            {"name": "exp_b", "instrument_name": "dsc_mettler_toledo_v0"},
        ])
        assert errors == [[], []]

    def test_duplicate_raw_data_per_instrument_is_reported_on_both_rows(self):
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": "run_jan15"},
            {"name": "exp_b", "instrument_name": "DSC_Mettler_Toledo_V0", "raw_data_filename": "run_jan15"},
        ])
        assert all(any("'run_jan15' is used by more than one dsc_mettler_toledo_v0 row" in m for m in row) for row in errors)

    def test_same_file_for_different_instruments_is_ok(self):
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": "run_jan15"},
            {"name": "exp_b", "instrument_name": "tga", "raw_data_filename": "run_jan15"},
        ])
        assert errors == [[], []]

    def test_rows_without_raw_data_filename_use_their_name(self):
        # Two rows without raw_data_filename are not duplicates of each other ...
        assert _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": None},
            {"name": "exp_b", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": None},
        ]) == [[], []]
        # ... but a name that equals another row's file is.
        errors = _errors_by_row([
            {"name": "poly1", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": None},
            {"name": "exp_b", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": "poly1"},
        ])
        assert all(any("'poly1' is used by more than one dsc_mettler_toledo_v0 row" in m for m in row) for row in errors)

    def test_names_as_people_write_them_are_fine(self):
        # Non-programmers name files with spaces, brackets and accents.
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": "my file (1)"},
            {"name": "exp_b", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": "Échantillon 2"},
        ])
        assert errors == [[], []]

    def test_a_path_as_file_name_is_reported_on_its_row(self):
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": "chitosan_jan15"},
            {"name": "exp_b", "instrument_name": "dsc_mettler_toledo_v0", "raw_data_filename": "../other/run1"},
        ])
        assert errors[0] == []
        assert any("'../other/run1' must be a plain name" in m for m in errors[1])
