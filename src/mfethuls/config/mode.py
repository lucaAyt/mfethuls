"""Application mode helpers (local vs service)."""

from __future__ import annotations

import os


def get_app_mode() -> str:
    value = (os.environ.get("MFETHULS_MODE") or "local").strip().lower()
    if value in {"service", "server"}:
        return "service"
    return "local"


def is_service_mode() -> bool:
    return get_app_mode() == "service"


def is_local_mode() -> bool:
    return get_app_mode() == "local"
