"""Application mode helpers (local vs service)."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_TEST_ENV_VARS = {
    "MFETHULS_TEST_DATA_ROOT": "PATH_TO_DATA",
    "MFETHULS_TEST_REGISTRY": "PATH_TO_REGISTRY",
    "MFETHULS_TEST_LOCAL_STORAGE": "PATH_TO_LOCAL_STORAGE",
}


def get_app_mode() -> str:
    value = (os.environ.get("MFETHULS_MODE") or "local").strip().lower()
    if value in {"service", "server"}:
        return "service"
    return "local"


def is_service_mode() -> bool:
    return get_app_mode() == "service"


def is_local_mode() -> bool:
    return get_app_mode() == "local"


def use_test_env() -> None:
    """Point mfethuls at the MFETHULS_TEST_* data, registry and storage from .env.

    Call before loading any data. Restart the session to switch back.
    A test variable that is not set is skipped with a warning, so the matching
    runtime variable keeps its normal value.
    """

    load_dotenv()
    for test_key, runtime_key in _TEST_ENV_VARS.items():
        value = os.environ.get(test_key)
        if not value:
            logger.warning(
                "use_test_env: %s is not set; %s keeps its current value.",
                test_key,
                runtime_key,
            )
            continue
        os.environ[runtime_key] = value
