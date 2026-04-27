from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

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


def _merge_required_columns(*layers: Dict[str, Any]) -> List[str]:
    required: List[str] = []
    for layer in layers:
        cols = layer.get("required_columns", []) if isinstance(layer, dict) else []
        if not isinstance(cols, list):
            continue
        for col in cols:
            col_str = str(col)
            if col_str not in required:
                required.append(col_str)
    return required


def _safe_layer(container: Dict[str, Any], key: Optional[str]) -> Dict[str, Any]:
    if not key:
        return {}
    value = container.get(key, {})
    return value if isinstance(value, dict) else {}


def apply_dataframe_schema(
    df: pd.DataFrame,
    *,
    instrument_type: str,
    instrument_model: str,
    measurement_profile: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Normalize parser output columns according to schema config.

    Returns a tuple ``(normalized_df, report)`` where report contains:
    - ``schema_applied``
    - ``schema_version``
    - ``renamed_columns``
    - ``missing_required_columns``
    - ``warnings``
    - ``measurement_profile``
    - ``layers_applied``
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

    instrument_model_map = schema.get("models", {})
    if not isinstance(instrument_model_map, dict):
        instrument_model_map = {}
    instrument_model_schema = _safe_layer(instrument_model_map, instrument_model)

    global_profile_map = schema.get("profiles", {}) if isinstance(schema.get("profiles", {}), dict) else {}
    model_profile_map = (
        instrument_model_schema.get("profiles", {})
        if isinstance(instrument_model_schema.get("profiles", {}), dict)
        else {}
    )
    profile_schema = _safe_layer(global_profile_map, measurement_profile)
    model_profile_schema = _safe_layer(model_profile_map, measurement_profile)

    layers = [
        schema,
        instrument_model_schema,
        profile_schema,
        model_profile_schema,
    ]

    aliases = _merge_aliases(*layers)
    required_columns = _merge_required_columns(*layers)
    dtypes = _merge_dtypes(*layers)

    normalized = df.copy()
    renamed_columns: Dict[str, str] = {}
    warnings: List[str] = []

    if measurement_profile:
        known_profiles = set(global_profile_map) | set(model_profile_map)
        if known_profiles and measurement_profile not in known_profiles:
            warnings.append(
                f"Unknown measurement_profile={measurement_profile!r} for instrument_type={instrument_type!r}, "
                f"instrument_model={instrument_model!r}."
            )

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

    missing_required_columns = [col for col in required_columns if col not in normalized.columns]

    report = {
        "schema_applied": True,
        "schema_version": str(schema.get("schema_version", "1.0")),
        "renamed_columns": renamed_columns,
        "missing_required_columns": missing_required_columns,
        "warnings": warnings,
        "measurement_profile": measurement_profile,
        "layers_applied": {
            "model": bool(instrument_model_schema),
            "profile": bool(profile_schema or model_profile_schema),
        },
    }
    return normalized, report
