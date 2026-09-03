"""Unit tests for the PURE half of app/domain/razorpay_webhooks.py --
verify_signature() and map_webhook_payload(). Phase 10, Milestone 2.

No database, no FastAPI, no network -- mirrors the existing pure-domain
test tier (tests/test_sandbox_executor.py, tests/test_outcome_verification.py
would be, if that pure comparator had its own file separate from the
DB-touching tests/test_verifications.py). This is genuinely executable
without the project's Postgres/venv, unlike
tests/test_razorpay_webhooks_router.py (the DB-touching orchestration
tier, same shape as tests/test_events.py/test_actions.py).
"""
import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.razorpay_webhooks import (
    SUPPORTED_EVENT_TYPES,
    MalformedPayloadError,
    map_webhook_payload,
    verify_signature,
)

# --- verify_signature ------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_correct_signature():
    body = b'{"event": "payment.captured"}'
    secret = "whsec_test_123"
    assert verify_signature(body, _sign(body, secret), secret) is True


def test_verify_signature_rejects_wrong_secret():
    body = b'{"event": "payment.captured"}'
    assert verify_signature(body, _sign(body, "right_secret"), "wrong_secret") is False


def test_verify_signature_rejects_tampered_body():
    secret = "whsec_test_123"
    original = b'{"event": "payment.captured", "amount": 100}'
    tampered = b'{"event": "payment.captured", "amount": 999999}'
    signature = _sign(original, secret)
    assert verify_signature(tampered, signature, secret) is False


def test_verify_signature_rejects_garbage_signature():
    body = b'{"event": "payment.captured"}'
    assert verify_signature(body, "not-a-real-signature", "whsec_test_123") is False


def test_verify_signature_is_sensitive_to_byte_level_reserialization():
    """A signature computed over one JSON serialization of the same
    logical object must NOT verify against a different serialization
    (different key order/whitespace) -- this is exactly why the router
    must sign the raw bytes, never a re-serialized body. Locks in that
    verify_signature has no leniency baked in that could paper over a
    router bug that re-serializes before verifying."""
    secret = "whsec_test_123"
    raw = b'{"event":"payment.captured","amount":100}'
    reserialized = json.dumps(json.loads(raw)).encode("utf-8")
    assert raw != reserialized
    signature = _sign(raw, secret)
    assert verify_signature(reserialized, signature, secret) is False


# --- map_webhook_payload: payment.captured / payment.failed ----------------


def _payment_body(event: str, entity_overrides: dict | None = None) -> dict:
    entity = {
        "id": "pay_DESp9bgForNoUd",
        "amount": 10000,
        "currency": "INR",
        "status": "captured" if event == "payment.captured" else "failed",
        "order_id": "order_DESoU0U4ikYA19",
        "error_code": "",
        "error_description": "",
    }
    if entity_overrides:
        entity.update(entity_overrides)
    return {
        "entity": "event",
        "event": event,
        "created_at": 1691735748,
        "contains": ["payment"],
        "payload": {"payment": {"entity": entity}},
    }


def test_map_payment_captured_success():
    mapped = map_webhook_payload("payment.captured", _payment_body("payment.captured"))
    assert mapped.event_type == "payment_succeeded"
    assert mapped.external_reference == "pay_DESp9bgForNoUd"
    assert mapped.amount == Decimal("100.00")
    assert mapped.currency == "INR"
    assert mapped.status == "captured"
    assert mapped.occurred_at == datetime.fromtimestamp(1691735748, tz=UTC)
    assert mapped.payload["event"] == "payment.captured"


def test_map_payment_failed_success():
    body = _payment_body(
        "payment.failed",
        {
            "status": "failed",
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Card declined",
        },
    )
    mapped = map_webhook_payload("payment.failed", body)
    assert mapped.event_type == "payment_failed"
    assert mapped.external_reference == "pay_DESp9bgForNoUd"
    assert mapped.status == "failed"
    # Error detail is preserved in the raw payload (for traceability / the
    # audit trail) even though FinancialEvent has no dedicated error_code
    # column -- never discarded, never promoted to a typed field that
    # would require a schema change.
    assert mapped.payload["payload"]["payment"]["entity"]["error_code"] == "BAD_REQUEST_ERROR"


def test_map_payment_amount_converted_from_minor_to_major_units():
    body = _payment_body("payment.captured", {"amount": 123456})
    mapped = map_webhook_payload("payment.captured", body)
    assert mapped.amount == Decimal("1234.56")


def test_map_payment_missing_payload_object_raises():
    with pytest.raises(MalformedPayloadError):
        map_webhook_payload("payment.captured", {"event": "payment.captured"})


def test_map_payment_missing_payment_entity_raises():
    with pytest.raises(MalformedPayloadError):
        map_webhook_payload("payment.captured", {"event": "payment.captured", "payload": {}})


def test_map_payment_missing_id_raises():
    body = _payment_body("payment.captured")
    del body["payload"]["payment"]["entity"]["id"]
    with pytest.raises(MalformedPayloadError):
        map_webhook_payload("payment.captured", body)


def test_map_payment_currency_is_uppercased():
    body = _payment_body("payment.captured", {"currency": "inr"})
    mapped = map_webhook_payload("payment.captured", body)
    assert mapped.currency == "INR"


# --- map_webhook_payload: order.paid ----------------------------------------


def _order_paid_body(*, include_payment_entity: bool = True) -> dict:
    payload = {
        "order": {
            "entity": {
                "id": "order_DESoU0U4ikYA19",
                "amount": 10000,
                "amount_paid": 10000,
                "amount_due": 0,
                "currency": "INR",
                "receipt": "rcpt_1",
                "status": "paid",
            }
        }
    }
    if include_payment_entity:
        payload["payment"] = {
            "entity": {
                "id": "pay_DESp9bgForNoUd",
                "amount": 10000,
                "currency": "INR",
                "status": "captured",
            }
        }
    return {
        "entity": "event",
        "event": "order.paid",
        "created_at": 1691735748,
        "payload": payload,
    }


def test_map_order_paid_prefers_payment_id_when_present():
    """Same payment_id as a payment.captured event for the same payment
    lets FinancialEvent's own (source, external_reference) dedup collapse
    both webhooks into one row -- see map_webhook_payload's docstring."""
    mapped = map_webhook_payload("order.paid", _order_paid_body(include_payment_entity=True))
    assert mapped.event_type == "payment_succeeded"
    assert mapped.external_reference == "pay_DESp9bgForNoUd"
    assert mapped.amount == Decimal("100.00")
    assert mapped.currency == "INR"
    assert mapped.status == "paid"


def test_map_order_paid_falls_back_to_order_id_without_payment_entity():
    mapped = map_webhook_payload("order.paid", _order_paid_body(include_payment_entity=False))
    assert mapped.external_reference == "order_DESoU0U4ikYA19"
    assert mapped.amount == Decimal("100.00")


def test_map_order_paid_missing_order_entity_raises():
    with pytest.raises(MalformedPayloadError):
        map_webhook_payload("order.paid", {"event": "order.paid", "payload": {}})


def test_map_order_paid_missing_order_id_raises():
    body = _order_paid_body()
    del body["payload"]["order"]["entity"]["id"]
    with pytest.raises(MalformedPayloadError):
        map_webhook_payload("order.paid", body)


# --- vocabulary consistency --------------------------------------------------


def test_supported_event_types_is_exactly_the_milestone_2_scope():
    """Locks in scope item 4: ONLY these three, no silent expansion."""
    assert SUPPORTED_EVENT_TYPES == {"payment.failed", "payment.captured", "order.paid"}


def test_map_webhook_payload_raises_for_unsupported_event_type():
    """map_webhook_payload itself still refuses an unsupported type if
    ever called with one directly (defense in depth -- the router/
    process_webhook are expected to filter these out first via
    SUPPORTED_EVENT_TYPES, but this function does not trust that blindly
    either)."""
    with pytest.raises(MalformedPayloadError):
        map_webhook_payload("refund.created", {"event": "refund.created", "payload": {}})
