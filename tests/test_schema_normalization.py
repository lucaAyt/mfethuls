"""The schema of each instrument type: required columns, dtypes, measurement profiles and time_s.

Column names and units are the instrument definitions' job (tests/test_instrument_definitions.py);
the schema no longer renames file columns.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from mfethuls.schema_normalization import add_elapsed_time, apply_dataframe_schema

SCHEMAS = sorted((Path(__file__).resolve().parents[1] / "src" / "mfethuls" / "config" / "schemas").glob("*.json"))


def _required(schema, profile=None):
    layer = schema["profiles"][profile] if profile else schema
    return [entry[0] if isinstance(entry, list) else entry for entry in layer.get("required_columns", [])]


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: p.stem)
def test_a_type_with_its_required_columns_passes_and_numbers_are_cast(path):
    schema = json.loads(path.read_text(encoding="utf8"))
    required = _required(schema)
    df = pd.DataFrame({column: ["1.5", "2.5"] for column in required} | {"name": ["a", "a"]})
    normalized, report = apply_dataframe_schema(df, instrument_type=path.stem, instrument_model="any")
    assert report["schema_applied"] is True and report["missing_required_columns"] == []
    for column in required:
        if str(schema.get("dtypes", {}).get(column, "")).startswith("float"):
            assert str(normalized[column].dtype) == "float64"


@pytest.mark.parametrize("path", [p for p in SCHEMAS if json.loads(p.read_text(encoding="utf8")).get("required_columns")],
                         ids=lambda p: p.stem)
def test_a_missing_required_column_is_reported(path):
    schema = json.loads(path.read_text(encoding="utf8"))
    required = _required(schema)
    df = pd.DataFrame({column: [1.0] for column in required[1:]})
    _, report = apply_dataframe_schema(df, instrument_type=path.stem, instrument_model="any")
    assert report["missing_required_columns"][0].split(" or ")[0] == required[0]


PROFILES = [(path.stem, profile) for path in SCHEMAS
            for profile in json.loads(path.read_text(encoding="utf8")).get("profiles", {})]


@pytest.mark.parametrize("instrument_type, profile", PROFILES)
def test_a_measurement_profile_adds_its_required_columns(instrument_type, profile):
    schema = json.loads((SCHEMAS[0].parent / f"{instrument_type}.json").read_text(encoding="utf8"))
    required = _required(schema, profile)
    complete = pd.DataFrame({column: [1.0, 2.0] for column in required})
    _, report = apply_dataframe_schema(complete, instrument_type=instrument_type, instrument_model="any",
                                       measurement_profile=profile)
    assert report["layers_applied"]["profile"] is True and report["missing_required_columns"] == []
    if required:
        _, report = apply_dataframe_schema(complete.drop(columns=required[0]), instrument_type=instrument_type,
                                           instrument_model="any", measurement_profile=profile)
        assert required[0] in report["missing_required_columns"]


def test_an_unknown_profile_is_warned_about():
    df = pd.DataFrame({"angular_frequency_rad_s": [1.0]})
    _, report = apply_dataframe_schema(df, instrument_type="rheometer", instrument_model="anton_paar",
                                       measurement_profile="not_a_profile")
    assert any("Unknown measurement_profile" in w for w in report["warnings"])


def test_the_schema_does_not_rename_file_columns():
    # A column the instrument definition left unmapped keeps its file name (keep-all-data).
    df = pd.DataFrame({"temperature_C": [25.0], "mass_mg": [10.0], "Tr [mg]": [1.0], "t [°C]": [2.0]})
    normalized, report = apply_dataframe_schema(df, instrument_type="tga", instrument_model="tgaX")
    assert list(normalized.columns)[:4] == ["temperature_C", "mass_mg", "Tr [mg]", "t [°C]"]
    assert report["renamed_columns"] == {}


def test_time_s_is_derived_from_timestamps():
    df = pd.DataFrame({"wavelength_nm": [400.0, 400.0], "emission_counts": [1.0, 2.0],
                       "timestamp": ["2026-04-23T10:00:00Z", "2026-04-23T10:00:30Z"]})
    normalized, _ = apply_dataframe_schema(df, instrument_type="fluorescence", instrument_model="flame")
    assert normalized["time_s"].tolist() == [0.0, 30.0]


def test_apply_dataframe_schema_returns_report_when_schema_missing():
    df = pd.DataFrame({"a": [1, 2]})

    normalized, report = apply_dataframe_schema(
        df,
        instrument_type="unknown_type",
        instrument_model="unknown_model",
    )

    assert normalized.equals(df)
    assert report["schema_applied"] is False
    assert report["schema_version"] is None
    assert report["missing_required_columns"] == []
    assert report["warnings"]


def test_add_elapsed_time_counts_seconds_from_first_timestamp():
    df = pd.DataFrame(
        {
            "wavelength_nm": [400.0, 500.0, 400.0, 500.0],
            "timestamp": pd.to_datetime(
                ["2025-05-11 16:11:09.757", "2025-05-11 16:11:09.757", "2025-05-11 16:11:11.257", "2025-05-11 16:11:11.257"],
                utc=True,
            ),
        }
    )

    result = add_elapsed_time(df)

    assert result["time_s"].tolist() == [0.0, 0.0, 1.5, 1.5]
    assert "time_s" not in df.columns  # input is not modified


def test_add_elapsed_time_keeps_existing_time_and_skips_missing_timestamps():
    with_time = pd.DataFrame({"timestamp": pd.to_datetime(["2025-01-01", "2025-01-02"]), "time_s": [5.0, 6.0]})
    no_timestamps = pd.DataFrame({"timestamp": [pd.NaT, pd.NaT]})
    no_column = pd.DataFrame({"x": [1, 2]})

    assert add_elapsed_time(with_time)["time_s"].tolist() == [5.0, 6.0]
    assert "time_s" not in add_elapsed_time(no_timestamps).columns
    assert add_elapsed_time(no_column) is no_column


def test_dsc_needs_heat_flow_in_mw_or_per_gram():
    """A required entry that is a list is met by any one of its columns."""
    per_gram = pd.DataFrame({"temperature_C": [25.0], "heat_flow_W_g": [0.1]})
    _, report = apply_dataframe_schema(per_gram, instrument_type="dsc", instrument_model="mettler_toledo_v0")
    assert report["missing_required_columns"] == []
    _, report = apply_dataframe_schema(per_gram[["temperature_C"]], instrument_type="dsc", instrument_model="mettler_toledo_v0")
    assert report["missing_required_columns"] == ["heat_flow_mW or heat_flow_W_g"]
