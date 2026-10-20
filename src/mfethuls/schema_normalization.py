"""Check a parsed table against its instrument type's schema (config/schemas): required columns and dtypes."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

import pandas as pd


def _get_schema_file_path(instrument_type: str) -> str:
    base_dir = os.path.join(os.path.dirname(__file__), "config", "schemas")
    return os.path.join(base_dir, f"{instrument_type}.json")


def _load_instrument_schema(instrument_type: str) -> Dict[str, Any]:
    path = _get_schema_file_path(instrument_type)
    if not os.path.exists(path):
        return {}

    with open(path, encoding="utf8") as f:
        return json.load(f)


def _coerce_dtype(series: pd.Series, dtype: str) -> pd.Series:
    dtype_lower = str(dtype).lower()
    if dtype_lower.startswith("float"):
        return pd.to_numeric(series, errors="coerce").astype(dtype)
    if dtype_lower in {"int", "int32", "int64", "integer"}:
        return pd.to_numeric(series, errors="coerce").astype("Int64")
    return series.astype(dtype)


def add_elapsed_time(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``time_s``, seconds since the earliest ``timestamp``, when only timestamps exist.

    Instruments that record a wall-clock ``timestamp`` per row or spectrum (e.g. a
    series of Flame spectra) get a numeric time axis, which plots as a continuous
    colour scale or x-axis. An existing ``time_s`` is never overwritten. Returns the
    same frame when nothing is added.
    """

    if "timestamp" not in df.columns or "time_s" in df.columns:
        return df

    timestamps = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    if timestamps.isna().all():
        return df

    df = df.copy()
    df["time_s"] = (timestamps - timestamps.min()).dt.total_seconds()
    return df


def _merge_aliases(*layers: Dict[str, Any]) -> Dict[str, List[str]]:
    merged: Dict[str, List[str]] = {}
    for layer in layers:
        aliases = layer.get("aliases", {}) if isinstance(layer, dict) else {}
        if not isinstance(aliases, dict):
            continue
        for canonical, candidates in aliases.items():
            if isinstance(candidates, list):
                merged[canonical] = [str(c) for c in candidates]
    return merged


def _merge_dtypes(*layers: Dict[str, Any]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for layer in layers:
        dtypes = layer.get("dtypes", {}) if isinstance(layer, dict) else {}
        if not isinstance(dtypes, dict):
            continue
        for col, dtype in dtypes.items():
            merged[str(col)] = str(dtype)
    return merged


def _merge_required_columns(*layers: Dict[str, Any]) -> List[Any]:
    """Required columns of all layers; an entry that is a list means "one of these"."""
    required: List[Any] = []
    for layer in layers:
        cols = layer.get("required_columns", []) if isinstance(layer, dict) else []
        if not isinstance(cols, list):
            continue
        for col in cols:
            entry = [str(c) for c in col] if isinstance(col, list) else str(col)
            if entry not in required:
                required.append(entry)
    return required


def missing_required(required: List[Any], columns) -> List[str]:
    """The required entries ``columns`` lacks; a "one of" entry is shown as ``a or b``."""
    present = set(columns)
    missing: List[str] = []
    for entry in required:
        options = entry if isinstance(entry, list) else [entry]
        if not present.intersection(options):
            missing.append(" or ".join(options))
    return missing


def apply_dataframe_schema(
    df: pd.DataFrame,
    *,
    instrument_type: str,
    instrument_model: str,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Normalize parser output columns according to schema config.

    Returns a tuple ``(normalized_df, report)`` where report contains:
    - ``schema_applied``
    - ``schema_version``
    - ``renamed_columns``
    - ``missing_required_columns``
    - ``warnings``
    """

    schema = _load_instrument_schema(instrument_type)
    if not schema:
        return df, {
            "schema_applied": False,
            "schema_version": None,
            "renamed_columns": {},
            "missing_required_columns": [],
            "warnings": [f"No schema config found for instrument_type={instrument_type!r}"],
        }

    # How a model's files are read (column names, units) is its instrument definition's job;
    # the schema is the type's contract: required columns and dtypes.
    aliases = _merge_aliases(schema)
    required_columns = _merge_required_columns(schema)
    dtypes = _merge_dtypes(schema)

    normalized = df.copy()
    renamed_columns: Dict[str, str] = {}
    warnings: List[str] = []

    rename_map: Dict[str, str] = {}
    for canonical, candidates in aliases.items():
        if canonical in normalized.columns:
            continue

        present = [c for c in candidates if c in normalized.columns]
        if not present:
            continue

        if len(present) > 1:
            warnings.append(
                f"Multiple candidate columns found for {canonical!r}: {present}; using {present[0]!r}."
            )

        rename_map[present[0]] = canonical
        renamed_columns[canonical] = present[0]

    if rename_map:
        normalized = normalized.rename(columns=rename_map)

    for col, dtype in dtypes.items():
        if col not in normalized.columns:
            continue
        try:
            normalized[col] = _coerce_dtype(normalized[col], dtype)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Could not cast column {col!r} to {dtype!r}: {exc}")

    normalized = add_elapsed_time(normalized)

    missing_required_columns = missing_required(required_columns, normalized.columns)

    report = {
        "schema_applied": True,
        "schema_version": str(schema.get("schema_version", "1.0")),
        "renamed_columns": renamed_columns,
        "missing_required_columns": missing_required_columns,
        "warnings": warnings,
    }
    return normalized, report
