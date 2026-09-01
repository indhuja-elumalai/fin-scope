"""API-key authentication for protected routes.

Single shared key via the API_KEY env var, per the approved Phase 1 auth
decision. This dependency must NOT be used on webhook routes (added in a
later phase) -- those authenticate via Razorpay signature verification
instead, or on /health, which must stay reachable unauthenticated.
"""
from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if x_api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
