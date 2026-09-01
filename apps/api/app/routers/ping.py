"""Minimal API-key-protected route.

Exists only to prove the auth dependency works end-to-end in Phase 1. Not a
real product endpoint -- later phases replace it with actual API surface.
"""
from fastapi import APIRouter, Depends

from app.auth import require_api_key

router = APIRouter()


@router.get("/v1/ping", dependencies=[Depends(require_api_key)])
def ping() -> dict:
    return {"status": "ok"}
