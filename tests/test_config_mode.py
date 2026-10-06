import logging
import os

import pytest

from mfethuls.config.mode import use_test_env
from mfethuls.settings import get_settings


@pytest.fixture
def runtime_paths(monkeypatch):
    for runtime_key in ("PATH_TO_DATA", "PATH_TO_REGISTRY", "PATH_TO_LOCAL_STORAGE"):
        monkeypatch.setenv(runtime_key, f"original_{runtime_key}")
    return monkeypatch


def test_use_test_env_switches_settings_to_test_paths(runtime_paths):
    runtime_paths.setenv("MFETHULS_TEST_DATA_ROOT", "test/data")
    runtime_paths.setenv("MFETHULS_TEST_REGISTRY", "test/registry.csv")
    runtime_paths.setenv("MFETHULS_TEST_LOCAL_STORAGE", "test/storage")

    use_test_env()

    settings = get_settings()
    assert (settings.data_root, settings.registry_path, settings.local_storage) == (
        "test/data",
        "test/registry.csv",
        "test/storage",
    )
    # The environment itself is left alone.
    assert os.environ["PATH_TO_DATA"] == "original_PATH_TO_DATA"


def test_use_test_env_warns_and_keeps_value_when_test_var_missing(runtime_paths, caplog):
    runtime_paths.setenv("MFETHULS_TEST_DATA_ROOT", "test/data")
    runtime_paths.setenv("MFETHULS_TEST_LOCAL_STORAGE", "test/storage")

    with caplog.at_level(logging.WARNING, logger="mfethuls.config.mode"):
        use_test_env()

    assert get_settings().data_root == "test/data"
    assert get_settings().registry_path == "original_PATH_TO_REGISTRY"
    assert "MFETHULS_TEST_REGISTRY is not set" in caplog.text
