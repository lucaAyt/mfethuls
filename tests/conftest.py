import os

import pytest

from mfethuls import settings as mfethuls_settings


def _is_mfethuls_variable(name: str) -> bool:
    return name.startswith(("MFETHULS_", "PATH_TO_")) or name.endswith("_FOLDER_NAME")


def pytest_configure(config):
    # Tests never read a developer's .env.
    mfethuls_settings.disable_dotenv()


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Start every test from a clean mfethuls environment, inside its own temporary directory.

    Storage defaults to a folder under ``tmp_path`` so nothing is written into the repo.
    Tests set the variables they need with ``monkeypatch.setenv``.
    """

    for name in list(os.environ):
        if _is_mfethuls_variable(name):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", str(tmp_path / "storage"))
    monkeypatch.chdir(tmp_path)
    mfethuls_settings.configure(None)
    yield
    mfethuls_settings.configure(None)


@pytest.fixture
def service_mode(monkeypatch):
    monkeypatch.setenv("MFETHULS_MODE", "service")


@pytest.fixture
def local_mode(monkeypatch):
    monkeypatch.setenv("MFETHULS_MODE", "local")
