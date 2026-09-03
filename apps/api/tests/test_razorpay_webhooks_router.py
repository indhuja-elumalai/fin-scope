"""Router-level tests for POST /v1/webhooks/razorpay -- Phase 10,
Milestone 2.

Same tier as tests/test_events.py / tests/test_actions.py: TestClient
against the real app, real Postgres via app.db.SessionLocal (not
mocked), real signature bytes over the wire. This is the DB-touching
orchestration tier of app.domain.razorpay_webhooks -- the pure
verify_signature()/map_webhook_payload() logic has its own fully
offline-executable coverage in test_razorpay_webhooks_domain.py.

No live Razorpay call is made anywhere in this file -- every request in
every test is this test process signing its own synthetic payload with
the fixture secret (conftest.TEST_RAZORPAY_WEBHOOK_SECRET) and posting it
to the local app, exactly the shape a real Razorpay delivery would have
on the wire, never a call out to api.razorpay.com.
"""
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

from sqlalchemy import select

from app.db import SessionLocal
from app.models.audit_log import AuditLog
from app.models.financial_event import FinancialEvent
from app.models.razorpay_webhook_event import RazorpayWebhookEvent

WEBHOOK_URL = "/v1/webhooks/razorpay"


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post_webhook(
    client,
    body: dict,
    secret: str,
    *,
    event_id: str | None = None,
    signature: str | None = None,
):
    raw = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Razorpay-Signature"] = signature
    elif secret is not None:
        headers["X-Razorpay-Signature"] = _sign(raw, secret)
    if event_id is not None:
        headers["x-razorpay-event-id"] = event_id
    return client.post(WEBHOOK_URL, content=raw, headers=headers)


def _payment_captured_body(payment_id: str, *, amount: int = 10000, currency: str = "INR") -> dict:
    return {
        "entity": "event",
        "event": "payment.captured",
        "created_at": 1691735748,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount,
                    "currency": currency,
                    "status": "captured",
                    "order_id": "order_test_1",
                    "error_code": "",
                    "error_description": "",
                }
            }
        },
    }


def _payment_failed_body(payment_id: str) -> dict:
    return {
        "entity": "event",
        "event": "payment.failed",
        "created_at": 1691735748,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 5000,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_test_2",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed",
                }
            }
        },
    }


def _order_paid_body(order_id: str, payment_id: str) -> dict:
    return {
        "entity": "event",
        "event": "order.paid",
        "created_at": 1691735748,
        "payload": {
            "order": {
                "entity": {
                    "id": order_id,
                    "amount": 10000,
                    "amount_paid": 10000,
                    "amount_due": 0,
                    "currency": "INR",
                    "status": "paid",
                }
            },
            "payment": {"entity": {"id": payment_id, "amount": 10000, "currency": "INR"}},
        },
    }


def _financial_event_for_reference(external_reference: str) -> FinancialEvent | None:
    db = SessionLocal()
    try:
        return db.scalars(
            select(FinancialEvent).where(
                FinancialEvent.source == "razorpay_webhook",
                FinancialEvent.external_reference == external_reference,
            )
        ).first()
    finally:
        db.close()


def _audit_rows_for(entity_id: str) -> list[AuditLog]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(AuditLog).where(AuditLog.entity_id == entity_id)
            )
        )
    finally:
        db.close()


# --- authentication / signature ---------------------------------------------


def test_missing_signature_rejected(client, razorpay_test_merchant):
    response = client.post(
        WEBHOOK_URL,
        content=json.dumps(_payment_captured_body(f"pay_{uuid.uuid4()}")).encode(),
        headers={"x-razorpay-event-id": str(uuid.uuid4()), "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_invalid_signature_rejected(client, razorpay_test_merchant):
    response = _post_webhook(
        client,
        _payment_captured_body(f"pay_{uuid.uuid4()}"),
        secret=None,
        signature="0" * 64,
        event_id=str(uuid.uuid4()),
    )
    assert response.status_code == 401


def test_signature_computed_with_wrong_secret_rejected(client, razorpay_test_merchant):
    response = _post_webhook(
        client,
        _payment_captured_body(f"pay_{uuid.uuid4()}"),
        secret="not-the-real-secret",
        event_id=str(uuid.uuid4()),
    )
    assert response.status_code == 401


def test_missing_event_id_rejected(client, razorpay_webhook_secret, razorpay_test_merchant):
    response = _post_webhook(
        client, _payment_captured_body(f"pay_{uuid.uuid4()}"), razorpay_webhook_secret
    )
    assert response.status_code == 400


def test_no_api_key_required(client, razorpay_webhook_secret, razorpay_test_merchant):
    """Unlike /v1/events, this route must be reachable with no X-API-Key
    at all -- Razorpay never sends one. A valid signature is sufficient
    and necessary authentication on its own."""
    response = _post_webhook(
        client,
        _payment_captured_body(f"pay_{uuid.uuid4()}"),
        razorpay_webhook_secret,
        event_id=str(uuid.uuid4()),
    )
    assert response.status_code in (200, 201)


def test_malformed_json_body_rejected(client, razorpay_webhook_secret, razorpay_test_merchant):
    raw = b"{not valid json"
    response = client.post(
        WEBHOOK_URL,
        content=raw,
        headers={
            "X-Razorpay-Signature": _sign(raw, razorpay_webhook_secret),
            "x-razorpay-event-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


# --- supported event types --------------------------------------------------


def test_payment_captured_creates_financial_event(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    payment_id = f"pay_{uuid.uuid4()}"
    response = _post_webhook(
        client,
        _payment_captured_body(payment_id, amount=250000, currency="inr"),
        razorpay_webhook_secret,
        event_id=str(uuid.uuid4()),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["outcome"] == "accepted"

    event = _financial_event_for_reference(payment_id)
    assert event is not None
    assert event.event_type == "payment_succeeded"
    assert event.merchant_id == razorpay_test_merchant
    assert str(event.amount) == "2500.00"
    assert event.currency == "INR"
    assert event.status == "captured"


def test_payment_failed_creates_financial_event(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    payment_id = f"pay_{uuid.uuid4()}"
    response = _post_webhook(
        client,
        _payment_failed_body(payment_id),
        razorpay_webhook_secret,
        event_id=str(uuid.uuid4()),
    )
    assert response.status_code == 201, response.text
    event = _financial_event_for_reference(payment_id)
    assert event is not None
    assert event.event_type == "payment_failed"
    assert event.status == "failed"
    # error detail preserved in payload JSONB, not silently dropped
    assert event.payload["payload"]["payment"]["entity"]["error_code"] == "BAD_REQUEST_ERROR"


def test_order_paid_creates_financial_event(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    payment_id = f"pay_{uuid.uuid4()}"
    order_id = f"order_{uuid.uuid4()}"
    response = _post_webhook(
        client,
        _order_paid_body(order_id, payment_id),
        razorpay_webhook_secret,
        event_id=str(uuid.uuid4()),
    )
    assert response.status_code == 201, response.text
    event = _financial_event_for_reference(payment_id)
    assert event is not None
    assert event.event_type == "payment_succeeded"


def test_order_paid_and_payment_captured_collapse_into_one_financial_event(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    """Both webhooks can fire for the same underlying payment (delivery
    order not guaranteed) -- they must produce exactly ONE FinancialEvent,
    via FinancialEvent's own existing (source, external_reference) dedup,
    not two."""
    payment_id = f"pay_{uuid.uuid4()}"
    order_id = f"order_{uuid.uuid4()}"

    first = _post_webhook(
        client,
        _order_paid_body(order_id, payment_id),
        razorpay_webhook_secret,
        event_id=str(uuid.uuid4()),
    )
    second = _post_webhook(
        client,
        _payment_captured_body(payment_id),
        razorpay_webhook_secret,
        event_id=str(uuid.uuid4()),
    )
    assert first.status_code == 201
    assert second.status_code == 200  # already existed -- ingest_event's own dedup
    assert first.json()["financial_event_id"] == second.json()["financial_event_id"]


# --- idempotency / replay ---------------------------------------------------


def test_duplicate_delivery_of_same_event_id_is_idempotent(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    payment_id = f"pay_{uuid.uuid4()}"
    event_id = str(uuid.uuid4())
    body = _payment_captured_body(payment_id)

    first = _post_webhook(client, body, razorpay_webhook_secret, event_id=event_id)
    second = _post_webhook(client, body, razorpay_webhook_secret, event_id=event_id)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["financial_event_id"] == second.json()["financial_event_id"]

    # No duplicate FinancialEvent...
    db = SessionLocal()
    try:
        count = len(
            db.scalars(
                select(FinancialEvent).where(
                    FinancialEvent.source == "razorpay_webhook",
                    FinancialEvent.external_reference == payment_id,
                )
            ).all()
        )
    finally:
        db.close()
    assert count == 1

    # ...and no duplicate audit row for the replay.
    audit_rows = _audit_rows_for(event_id)
    accepted_rows = [r for r in audit_rows if r.event_type == "razorpay_webhook_accepted"]
    assert len(accepted_rows) == 1


def test_ledger_row_written_exactly_once_per_event_id(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    event_id = str(uuid.uuid4())
    body = _payment_captured_body(f"pay_{uuid.uuid4()}")
    _post_webhook(client, body, razorpay_webhook_secret, event_id=event_id)
    _post_webhook(client, body, razorpay_webhook_secret, event_id=event_id)

    db = SessionLocal()
    try:
        rows = list(
            db.scalars(
                select(RazorpayWebhookEvent).where(
                    RazorpayWebhookEvent.razorpay_event_id == event_id
                )
            )
        )
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0].outcome == "accepted"


# --- unsupported / malformed -------------------------------------------------


def test_unsupported_event_type_is_ignored_not_processed(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    body = {"entity": "event", "event": "refund.created", "payload": {"refund": {"entity": {}}}}
    response = _post_webhook(client, body, razorpay_webhook_secret, event_id=str(uuid.uuid4()))
    assert response.status_code == 200
    assert response.json()["outcome"] == "ignored_unsupported_event"
    assert response.json()["financial_event_id"] is None


def test_unsupported_event_type_never_creates_financial_event(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    marker = f"refund_marker_{uuid.uuid4()}"
    body = {
        "entity": "event",
        "event": "refund.created",
        "payload": {"refund": {"entity": {"id": marker}}},
    }
    _post_webhook(client, body, razorpay_webhook_secret, event_id=str(uuid.uuid4()))
    assert _financial_event_for_reference(marker) is None


def test_malformed_supported_payload_rejected(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    """payment.captured with no payload.payment.entity.id at all."""
    body = {"entity": "event", "event": "payment.captured", "payload": {"payment": {"entity": {}}}}
    response = _post_webhook(client, body, razorpay_webhook_secret, event_id=str(uuid.uuid4()))
    assert response.status_code == 422


def test_missing_required_fields_no_payload_object(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    body = {"entity": "event", "event": "payment.captured"}
    response = _post_webhook(client, body, razorpay_webhook_secret, event_id=str(uuid.uuid4()))
    assert response.status_code == 422


def test_missing_event_field_rejected(client, razorpay_webhook_secret, razorpay_test_merchant):
    body = {"entity": "event", "payload": {}}
    response = _post_webhook(client, body, razorpay_webhook_secret, event_id=str(uuid.uuid4()))
    assert response.status_code == 400


# --- persistence failure -----------------------------------------------------


def test_persistence_failure_returns_500_and_is_retryable(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    """A genuine DB/persistence failure during ingest_event must become a
    5xx (so Razorpay retries) and must NOT write a ledger row -- so a
    retry after the transient problem clears actually reprocesses and
    succeeds, rather than being silently swallowed as 'already handled'.
    """
    payment_id = f"pay_{uuid.uuid4()}"
    event_id = str(uuid.uuid4())
    body = _payment_captured_body(payment_id)

    with patch(
        "app.domain.razorpay_webhooks.event_domain.ingest_event",
        side_effect=RuntimeError("simulated DB failure"),
    ):
        failed_response = _post_webhook(client, body, razorpay_webhook_secret, event_id=event_id)
    assert failed_response.status_code == 500

    # No ledger row for the failed attempt...
    db = SessionLocal()
    try:
        rows = list(
            db.scalars(
                select(RazorpayWebhookEvent).where(
                    RazorpayWebhookEvent.razorpay_event_id == event_id
                )
            )
        )
    finally:
        db.close()
    assert len(rows) == 0

    # ...so the SAME event_id, retried without the simulated failure,
    # actually reprocesses and succeeds rather than being treated as a
    # dedup replay of a "success" that never happened.
    retried_response = _post_webhook(client, body, razorpay_webhook_secret, event_id=event_id)
    assert retried_response.status_code == 201
    assert _financial_event_for_reference(payment_id) is not None


def test_unconfigured_merchant_returns_500_not_ledger_recorded(
    client, razorpay_webhook_secret, monkeypatch
):
    """RAZORPAY_DEFAULT_MERCHANT_ID naming a merchant that does not exist
    is a configuration failure, not a payload problem -- 500, and (like
    the persistence-failure case) must not be ledger-recorded."""
    from app.config import get_settings

    bogus_merchant_id = str(uuid.uuid4())
    monkeypatch.setattr(get_settings(), "razorpay_default_merchant_id", bogus_merchant_id)

    event_id = str(uuid.uuid4())
    response = _post_webhook(
        client,
        _payment_captured_body(f"pay_{uuid.uuid4()}"),
        razorpay_webhook_secret,
        event_id=event_id,
    )
    assert response.status_code == 500

    db = SessionLocal()
    try:
        rows = list(
            db.scalars(
                select(RazorpayWebhookEvent).where(
                    RazorpayWebhookEvent.razorpay_event_id == event_id
                )
            )
        )
    finally:
        db.close()
    assert len(rows) == 0


# --- audit behavior -----------------------------------------------------


def test_accepted_webhook_writes_exactly_one_audit_row(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    event_id = str(uuid.uuid4())
    _post_webhook(
        client, _payment_captured_body(f"pay_{uuid.uuid4()}"), razorpay_webhook_secret,
        event_id=event_id,
    )
    rows = _audit_rows_for(event_id)
    assert len(rows) == 1
    assert rows[0].event_type == "razorpay_webhook_accepted"
    assert rows[0].actor == "system"


def test_rejected_malformed_payload_writes_audit_row_without_secret_leak(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    event_id = str(uuid.uuid4())
    body = {"entity": "event", "event": "payment.captured", "payload": {"payment": {"entity": {}}}}
    _post_webhook(client, body, razorpay_webhook_secret, event_id=event_id)

    rows = _audit_rows_for(event_id)
    assert len(rows) == 1
    assert rows[0].event_type == "razorpay_webhook_rejected"
    dumped = json.dumps(rows[0].payload)
    assert razorpay_webhook_secret not in dumped


def test_ignored_unsupported_event_writes_audit_row(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    event_id = str(uuid.uuid4())
    body = {"entity": "event", "event": "refund.created", "payload": {}}
    _post_webhook(client, body, razorpay_webhook_secret, event_id=event_id)

    rows = _audit_rows_for(event_id)
    assert len(rows) == 1
    assert rows[0].event_type == "razorpay_webhook_ignored"


def test_response_never_contains_webhook_secret(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    response = _post_webhook(
        client,
        _payment_captured_body(f"pay_{uuid.uuid4()}"),
        razorpay_webhook_secret,
        event_id=str(uuid.uuid4()),
    )
    assert razorpay_webhook_secret not in response.text


def test_invalid_signature_response_never_contains_secret_or_signature(
    client, razorpay_webhook_secret, razorpay_test_merchant
):
    response = _post_webhook(
        client,
        _payment_captured_body(f"pay_{uuid.uuid4()}"),
        secret=None,
        signature="deadbeef" * 8,
        event_id=str(uuid.uuid4()),
    )
    assert razorpay_webhook_secret not in response.text
    assert "deadbeef" not in response.text
