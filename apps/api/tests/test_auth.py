"""Unit tests for API-key authentication on protected routes."""
from fastapi.testclient import TestClient


def test_ping_rejects_missing_api_key(client: TestClient) -> None:
    response = client.get("/v1/ping")
    assert response.status_code == 401


def test_ping_rejects_invalid_api_key(client: TestClient) -> None:
    response = client.get("/v1/ping", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_ping_accepts_valid_api_key(client: TestClient, api_key: str) -> None:
    response = client.get("/v1/ping", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_require_api_key(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code in (200, 503)
