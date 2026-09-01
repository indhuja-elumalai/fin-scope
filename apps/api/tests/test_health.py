"""Integration tests for /health.

The happy-path test requires Postgres and Redis to actually be reachable at
DATABASE_URL / REDIS_URL (see docs/verification/phase-01.md for how they were
started for this run). The failure-mode tests are self-contained -- they
point the health check at a deliberately unreachable host rather than
depending on the real services being stopped mid-run.
"""
from unittest.mock import patch

import redis
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_health_ok_when_db_and_redis_available(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"


def test_health_reports_database_failure(client: TestClient) -> None:
    broken_engine = create_engine(
        "postgresql+psycopg://baduser:badpass@localhost:1/doesnotexist",
        connect_args={"connect_timeout": 2},
    )
    broken_session = sessionmaker(bind=broken_engine)
    with patch("app.routers.health.SessionLocal", broken_session):
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"]["status"] == "error"


def test_health_reports_redis_failure(client: TestClient) -> None:
    broken_redis = redis.Redis(host="localhost", port=1, socket_connect_timeout=1)
    with patch("app.routers.health.redis_client", broken_redis):
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["redis"]["status"] == "error"
