"""Runtime configuration, read in one place: settings saved by the app, environment variables and ``.env``.

``get_settings()`` returns the current :class:`Settings`. Unless settings were set
explicitly with :func:`configure` (or :func:`using`), they are rebuilt on each call,
so a change takes effect immediately:

1. environment variables, with ``.env`` loaded once on the first call (it never
   overrides variables that are already set);
2. then the data folder, registry and storage saved by the app (:func:`save_settings`,
   in ``~/.mfethuls/settings.json``, or ``MFETHULS_SETTINGS_FILE``). They take
   precedence, so a change made in the app is not undone by ``.env``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

from ._files import replace_with_retry

# MFETHULS_TEST_* variables that use_test_env() swaps in for the runtime paths.
TEST_PATH_VARIABLES = {
    "data_root": "MFETHULS_TEST_DATA_ROOT",
    "registry_path": "MFETHULS_TEST_REGISTRY",
    "local_storage": "MFETHULS_TEST_LOCAL_STORAGE",
}


# Settings the app saves; everything else comes from the environment.
SAVED_FIELDS = ("data_root", "registry_path", "local_storage")
SETTINGS_FILE_VARIABLE = "MFETHULS_SETTINGS_FILE"


@dataclass(frozen=True)
class Settings:
    data_root: Optional[str] = None
    registry_path: Optional[str] = None
    local_storage: Optional[str] = None
    duckdb_path: Optional[str] = None

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


def settings_file() -> Path:
    """Where the app saves settings: ``MFETHULS_SETTINGS_FILE``, else ``~/.mfethuls/settings.json``."""
    return Path(os.environ.get(SETTINGS_FILE_VARIABLE) or Path.home() / ".mfethuls" / "settings.json")


def load_saved_settings() -> Dict[str, str]:
    """The settings saved by the app (empty if none, or if the file cannot be read)."""
    path = settings_file()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logging.getLogger(__name__).warning("Ignoring unreadable settings file %s", path)
        return {}
    return {name: str(saved[name]) for name in SAVED_FIELDS if isinstance(saved, dict) and saved.get(name)}


def save_settings(**values: Optional[str]) -> Path:
    """Save some of ``SAVED_FIELDS`` (``None`` or ``""`` removes one); returns the file written."""
    unknown = set(values) - set(SAVED_FIELDS)
    if unknown:
        raise ValueError(f"Only {', '.join(SAVED_FIELDS)} can be saved, not {', '.join(sorted(unknown))}.")
    saved: Dict[str, Any] = load_saved_settings()
    for name, value in values.items():
        if value:
            saved[name] = str(value)
        else:
            saved.pop(name, None)
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(saved, handle, indent=2)
    replace_with_retry(tmp, path)
    return path


def get_settings() -> Settings:
    """The configured settings, or settings read from the environment and the saved settings right now."""

    if _configured is not None:
        return _configured
    load_dotenv_once()
    return replace(Settings.from_env(), **load_saved_settings())


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


def use_folders(
    data_root: Optional[str] = None,
    registry_path: Optional[str] = None,
    local_storage: Optional[str] = None,
) -> Settings:
    """Use these folders for the rest of this session (e.g. a notebook); the ones not given stay as they are.

    Saved and environment settings are not changed. Setting ``os.environ`` in a
    notebook would not work once folders are saved in the app, as those take precedence.
    """
    given = {name: str(value) for name, value in
             {"data_root": data_root, "registry_path": registry_path, "local_storage": local_storage}.items() if value}
    settings = replace(get_settings(), **given)
    configure(settings)
    return settings


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
