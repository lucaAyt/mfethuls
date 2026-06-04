from __future__ import annotations

from mfethuls.experiments import experiment_from_registry_record


def test_invalid_experiment_id_returns_errors():
    result = experiment_from_registry_record(
        {
            "name": "bad",
            "experiment_id": "BAD",
            "instrument_name": "dsc_mettler_toledo",
        }
    )
    assert result.experiment is None
    assert result.errors


def test_valid_row_builds_experiment():
    result = experiment_from_registry_record(
        {
            "name": "ok",
            "experiment_id": "EXP001",
            "instrument_name": "dsc_mettler_toledo",
            "sample_id": "S001",
        }
    )
    assert result.errors == []
    assert result.experiment is not None
    assert result.experiment.experiment_id == "EXP001"
    assert result.experiment.instrument_name == "dsc_mettler_toledo"


def test_missing_instrument_is_warning_not_error():
    result = experiment_from_registry_record(
        {
            "name": "no_instr",
            "experiment_id": "EXP002",
            "instrument_name": "",
        }
    )
    assert result.errors == []
    assert result.warnings
    assert result.experiment is not None
    assert result.experiment.instrument_name is None
