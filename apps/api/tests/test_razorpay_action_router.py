"""Integration tests for Phase 10, Milestone 3's real Razorpay TEST action
(POST/GET .../decisions/{decision_id}/razorpay-action, GET .../razorpay-actions).

Same tier as tests/test_actions.py / tests/test_verifications.py: TestClient
against the real app, real Postgres via app.db.SessionLocal. No test in
this file ever calls the real Razorpay API -- every test injects a
FakeRazorpayClient via FastAPI's dependency_overrides
(app.routers.investigations.get_razorpay_client), the exact same pattern
tests/test_reasoning.py already establishes for the reasoning provider.
The pure amount/receipt-derivation logic these integration paths call has
its own fully offline-executable coverage in
tests/test_razorpay_action_domain.py.
"""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models.audit_log import AuditLog
from app.models.investigation_decision import InvestigationDecision
from app.providers.razorpay import RazorpayClientError
from app.routers.investigations import get_razorpay_client
from tests.test_actions import (
    _allowed_decision,
    _create_merchant,
    _decide,
    _incident_investigation_with_failed_payments,
    _run_investigation,
    _simulate,
)


class FakeRazorpayOrder:
    def __init__(
        self,
        id="order_test_fixture",
        status="created",
        amount=1000,
        currency="INR",
        receipt=None,
        amount_paid=0,
        amount_due=1000,
    ):
        self.id = id
        self.status = status
        self.amount = amount
        self.currency = currency
        self.receipt = receipt
        self.amount_paid = amount_paid
        self.amount_due = amount_due


class FakeRazorpayClient:
    """Test double satisfying app.domain.razorpay_action.RazorpayClientProtocol.
    Records every call so tests can assert Razorpay was (or was not)
    invoked, and never performs any real network I/O."""

    def __init__(self, order: FakeRazorpayOrder | None = None, error: Exception | None = None):
        self.order = order
        self.error = error
        self.call_count = 0
        self.last_kwargs: dict | None = None

    def create_order(self, *, amount, currency, receipt, notes=None):
        self.call_count += 1
        self.last_kwargs = {
            "amount": amount,
            "currency": currency,
            "receipt": receipt,
            "notes": notes,
        }
        if self.error is not None:
            raise self.error
        assert self.order is not None
        return self.order


@pytest.fixture(autouse=True)
def _clear_client_override():
    # Every test sets its own override (or leaves none = "not configured",
    # exercising the same client-is-None rejection path as a real
    # unconfigured deployment). Guarantees no override leaks between
    # tests regardless of pass/fail.
    yield
    app.dependency_overrides.pop(get_razorpay_client, None)


def _override_client(client_double) -> None:
    app.dependency_overrides[get_razorpay_client] = lambda: client_double


def _razorpay_action(client, api_key, investigation_id, decision_id, body=None):
    kwargs = {"headers": {"X-API-Key": api_key}}
    if body is not None:
        kwargs["json"] = body
    return client.post(
        f"/v1/investigations/{investigation_id}/decisions/{decision_id}/razorpay-action", **kwargs
    )


def _audit_count(entity_id: str) -> int:
    db = SessionLocal()
    try:
        return len(
            list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.event_type == "investigation_razorpay_action_completed",
                        AuditLog.entity_id == entity_id,
                    )
                )
            )
        )
    finally:
        db.close()


# --- 1/2/3/4. valid ALLOWED decision -> real Order created exactly once ---


def test_allowed_decision_calls_razorpay_client_exactly_once_and_persists_order(
    client, api_key
):
    order = FakeRazorpayOrder(id="order_abc123", status="created", amount=3000, currency="INR")
    fake = FakeRazorpayClient(order=order)
    _override_client(fake)

    investigation, decision = _allowed_decision(client, api_key)
    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201, response.text
    body = response.json()

    assert fake.call_count == 1
    assert body["status"] == "executed"
    assert body["rejection_reason"] is None
    assert body["razorpay_order_id"] == "order_abc123"
    assert body["razorpay_receipt"] is not None
    assert body["policy_decision_snapshot"] == "ALLOWED"
    assert body["scenario"] == "RETRY_AFFECTED_PAYMENTS"
    assert _audit_count(body["id"]) == 1


# --- 5/6. idempotency: repeated request returns same action, client not called again ---


def test_repeated_request_returns_same_action_and_does_not_call_client_again(client, api_key):
    order = FakeRazorpayOrder(id="order_once_only")
    fake = FakeRazorpayClient(order=order)
    _override_client(fake)

    investigation, decision = _allowed_decision(client, api_key)
    first = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert first.status_code == 201
    assert fake.call_count == 1

    second = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json() == first.json()
    assert fake.call_count == 1  # never called a second time
    assert _audit_count(first.json()["id"]) == 1


# --- 7. BLOCKED -> rejected, Razorpay not called ---------------------------


def test_blocked_decision_is_rejected_without_calling_razorpay(client, api_key, monkeypatch):
    import app.domain.decisions as decision_domain
    from app.domain.policy import PolicyConfig

    prohibiting_config = PolicyConfig(
        version=decision_domain.DEFAULT_POLICY_CONFIG.version,
        autonomous_exposure_threshold_by_currency=(
            decision_domain.DEFAULT_POLICY_CONFIG.autonomous_exposure_threshold_by_currency
        ),
        max_autonomous_eligible_event_count=(
            decision_domain.DEFAULT_POLICY_CONFIG.max_autonomous_eligible_event_count
        ),
        prohibited_scenarios=frozenset({"RETRY_AFFECTED_PAYMENTS"}),
    )
    monkeypatch.setattr(decision_domain, "DEFAULT_POLICY_CONFIG", prohibiting_config)

    fake = FakeRazorpayClient(order=FakeRazorpayOrder())
    _override_client(fake)

    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="10.00")
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "BLOCKED"

    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert body["policy_decision_snapshot"] == "BLOCKED"
    assert body["razorpay_order_id"] is None
    assert fake.call_count == 0


# --- 8. REQUIRES_HUMAN_APPROVAL -> rejected, Razorpay not called -----------


def test_requires_human_approval_is_rejected_without_calling_razorpay(client, api_key):
    fake = FakeRazorpayClient(order=FakeRazorpayOrder())
    _override_client(fake)

    investigation = _incident_investigation_with_failed_payments(
        client, api_key, count=3, amount="5000.00"
    )
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.1", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "REQUIRES_HUMAN_APPROVAL"

    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "not ALLOWED" in body["rejection_reason"]
    assert body["razorpay_order_id"] is None
    assert fake.call_count == 0


# --- 9. insufficient evidence -> rejected, Razorpay not called -------------


def test_insufficient_evidence_is_rejected_without_calling_razorpay(client, api_key):
    fake = FakeRazorpayClient(order=FakeRazorpayOrder())
    _override_client(fake)

    merchant = _create_merchant(client, api_key)
    investigation = _run_investigation(client, api_key, merchant["id"], datetime.now(UTC))
    assert investigation["incident_detected"] is False
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["status"] == "insufficient_evidence"

    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "insufficient_evidence" in body["rejection_reason"] or "not 'completed'" in body[
        "rejection_reason"
    ]
    assert fake.call_count == 0


# --- 10/11/12. not found -----------------------------------------------------


def test_unknown_investigation_returns_404(client, api_key):
    _override_client(FakeRazorpayClient(order=FakeRazorpayOrder()))
    response = _razorpay_action(client, api_key, uuid.uuid4(), uuid.uuid4())
    assert response.status_code == 404


def test_cross_investigation_decision_returns_404(client, api_key):
    _override_client(FakeRazorpayClient(order=FakeRazorpayOrder()))
    investigation_a, decision_a = _allowed_decision(client, api_key)
    investigation_b = _incident_investigation_with_failed_payments(client, api_key)

    response = _razorpay_action(client, api_key, investigation_b["id"], decision_a["id"])
    assert response.status_code == 404

    get_response = client.get(
        f"/v1/investigations/{investigation_b['id']}/decisions/{decision_a['id']}/razorpay-action",
        headers={"X-API-Key": api_key},
    )
    assert get_response.status_code == 404


def test_unknown_decision_returns_404(client, api_key):
    _override_client(FakeRazorpayClient(order=FakeRazorpayOrder()))
    investigation = _incident_investigation_with_failed_payments(client, api_key)
    response = _razorpay_action(client, api_key, investigation["id"], uuid.uuid4())
    assert response.status_code == 404


# --- 13. malformed persisted simulation -> rejected -------------------------


def test_defensively_rejects_corrupted_preferred_simulation_id(client, api_key):
    fake = FakeRazorpayClient(order=FakeRazorpayOrder())
    _override_client(fake)

    investigation, decision = _allowed_decision(client, api_key)
    db = SessionLocal()
    try:
        row = db.get(InvestigationDecision, uuid.UUID(decision["id"]))
        row.evaluation_result = {
            **row.evaluation_result,
            "preferred_simulation_id": str(uuid.uuid4()),
        }
        db.commit()
    finally:
        db.close()

    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "preferred simulation" in body["rejection_reason"]
    assert fake.call_count == 0


def test_rejects_when_simulation_has_no_derivable_amount(client, api_key):
    """A Razorpay-specific malformed-simulation case Phase 7 has no
    equivalent for: a completed, otherwise-valid simulation whose result
    has no usable estimated_recovery_by_currency to derive an Order
    amount from -- see app.domain.razorpay_action._derive_amount_and_currency.
    """
    from app.models.investigation_simulation import InvestigationSimulation

    fake = FakeRazorpayClient(order=FakeRazorpayOrder())
    _override_client(fake)

    investigation, decision = _allowed_decision(client, api_key)
    simulation_id = uuid.UUID(decision["evaluation_result"]["preferred_simulation_id"])
    db = SessionLocal()
    try:
        simulation = db.get(InvestigationSimulation, simulation_id)
        simulation.result = {**simulation.result, "estimated_recovery_by_currency": []}
        db.commit()
    finally:
        db.close()

    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "estimated_recovery_by_currency" in body["rejection_reason"]
    assert fake.call_count == 0


# --- 14/15. provider timeout / non-2xx -> sanitized rejection --------------


def test_provider_timeout_is_a_sanitized_rejection_not_a_500(client, api_key):
    fake = FakeRazorpayClient(error=RazorpayClientError("Razorpay request timed out"))
    _override_client(fake)

    investigation, decision = _allowed_decision(client, api_key)
    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert body["rejection_reason"] == "Razorpay request timed out"
    assert body["razorpay_order_id"] is None
    assert fake.call_count == 1


def test_provider_non_2xx_is_a_sanitized_rejection_not_a_500(client, api_key):
    fake = FakeRazorpayClient(
        error=RazorpayClientError("Razorpay request returned an error (HTTP 400)")
    )
    _override_client(fake)

    investigation, decision = _allowed_decision(client, api_key)
    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "HTTP 400" in body["rejection_reason"]
    assert body["razorpay_order_id"] is None


def test_provider_error_action_remains_idempotent(client, api_key):
    fake = FakeRazorpayClient(error=RazorpayClientError("Razorpay request timed out"))
    _override_client(fake)

    investigation, decision = _allowed_decision(client, api_key)
    first = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert first.status_code == 201
    second = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert fake.call_count == 1  # not retried automatically


# --- unconfigured client -> rejected (no client, no call attempted) --------


def test_unconfigured_client_is_rejected(client, api_key):
    app.dependency_overrides[get_razorpay_client] = lambda: None
    investigation, decision = _allowed_decision(client, api_key)
    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "no Razorpay TEST client is configured" in body["rejection_reason"]


# --- 16. no secret leakage ---------------------------------------------------


def test_no_secret_leakage_in_response_or_rejection(client, api_key):
    fake = FakeRazorpayClient(
        error=RazorpayClientError("Razorpay request returned an error (HTTP 401)")
    )
    _override_client(fake)
    investigation, decision = _allowed_decision(client, api_key)
    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    text = response.text
    assert "key_secret" not in text
    assert "Authorization" not in text
    assert "Basic " not in text


def test_executed_action_raw_response_has_only_allowlisted_fields(client, api_key):
    order = FakeRazorpayOrder(
        id="order_allowlist_test", status="created", amount=3000, currency="INR",
        receipt="fs-somereceipt", amount_paid=0, amount_due=3000,
    )
    fake = FakeRazorpayClient(order=order)
    _override_client(fake)
    investigation, decision = _allowed_decision(client, api_key)
    response = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    body = response.json()
    allowed_keys = {"id", "status", "amount", "currency", "receipt", "amount_paid", "amount_due"}
    assert set(body["raw_response"].keys()) <= allowed_keys


# --- 17. forged request body cannot override anything -----------------------


def test_forged_request_body_cannot_override_authorization(client, api_key):
    fake = FakeRazorpayClient(order=FakeRazorpayOrder())
    _override_client(fake)

    investigation = _incident_investigation_with_failed_payments(
        client, api_key, count=3, amount="5000.00"
    )
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.1", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "REQUIRES_HUMAN_APPROVAL"

    response = _razorpay_action(
        client,
        api_key,
        investigation["id"],
        decision["id"],
        body={
            "status": "executed",
            "policy_decision": "ALLOWED",
            "razorpay_order_id": "order_forged",
            "amount": 1,
            "currency": "INR",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert body["razorpay_order_id"] is None
    assert fake.call_count == 0


# --- 18. unauthorized request -> 401 ----------------------------------------


def test_razorpay_action_endpoints_require_api_key(client):
    investigation_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    assert (
        client.post(
            f"/v1/investigations/{investigation_id}/decisions/{decision_id}/razorpay-action"
        ).status_code
        == 401
    )
    assert (
        client.get(
            f"/v1/investigations/{investigation_id}/decisions/{decision_id}/razorpay-action"
        ).status_code
        == 401
    )
    assert client.get(f"/v1/investigations/{investigation_id}/razorpay-actions").status_code == 401


# --- concurrent-insert race (simulated deterministically) ------------------


def test_concurrent_insert_race_resolves_to_one_row_before_any_razorpay_call(client, api_key):
    """Mirrors tests/test_actions.py::test_concurrent_insert_race_resolves_to_one_row,
    adapted for the Part 4 'pending row committed before the real external
    call' ordering: a second InvestigationRazorpayAction row for the same
    decision_id is rejected by the UNIQUE(decision_id) constraint at the
    database level -- the actual safety net that keeps two concurrent
    requests from ever both reaching RazorpayClient.create_order for one
    decision.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.investigation_razorpay_action import InvestigationRazorpayAction

    fake = FakeRazorpayClient(order=FakeRazorpayOrder(id="order_race"))
    _override_client(fake)

    investigation, decision = _allowed_decision(client, api_key)
    first = _razorpay_action(client, api_key, investigation["id"], decision["id"]).json()

    db = SessionLocal()
    try:
        duplicate = InvestigationRazorpayAction(
            investigation_id=uuid.UUID(investigation["id"]),
            decision_id=uuid.UUID(decision["id"]),
            status="pending",
            scenario="RETRY_AFFECTED_PAYMENTS",
            simulation_id=None,
            policy_decision_snapshot="ALLOWED",
            executor_version="1",
            raw_response={},
        )
        db.add(duplicate)
        try:
            db.flush()
            raised = False
        except IntegrityError:
            raised = True
            db.rollback()
    finally:
        db.close()

    assert raised, "UNIQUE(decision_id) did not reject a second razorpay action row"

    replay = _razorpay_action(client, api_key, investigation["id"], decision["id"])
    assert replay.status_code == 200
    assert replay.json()["id"] == first["id"]
    assert fake.call_count == 1


# --- list ordering -----------------------------------------------------------


def test_razorpay_action_history_is_newest_first(client, api_key):
    fake = FakeRazorpayClient(order=FakeRazorpayOrder())
    _override_client(fake)

    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="10.00")
    _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    decision_1 = _decide(client, api_key, investigation["id"]).json()
    action_1 = _razorpay_action(client, api_key, investigation["id"], decision_1["id"]).json()

    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    decision_2 = _decide(client, api_key, investigation["id"]).json()
    action_2 = _razorpay_action(client, api_key, investigation["id"], decision_2["id"]).json()

    response = client.get(
        f"/v1/investigations/{investigation['id']}/razorpay-actions",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids.index(action_2["id"]) < ids.index(action_1["id"])
