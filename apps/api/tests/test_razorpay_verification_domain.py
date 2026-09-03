"""Pure-logic tests for Phase 10, Milestone 3's real Razorpay TEST
outcome verification domain (app.domain.razorpay_verification) -- the
webhook-payload order-id extraction and observed-snapshot derivation
helpers, plus the module's own static safety properties. These need no
database and no network.
"""
import ast
import uuid
from decimal import Decimal

from app.domain.razorpay_verification import _derive_observed_snapshot, _extract_order_id


class _FakeFinancialEvent:
    """A minimal stand-in for app.models.financial_event.FinancialEvent --
    only the attributes _derive_observed_snapshot actually reads."""

    def __init__(self, event_type, amount=None, currency=None):
        self.event_type = event_type
        self.amount = amount
        self.currency = currency
        self.source = "razorpay_webhook"
        self.id = uuid.uuid4()


# --- _extract_order_id ---------------------------------------------------


def test_extract_order_id_from_payment_captured_payload():
    payload = {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_123", "order_id": "order_abc"}}},
    }
    assert _extract_order_id(payload) == "order_abc"


def test_extract_order_id_from_payment_failed_payload():
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"id": "pay_456", "order_id": "order_def"}}},
    }
    assert _extract_order_id(payload) == "order_def"


def test_extract_order_id_from_order_paid_payload_without_payment_entity():
    payload = {"event": "order.paid", "payload": {"order": {"entity": {"id": "order_xyz"}}}}
    assert _extract_order_id(payload) == "order_xyz"


def test_extract_order_id_prefers_payment_order_id_when_both_present():
    payload = {
        "event": "order.paid",
        "payload": {
            "payment": {"entity": {"id": "pay_1", "order_id": "order_from_payment"}},
            "order": {"entity": {"id": "order_from_order_entity"}},
        },
    }
    assert _extract_order_id(payload) == "order_from_payment"


def test_extract_order_id_missing_payload_section_returns_none():
    assert _extract_order_id({"event": "payment.failed"}) is None


def test_extract_order_id_malformed_shapes_never_raise():
    assert _extract_order_id({}) is None
    assert _extract_order_id({"payload": "not-a-dict"}) is None
    assert _extract_order_id({"payload": {"payment": "not-a-dict"}}) is None
    assert _extract_order_id({"payload": {"payment": {"entity": "not-a-dict"}}}) is None
    assert _extract_order_id({"payload": {"payment": {"entity": {"order_id": 12345}}}}) is None
    assert _extract_order_id(None) is None  # type: ignore[arg-type]
    assert _extract_order_id("not-a-dict") is None  # type: ignore[arg-type]


# --- _derive_observed_snapshot --------------------------------------------


def test_derive_observed_snapshot_success():
    event = _FakeFinancialEvent("payment_succeeded", amount=Decimal("150.00"), currency="INR")
    snapshot = _derive_observed_snapshot(event)
    assert snapshot["available"] is True
    assert snapshot["observed_success_count"] == 1
    assert snapshot["observed_failure_count"] == 0
    assert snapshot["observed_recovery_by_currency"] == [{"currency": "INR", "amount": "150.00"}]
    assert snapshot["observation_financial_event_id"] == str(event.id)


def test_derive_observed_snapshot_failure():
    event = _FakeFinancialEvent("payment_failed", amount=Decimal("150.00"), currency="INR")
    snapshot = _derive_observed_snapshot(event)
    assert snapshot["available"] is True
    assert snapshot["observed_success_count"] == 0
    assert snapshot["observed_failure_count"] == 1
    assert snapshot["observed_recovery_by_currency"] == [{"currency": "INR", "amount": "0.00"}]


def test_derive_observed_snapshot_unrecognized_event_type_is_unavailable():
    event = _FakeFinancialEvent("something_else", amount=Decimal("1.00"), currency="INR")
    snapshot = _derive_observed_snapshot(event)
    assert snapshot["available"] is False
    assert "unrecognized" in snapshot["reason"]


def test_derive_observed_snapshot_missing_amount_omits_recovery_entry():
    event = _FakeFinancialEvent("payment_succeeded", amount=None, currency="INR")
    snapshot = _derive_observed_snapshot(event)
    assert snapshot["available"] is True
    assert snapshot["observed_recovery_by_currency"] == []


def test_derive_observed_snapshot_missing_currency_omits_recovery_entry():
    event = _FakeFinancialEvent("payment_succeeded", amount=Decimal("1.00"), currency=None)
    snapshot = _derive_observed_snapshot(event)
    assert snapshot["available"] is True
    assert snapshot["observed_recovery_by_currency"] == []


# --- observed snapshot feeds the SAME pure comparator Phase 8 already uses -


def test_observed_snapshot_shape_is_accepted_by_the_unmodified_phase_8_comparator():
    from app.domain import outcome_verification

    event = _FakeFinancialEvent("payment_succeeded", amount=Decimal("30.00"), currency="INR")
    observed = _derive_observed_snapshot(event)
    expected = {
        "available": True,
        "scenario": "RETRY_AFFECTED_PAYMENTS",
        "simulator_version": "1",
        "eligible_event_count": 1,
        "projected_success_count": 1,
        "projected_failure_count": 0,
        "projected_exposure_by_currency": [],
        "estimated_recovery_by_currency": [{"currency": "INR", "amount": "30.00"}],
    }
    comparison = outcome_verification.verify(expected=expected, observed=observed)
    assert comparison["status"] == outcome_verification.VERIFIED_SUCCESS
    assert comparison["matched_dimension_count"] == 3


# --- static safety: no reasoning / provider / network dependency ---------


def test_module_has_no_reasoning_or_network_dependency():
    """Static inspection proving app.domain.razorpay_verification never
    imports app.domain.reasoning / app.providers.reasoning / any network
    library -- verification is a pure DB + comparison orchestration, with
    no execution path to Claude's output or an external network call
    (Part 14's required static check). Mirrors
    tests/test_actions.py::test_sandbox_executor_module_has_no_network_or_db_dependency's
    own AST-based technique.
    """
    import app.domain.razorpay_verification as module

    tree = ast.parse(open(module.__file__).read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [n.name for n in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    forbidden = {
        "app.domain.reasoning",
        "app.providers.reasoning",
        "httpx",
        "requests",
        "socket",
        "urllib",
        "anthropic",
    }
    assert not (set(names) & forbidden), f"forbidden import(s) found: {set(names) & forbidden}"
