"""Health check endpoint.

Deliberately deterministic and dependency-light: it proves DB and Redis are
reachable right now, nothing more. It is intentionally NOT behind API-key
auth -- an orchestrator or load balancer must be able to call it
unauthenticated.
"""
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db import SessionLocal
from app.redis_client import redis_client

router = APIRouter()


@router.get("/health")
def health(response: Response) -> dict:
    checks = {"database": _check_database(), "redis": _check_redis()}
    healthy = all(check["status"] == "ok" for check in checks.values())
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "unhealthy", "checks": checks}


def _check_database() -> dict:
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 -- a health check must never raise
        return {"status": "error", "detail": str(exc)}


def _check_redis() -> dict:
    try:
        redis_client.ping()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}
