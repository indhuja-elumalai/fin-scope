"""Phase 10, Milestone 3 (Part 5/6) real Razorpay TEST outcome
verification orchestration: LOAD -> LOCATE REAL OBSERVATION -> COMPARE ->
persisted RAZORPAY VERIFICATION.

This module is the only place that touches the database for Milestone
3's verification step. It never imports app.domain.reasoning or
app.providers.reasoning (verified by static inspection; see the
Milestone 3 verification report), never makes a network call, and never
uses randomness or the current time in its comparison logic -- the same
purity discipline app.domain.verifications already establishes for Phase
8, extended here to a REAL external observation instead of a sandbox one.

EXPECTED vs OBSERVED, and why OBSERVED here is fundamentally different
from Phase 8's:
  - EXPECTED is loaded exactly the way app.domain.verifications loads it
    for Phase 8 -- re-derived from the razorpay action's own persisted
    decision -> preferred simulation chain, via the SAME pure
    app.domain.outcome_verification.derive_expected_snapshot(), reused
    unmodified (Part 6: no second expected-snapshot builder).
  - OBSERVED is NEVER derived from Phase 5's simulation result, Phase 7's
    sandbox_result, LLM output, a client-submitted value, or a copy of
    EXPECTED. It originates ONLY from a real, already-persisted
    FinancialEvent row that Milestone 2's webhook ingestion pipeline
    (app.domain.razorpay_webhooks) wrote from an actually-verified
    Razorpay webhook delivery. If no such FinancialEvent has been
    ingested yet for this action's Order, OBSERVED is
    {"available": False, "reason": ...} -- never fabricated, never
    guessed, never backfilled from EXPECTED.

REAL OBSERVATION LINKAGE (Part 5's "smallest additive mechanism"):
InvestigationRazorpayAction.razorpay_order_id is a Razorpay ORDER id
(order_xxx). app.domain.razorpay_webhooks.map_webhook_payload deliberately
sets FinancialEvent.external_reference to the Razorpay PAYMENT id
(pay_xxx) for all three supported webhook event types when a payment
entity is present -- so there is no direct external_reference join key
from an order id to the FinancialEvent(s) it produced. Redesigning
FinancialEvent (a new order_id column, a new index) was ruled out per the
Milestone 3 spec's explicit "prefer linking through existing M2 records,
do NOT redesign FinancialEvent" instruction. Instead, this module reads
the SAME raw webhook envelope Milestone 2 already stores verbatim on
FinancialEvent.payload (see map_webhook_payload's `payload=body`) and
inspects it for the order id FIN-SCOPE already has evidence of:
  - payment.failed / payment.captured envelopes carry
    payload.payment.entity.order_id
  - order.paid envelopes carry payload.order.entity.id directly
No migration, no new column, no change to app.models.financial_event or
app.models.razorpay_webhook_event was required or made. This is a
targeted, in-Python scan over one merchant's razorpay_webhook-sourced
FinancialEvent rows (see _find_observation_event) -- acceptable at this
milestone's scale (one investigation's worth of TEST activity); it is
explicitly NOT a proposal for how this should scale to production webhook
volume, which would warrant an indexed column and is out of scope here.

If more than one FinancialEvent's payload references the same Order
(e.g. a failed payment attempt followed by a later successful one against
the same Order -- Razorpay allows multiple payment attempts per Order),
the MOST RECENT one by `ingested_at` is used as the observation. This is a
documented, deliberate MVP simplification (most-recent-wins), not a
"first success wins" or "any success wins" policy -- flagged explicitly in
the Milestone 3 report as a known limitation, not a hidden assumption.

SCALE MISMATCH (also flagged in the Milestone 3 report, Part J): Phase 5's
EXPECTED projection is typically MULTI-event (it projects an outcome
across every eligible event in the investigation's evidence window), while
a real Razorpay TEST Order observation is necessarily a SINGLE 0/1 outcome
(one Order, one terminal payment result). PARTIALLY_VERIFIED or FAILED is
therefore the realistic, structurally-correct outcome for most real
Milestone 3 scenarios -- not a bug in this module or in
app.domain.outcome_verification.verify(), which is reused completely
unmodified (Part 6).

Idempotency: `razorpay_action_id` is UNIQUE on
investigation_razorpay_verifications (see the 0011 migration). This
module always SELECTs for an existing row first and returns it unchanged
if found, before doing any comparison or observation-lookup work at all --
the exact same discipline app.domain.verifications already applies to
action_id. A concurrent duplicate insert is caught as an IntegrityError
and resolved by re-reading the row the other request created.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import decisions as decision_domain
from app.domain import outcome_verification
from app.domain import razorpay_action as razorpay_action_domain
from app.domain.razorpay_webhooks import WEBHOOK_SOURCE
from app.models.audit_log import AuditLog
from app.models.financial_event import FinancialEvent
from app.models.investigation import Investigation
from app.models.investigation_razorpay_action import InvestigationRazorpayAction
from app.models.investigation_razorpay_verification import InvestigationRazorpayVerification
from app.models.investigation_simulation import InvestigationSimulation

OBSERVATION_MODEL_VERSION = "1"

# The exact, and only, event types app.domain.razorpay_webhooks ever maps
# a real webhook into (see that module's _EVENT_TYPE_MAP) -- reused here,
# never redefined, so this module's notion of "success"/"failure" can
# never silently drift from Milestone 2's own mapping.
_SUCCESS_EVENT_TYPE = "payment_succeeded"
_FAILURE_EVENT_TYPE = "payment_failed"


class RazorpayActionNotFoundError(Exception):
    """Raised when the razorpay action does not exist, or does not belong
    to the given investigation_id -- mirrors
    app.domain.verifications.ActionNotFoundError exactly."""


def _existing_verification(
    db: Session, *, razorpay_action_id: uuid.UUID
) -> InvestigationRazorpayVerification | None:
    return db.scalars(
        select(InvestigationRazorpayVerification).where(
            InvestigationRazorpayVerification.razorpay_action_id == razorpay_action_id
        )
    ).first()


def _extract_order_id(payload: dict) -> str | None:
    """Pure. Reads the same raw webhook envelope shape
    app.domain.razorpay_webhooks.map_webhook_payload already parses (see
    that module's _entity helper) -- never invents a field Milestone 2
    does not already rely on. Returns None (never raises) for any shape
    it does not recognize."""
    if not isinstance(payload, dict):
        return None
    payload_section = payload.get("payload")
    if not isinstance(payload_section, dict):
        return None

    payment_section = payload_section.get("payment")
    if isinstance(payment_section, dict):
        payment_entity = payment_section.get("entity")
        if isinstance(payment_entity, dict):
            order_id = payment_entity.get("order_id")
            if isinstance(order_id, str) and order_id:
                return order_id

    order_section = payload_section.get("order")
    if isinstance(order_section, dict):
        order_entity = order_section.get("entity")
        if isinstance(order_entity, dict):
            order_id = order_entity.get("id")
            if isinstance(order_id, str) and order_id:
                return order_id

    return None


def _find_observation_event(
    db: Session, *, merchant_id: uuid.UUID, razorpay_order_id: str
) -> FinancialEvent | None:
    """Scan this merchant's razorpay-webhook-sourced FinancialEvent rows,
    most-recent-ingested first, for one whose raw webhook envelope
    references `razorpay_order_id` -- see module docstring for exactly
    why this scan (rather than a direct join key) is the smallest
    additive linkage mechanism available without redesigning
    FinancialEvent, and why most-recent-wins is the documented tie-break
    when more than one matches."""
    stmt = (
        select(FinancialEvent)
        .where(
            FinancialEvent.merchant_id == merchant_id,
            FinancialEvent.source == WEBHOOK_SOURCE,
        )
        .order_by(FinancialEvent.ingested_at.desc())
    )
    for event in db.scalars(stmt):
        if _extract_order_id(event.payload) == razorpay_order_id:
            return event
    return None


def _derive_observed_snapshot(event: FinancialEvent) -> dict:
    """Build the OBSERVED snapshot from exactly one already-persisted,
    already-webhook-verified FinancialEvent -- never from Phase 5/7/LLM
    output (see module docstring). Matches the exact contract
    app.domain.outcome_verification.verify() reads
    (observed_success_count / observed_failure_count /
    observed_recovery_by_currency), the same shape
    app.domain.outcome_verification.derive_observed_snapshot already
    produces for Phase 7, so the SAME pure comparator applies unmodified.
    """
    if event.event_type == _SUCCESS_EVENT_TYPE:
        observed_success_count = 1
        observed_failure_count = 0
    elif event.event_type == _FAILURE_EVENT_TYPE:
        observed_success_count = 0
        observed_failure_count = 1
    else:
        # Defensive only: app.domain.razorpay_webhooks never writes any
        # other event_type for source == WEBHOOK_SOURCE (see
        # _EVENT_TYPE_MAP and its own assert), but this module does not
        # trust that blindly either -- it refuses to guess rather than
        # silently miscounting an unrecognized outcome.
        return {
            "available": False,
            "reason": (
                "the matched webhook-ingested FinancialEvent has an unrecognized "
                f"event_type {event.event_type!r} -- refusing to guess an observed outcome"
            ),
        }

    observed_recovery_by_currency: list[dict[str, str]] = []
    if event.currency and event.amount is not None:
        observed_amount = event.amount if observed_success_count else Decimal("0.00")
        observed_recovery_by_currency = [
            {"currency": event.currency, "amount": str(observed_amount)}
        ]

    return {
        "available": True,
        "observed_success_count": observed_success_count,
        "observed_failure_count": observed_failure_count,
        "observed_recovery_by_currency": observed_recovery_by_currency,
        "observation_model_version": OBSERVATION_MODEL_VERSION,
        "observation_financial_event_id": str(event.id),
        "observation_source": event.source,
        "observation_event_type": event.event_type,
    }


def _load_expected_snapshot(
    db: Session, *, action: InvestigationRazorpayAction
) -> tuple[dict, uuid.UUID | None]:
    """Re-derive the EXPECTED snapshot from the razorpay action's own
    persisted decision -> preferred simulation chain, re-verifying each
    hop rather than trusting the action's own stored fields blindly --
    mirrors app.domain.verifications._load_expected_snapshot exactly,
    substituting InvestigationRazorpayAction for InvestigationAction."""
    if action.status != razorpay_action_domain.EXECUTED:
        return (
            {
                "available": False,
                "reason": (
                    f"razorpay action status is '{action.status}', not 'executed' -- there is "
                    "no completed real Razorpay TEST action to establish an expected outcome for"
                ),
            },
            None,
        )

    decision = decision_domain.get_decision(
        db, investigation_id=action.investigation_id, decision_id=action.decision_id
    )
    if decision is None:
        return (
            {
                "available": False,
                "reason": "the action's authorizing decision could not be re-verified",
            },
            None,
        )

    if action.simulation_id is None:
        return (
            {
                "available": False,
                "reason": "the action has no preferred_simulation_id to verify against",
            },
            None,
        )

    simulation = db.get(InvestigationSimulation, action.simulation_id)
    if (
        simulation is None
        or simulation.investigation_id != action.investigation_id
        or simulation.status != "completed"
    ):
        return (
            {
                "available": False,
                "reason": "the action's originating simulation could not be re-verified as a "
                "completed simulation belonging to this investigation",
            },
            action.simulation_id,
        )

    if action.scenario is None:
        return (
            {
                "available": False,
                "reason": "the action has no recorded scenario to verify against",
            },
            simulation.id,
        )

    snapshot = outcome_verification.derive_expected_snapshot(
        simulation_result=simulation.result,
        scenario=action.scenario,
        simulator_version=simulation.simulator_version,
    )
    return snapshot, simulation.id


def _persist(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    razorpay_action_id: uuid.UUID,
    decision_id: uuid.UUID | None,
    simulation_id: uuid.UUID | None,
    razorpay_order_id: str | None,
    expected_snapshot: dict,
    observed_snapshot: dict,
    comparison: dict,
) -> tuple[InvestigationRazorpayVerification, bool]:
    """Insert a new InvestigationRazorpayVerification row, or -- if a
    concurrent request for the same razorpay_action_id won the
    UNIQUE(razorpay_action_id) race -- roll back and return the row that
    request created instead. Mirrors app.domain.verifications._persist
    exactly."""
    evidence = {
        "razorpay_action_id": str(razorpay_action_id),
        "decision_id": str(decision_id) if decision_id else None,
        "simulation_id": str(simulation_id) if simulation_id else None,
        "razorpay_order_id": razorpay_order_id,
        "observation_financial_event_id": observed_snapshot.get("observation_financial_event_id"),
        "executor_version": razorpay_action_domain.EXECUTOR_VERSION,
        "observation_version": outcome_verification.VERIFIER_VERSION,
        "observation_model_version": observed_snapshot.get("observation_model_version"),
    }
    verification = InvestigationRazorpayVerification(
        investigation_id=investigation_id,
        razorpay_action_id=razorpay_action_id,
        decision_id=decision_id,
        simulation_id=simulation_id,
        status=comparison["status"],
        verifier_version=comparison["verifier_version"],
        expected_snapshot=expected_snapshot,
        observed_snapshot=observed_snapshot,
        comparison=comparison,
        evidence=evidence,
    )
    db.add(verification)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = _existing_verification(db, razorpay_action_id=razorpay_action_id)
        assert winner is not None  # the constraint violation guarantees this
        return winner, False

    db.add(
        AuditLog(
            event_type="investigation_razorpay_outcome_verified",
            entity_type="investigation_razorpay_verification",
            entity_id=str(verification.id),
            actor="system",
            payload={
                "investigation_id": str(investigation_id),
                "razorpay_action_id": str(razorpay_action_id),
                "decision_id": str(decision_id) if decision_id else None,
                "verification_id": str(verification.id),
                "status": comparison["status"],
                "verifier_version": comparison["verifier_version"],
            },
        )
    )
    db.commit()
    db.refresh(verification)
    return verification, True


def run_razorpay_verification(
    db: Session, *, investigation_id: uuid.UUID, razorpay_action_id: uuid.UUID
) -> tuple[InvestigationRazorpayVerification, bool]:
    """Verify (or persist a deterministic INSUFFICIENT_OBSERVATION for)
    the REAL outcome of `razorpay_action_id`. Returns
    (verification, created) -- created is False for both an idempotent
    replay and the losing side of a concurrent insert race (see
    _persist).

    Raises RazorpayActionNotFoundError for an action that does not exist
    or does not belong to `investigation_id` (404 at the API boundary).
    Never raises for a rejected/pending action, or one with no matching
    webhook observation yet -- those are persisted
    status="INSUFFICIENT_OBSERVATION" rows, the same "never raise for a
    legitimate business/timing outcome" discipline
    app.domain.verifications already applies.
    """
    action = razorpay_action_domain.get_action(
        db, investigation_id=investigation_id, action_id=razorpay_action_id
    )
    if action is None:
        raise RazorpayActionNotFoundError(razorpay_action_id)

    existing = _existing_verification(db, razorpay_action_id=razorpay_action_id)
    if existing is not None:
        return existing, False

    expected_snapshot, simulation_id = _load_expected_snapshot(db, action=action)

    if action.status != razorpay_action_domain.EXECUTED or not action.razorpay_order_id:
        observed_snapshot = {
            "available": False,
            "reason": (
                f"razorpay action status is '{action.status}' -- there is no real Razorpay "
                "Order to observe an outcome for"
            ),
        }
    else:
        investigation = db.get(Investigation, investigation_id)
        if investigation is None:
            # Defensive only -- unreachable via the router, which already
            # 404s before this function is ever called, but this module
            # never trusts that blindly either.
            observed_snapshot = {
                "available": False,
                "reason": "the action's investigation could not be re-verified",
            }
        else:
            event = _find_observation_event(
                db,
                merchant_id=investigation.merchant_id,
                razorpay_order_id=action.razorpay_order_id,
            )
            if event is None:
                observed_snapshot = {
                    "available": False,
                    "reason": (
                        "no Razorpay webhook-ingested FinancialEvent has been observed yet for "
                        f"Order {action.razorpay_order_id} -- the real webhook delivery has not "
                        "arrived (or has not been ingested) yet"
                    ),
                }
            else:
                observed_snapshot = _derive_observed_snapshot(event)

    comparison = outcome_verification.verify(expected=expected_snapshot, observed=observed_snapshot)

    return _persist(
        db,
        investigation_id=investigation_id,
        razorpay_action_id=action.id,
        decision_id=action.decision_id,
        simulation_id=simulation_id,
        razorpay_order_id=action.razorpay_order_id,
        expected_snapshot=expected_snapshot,
        observed_snapshot=observed_snapshot,
        comparison=comparison,
    )


def get_verification_for_action(
    db: Session, *, investigation_id: uuid.UUID, razorpay_action_id: uuid.UUID
) -> InvestigationRazorpayVerification | None:
    """The single verification for `razorpay_action_id`, scoped to
    `investigation_id` -- a verification belonging to a different
    investigation is treated as not found, never returned. Mirrors
    app.domain.verifications.get_verification_for_action exactly."""
    verification = _existing_verification(db, razorpay_action_id=razorpay_action_id)
    if verification is None or verification.investigation_id != investigation_id:
        return None
    return verification


def list_verifications(
    db: Session, *, investigation_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> tuple[list[InvestigationRazorpayVerification], int]:
    """Append-only razorpay-outcome-verification history for one
    investigation, across every razorpay action it has ever verified,
    newest first. Mirrors app.domain.verifications.list_verifications
    exactly."""
    stmt = select(InvestigationRazorpayVerification).where(
        InvestigationRazorpayVerification.investigation_id == investigation_id
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = (
        stmt.order_by(InvestigationRazorpayVerification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt))
    return items, total
