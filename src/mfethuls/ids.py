from __future__ import annotations

import re
from typing import Iterable, Optional


_EXP_RE = re.compile(r"^EXP[0-9]{3,6}$")
_S_RE = re.compile(r"^S[0-9]{3,6}$")
_R_RE = re.compile(r"^R[0-9]{3,6}$")


def validate_experiment_id(experiment_id: str) -> str:
    """Validate and return a canonical experiment id (e.g. EXP001).

    Raises ValueError if the id does not match the expected pattern.
    """

    if not isinstance(experiment_id, str) or not _EXP_RE.fullmatch(experiment_id):
        raise ValueError(f"Invalid experiment_id: {experiment_id!r}. Expected pattern EXP### (e.g. EXP001).")
    return experiment_id


def validate_sample_id(sample_id: Optional[str]) -> Optional[str]:
    """Validate a sample id (e.g. S001). None is allowed and returned as-is.

    Raises ValueError if non-None value does not match the expected pattern.
    """

    if sample_id is None:
        return None
    if not isinstance(sample_id, str) or not _S_RE.fullmatch(sample_id):
        raise ValueError(f"Invalid sample_id: {sample_id!r}. Expected pattern S### (e.g. S001).")
    return sample_id


def validate_run_id(run_id: Optional[str]) -> Optional[str]:
    """Validate a run id (e.g. R001). None is allowed and returned as-is.

    Raises ValueError if non-None value does not match the expected pattern.
    """

    if run_id is None:
        return None
    if not isinstance(run_id, str) or not _R_RE.fullmatch(run_id):
        raise ValueError(f"Invalid run_id: {run_id!r}. Expected pattern R### (e.g. R001).")
    return run_id


def next_code(prefix: str, existing: Iterable[str]) -> str:
    """Generate the next sequential code with the given prefix.

    Example:
        next_code("S", ["S001", "S002"]) -> "S003"
    """

    prefix = str(prefix)
    numbers = []
    for code in existing:
        if isinstance(code, str) and code.startswith(prefix):
            suffix = code[len(prefix):]
            if suffix.isdigit():
                numbers.append(int(suffix))
    n = max(numbers) + 1 if numbers else 1
    width = max(3, len(str(n)))
    return f"{prefix}{n:0{width}d}"
