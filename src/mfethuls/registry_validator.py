"""Registry validator: fail-fast checks before parsing.

Validates that instrument, model, profile, and schema expectations are
coherent before attempting to parse, reducing runtime surprises.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from mfethuls.parsers.registry import _PARSER_REGISTRY
from mfethuls.schema_normalization import _load_instrument_schema

if TYPE_CHECKING:
    from mfethuls.experiments import Experiment


logger = logging.getLogger(__name__)


_EXP_RE = re.compile(r"^EXP[0-9]{3,6}$")
_S_RE = re.compile(r"^S[0-9]{3,6}$")
_R_RE = re.compile(r"^R[0-9]{3,6}$")


def _load_instrument_config() -> List[Dict[str, Any]]:
    """Load the instrument configuration file."""
    config_path = os.path.join(
        os.path.dirname(__file__), "config", "instrument_params.json"
    )
    if not os.path.exists(config_path):
        return []
    with open(config_path, encoding="utf8") as f:
        return json.load(f)


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
    model_profiles: Dict[str, Any] = {}

    if instrument_model and isinstance(schema.get("models", {}), dict):
        model_layer = schema.get("models", {}).get(instrument_model, {})
        model_profiles = model_layer.get("profiles", {}) if isinstance(model_layer.get("profiles", {}), dict) else {}

    return set(global_profiles) | set(model_profiles)


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

    The schema loading lives here so the caller can stay focused on matching.
    Matching is conservative: exact, case-insensitive, and underscore-normalized
    comparisons only.
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
            errors.append(
                f"Instrument '{experiment.instrument_name}' not found in instrument_params.json. "
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

        # 4. Check schema exists
        schema = _load_instrument_schema(instr_type)
        if not schema:
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

    @staticmethod
    def validate_experiment_id(experiment_id: str) -> str:
        """Validate and return a canonical experiment id (e.g. EXP001)."""

        if not isinstance(experiment_id, str) or not _EXP_RE.fullmatch(experiment_id):
            raise ValueError(
                f"Invalid experiment_id: {experiment_id!r}. "
                "Expected pattern EXP### (e.g. EXP001)."
            )
        return experiment_id

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

    @staticmethod
    def next_code(prefix: str, existing: Iterable[str]) -> str:
        """Generate the next sequential code with the given prefix."""

        prefix = str(prefix)
        numbers: List[int] = []
        for code in existing:
            if isinstance(code, str) and code.startswith(prefix):
                suffix = code[len(prefix) :]
                if suffix.isdigit():
                    numbers.append(int(suffix))
        n = max(numbers) + 1 if numbers else 1
        width = max(3, len(str(n)))
        return f"{prefix}{n:0{width}d}"

    def _validate_measurement_profile(
        self,
        experiment: Experiment,
        instr_type: str,
        instr_model: Optional[str],
        schema: Dict[str, Any],
    ) -> List[str]:
        """Validate measurement profile for profile-driven instruments."""
        errors: List[str] = []
        measurement_profile = experiment.metadata.get("measurement_profile")
        canonical_profiles = _load_canonical_profiles_from_schema(schema)

        if not measurement_profile:
            logger.warning(
                "No measurement_profile provided for %s experiment %s. "
                "Schema normalization will use profile inference.",
                instr_type,
                experiment.name,
            )
            return errors

        # Check if profile is known in schema
        matched_profile = _match_canonical_profile(measurement_profile, canonical_profiles)
        if matched_profile is None:
            available = sorted(canonical_profiles)
            errors.append(
                f"Unknown measurement_profile '{measurement_profile}' for {instr_type}. "
                f"Available profiles: {available}"
            )
            return errors

        # Check that profile has required columns defined
        profile_def = schema.get("profiles", {}).get(matched_profile, {}) if isinstance(schema.get("profiles", {}), dict) else {}
        if not profile_def and isinstance(schema.get("models", {}), dict) and instr_model:
            model_layer = schema.get("models", {}).get(instr_model, {})
            if isinstance(model_layer, dict):
                model_profiles = model_layer.get("profiles", {})
                if isinstance(model_profiles, dict):
                    profile_def = model_profiles.get(matched_profile, {})
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

    def validate_all(self) -> Tuple[bool, Dict[str, List[str]]]:
        """Run a diagnostic pass over all registered instruments.

        Returns a tuple (all_valid, detailed_errors_dict).
        """
        all_errors: Dict[str, List[str]] = {}
        for entry in self.config:
            instr_name = entry.get("name", "unknown")
            instr_type = entry.get("type", "unknown")
            instr_model = entry.get("model", "unknown")

            # Check parser registration
            parser_key = (instr_type, instr_model)
            if parser_key not in _PARSER_REGISTRY:
                if instr_name not in all_errors:
                    all_errors[instr_name] = []
                all_errors[instr_name].append(
                    f"No parser for ({instr_type}, {instr_model})"
                )

            # Check schema existence
            schema = _load_instrument_schema(instr_type)
            if not schema:
                if instr_name not in all_errors:
                    all_errors[instr_name] = []
                all_errors[instr_name].append(f"No schema for type '{instr_type}'")

        return len(all_errors) == 0, all_errors
