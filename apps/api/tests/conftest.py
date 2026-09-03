import os
import uuid

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

# Phase 10, Milestone 2: forced (not setdefault), same rationale as
# API_KEY above -- tests/test_razorpay_webhooks_router.py signs requests
# with this exact secret and asserts against this exact merchant id, so
# an ambient value already exported in the developer's shell must never
# silently win. TEST_RAZORPAY_DEFAULT_MERCHANT_ID is not created via the
# API (Merchant.id is server-generated, not client-settable) -- see the
# razorpay_test_merchant fixture below, which inserts a Merchant row with
# exactly this id directly.
TEST_RAZORPAY_WEBHOOK_SECRET = "whsec_test_fixture_secret"
TEST_RAZORPAY_DEFAULT_MERCHANT_ID = "11111111-1111-1111-1111-111111111111"

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://finscope:finscope@localhost:5432/finscope"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["API_KEY"] = TEST_API_KEY
os.environ["RAZORPAY_WEBHOOK_SECRET"] = TEST_RAZORPAY_WEBHOOK_SECRET
os.environ["RAZORPAY_DEFAULT_MERCHANT_ID"] = TEST_RAZORPAY_DEFAULT_MERCHANT_ID

from app.db import SessionLocal  # noqa: E402  -- env vars must be set before import
from app.main import app  # noqa: E402  -- see note above
from app.models.merchant import Merchant  # noqa: E402  -- see note above


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def api_key() -> str:
    return TEST_API_KEY


@pytest.fixture
def razorpay_webhook_secret() -> str:
    return TEST_RAZORPAY_WEBHOOK_SECRET


@pytest.fixture
def razorpay_default_merchant_id() -> str:
    return TEST_RAZORPAY_DEFAULT_MERCHANT_ID


@pytest.fixture
def razorpay_test_merchant(razorpay_default_merchant_id):
    """Ensures a Merchant row exists with exactly
    conftest.TEST_RAZORPAY_DEFAULT_MERCHANT_ID as its id. Not created
    through the /v1/merchants API -- Merchant.id is server-generated
    (default=uuid.uuid4), so the only way to give a test merchant this
    exact, Settings-matching id is a direct insert. Idempotent (checks
    for an existing row first) so running many tests in one session
    never collides on a duplicate insert.

    Shared across every Razorpay-related test module (webhooks, actions,
    verification) -- lives here rather than in one test file so no test
    file needs to import-and-reexport it from a sibling module."""
    merchant_id = uuid.UUID(razorpay_default_merchant_id)
    db = SessionLocal()
    try:
        existing = db.get(Merchant, merchant_id)
        if existing is None:
            db.add(Merchant(id=merchant_id, name="Razorpay Webhook Test Merchant"))
            db.commit()
    finally:
        db.close()
    return merchant_id
