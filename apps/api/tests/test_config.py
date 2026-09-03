"""Unit tests for settings validation -- required values must fail fast."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_missing_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("API_KEY", "test-api-key")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_load_with_required_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("API_KEY", "test-api-key")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url.startswith("postgresql")
    assert settings.api_key == "test-api-key"


def test_anthropic_model_and_timeout_have_sensible_defaults_and_are_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 9: ANTHROPIC_MODEL / ANTHROPIC_TIMEOUT_SECONDS must never be
    required -- startup (and every existing test) must keep working with
    neither set, exactly as ANTHROPIC_API_KEY already does."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_TIMEOUT_SECONDS", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.anthropic_model == "claude-sonnet-5"
    assert settings.anthropic_timeout_seconds == 30.0
    assert settings.anthropic_api_key is None


def test_anthropic_model_and_timeout_are_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-test-override")
    monkeypatch.setenv("ANTHROPIC_TIMEOUT_SECONDS", "45")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.anthropic_model == "claude-sonnet-5-test-override"
    assert settings.anthropic_timeout_seconds == 45.0


def test_anthropic_workspace_id_defaults_to_none_and_is_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional, defaulting to None -- a standalone (non-workspace) API
    key must keep working with this unset, exactly as before it existed."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.anthropic_workspace_id is None

    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_test_override")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.anthropic_workspace_id == "wrkspc_test_override"


def test_razorpay_test_mode_confirmed_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 10: must default to False so Razorpay integration stays inert
    (app.providers.razorpay.RazorpayClient refuses to construct) unless an
    operator has explicitly opted in -- exactly the fail-closed-by-default
    posture the Phase 10 plan requires."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.delenv("RAZORPAY_TEST_MODE_CONFIRMED", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.razorpay_test_mode_confirmed is False


def test_razorpay_test_mode_confirmed_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.setenv("RAZORPAY_TEST_MODE_CONFIRMED", "true")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.razorpay_test_mode_confirmed is True


def test_env_file_path_is_absolute_and_cwd_independent() -> None:
    """Regression test for a real bug found during Phase 2 verification.

    `env_file=".env"` used to be a bare relative path, resolved against the
    process's current working directory at Settings() instantiation time --
    not against this file's location. The documented local-setup steps run
    uvicorn from apps/api/, where a bare ".env" does not exist (only the
    repo-root one does), so the file was silently never found there and the
    app fell back to whatever happened to already be exported in the shell.
    env_file must therefore be an absolute path anchored to the repo root,
    regardless of where the process is started from.
    """
    env_file = Path(Settings.model_config["env_file"])
    assert env_file.is_absolute()
    assert env_file.name == ".env"
    # Anchored to the actual repo root, not just any absolute path.
    assert (env_file.parent / ".env.example").exists()
    assert (env_file.parent / "apps" / "api").is_dir()
