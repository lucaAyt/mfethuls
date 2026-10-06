"""Application mode helpers (local vs service)."""

from __future__ import annotations

import logging

from ..settings import configure, get_settings

logger = logging.getLogger(__name__)


def get_app_mode() -> str:
    return get_settings().mode


def is_service_mode() -> bool:
    return get_app_mode() == "service"


def is_local_mode() -> bool:
    return get_app_mode() == "local"


def use_test_env() -> None:
    """Point mfethuls at the MFETHULS_TEST_* data, registry and storage from .env.

    Call before loading any data. Restart the session to switch back.
    A test variable that is not set is skipped with a warning, so the matching
    runtime path keeps its normal value. The environment itself is not changed.
    """

    settings, missing = get_settings().with_test_paths()
    for variable in missing:
        logger.warning("use_test_env: %s is not set; the runtime path keeps its current value.", variable)
    configure(settings)
