"""Application configuration.

Settings are loaded once from environment variables (see .env.example for the
full list). Required values fail fast at startup rather than silently
defaulting -- a missing DATABASE_URL, REDIS_URL, or API_KEY should never be
discovered later as a runtime error under load.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    database_url: str
    redis_url: str
    api_key: str

    # Provisioned for later phases; intentionally optional until their
    # adapters exist, so Phase 1 does not require Razorpay/Anthropic keys.
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    anthropic_api_key: str | None = None
    sentry_dsn: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
