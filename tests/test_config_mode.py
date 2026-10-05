import logging
import os

import pytest

from mfethuls.config import mode
from mfethuls.config.mode import use_test_env


@pytest.fixture
def isolated_env(monkeypatch):
    """Keep the real .env out of the test and restore all variables afterwards."""
    monkeypatch.setattr(mode, "load_dotenv", lambda: None)
    for test_key, runtime_key in mode._TEST_ENV_VARS.items():
        monkeypatch.delenv(test_key, raising=False)
        monkeypatch.setenv(runtime_key, f"original_{runtime_key}")
    return monkeypatch


def test_use_test_env_copies_test_vars_to_runtime_vars(isolated_env):
    isolated_env.setenv("MFETHULS_TEST_DATA_ROOT", "test/data")
    isolated_env.setenv("MFETHULS_TEST_REGISTRY", "test/registry.csv")
    isolated_env.setenv("MFETHULS_TEST_LOCAL_STORAGE", "test/storage")

    use_test_env()

    assert os.environ["PATH_TO_DATA"] == "test/data"
    assert os.environ["PATH_TO_REGISTRY"] == "test/registry.csv"
    assert os.environ["PATH_TO_LOCAL_STORAGE"] == "test/storage"


def test_use_test_env_warns_and_keeps_value_when_test_var_missing(isolated_env, caplog):
    isolated_env.setenv("MFETHULS_TEST_DATA_ROOT", "test/data")
    isolated_env.setenv("MFETHULS_TEST_LOCAL_STORAGE", "test/storage")

    with caplog.at_level(logging.WARNING, logger="mfethuls.config.mode"):
        use_test_env()

    assert os.environ["PATH_TO_DATA"] == "test/data"
    assert os.environ["PATH_TO_REGISTRY"] == "original_PATH_TO_REGISTRY"
    assert "MFETHULS_TEST_REGISTRY is not set" in caplog.text
