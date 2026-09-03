"""Pure-logic tests for Phase 10, Milestone 3's real Razorpay TEST action
domain (app.domain.razorpay_action) -- the receipt/amount-derivation
helpers and the module's own static safety properties. These need no
database and no network; genuinely executed in this environment via the
dependency-free harness described in the Milestone 3 report, mirroring
the same DB-free tier tests/test_outcome_verification.py already
establishes for Phase 8's pure comparator.
"""
import ast
import uuid

from app.domain.razorpay_action import (
    _MINIMUM_AMOUNT_MINOR_UNITS,
    _derive_amount_and_currency,
    _derive_receipt,
)

# --- _derive_receipt ---------------------------------------------------


def test_derive_receipt_is_deterministic_and_under_40_chars():
    decision_id = uuid.uuid4()
    first = _derive_receipt(decision_id)
    second = _derive_receipt(decision_id)
    assert first == second
    assert len(first) <= 40
    assert first.startswith("fs-")


def test_derive_receipt_differs_for_different_decisions():
    assert _derive_receipt(uuid.uuid4()) != _derive_receipt(uuid.uuid4())


# --- _derive_amount_and_currency ----------------------------------------


def test_derive_amount_and_currency_single_currency():
    result = _derive_amount_and_currency(
        {"estimated_recovery_by_currency": [{"currency": "INR", "amount": "150.00"}]}
    )
    assert result == (15000, "INR")


def test_derive_amount_and_currency_empty_list_rejects():
    amount, reason = _derive_amount_and_currency({"estimated_recovery_by_currency": []})
    assert amount is None
    assert "no estimated_recovery_by_currency" in reason


def test_derive_amount_and_currency_missing_key_rejects():
    amount, reason = _derive_amount_and_currency({})
    assert amount is None
    assert "no estimated_recovery_by_currency" in reason


def test_derive_amount_and_currency_multi_currency_rejects():
    amount, reason = _derive_amount_and_currency(
        {
            "estimated_recovery_by_currency": [
                {"currency": "INR", "amount": "150.00"},
                {"currency": "USD", "amount": "10.00"},
            ]
        }
    )
    assert amount is None
    assert "multiple currencies" in reason


def test_derive_amount_and_currency_non_positive_rejects():
    amount, reason = _derive_amount_and_currency(
        {"estimated_recovery_by_currency": [{"currency": "INR", "amount": "0.00"}]}
    )
    assert amount is None
    assert "no positive amount" in reason


def test_derive_amount_and_currency_below_minimum_rejects():
    # 0.50 INR = 50 minor units, below Razorpay's documented 100 minimum
    # (verified during Phase 10 planning).
    amount, reason = _derive_amount_and_currency(
        {"estimated_recovery_by_currency": [{"currency": "INR", "amount": "0.50"}]}
    )
    assert amount is None
    assert "below Razorpay's documented minimum" in reason
    assert str(_MINIMUM_AMOUNT_MINOR_UNITS) in reason


def test_derive_amount_and_currency_malformed_entries_are_skipped_not_raised():
    amount, currency = _derive_amount_and_currency(
        {
            "estimated_recovery_by_currency": [
                {"currency": "INR"},  # missing amount
                {"amount": "10.00"},  # missing currency
                "not-a-dict",
                {"currency": "INR", "amount": "not-a-number"},
                {"currency": "INR", "amount": "150.00"},
            ]
        }
    )
    assert (amount, currency) == (15000, "INR")


def test_derive_amount_and_currency_non_list_input_rejects():
    amount, reason = _derive_amount_and_currency({"estimated_recovery_by_currency": "oops"})
    assert amount is None
    assert "no estimated_recovery_by_currency" in reason


# --- static safety: no reasoning / provider / network dependency --------


def test_module_has_no_reasoning_or_network_dependency():
    """Static inspection proving app.domain.razorpay_action never imports
    app.domain.reasoning / app.providers.reasoning / httpx / any network
    library -- there is structurally no execution path from Claude's
    output to RazorpayClient. Mirrors
    tests/test_actions.py::test_sandbox_executor_module_has_no_network_or_db_dependency's
    own AST-based technique.
    """
    import app.domain.razorpay_action as module

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
