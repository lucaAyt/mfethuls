"""Runtime configuration, read from environment variables (and ``.env``) in one place.

``get_settings()`` returns the current :class:`Settings`. Unless settings were set
explicitly with :func:`configure` (or :func:`using`), they are rebuilt from the
environment on each call, so changing an environment variable takes effect
immediately. ``.env`` is loaded once, on the first call, and never overrides
variables that are already set.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, replace
import logging
from typing import Iterator, Mapping, Optional

_TRUE = {"1", "true", "yes"}

# MFETHULS_TEST_* variables that use_test_env() swaps in for the runtime paths.
TEST_PATH_VARIABLES = {
    "data_root": "MFETHULS_TEST_DATA_ROOT",
    "registry_path": "MFETHULS_TEST_REGISTRY",
    "local_storage": "MFETHULS_TEST_LOCAL_STORAGE",
}


def _flag(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in _TRUE


@dataclass(frozen=True)
class Settings:
    data_root: Optional[str] = None
    registry_path: Optional[str] = None
    local_storage: Optional[str] = None
    duckdb_path: Optional[str] = None
    disable_storage: bool = False
    storage_debug: bool = False

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "Settings":
        """Build settings from environment variables (``os.environ`` by default)."""

        env = os.environ if environ is None else environ
        get = env.get

        return cls(
            data_root=get("PATH_TO_DATA") or None,
            registry_path=get("PATH_TO_REGISTRY") or None,
            local_storage=get("PATH_TO_LOCAL_STORAGE") or None,
            duckdb_path=get("MFETHULS_DUCKDB_PATH") or None,
            disable_storage=_flag(get("MFETHULS_DISABLE_STORAGE")),
            storage_debug=bool(get("MFETHULS_STORAGE_DEBUG")),
        )

    def with_test_paths(self, environ: Optional[Mapping[str, str]] = None) -> tuple["Settings", list[str]]:
        """These settings with the MFETHULS_TEST_* paths swapped in.

        Returns the new settings and the names of test variables that were not set
        (their runtime paths are kept).
        """

        env = os.environ if environ is None else environ
        overrides = {name: env.get(var) for name, var in TEST_PATH_VARIABLES.items() if env.get(var)}
        missing = [var for name, var in TEST_PATH_VARIABLES.items() if name not in overrides]
        return replace(self, **overrides), missing


_configured: Optional[Settings] = None
_dotenv_loaded = False


def load_dotenv_once() -> None:
    """Load ``.env`` into the environment the first time; existing variables win."""

    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    from dotenv import load_dotenv

    load_dotenv()


def disable_dotenv() -> None:
    """Never load ``.env`` in this process (used by the test suite)."""

    global _dotenv_loaded
    _dotenv_loaded = True


def get_settings() -> Settings:
    """The configured settings, or settings read from the environment right now."""

    if _configured is not None:
        return _configured
    load_dotenv_once()
    return Settings.from_env()


def configure(settings: Optional[Settings]) -> None:
    """Use ``settings`` from now on; ``None`` goes back to reading the environment."""

    global _configured
    _configured = settings


@contextmanager
def using(settings: Settings) -> Iterator[Settings]:
    """Use ``settings`` inside the block, then restore what was there before."""

    global _configured
    previous = _configured
    _configured = settings
    try:
        yield settings
    finally:
        _configured = previous


def use_test_env() -> None:
    """Point mfethuls at the MFETHULS_TEST_* data, registry and storage from .env.

    Call before loading any data. Restart the session to switch back.
    A test variable that is not set is skipped with a warning, so the matching
    runtime path keeps its normal value. The environment itself is not changed.
    """

    settings, missing = get_settings().with_test_paths()
    for variable in missing:
        logging.getLogger(__name__).warning(
            "use_test_env: %s is not set; the runtime path keeps its current value.", variable
        )
    configure(settings)
