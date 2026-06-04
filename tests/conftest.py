import pytest


@pytest.fixture
def service_mode(monkeypatch):
    monkeypatch.setenv("MFETHULS_MODE", "service")


@pytest.fixture
def local_mode(monkeypatch):
    monkeypatch.setenv("MFETHULS_MODE", "local")
