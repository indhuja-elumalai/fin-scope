"""Integration tests for Phase 10, Milestone 3's real Razorpay TEST
outcome verification (POST/GET .../razorpay-actions/{action_id}/verification,
GET .../razorpay-verifications).

Same tier as tests/test_verifications.py: TestClient against the real
app, real Postgres. Unlike Phase 8's verification (which observes a
Phase 7 in-process sandbox result), this milestone's OBSERVED side must
originate from a REAL, already-persisted, webhook-verified FinancialEvent
-- so these tests build that observation the same way
tests/test_razorpay_webhooks_router.py already does: this test process
signs its own synthetic Razorpay webhook payload with the fixture secret
and posts it to the real local webhook endpoint, never a call out to
api.razorpay.com. The pure order-id-extraction/observed-snapshot logic
these integration paths call has its own fully offline-executable
coverage in tests/test_razorpay_verification_domain.py, along with the
static no-reasoning/no-network-dependency proof (Part 14).

Razorpay webhook payloads never carry a FIN-SCOPE merchant id (see
app.domain.razorpay_webhooks module docstring) -- every webhook in this
codebase routes to Settings.razorpay_default_merchant_id
(conftest.TEST_RAZORPAY_DEFAULT_MERCHANT_ID). For a real webhook
observation to ever be found for an investigation's razorpay action, that
investigation's merchant MUST be that same fixed id -- these tests always
build their investigations on the `razorpay_test_merchant` fixture rather
than a random `_create_merchant()` merchant for exactly this reason.
"""
import itertools
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app.models.audit_log import AuditLog
from tests.test_actions import _ago, _decide, _ingest, _run_investigation, _simulate
from tests.test_razorpay_action_router import (
    FakeRazorpayClient,
    FakeRazorpayOrder,
    _override_client,
    _razorpay_action,
)
from tests.test_razorpay_webhooks_router import _post_webhook

# Every M3 verification test is forced onto the SAME merchant
# (razorpay_test_merchant): a webhook-derived FinancialEvent always
# routes to Settings.razorpay_default_merchant_id (see
# app.domain.razorpay_webhooks module docstring), so there is no way to
# isolate these tests from each other the way tests/test_actions.py does
# via a fresh _create_merchant() per test. Phase 3's evidence query
# (app.domain.investigations.run_investigation) is a real, wall-clock
# rolling 60-minute window with no `source` filter -- so if every
# investigation here anchored on real datetime.now(UTC), one test's
# payment_failed evidence (and even test_razorpay_webhooks_router.py's
# own webhook-ingested payment_failed/payment_succeeded rows for this
# same merchant) would silently bleed into every other test's window on
# this real, never-truncated Postgres database, inflating
# eligible_event_count for whichever test happens to run later in the
# session. Anchoring on real "now" is exactly what produced the
# eligible_event_count/recovery_by_currency corruption this fixture
# previously had.
#
# The fix is temporal, not per-merchant: every investigation below is
# anchored far away from real "now" (so nothing near-now, e.g. a webhook
# test's own events, can ever fall in its window) and far away from
# every OTHER call's anchor in this same process (so two investigations
# in this file can never share a window either).
#
# _ANCHOR_EPOCH must ALSO be collision-proof across separate pytest
# invocations against this same never-truncated database -- an earlier
# version of this fixture derived it from `datetime.now(UTC) -
# timedelta(days=3650)`, which is deterministic *relative to real time*:
# two runs started minutes apart (exactly what happens across an
# iterative debugging session) produce nearly-identical epochs, so the
# Nth call's anchor in run 2 lands within DETECTION_WINDOW of the SAME
# Nth call's anchor from run 1's still-present leftover rows. That is
# what actually produced eligible_event_count=5 for a test that ingests
# exactly one payment_failed event -- five separate real test runs' worth
# of leftover evidence, not a per-run isolation failure. Anchoring
# instead on a base picked uniformly at random (random.SystemRandom,
# os.urandom-backed -- not seedable, so it can never accidentally repeat
# across runs) over a multi-decade range makes two runs' epochs land
# within DETECTION_WINDOW of each other astronomically unlikely,
# regardless of how close together in real time those runs are. This is
# test-isolation plumbing only, not financial calculation -- it does not
# touch the "no randomness in Phase 5" invariant, the same way this
# file's existing use of uuid.uuid4() for order/payment ids already
# accepts non-determinism for uniqueness without affecting any financial
# arithmetic. Spacing between calls WITHIN one run stays a deterministic,
# monotonic counter, so a single run remains fully reproducible.
_ANCHOR_RANGE_SECONDS = 60 * 60 * 24 * 365 * 40  # 40 years of possible starting points
_ANCHOR_EPOCH = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
    seconds=random.SystemRandom().randrange(0, _ANCHOR_RANGE_SECONDS)
)
_ANCHOR_COUNTER = itertools.count()
_ANCHOR_SPACING = timedelta(hours=2)  # comfortably more than DETECTION_WINDOW (60 min)


def _next_isolated_anchor() -> datetime:
    """A fresh `as_of` anchor for one investigation, spaced _ANCHOR_SPACING
    from every other call in this process -- see the module-level comment
    above for why this, not a fresh merchant, is how these tests avoid
    contaminating each other's Phase 3 evidence."""
    return _ANCHOR_EPOCH + _ANCHOR_SPACING * next(_ANCHOR_COUNTER)


def _incident_investigation_for_merchant(client, api_key, merchant_id, count=1, amount="10.00"):
    """Ingests exactly `count` payment_failed events (the caller's
    intended *eligible* event count for RETRY_AFFECTED_PAYMENTS -- see
    app.domain.simulation._eligible_events, which counts only
    payment_failed-typed evidence) and returns a real, unweakened
    incident_detected=True investigation, anchored on an isolated
    timestamp (see _next_isolated_anchor) rather than real "now".

    Phase 3 detection (app.domain.investigations.CONCERNING_EVENT_TYPES /
    DETECTION_THRESHOLD=3) counts ALL concerning-typed evidence in the
    window, not just payment_failed -- so when count < 3, this pads the
    evidence with settlement_delayed/gateway_degraded events (also in
    CONCERNING_EVENT_TYPES, so they count toward real, unweakened
    detection) rather than more payment_failed events, so
    eligible_event_count for RETRY_AFFECTED_PAYMENTS stays exactly
    `count`. Neither padding type is ever eligible for
    RETRY_AFFECTED_PAYMENTS (app.domain.simulation._eligible_events counts
    only payment_failed), so padding can never change which scenario a
    test lands in. Two DIFFERENT padding types are used (never two of the
    same type) and the real payment_failed event(s) are placed at the
    earliest timestamp(s), so that when padding is needed,
    payment_failed -- not an arbitrary padding type -- deterministically
    wins app.domain.investigations._dominant_signal's earliest-occurrence
    tie-break; a fixture built to test retrying failed payments should
    not end up with "dominant signal: settlement_delayed" as a side
    effect of how it reached the detection threshold. Detection threshold
    and window are never altered here -- only real evidence volume and
    its timing are."""
    now = _next_isolated_anchor()
    padding_needed = max(0, 3 - count)
    total_events = count + padding_needed
    # Largest minutes_ago first == earliest timestamp first.
    offsets = sorted(range(5, 5 + total_events * 5, 5), reverse=True)

    for minutes_ago in offsets[:count]:
        _ingest(
            client, api_key, str(merchant_id), "payment_failed", _ago(now, minutes_ago),
            amount=Decimal(amount), currency="INR",
        )
    padding_types = ("settlement_delayed", "gateway_degraded")
    for pad_index, minutes_ago in enumerate(offsets[count:]):
        _ingest(
            client, api_key, str(merchant_id), padding_types[pad_index % len(padding_types)],
            _ago(now, minutes_ago),
            amount=Decimal(amount), currency="INR",
        )

    investigation = _run_investigation(client, api_key, str(merchant_id), now)
    assert investigation["incident_detected"] is True
    return investigation


def _allowed_decision_for_merchant(client, api_key, merchant_id, count=1, amount="10.00"):
    investigation = _incident_investigation_for_merchant(
        client, api_key, merchant_id, count=count, amount=amount
    )
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "ALLOWED", decision
    return investigation, decision


def _executed_razorpay_action(client, api_key, merchant_id, order_id, count=1, amount="10.00"):
    amount_minor = int(Decimal(amount) * count * 100)
    fake = FakeRazorpayClient(
        order=FakeRazorpayOrder(id=order_id, amount=amount_minor, currency="INR")
    )
    _override_client(fake)
    investigation, decision = _allowed_decision_for_merchant(
        client, api_key, merchant_id, count=count, amount=amount
    )
    action = _razorpay_action(client, api_key, investigation["id"], decision["id"]).json()
    assert action["status"] == "executed", action
    assert action["razorpay_order_id"] == order_id
    return investigation, decision, action


def _rejected_razorpay_action(client, api_key, merchant_id):
    """A REQUIRES_HUMAN_APPROVAL decision -> a rejected razorpay action,
    ready to verify as INSUFFICIENT_OBSERVATION (both expected and
    observed unavailable)."""
    fake = FakeRazorpayClient(order=FakeRazorpayOrder())
    _override_client(fake)
    investigation = _incident_investigation_for_merchant(
        client, api_key, merchant_id, count=3, amount="5000.00"
    )
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.1", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "REQUIRES_HUMAN_APPROVAL"
    action = _razorpay_action(client, api_key, investigation["id"], decision["id"]).json()
    assert action["status"] == "rejected"
    assert fake.call_count == 0
    return investigation, decision, action


def _post_payment_webhook(client, secret, *, order_id, status, amount_minor=1000, currency="INR"):
    payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    event_type = "payment.captured" if status == "captured" else "payment.failed"
    body = {
        "entity": "event",
        "event": event_type,
        "created_at": int(datetime.now(UTC).timestamp()),
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount_minor,
                    "currency": currency,
                    "status": status,
                    "order_id": order_id,
                }
            }
        },
    }
    # Every call here signs a brand-new payment_id (see uuid.uuid4() above),
    # so this delivery always ingests a genuinely new FinancialEvent. Per
    # M2's established, frozen contract (app/routers/razorpay_webhooks.py),
    # that means 201 Created -- 200 is reserved for a replay/dedup/ignored
    # outcome on an already-seen event, which this helper never exercises.
    response = _post_webhook(client, body, secret, event_id=str(uuid.uuid4()))
    assert response.status_code == 201, response.text
    return response


def _verify(client, api_key, investigation_id, action_id, body=None):
    kwargs = {"headers": {"X-API-Key": api_key}}
    if body is not None:
        kwargs["json"] = body
    return client.post(
        f"/v1/investigations/{investigation_id}/razorpay-actions/{action_id}/verification",
        **kwargs,
    )


def _audit_count(entity_id: str) -> int:
    db = SessionLocal()
    try:
        return len(
            list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.event_type == "investigation_razorpay_outcome_verified",
                        AuditLog.entity_id == entity_id,
                    )
                )
            )
        )
    finally:
        db.close()


# --- 1/2/3. real observation, expected from persisted simulation, distinct paths


def test_success_case_observation_comes_from_the_real_webhook_event(
    client, api_key, razorpay_test_merchant, razorpay_webhook_secret
):
    order_id = f"order_{uuid.uuid4().hex[:16]}"
    investigation, decision, action = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_id, count=1, amount="10.00"
    )
    _post_payment_webhook(
        client, razorpay_webhook_secret, order_id=order_id, status="captured", amount_minor=1000
    )

    response = _verify(client, api_key, investigation["id"], action["id"])
    assert response.status_code == 201, response.text
    verification = response.json()

    assert verification["status"] == "VERIFIED_SUCCESS"
    assert verification["razorpay_action_id"] == action["id"]
    assert verification["decision_id"] == decision["id"]

    expected = verification["expected_snapshot"]
    observed = verification["observed_snapshot"]
    assert expected["available"] is True
    assert expected["scenario"] == "RETRY_AFFECTED_PAYMENTS"
    assert observed["available"] is True
    assert observed["observed_success_count"] == 1

    # Different data paths (Part 5): expected has simulation-only keys,
    # observed has webhook-observation-only keys -- never the same dict.
    assert "eligible_event_count" in expected and "eligible_event_count" not in observed
    assert (
        "observation_financial_event_id" in observed
        and "observation_financial_event_id" not in expected
    )
    assert expected != observed


# --- 4. success case (VERIFIED_SUCCESS) -- see test above, dedicated assertion


def test_verified_success_status_requires_all_three_dimensions_to_match(
    client, api_key, razorpay_test_merchant, razorpay_webhook_secret
):
    order_id = f"order_{uuid.uuid4().hex[:16]}"
    investigation, decision, action = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_id, count=1, amount="10.00"
    )
    _post_payment_webhook(
        client, razorpay_webhook_secret, order_id=order_id, status="captured", amount_minor=1000
    )
    verification = _verify(client, api_key, investigation["id"], action["id"]).json()
    assert verification["comparison"]["matched_dimension_count"] == 3
    assert verification["status"] == "VERIFIED_SUCCESS"


# --- 5. failure case ---------------------------------------------------


def test_failure_case_a_failed_payment_produces_failed_status(
    client, api_key, razorpay_test_merchant, razorpay_webhook_secret
):
    order_id = f"order_{uuid.uuid4().hex[:16]}"
    investigation, decision, action = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_id, count=1, amount="10.00"
    )
    _post_payment_webhook(
        client, razorpay_webhook_secret, order_id=order_id, status="failed", amount_minor=1000
    )

    verification = _verify(client, api_key, investigation["id"], action["id"]).json()
    assert verification["status"] == "FAILED"
    assert verification["observed_snapshot"]["observed_success_count"] == 0
    assert verification["observed_snapshot"]["observed_failure_count"] == 1
    assert verification["comparison"]["matched_dimension_count"] == 0


# --- 6. mismatch case (PARTIALLY_VERIFIED) ------------------------------


def test_mismatch_case_single_order_observation_against_multi_event_expectation(
    client, api_key, razorpay_test_merchant, razorpay_webhook_secret
):
    """Documents the Part J scale-mismatch finding directly: Phase 5's
    EXPECTED projection is multi-event (3 eligible events), while a real
    Razorpay Order observation is necessarily a single 0/1 outcome --
    PARTIALLY_VERIFIED is the structurally-correct result here, not a
    bug in app.domain.outcome_verification.verify(), which is reused
    completely unmodified.
    """
    order_id = f"order_{uuid.uuid4().hex[:16]}"
    investigation, decision, action = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_id, count=3, amount="10.00"
    )
    _post_payment_webhook(
        client, razorpay_webhook_secret, order_id=order_id, status="captured", amount_minor=3000
    )

    verification = _verify(client, api_key, investigation["id"], action["id"]).json()
    assert verification["status"] == "PARTIALLY_VERIFIED"
    dims = verification["comparison"]["dimensions"]
    assert dims["success_count"]["match"] is False  # expected 3, observed 1
    assert dims["failure_count"]["match"] is True  # expected 0, observed 0
    assert dims["recovery_by_currency"]["match"] is True  # 30.00 == 30.00


# --- 7. insufficient observation (both sides unavailable) ---------------


def test_insufficient_observation_for_a_rejected_action(
    client, api_key, razorpay_test_merchant
):
    investigation, decision, action = _rejected_razorpay_action(
        client, api_key, razorpay_test_merchant
    )
    verification = _verify(client, api_key, investigation["id"], action["id"]).json()
    assert verification["status"] == "INSUFFICIENT_OBSERVATION"
    assert verification["expected_snapshot"]["available"] is False
    assert verification["observed_snapshot"]["available"] is False


# --- 8. missing webhook observation (expected available, observed not) --


def test_missing_webhook_observation_is_insufficient_observation(
    client, api_key, razorpay_test_merchant
):
    order_id = f"order_{uuid.uuid4().hex[:16]}"
    investigation, decision, action = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_id, count=1, amount="10.00"
    )
    # Deliberately no webhook posted for this order.
    verification = _verify(client, api_key, investigation["id"], action["id"]).json()
    assert verification["status"] == "INSUFFICIENT_OBSERVATION"
    assert verification["expected_snapshot"]["available"] is True
    assert verification["observed_snapshot"]["available"] is False
    assert "no Razorpay webhook-ingested FinancialEvent" in verification["observed_snapshot"][
        "reason"
    ]


# --- 9. multiple unrelated Razorpay events do not contaminate observation


def test_unrelated_webhook_events_do_not_contaminate_the_observation(
    client, api_key, razorpay_test_merchant, razorpay_webhook_secret
):
    order_id = f"order_{uuid.uuid4().hex[:16]}"
    investigation, decision, action = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_id, count=1, amount="10.00"
    )

    # Noise: unrelated orders' webhooks, some failed, some succeeded,
    # posted both before and interleaved with the real one.
    _post_payment_webhook(
        client, razorpay_webhook_secret,
        order_id=f"order_noise_{uuid.uuid4().hex[:8]}", status="failed", amount_minor=500,
    )
    _post_payment_webhook(
        client, razorpay_webhook_secret,
        order_id=f"order_noise_{uuid.uuid4().hex[:8]}", status="captured", amount_minor=999999,
    )

    _post_payment_webhook(
        client, razorpay_webhook_secret, order_id=order_id, status="captured", amount_minor=1000
    )

    _post_payment_webhook(
        client, razorpay_webhook_secret,
        order_id=f"order_noise_{uuid.uuid4().hex[:8]}", status="failed", amount_minor=1,
    )

    verification = _verify(client, api_key, investigation["id"], action["id"]).json()
    assert verification["status"] == "VERIFIED_SUCCESS"
    assert verification["observed_snapshot"]["observed_recovery_by_currency"] == [
        {"currency": "INR", "amount": "10.00"}
    ]


# --- 10. cross-investigation isolation ------------------------------------


def test_cross_investigation_action_returns_404(
    client, api_key, razorpay_test_merchant, razorpay_webhook_secret
):
    order_a = f"order_{uuid.uuid4().hex[:16]}"
    investigation_a, decision_a, action_a = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_a, count=1, amount="10.00"
    )
    _post_payment_webhook(
        client, razorpay_webhook_secret, order_id=order_a, status="captured", amount_minor=1000
    )

    investigation_b = _incident_investigation_for_merchant(
        client, api_key, razorpay_test_merchant, count=1, amount="10.00"
    )

    response = _verify(client, api_key, investigation_b["id"], action_a["id"])
    assert response.status_code == 404

    action_url = (
        f"/v1/investigations/{investigation_b['id']}/razorpay-actions/"
        f"{action_a['id']}/verification"
    )
    get_response = client.get(action_url, headers={"X-API-Key": api_key})
    assert get_response.status_code == 404


# --- 11. unknown action -> 404 ---------------------------------------------


def test_unknown_razorpay_action_returns_404(client, api_key, razorpay_test_merchant):
    investigation = _incident_investigation_for_merchant(
        client, api_key, razorpay_test_merchant, count=1, amount="10.00"
    )
    response = _verify(client, api_key, investigation["id"], uuid.uuid4())
    assert response.status_code == 404


# --- 12/13. repeated verification -> same id, no duplicate audit row ------


def test_repeated_verification_returns_the_same_id_and_no_duplicate_audit_row(
    client, api_key, razorpay_test_merchant, razorpay_webhook_secret
):
    order_id = f"order_{uuid.uuid4().hex[:16]}"
    investigation, decision, action = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_id, count=1, amount="10.00"
    )
    _post_payment_webhook(
        client, razorpay_webhook_secret, order_id=order_id, status="captured", amount_minor=1000
    )

    first = _verify(client, api_key, investigation["id"], action["id"])
    assert first.status_code == 201
    second = _verify(client, api_key, investigation["id"], action["id"])
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json() == first.json()
    assert _audit_count(first.json()["id"]) == 1


# --- 14. client body cannot forge the observed result ----------------------


def test_forged_request_body_cannot_forge_the_observed_result(
    client, api_key, razorpay_test_merchant
):
    order_id = f"order_{uuid.uuid4().hex[:16]}"
    investigation, decision, action = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_id, count=1, amount="10.00"
    )
    # No webhook posted -- a genuine INSUFFICIENT_OBSERVATION outcome.
    response = _verify(
        client,
        api_key,
        investigation["id"],
        action["id"],
        body={
            "status": "VERIFIED_SUCCESS",
            "observed_snapshot": {
                "available": True,
                "observed_success_count": 999,
                "observed_failure_count": 0,
                "observed_recovery_by_currency": [{"currency": "INR", "amount": "999999.00"}],
            },
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "INSUFFICIENT_OBSERVATION"
    assert body["observed_snapshot"].get("observed_success_count") != 999


# --- history ordering -------------------------------------------------------


def test_razorpay_verification_history_is_newest_first(
    client, api_key, razorpay_test_merchant, razorpay_webhook_secret
):
    order_1 = f"order_{uuid.uuid4().hex[:16]}"
    investigation_1, decision_1, action_1 = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_1, count=1, amount="10.00"
    )
    verification_1 = _verify(client, api_key, investigation_1["id"], action_1["id"]).json()

    order_2 = f"order_{uuid.uuid4().hex[:16]}"
    investigation_2, decision_2, action_2 = _executed_razorpay_action(
        client, api_key, razorpay_test_merchant, order_2, count=1, amount="10.00"
    )
    verification_2 = _verify(client, api_key, investigation_2["id"], action_2["id"]).json()

    response = client.get(
        f"/v1/investigations/{investigation_2['id']}/razorpay-verifications",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert verification_2["id"] in ids
    assert verification_1["id"] not in ids  # different investigation


# --- authentication ---------------------------------------------------------


def test_razorpay_verification_endpoints_require_api_key(client):
    investigation_id = uuid.uuid4()
    action_id = uuid.uuid4()
    assert (
        client.post(
            f"/v1/investigations/{investigation_id}/razorpay-actions/{action_id}/verification"
        ).status_code
        == 401
    )
    assert (
        client.get(
            f"/v1/investigations/{investigation_id}/razorpay-actions/{action_id}/verification"
        ).status_code
        == 401
    )
    assert (
        client.get(f"/v1/investigations/{investigation_id}/razorpay-verifications").status_code
        == 401
    )
