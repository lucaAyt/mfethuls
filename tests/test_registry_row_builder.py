from __future__ import annotations

from mfethuls.experiments import experiment_from_registry_record


def test_valid_row_builds_experiment():
    result = experiment_from_registry_record(
        {
            "name": "ok",
            "instrument_name": "dsc_mettler_toledo",
            "raw_data_filename": "my_data_file",
            "sample_id": "S001",
        }
    )
    assert result.errors == []
    assert result.experiment is not None
    assert result.experiment.name == "ok"
    assert result.experiment.raw_data_filename == "my_data_file"
    assert result.experiment.instrument_name == "dsc_mettler_toledo"
    assert result.experiment.experiment_id is None


def test_raw_data_filename_defaults_to_name_when_absent():
    result = experiment_from_registry_record(
        {
            "name": "CL_dsc_001",
            "instrument_name": "dsc_mettler_toledo",
        }
    )
    assert result.errors == []
    assert result.experiment is not None
    assert result.experiment.raw_data_filename == "CL_dsc_001"


def test_missing_name_returns_error():
    result = experiment_from_registry_record(
        {
            "instrument_name": "dsc_mettler_toledo",
        }
    )
    assert result.experiment is None
    assert result.errors


def test_missing_instrument_is_warning_not_error():
    result = experiment_from_registry_record(
        {
            "name": "no_instr",
            "instrument_name": "",
        }
    )
    assert result.errors == []
    assert result.warnings
    assert result.experiment is not None
    assert result.experiment.instrument_name is None
