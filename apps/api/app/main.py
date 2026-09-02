"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import events, health, investigations, merchants, ping

app = FastAPI(title="FIN-SCOPE API", version="0.1.0")

settings = get_settings()

# In development, the frontend's local port varies (Next.js falls back to
# 3001 when 3000 is already taken), so both are allowlisted. Outside
# development, nothing is allowed by default -- there is no deployed
# frontend origin yet, and CORS must fail closed until one is explicitly
# configured via CORS_ALLOWED_ORIGINS, not default open.
if settings.environment == "development":
    _cors_origins = ["http://localhost:3000", "http://localhost:3001"]
elif settings.cors_allowed_origins:
    _cors_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",")]
else:
    _cors_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)

app.include_router(health.router)
app.include_router(ping.router)
app.include_router(merchants.router)
app.include_router(events.router)
app.include_router(investigations.router)
