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
