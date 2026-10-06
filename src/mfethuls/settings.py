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
from dataclasses import dataclass, field, replace
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
class PostgresSettings:
    enabled: bool = False
    user: Optional[str] = None
    password: Optional[str] = None
    host: str = "localhost"
    port: Optional[str] = None
    database: Optional[str] = None
    job_db_url: Optional[str] = None


@dataclass(frozen=True)
class S3Settings:
    bucket: Optional[str] = None
    prefix: Optional[str] = None
    region: Optional[str] = None
    endpoint: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None


@dataclass(frozen=True)
class AzureSettings:
    connection_string: Optional[str] = None
    account: Optional[str] = None
    container: Optional[str] = None
    prefix: Optional[str] = None
    key: Optional[str] = None
    sas_token: Optional[str] = None


@dataclass(frozen=True)
class Settings:
    mode: str = "local"
    data_root: Optional[str] = None
    registry_path: Optional[str] = None
    local_storage: Optional[str] = None
    duckdb_path: Optional[str] = None
    disable_storage: bool = False
    storage_debug: bool = False
    metadata_db_enabled: bool = False
    api_key: Optional[str] = None
    api_url: str = "http://localhost:8000"
    job_timeout_s: int = 1800
    # <TYPE>_FOLDER_NAME overrides for instrument folders, keyed by lower-case type.
    instrument_folders: Mapping[str, str] = field(default_factory=dict)
    postgres: PostgresSettings = field(default_factory=PostgresSettings)
    s3: S3Settings = field(default_factory=S3Settings)
    azure: AzureSettings = field(default_factory=AzureSettings)

    @property
    def is_service_mode(self) -> bool:
        return self.mode == "service"

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "Settings":
        """Build settings from environment variables (``os.environ`` by default)."""

        env = os.environ if environ is None else environ
        get = env.get

        mode = (get("MFETHULS_MODE") or "local").strip().lower()
        local_storage = next(
            (get(key) for key in ("PATH_TO_LOCAL_STORAGE", "PATH_TO_STORAGE", "MFETHULS_STORAGE_ROOT") if get(key)),
            None,
        )
        folders = {
            key[: -len("_FOLDER_NAME")].lower(): value
            for key, value in env.items()
            if key.endswith("_FOLDER_NAME") and value
        }
        return cls(
            mode="service" if mode in {"service", "server"} else "local",
            data_root=get("PATH_TO_DATA") or None,
            registry_path=get("PATH_TO_REGISTRY") or None,
            local_storage=local_storage,
            duckdb_path=get("MFETHULS_DUCKDB_PATH") or None,
            disable_storage=_flag(get("MFETHULS_DISABLE_STORAGE")),
            storage_debug=bool(get("MFETHULS_STORAGE_DEBUG")),
            metadata_db_enabled=_flag(get("MFETHULS_METADATA_DB_ENABLED")),
            api_key=get("MFETHULS_API_KEY") or None,
            api_url=get("MFETHULS_API_URL") or "http://localhost:8000",
            job_timeout_s=int(get("MFETHULS_JOB_TIMEOUT_SECONDS") or 1800),
            instrument_folders=folders,
            postgres=PostgresSettings(
                enabled=_flag(get("MFETHULS_POSTGRES_ENABLED")),
                user=get("MFETHULS_POSTGRES_USER") or None,
                password=get("MFETHULS_POSTGRES_PASSWORD") or None,
                host=get("MFETHULS_POSTGRES_HOST") or "localhost",
                port=get("MFETHULS_POSTGRES_PORT") or None,
                database=get("MFETHULS_POSTGRES_DB") or None,
                job_db_url=get("MFETHULS_JOB_DB_URL") or None,
            ),
            s3=S3Settings(
                bucket=get("MFETHULS_S3_BUCKET") or None,
                prefix=get("MFETHULS_S3_PREFIX") or None,
                region=get("MFETHULS_S3_REGION") or None,
                endpoint=get("MFETHULS_S3_ENDPOINT") or None,
                access_key_id=get("MFETHULS_S3_ACCESS_KEY") or None,
                secret_access_key=get("MFETHULS_S3_SECRET_KEY") or None,
            ),
            azure=AzureSettings(
                connection_string=get("MFETHULS_AZURE_CONNECTION_STRING") or None,
                account=get("MFETHULS_AZURE_ACCOUNT") or None,
                container=get("MFETHULS_AZURE_CONTAINER") or None,
                prefix=get("MFETHULS_AZURE_PREFIX") or None,
                key=get("MFETHULS_AZURE_KEY") or None,
                sas_token=get("MFETHULS_AZURE_SAS_TOKEN") or None,
            ),
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
