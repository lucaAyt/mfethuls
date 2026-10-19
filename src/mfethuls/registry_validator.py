"""Registry validator: fail-fast checks before parsing.

Validates that instrument, model, profile, and schema expectations are
coherent before attempting to parse, reducing runtime surprises.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from mfethuls.parsers.registry import _PARSER_REGISTRY
from mfethuls.schema_normalization import _load_instrument_schema
from mfethuls.naming import stem_key, view_key, view_name
from mfethuls.settings import get_settings

if TYPE_CHECKING:
    from mfethuls.experiments import Experiment


logger = logging.getLogger(__name__)


_S_RE = re.compile(r"^S[0-9]{3,6}$")
_R_RE = re.compile(r"^R[0-9]{3,6}$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]+$")

# Built-in instruments that were renamed: old name -> new name. Only to say so when a
# registry row still uses the old name; the old name is not accepted.
_RENAMED_INSTRUMENTS = {"dsc": "dsc_mettler_toledo_v0", "dsc_mettler_toledo": "dsc_mettler_toledo_v1"}


def _load_instrument_config() -> List[Dict[str, Any]]:
    """Every instrument: ``instrument_params.json`` plus instrument definitions."""
    from mfethuls.instruments.configured import instrument_entries

    return instrument_entries()


def _get_instrument_entry(name: str) -> Optional[Dict[str, Any]]:
    """Retrieve an instrument config entry by name."""
    config = _load_instrument_config()
    name_norm = str(name).casefold()
    for entry in config:
        entry_name = entry.get("name")
        if isinstance(entry_name, str) and entry_name.casefold() == name_norm:
            return entry
    return None


def _load_canonical_profiles_from_schema(
    schema: Dict[str, Any], instrument_model: Optional[str] = None
) -> set[str]:
    """Collect canonical profile keys from global and model-specific schema layers."""

    global_profiles = schema.get("profiles", {}) if isinstance(schema.get("profiles", {}), dict) else {}
    return set(global_profiles)


def _profile_tokens(profile: str) -> set[str]:
    """Split a profile string into comparable tokens."""

    return {token for token in re.findall(r"[a-z0-9]+", str(profile).casefold()) if token}


def _profile_similarity_matches(registry_profile: str, canonical_profile: str) -> bool:
    """Return True when the registry profile is a token subset of the canonical profile."""

    registry_tokens = _profile_tokens(registry_profile)
    canonical_tokens = _profile_tokens(canonical_profile)
    if not registry_tokens or not canonical_tokens:
        return False
    return registry_tokens.issubset(canonical_tokens)


def _match_canonical_profile(
    registry_profile: Optional[str], canonical_profiles: Iterable[str]
) -> Optional[str]:
    """Match a registry profile to a canonical schema profile conservatively."""

    if not registry_profile:
        return None

    known_profiles = [str(profile) for profile in canonical_profiles]
    if not known_profiles:
        return None

    if registry_profile in known_profiles:
        return registry_profile

    profile_cf = registry_profile.casefold()
    for canonical in known_profiles:
        if canonical.casefold() == profile_cf:
            return canonical

    normalized = profile_cf.replace(" ", "_").replace("-", "_")
    for canonical in known_profiles:
        if canonical.casefold() == normalized:
            return canonical

    subset_matches = [canonical for canonical in known_profiles if _profile_similarity_matches(profile_cf, canonical)]
    if subset_matches:
        subset_matches.sort(key=lambda canonical: (len(_profile_tokens(canonical)), canonical.casefold()))
        return subset_matches[0]

    return None


def infer_canonical_profile_from_registry_profile(
    instrument_type: str, registry_profile: Optional[str], instrument_model: Optional[str] = None
) -> Optional[str]:
    """Map a registry-provided measurement_profile to a canonical schema profile key.

    Canonicalization happens in parsers/datasets, not at registry load time.
    The registry only stores the raw registry_measurement_profile value.

    Matching strategy (conservative):
    1. Exact match (registry_profile in canonical_profiles)
    2. Case-insensitive match
    3. Underscore-normalized match (spaces/hyphens → underscores)
    4. Token subset match (all registry tokens are in canonical)

    Returns canonical profile name, or None if no match found.
    """

    if not registry_profile:
        return None

    schema = _load_instrument_schema(instrument_type)
    if not schema:
        return None

    canonical_profiles = _load_canonical_profiles_from_schema(schema, instrument_model)
    return _match_canonical_profile(registry_profile, canonical_profiles)


class RegistryValidationError(ValueError):
    """Raised when registry validation fails."""

    pass


class RegistryValidator:
    """Validates experiment and instrument setup before parsing."""

    def __init__(self):
        self.config = _load_instrument_config()

    def validate_experiment(self, experiment: Experiment) -> Tuple[bool, List[str]]:
        """Validate an Experiment against the registry.

        Returns a tuple (is_valid, error_messages).
        """
        errors: List[str] = []

        # 1. Check instrument exists in config
        instr_entry = _get_instrument_entry(experiment.instrument_name)
        if instr_entry is None:
            renamed = _RENAMED_INSTRUMENTS.get(str(experiment.instrument_name or "").casefold())
            if renamed:
                errors.append(
                    f"Instrument '{experiment.instrument_name}' was renamed to '{renamed}' in mfethuls 0.4.0. "
                    f"Change instrument_name in the registry, then run Clean up."
                )
            else:
                errors.append(
                    f"Instrument '{experiment.instrument_name}' is not a known instrument. "
                    f"Available instruments: {self._list_instrument_names()}"
                )
            return False, errors

        # 2. Extract type and model from config
        instr_type = instr_entry.get("type")
        instr_model = instr_entry.get("model")

        if not instr_type or not instr_model:
            errors.append(
                f"Instrument '{experiment.instrument_name}' has missing type or model in config."
            )
            return False, errors

        # 3. Check parser is registered
        parser_key = (instr_type, instr_model)
        if parser_key not in _PARSER_REGISTRY:
            errors.append(
                f"No parser registered for ({instr_type}, {instr_model}). "
                f"Available parsers: {self._list_available_parsers()}"
            )
            return False, errors

        # 4. Check schema exists (an instrument definition may bring a new measurement type)
        schema = _load_instrument_schema(instr_type)
        if not schema and instr_entry.get("definition") is None:
            errors.append(
                f"No schema file found for instrument type '{instr_type}'. "
                f"Expected: schemas/{instr_type}.json"
            )
            return False, errors

        # 5. For profile-driven instruments, validate profile and requirements
        if instr_type in {"rheometer", "dma"}:
            profile_errors = self._validate_measurement_profile(
                experiment, instr_type, instr_model, schema
            )
            errors.extend(profile_errors)

        return len(errors) == 0, errors

    def validate_experiment_details(
        self,
        experiment: Experiment,
        *,
        check_data_paths: bool = False,
        data_root: Optional[str] = None,
    ) -> Tuple[List[str], List[Tuple[str, str]]]:
        """Validate an Experiment and collect warnings.

        Returns (errors, warnings) where warnings are tuples of (field, message).
        """
        warnings: List[Tuple[str, str]] = []

        if experiment.instrument_name is None:
            warnings.append(
                ("instrument_name", "missing instrument_name")
            )
            return [], warnings

        ok, errors = self.validate_experiment(experiment)
        if not ok:
            return errors, warnings

        if check_data_paths:
            data_root = data_root or get_settings().data_root
            if not data_root:
                warnings.append(
                    ("data_path", "No data_root provided; cannot validate data paths.")
                )
            else:
                from mfethuls.manifest import find_data_files
                entry = _get_instrument_entry(experiment.instrument_name)
                folder_name = entry.get("folder_name") if entry else None
                if not folder_name:
                    warnings.append(
                        (
                            "data_path",
                            f"Instrument '{experiment.instrument_name}' has no folder_name configured.",
                        )
                    )
                else:
                    instrument_path = os.path.join(data_root, folder_name)
                    raw_filename = experiment.raw_data_filename or experiment.name
                    try:
                        find_data_files(instrument_path, raw_filename)
                    except FileNotFoundError as exc:
                        warnings.append(("data_path", str(exc)))
                    except ValueError as exc:
                        warnings.append(("data_path", str(exc)))

        return [], warnings

    @staticmethod
    def validate_sample_id(sample_id: Optional[str]) -> Optional[str]:
        """Validate a sample id (e.g. S001). None is allowed."""

        if sample_id is None:
            return None
        if not isinstance(sample_id, str) or not _S_RE.fullmatch(sample_id):
            raise ValueError(
                f"Invalid sample_id: {sample_id!r}. "
                "Expected pattern S### (e.g. S001)."
            )
        return sample_id

    @staticmethod
    def validate_run_id(run_id: Optional[str]) -> Optional[str]:
        """Validate a run id (e.g. R001). None is allowed."""

        if run_id is None:
            return None
        if not isinstance(run_id, str) or not _R_RE.fullmatch(run_id):
            raise ValueError(
                f"Invalid run_id: {run_id!r}. "
                "Expected pattern R### (e.g. R001)."
            )
        return run_id

    def _validate_measurement_profile(
        self,
        experiment: Experiment,
        instr_type: str,
        instr_model: Optional[str],
        schema: Dict[str, Any],
    ) -> List[str]:
        """Validate measurement profile for profile-driven instruments.

        Checks that registry_measurement_profile (raw registry value) can be
        canonicalized to a known schema profile.
        """
        errors: List[str] = []
        registry_profile = experiment.metadata.get("registry_measurement_profile")
        canonical_profiles = _load_canonical_profiles_from_schema(schema)

        if not registry_profile:
            logger.warning(
                "No registry_measurement_profile provided for %s experiment %s. "
                "Schema normalization will use profile inference.",
                instr_type,
                experiment.name,
            )
            return errors

        # Check if registry profile can be canonicalized
        matched_profile = _match_canonical_profile(registry_profile, canonical_profiles)
        if matched_profile is None:
            available = sorted(canonical_profiles)
            logger.warning(
                "Could not canonicalize registry_measurement_profile '%s' for %s experiment %s. "
                "Available profiles: %s. Parsing will attempt inference from data.",
                registry_profile,
                instr_type,
                experiment.name,
                available,
            )
            return errors

        # Check that profile has required columns defined
        profile_def = schema.get("profiles", {}).get(matched_profile, {}) if isinstance(schema.get("profiles", {}), dict) else {}
        required_cols = profile_def.get("required_columns", [])
        if not required_cols:
            logger.warning(
                "Profile '%s' for %s has no required_columns defined.",
                matched_profile,
                instr_type,
            )

        return errors

    def _list_instrument_names(self) -> str:
        """Return comma-separated list of available instrument names."""
        names = [entry.get("name") for entry in self.config if entry.get("name")]
        return ", ".join(sorted(set(names))) or "(none)"

    def _list_available_parsers(self) -> str:
        """Return comma-separated list of registered (type, model) pairs."""
        parsers = sorted(_PARSER_REGISTRY.keys())
        return ", ".join(f"({t}, {m})" for t, m in parsers) or "(none)"


def _text(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _view_of(rec: Dict[str, Any], name: str) -> str:
    """The catalog view basename of a registry row (as ``storage.config._view_basename``)."""
    parts = [name, _text(rec.get("sample_id")), _text(rec.get("run_id")) or "R001"]
    return "_".join(part for part in parts if part)


def _table_errors(df: pd.DataFrame) -> List[List[Dict[str, str]]]:
    """Errors that need the whole table: duplicate names and files, unsafe file names.

    Returned per row (same order as ``df``) so each problem shows on the rows involved.
    A row's file is its ``raw_data_filename``, or its ``name`` when that is empty.
    """

    records = df.to_dict(orient="records")
    errors: List[List[Dict[str, str]]] = [[] for _ in records]
    names = [_text(rec.get("name")) for rec in records]
    files = [_text(rec.get("raw_data_filename")) or name for rec, name in zip(records, names)]
    instruments = [(_text(rec.get("instrument_name")) or "").casefold() or None for rec in records]

    name_count: Dict[str, int] = {}
    for name in names:
        if name:
            name_count[name] = name_count.get(name, 0) + 1
    # Raw data names are compared ignoring case, as when their files are found.
    file_count: Dict[Tuple[str, str], int] = {}
    for file, instrument in zip(files, instruments):
        if file and instrument:
            key = (stem_key(file), instrument)
            file_count[key] = file_count.get(key, 0) + 1
    # Each row's catalog view (name_sample_run): DuckDB names ignore case and punctuation becomes "_".
    views = [_view_of(rec, name) if name else None for rec, name in zip(records, names)]
    view_rows: Dict[str, List[int]] = {}
    for idx, view in enumerate(views):
        if view:
            view_rows.setdefault(view_key(view), []).append(idx)

    for idx, rec in enumerate(records):
        if names[idx] and name_count[names[idx]] > 1:
            errors[idx].append({
                "field": "name",
                "message": f"Name {names[idx]!r} is used by more than one row. Each name must be unique.",
            })
        others = [names[i] for i in view_rows.get(view_key(views[idx]), []) if i != idx] if views[idx] else []
        if others and names[idx] not in others:
            errors[idx].append({
                "field": "name",
                "message": (
                    f"Name {names[idx]!r} and {', '.join(map(repr, sorted(set(others))))} would share the table "
                    f"name {view_name(views[idx])!r} (table names ignore case and turn other characters "
                    "into '_'). Rename one."
                ),
            })
        if files[idx] and instruments[idx] and file_count[(stem_key(files[idx]), instruments[idx])] > 1:
            errors[idx].append({
                "field": "raw_data_filename",
                "message": (
                    f"Raw data {files[idx]!r} is used by more than one {instruments[idx]} row. "
                    "Each file must map to exactly one experiment."
                ),
            })
        declared = _text(rec.get("raw_data_filename"))
        if declared and not _SAFE_FILENAME_RE.fullmatch(declared):
            errors[idx].append({
                "field": "raw_data_filename",
                "message": (
                    f"raw_data_filename {declared!r} contains characters outside [A-Za-z0-9_\\-.]. "
                    "Use only alphanumeric characters, underscores, hyphens, and dots."
                ),
            })
    return errors


def validate_registry_dataframe(
    df: pd.DataFrame,
    *,
    check_data_paths: bool = False,
    data_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate all rows in an uploaded registry spreadsheet.

    Uses the same rules as pre-parse validation (instrument config, parser,
    schema, profiles) without mutating the in-memory experiment registry.
    """

    from mfethuls.experiments import experiment_from_registry_record

    validator = RegistryValidator()
    rows_out: List[Dict[str, Any]] = []
    valid_count = 0

    table_errors = _table_errors(df)

    for idx, rec in enumerate(df.to_dict(orient="records"), start=1):
        row_result = experiment_from_registry_record(rec)
        errors = table_errors[idx - 1] + [{"field": "registry", "message": message} for message in row_result.errors]
        warnings = [{"field": "registry", "message": message} for message in row_result.warnings]

        experiment = row_result.experiment
        if experiment is not None and not row_result.errors:
            extra_errors, extra_warnings = validator.validate_experiment_details(
                experiment,
                check_data_paths=check_data_paths,
                data_root=data_root,
            )
            if extra_errors:
                errors.extend(
                    [{"field": "instrument", "message": message} for message in extra_errors]
                )
            for field, message in extra_warnings:
                warnings.append({"field": field, "message": message})

        is_valid = len(errors) == 0
        if is_valid:
            valid_count += 1

        rows_out.append(
            {
                "row_number": idx,
                "values": rec,
                "valid": is_valid,
                "errors": errors,
                "warnings": warnings,
            }
        )

    total = len(rows_out)
    return {
        "rows": rows_out,
        "summary": {
            "total": total,
            "valid": valid_count,
            "invalid": total - valid_count,
        },
    }
