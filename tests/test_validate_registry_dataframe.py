from __future__ import annotations

import pandas as pd

from mfethuls.registry_validator import validate_registry_dataframe


def test_unknown_instrument_invalid():
    df = pd.DataFrame(
        [
            {
                "name": "bad",
                "experiment_id": "EXP001",
                "instrument_name": "nonexistent_instrument_xyz",
            }
        ]
    )
    result = validate_registry_dataframe(df)
    assert result["summary"]["invalid"] == 1
    assert result["rows"][0]["errors"]


def test_known_instrument_valid():
    df = pd.DataFrame(
        [
            {
                "name": "ok",
                "experiment_id": "EXP001",
                "instrument_name": "dsc_mettler_toledo",
                "sample_id": "S001",
            }
        ]
    )
    result = validate_registry_dataframe(df)
    assert result["summary"]["valid"] == 1
    assert result["rows"][0]["valid"] is True
