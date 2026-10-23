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
        assert any("is not a known instrument" in err for err in errors)

    def test_validate_rheometer_needs_no_measurement_profile(self):
        """Plots read what the run swept from the data; an old profile column is only metadata."""
        validator = RegistryValidator()
        for metadata in ({}, {"measurement_profile": "nonexistent_profile"}):
            exp = Experiment(name="test_rheometer", instrument_name="rheometer", metadata=metadata)
            is_valid, errors = validator.validate_experiment(exp)
            assert is_valid, f"Validation failed with errors: {errors}"

    def test_a_reader_is_not_an_instrument(self):
        exp = Experiment(name="old_dsc", instrument_name="dsc_mettler_toledo_v0", sample_id="S001")
        is_valid, errors = RegistryValidator().validate_experiment(exp)
        assert not is_valid
        assert errors == ["'dsc_mettler_toledo_v0' is a reader (an export format of dsc data), not an instrument: "
                          "use the instrument whose folder holds the files (dsc)."]

    def test_parse_experiment_fails_with_invalid_instrument(self):
        exp = Experiment(name="test_invalid", instrument_name="nonexistent_instrument")

        class MockInstrument:
            type_ = "unknown"
            model = "unknown"
            name = "nonexistent_instrument"

        with pytest.raises(RegistryValidationError):
            parse_experiment(exp, {}, MockInstrument())

    def test_an_unknown_instrument_lists_the_known_ones(self):
        exp = Experiment(name="x", instrument_name="nonexistent_instrument")
        (error,) = RegistryValidator().validate_experiment(exp)[1]
        assert "Available instruments: dma, dsc," in error and "rheometer" in error

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
            {"name": "exp_b", "instrument_name": "dsc"},
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "run1"},
            {"name": "exp_a", "instrument_name": "tga", "raw_data_filename": "run2"},
        ])
        assert errors[0] == []
        assert all(any("'exp_a' is used by more than one row" in m for m in row) for row in errors[1:])

    def test_unique_names_pass(self):
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc"},
            {"name": "exp_b", "instrument_name": "dsc"},
        ])
        assert errors == [[], []]

    def test_duplicate_raw_data_per_instrument_is_reported_on_both_rows(self):
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "run_jan15"},
            {"name": "exp_b", "instrument_name": "DSC", "raw_data_filename": "run_jan15"},  # case ignored
        ])
        assert all(any("'run_jan15' is used by more than one dsc row" in m for m in row) for row in errors)

    def test_same_file_for_different_instruments_is_ok(self):
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "run_jan15"},
            {"name": "exp_b", "instrument_name": "tga", "raw_data_filename": "run_jan15"},
        ])
        assert errors == [[], []]

    def test_rows_without_raw_data_filename_use_their_name(self):
        # Two rows without raw_data_filename are not duplicates of each other ...
        assert _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": None},
            {"name": "exp_b", "instrument_name": "dsc", "raw_data_filename": None},
        ]) == [[], []]
        # ... but a name that equals another row's file is.
        errors = _errors_by_row([
            {"name": "poly1", "instrument_name": "dsc", "raw_data_filename": None},
            {"name": "exp_b", "instrument_name": "dsc", "raw_data_filename": "poly1"},
        ])
        assert all(any("'poly1' is used by more than one dsc row" in m for m in row) for row in errors)

    def test_names_as_people_write_them_are_fine(self):
        # Non-programmers name files with spaces, brackets and accents.
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "my file (1)"},
            {"name": "exp_b", "instrument_name": "dsc", "raw_data_filename": "Échantillon 2"},
        ])
        assert errors == [[], []]

    def test_a_path_as_file_name_is_reported_on_its_row(self):
        errors = _errors_by_row([
            {"name": "exp_a", "instrument_name": "dsc", "raw_data_filename": "chitosan_jan15"},
            {"name": "exp_b", "instrument_name": "dsc", "raw_data_filename": "../other/run1"},
        ])
        assert errors[0] == []
        assert any("'../other/run1' must be a plain name" in m for m in errors[1])
