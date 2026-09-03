"""Application configuration.

Settings are loaded once from environment variables (see .env.example for the
full list). Required values fail fast at startup rather than silently
defaulting -- a missing DATABASE_URL, REDIS_URL, or API_KEY should never be
discovered later as a runtime error under load.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings resolves a relative env_file against the process's
# current working directory at startup, not against this file's location.
# The documented local-setup steps (see README) run uvicorn from apps/api/,
# where a bare ".env" does not exist -- only the repo-root one does. That
# silently skipped a real .env file rather than erroring, and Settings()
# fell through to whatever happened to already be exported in the shell.
# Resolving explicitly from this file's location makes env loading work the
# same regardless of the process's working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "development"

    database_url: str
    redis_url: str
    api_key: str

    # Comma-separated list of allowed frontend origins outside development
    # (where allowed origins are the fixed local dev ports instead -- see
    # main.py). Unset by design: no production origin exists yet, and CORS
    # must not default to permissive just because this is unconfigured.
    cors_allowed_origins: str | None = None

    # Provisioned for later phases; intentionally optional until their
    # adapters exist, so Phase 1 does not require Razorpay/Anthropic keys.
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None

    # Phase 10: a second, explicit gate beyond "the configured key happens
    # to start with rzp_test_" -- app.providers.razorpay.RazorpayClient
    # refuses to construct unless this is ALSO explicitly true, so a
    # misconfigured environment fails closed at construction time rather
    # than proceeding on prefix-matching alone. Defaults to False: Razorpay
    # integration is inert by default, exactly like anthropic_api_key was
    # before Phase 9 configured it.
    razorpay_test_mode_confirmed: bool = False

    # Phase 10, Milestone 2: Razorpay's webhook payloads identify a
    # Razorpay *account*, never a FIN-SCOPE merchant -- Merchant has no
    # provider-account mapping today, and a schema change to add one is
    # not justified for a single-TEST-account integration. Every accepted
    # webhook is attributed to this one merchant until multi-merchant
    # mapping is genuinely needed. Optional so importing this module
    # never breaks before an operator configures it -- see
    # app.domain.razorpay_webhooks.process_webhook, which treats an
    # unset or invalid value as an internal configuration failure (5xx,
    # never silently guessed, never ledger-recorded so a corrected
    # retry can still succeed).
    razorpay_default_merchant_id: str | None = None
    anthropic_api_key: str | None = None

    # Phase 9: the only two provider knobs worth exposing as configuration
    # (see app.providers.reasoning). Both have sensible defaults matching
    # the values the provider hardcoded before Phase 9, specifically so
    # existing startup/tests never need these set. The API URL and API
    # version stay internal module constants in app.providers.reasoning --
    # there is no concrete reason yet to make an internal implementation
    # detail like the wire endpoint configurable.
    anthropic_model: str = "claude-sonnet-5"
    anthropic_timeout_seconds: float = 30.0

    # Some Anthropic API keys are identity-linked to a Console workspace
    # rather than a standalone key, and the Messages API rejects those
    # without an `anthropic-workspace-id` header identifying which
    # workspace to bill/authorize against. Optional and defaults to None
    # so a standalone (non-workspace) key keeps working exactly as before
    # -- see app.providers.reasoning.HostedReasoningProvider, which only
    # sends the header at all when this is set.
    anthropic_workspace_id: str | None = None

    sentry_dsn: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
