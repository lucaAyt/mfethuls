from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mfethuls.api import app

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_CSV = FIXTURE_DIR / "registry_minimal.csv"
FIXTURE_INVALID = FIXTURE_DIR / "registry_invalid_instrument.csv"


API_KEY = "test-api-key"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MFETHULS_API_KEY", API_KEY)
    return TestClient(app, headers={"Authorization": f"Bearer {API_KEY}"})


def test_health_is_public(client, local_mode):
    """Health endpoint is exempt from auth and service-mode checks."""
    # Use a plain client with no auth header to verify it's truly public.
    plain = TestClient(app)
    response = plain.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ok_in_service_mode(client, service_mode):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_registry_preview_parses_csv(client, service_mode):
    content = FIXTURE_CSV.read_bytes()
    response = client.post(
        "/registry/preview",
        files={"file": ("registry.csv", content, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert "rows" in body
    assert "summary" in body
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["row_number"] == 1
    assert row["valid"] is True
    assert row["values"]["name"] == "api_smoke_test"


def test_registry_preview_invalid_instrument(client, service_mode):
    content = FIXTURE_INVALID.read_bytes()
    response = client.post(
        "/registry/preview",
        files={"file": ("registry.csv", content, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["invalid"] == 1
    assert body["rows"][0]["valid"] is False
    assert body["rows"][0]["errors"]


@patch("mfethuls.api.routes.create_job")
def test_ingest_returns_202_and_location(mock_create_job, client, service_mode):
    mock_create_job.return_value = None

    content = FIXTURE_CSV.read_bytes()
    response = client.post(
        "/ingest",
        files={"file": ("registry.csv", content, "text/csv")},
    )
    assert response.status_code == 202
    assert "Location" in response.headers
    body = response.json()
    assert "job_id" in body
    mock_create_job.assert_called_once()
    args = mock_create_job.call_args[0]
    registry_path = args[1]
    assert str(registry_path).endswith(".parquet")


@patch("mfethuls.api.routes.create_job")
def test_ingest_rejects_invalid_registry(mock_create_job, client, service_mode):
    content = FIXTURE_INVALID.read_bytes()
    response = client.post(
        "/ingest",
        files={"file": ("registry.csv", content, "text/csv")},
    )
    assert response.status_code == 422
    mock_create_job.assert_not_called()


@patch("mfethuls.api.routes.create_job")
def test_ingest_allow_invalid(mock_create_job, client, service_mode):
    mock_create_job.return_value = None

    content = FIXTURE_INVALID.read_bytes()
    response = client.post(
        "/ingest?allow_invalid=true",
        files={"file": ("registry.csv", content, "text/csv")},
    )
    assert response.status_code == 202
    mock_create_job.assert_called_once()
