import os

import pytest
from fastapi.testclient import TestClient

# The API key this test suite expects. Forced (not setdefault) on purpose:
# DATABASE_URL/REDIS_URL are legitimately allowed to come from the ambient
# environment (an operator may point tests at a different local DB), but
# API_KEY is a fixture value the tests assert against literally -- if it
# were left to setdefault, an API_KEY already exported in the developer's
# shell (e.g. while running the app manually) would silently win, and
# test_ping_accepts_valid_api_key would fail against the wrong key with no
# indication why. Forcing it here makes the test run deterministic
# regardless of what else is exported in the shell.
TEST_API_KEY = "test-api-key"

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://finscope:finscope@localhost:5432/finscope"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["API_KEY"] = TEST_API_KEY

from app.main import app  # noqa: E402  -- env vars must be set before import


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def api_key() -> str:
    return TEST_API_KEY
