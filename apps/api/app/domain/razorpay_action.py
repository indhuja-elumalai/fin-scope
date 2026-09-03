"""Real Razorpay TEST-mode bounded action orchestration -- Phase 10,
Milestone 3, Part 1/2/3/4.

This module is the only place that calls app.providers.razorpay.RazorpayClient
for real. It never imports or references app.domain.reasoning or
app.providers.reasoning in any way -- there is structurally no path from
Claude's output to this module (verified by static inspection; see the
Milestone 3 verification report). The client itself is passed in by the
caller (the router's get_razorpay_client() dependency, mirroring
app.routers.investigations.get_reasoning_provider()'s own injection
pattern) -- this module never constructs credentials itself.

Authorization is re-derived entirely from the single, immutable,
already-persisted InvestigationDecision named by decision_id -- the exact
same "no second policy engine, no trusting stored fields blindly"
discipline app.domain.actions._authorize_and_execute already applies for
Phase 7. Only decision.status == "completed" AND
decision.policy_decision == "ALLOWED" ever reach RazorpayClient.
BLOCKED and REQUIRES_HUMAN_APPROVAL are rejected before this module ever
imports/touches app.providers.razorpay's client at all.

SEMANTIC HONESTY (Phase 10 M3 critical rule): this module creates a NEW,
independent Razorpay TEST Order. It never claims to retry, resume, or
otherwise act on any specific existing (failed) payment -- Razorpay's
Orders API has no such mechanism. Every rejection_reason / audit payload /
persisted row produced here describes the outcome as "a bounded Razorpay
TEST payment artifact was created" (or was not), never as a retry.

IDEMPOTENCY AND THE UNAVOIDABLE FAILURE WINDOW (Part 4):
Because the external call here is REAL (even though TEST-mode), the
usual Phase 7 pattern -- insert speculatively, resolve an IntegrityError
by re-reading -- is NOT safe on its own: two concurrent requests could
both pass a "does a row exist yet" check, both proceed, and both call
Razorpay, creating two real Orders for one decision. This module instead:
  1. SELECTs for an existing row first (any status) -- a hit short-circuits
     immediately, no Razorpay call, regardless of the found row's status.
  2. If none exists, INSERTs a status="pending" row and COMMITS it BEFORE
     calling Razorpay at all. The database's UNIQUE(decision_id)
     constraint means only one concurrent request can ever win this
     insert; the loser's flush raises IntegrityError, rolls back, and
     re-reads the winner's (possibly still-pending) row -- it never calls
     Razorpay. This closes the concurrent-double-call failure mode
     completely.
  3. Only the single winner calls RazorpayClient.create_order(), then
     updates that same row to "executed" or "rejected" and commits again.

The one window this CANNOT close: if the process crashes after step 3's
Razorpay call genuinely succeeds but before the resulting UPDATE commits
locally, a real Razorpay TEST Order now exists that this database has no
record of (the row is stuck at "pending" forever). No local database
mechanism can undo or discover a real external side effect that already
happened -- this is a structural limitation of any exactly-once claim
over a real API call, not a bug in this module. Razorpay's own
receipt-based duplicate-request rejection (the `razorpay_receipt` value
persisted on this row, deterministically derived from decision_id) is the
second layer that would surface this specific situation on any future
retry attempt against the same decision, rather than silently creating a
second Order -- but reconciling a stuck "pending" row back to that
already-created real Order (e.g. via a receipt lookup) is explicitly NOT
built in this milestone; a row observed at rest in "pending" status is a
disclosed, visible signal for an operator to investigate, never
auto-resolved.
"""
from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal, InvalidOperation
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import decisions as decision_domain
from app.domain.simulation import SCENARIOS
from app.models.audit_log import AuditLog
from app.models.investigation_decision import InvestigationDecision
from app.models.investigation_razorpay_action import InvestigationRazorpayAction
from app.models.investigation_simulation import InvestigationSimulation
from app.providers.razorpay import RazorpayClientError

EXECUTOR_VERSION = "1"

PENDING = "pending"
EXECUTED = "executed"
REJECTED = "rejected"

# Razorpay's own documented Orders API minimum -- verified during Phase 10
# planning: currency subunits must be > 100 (e.g. INR paise). Enforced
# here as a defensive floor, not because this module invents the rule;
# a genuine Razorpay-side rejection is still handled safely via
# RazorpayClientError regardless.
_MINIMUM_AMOUNT_MINOR_UNITS = 100

# Razorpay's own documented receipt field limit (verified during Phase 10
# planning): max 40 characters. "fs-" + 32 hex chars = 35, safely under.
_RECEIPT_PREFIX = "fs-"


class RazorpayOrderProtocol(Protocol):
    id: str
    status: str
    amount: int
    currency: str
    receipt: str | None
    amount_paid: int
    amount_due: int


class RazorpayClientProtocol(Protocol):
    """The only surface this module depends on -- see
    app.providers.razorpay.RazorpayClient, which satisfies this
    structurally. Tests inject a fake satisfying this same shape, never
    a mock of unrelated RazorpayClient internals."""

    def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: dict[str, str] | None = None
    ) -> RazorpayOrderProtocol: ...


class DecisionNotFoundError(Exception):
    """Raised when the decision does not exist, or does not belong to the
    given investigation_id -- mirrors app.domain.actions.DecisionNotFoundError
    exactly."""


def _existing_action(db: Session, *, decision_id: uuid.UUID) -> InvestigationRazorpayAction | None:
    return db.scalars(
        select(InvestigationRazorpayAction).where(
            InvestigationRazorpayAction.decision_id == decision_id
        )
    ).first()


def _derive_receipt(decision_id: uuid.UUID) -> str:
    digest = hashlib.sha256(str(decision_id).encode("utf-8")).hexdigest()[:32]
    return f"{_RECEIPT_PREFIX}{digest}"


def _derive_amount_and_currency(simulation_result: dict) -> tuple[int, str] | tuple[None, str]:
    """Derive the ONE (amount_in_minor_units, currency) pair for the new
    Order entirely from the simulation's own already-computed
    estimated_recovery_by_currency -- never independently recalculated,
    never client-supplied (mirrors app.domain.sandbox_executor's
    verbatim-copy discipline). Returns (None, reason) rather than
    guessing when the data is empty, multi-currency (ambiguous -- a
    Razorpay Order is single-currency), non-positive, or below Razorpay's
    documented minimum.
    """
    entries = simulation_result.get("estimated_recovery_by_currency")
    if not isinstance(entries, list) or not entries:
        return None, (
            "simulation has no estimated_recovery_by_currency to derive an Order amount from"
        )

    parsed: dict[str, Decimal] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        currency = entry.get("currency")
        try:
            amount = Decimal(str(entry.get("amount")))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if isinstance(currency, str) and currency and amount > 0:
            parsed[currency] = amount

    if not parsed:
        return None, "simulation's estimated_recovery_by_currency has no positive amount"
    if len(parsed) > 1:
        return None, (
            "simulation's estimated_recovery_by_currency spans multiple currencies "
            f"({sorted(parsed)}) -- a single Razorpay Order cannot represent more than one "
            "currency, and this module never guesses which one"
        )

    (currency, amount), = parsed.items()
    amount_minor = int((amount * 100).to_integral_value())
    if amount_minor < _MINIMUM_AMOUNT_MINOR_UNITS:
        return None, (
            f"derived amount ({amount_minor} minor units {currency}) is below Razorpay's "
            f"documented minimum ({_MINIMUM_AMOUNT_MINOR_UNITS})"
        )
    return amount_minor, currency


def _persist_rejected(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    decision: InvestigationDecision,
    rejection_reason: str,
    scenario: str | None,
    simulation_id: uuid.UUID | None,
) -> tuple[InvestigationRazorpayAction, bool]:
    """Single-insert rejection -- used for every rejection branch that
    never attempts a Razorpay call at all (decision not completed, not
    ALLOWED, invalid scenario/simulation, no derivable amount, or no
    configured client). No 'pending' phase is needed here because
    RazorpayClient is never invoked."""
    action = InvestigationRazorpayAction(
        investigation_id=investigation_id,
        decision_id=decision.id,
        status=REJECTED,
        rejection_reason=rejection_reason[:500],
        scenario=scenario,
        simulation_id=simulation_id,
        policy_decision_snapshot=decision.policy_decision,
        executor_version=EXECUTOR_VERSION,
        raw_response={},
    )
    db.add(action)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = _existing_action(db, decision_id=decision.id)
        assert winner is not None
        return winner, False

    db.add(
        AuditLog(
            event_type="investigation_razorpay_action_completed",
            entity_type="investigation_razorpay_action",
            entity_id=str(action.id),
            actor="system",
            payload={
                "investigation_id": str(investigation_id),
                "decision_id": str(decision.id),
                "status": REJECTED,
                "scenario": scenario,
            },
        )
    )
    db.commit()
    db.refresh(action)
    return action, True


def run_razorpay_action(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    decision_id: uuid.UUID,
    client: RazorpayClientProtocol | None,
) -> tuple[InvestigationRazorpayAction, bool]:
    """Authorize (or reject) and, if authorized AND a client is
    configured, create a real (TEST-mode) Razorpay Order for
    `decision_id`. Returns (action, created).

    Raises DecisionNotFoundError for a decision that does not exist or
    does not belong to investigation_id. Never raises for an
    authorization failure -- that is always a persisted status="rejected"
    row, the same discipline app.domain.actions.run_action already
    applies.
    """
    decision = decision_domain.get_decision(
        db, investigation_id=investigation_id, decision_id=decision_id
    )
    if decision is None:
        raise DecisionNotFoundError(decision_id)

    existing = _existing_action(db, decision_id=decision_id)
    if existing is not None:
        return existing, False

    # --- 1. decision status ---
    if decision.status != "completed":
        return _persist_rejected(
            db,
            investigation_id=investigation_id,
            decision=decision,
            rejection_reason=(
                f"decision status is '{decision.status}' -- there is no completed decision "
                "evaluation to authorize a Razorpay TEST action from"
            ),
            scenario=None,
            simulation_id=None,
        )

    # --- 2. policy decision: the sole authorization source. BLOCKED and
    # REQUIRES_HUMAN_APPROVAL never reach RazorpayClient. ---
    if decision.policy_decision != "ALLOWED":
        reasons = "; ".join(decision.policy_reasons or ["(none recorded)"])
        return _persist_rejected(
            db,
            investigation_id=investigation_id,
            decision=decision,
            rejection_reason=(
                f"policy_decision is '{decision.policy_decision}', not ALLOWED -- a real "
                f"Razorpay TEST action may only run for an autonomously-authorized decision. "
                f"Policy reasons: {reasons}"
            ),
            scenario=None,
            simulation_id=None,
        )

    # --- 3. defense-in-depth: re-verify preferred scenario/simulation,
    # mirroring app.domain.actions._authorize_and_execute step 3 exactly. ---
    evaluation_result = decision.evaluation_result or {}
    scenario = evaluation_result.get("preferred_scenario")
    simulation_id_str = evaluation_result.get("preferred_simulation_id")

    if not scenario or scenario not in SCENARIOS:
        return _persist_rejected(
            db,
            investigation_id=investigation_id,
            decision=decision,
            rejection_reason=(
                "decision has no valid preferred_scenario to act on -- rejected defensively "
                "rather than trusted"
            ),
            scenario=None,
            simulation_id=None,
        )
    if not simulation_id_str:
        return _persist_rejected(
            db,
            investigation_id=investigation_id,
            decision=decision,
            rejection_reason=(
                "decision has no preferred_simulation_id to act on -- rejected defensively "
                "rather than trusted"
            ),
            scenario=scenario,
            simulation_id=None,
        )
    try:
        simulation_id = uuid.UUID(simulation_id_str)
    except (ValueError, AttributeError, TypeError):
        return _persist_rejected(
            db,
            investigation_id=investigation_id,
            decision=decision,
            rejection_reason=(
                "decision's preferred_simulation_id is not a valid identifier -- rejected "
                "defensively rather than trusted"
            ),
            scenario=scenario,
            simulation_id=None,
        )
    simulation = db.get(InvestigationSimulation, simulation_id)
    if (
        simulation is None
        or simulation.investigation_id != investigation_id
        or simulation.status != "completed"
    ):
        return _persist_rejected(
            db,
            investigation_id=investigation_id,
            decision=decision,
            rejection_reason=(
                "the decision's preferred simulation could not be re-verified as a completed "
                "simulation belonging to this investigation -- rejected defensively rather "
                "than trusted"
            ),
            scenario=scenario,
            simulation_id=simulation_id,
        )

    # --- 4. derive amount/currency from the simulation's own numbers --
    # never client-supplied, never independently recalculated. ---
    amount_minor, amount_or_reason = _derive_amount_and_currency(simulation.result or {})
    if amount_minor is None:
        return _persist_rejected(
            db,
            investigation_id=investigation_id,
            decision=decision,
            rejection_reason=amount_or_reason,
            scenario=scenario,
            simulation_id=simulation_id,
        )
    currency = amount_or_reason

    # --- 5. a real client must be configured -- never silently skipped. ---
    if client is None:
        return _persist_rejected(
            db,
            investigation_id=investigation_id,
            decision=decision,
            rejection_reason=(
                "no Razorpay TEST client is configured -- RAZORPAY_KEY_ID/KEY_SECRET/"
                "TEST_MODE_CONFIRMED must all be set before a real Razorpay TEST action "
                "can be authorized"
            ),
            scenario=scenario,
            simulation_id=simulation_id,
        )

    # --- 6. INSERT + COMMIT a "pending" row BEFORE calling Razorpay --
    # see module docstring for exactly why this ordering, and the one
    # failure window it does not close. ---
    receipt = _derive_receipt(decision.id)
    pending = InvestigationRazorpayAction(
        investigation_id=investigation_id,
        decision_id=decision.id,
        status=PENDING,
        scenario=scenario,
        simulation_id=simulation_id,
        policy_decision_snapshot=decision.policy_decision,
        executor_version=EXECUTOR_VERSION,
        razorpay_receipt=receipt,
        raw_response={},
    )
    db.add(pending)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = _existing_action(db, decision_id=decision.id)
        assert winner is not None
        return winner, False
    db.commit()
    db.refresh(pending)

    # --- 7. the real, external call. Only the single winner of step 6
    # ever reaches this line for a given decision_id. ---
    try:
        order = client.create_order(
            amount=amount_minor,
            currency=currency,
            receipt=receipt,
            notes={"investigation_id": str(investigation_id), "decision_id": str(decision.id)},
        )
    except RazorpayClientError as exc:
        pending.status = REJECTED
        # RazorpayClientError's own message is already sanitized -- see
        # app.providers.razorpay -- never raw upstream text.
        pending.rejection_reason = str(exc)[:500]
        db.add(
            AuditLog(
                event_type="investigation_razorpay_action_completed",
                entity_type="investigation_razorpay_action",
                entity_id=str(pending.id),
                actor="system",
                payload={
                    "investigation_id": str(investigation_id),
                    "decision_id": str(decision.id),
                    "status": REJECTED,
                    "scenario": scenario,
                },
            )
        )
        db.commit()
        db.refresh(pending)
        return pending, True

    pending.status = EXECUTED
    pending.razorpay_order_id = order.id
    # Minimal, explicitly-allowlisted fields only -- never order.raw, and
    # never anything credential/header-shaped (Orders API responses never
    # carry those, but this module does not trust that blindly either).
    pending.raw_response = {
        "id": order.id,
        "status": order.status,
        "amount": order.amount,
        "currency": order.currency,
        "receipt": order.receipt,
        "amount_paid": order.amount_paid,
        "amount_due": order.amount_due,
    }
    db.add(
        AuditLog(
            event_type="investigation_razorpay_action_completed",
            entity_type="investigation_razorpay_action",
            entity_id=str(pending.id),
            actor="system",
            payload={
                "investigation_id": str(investigation_id),
                "decision_id": str(decision.id),
                "status": EXECUTED,
                "scenario": scenario,
                "razorpay_order_id": order.id,
            },
        )
    )
    db.commit()
    db.refresh(pending)
    return pending, True


def get_action(
    db: Session, *, investigation_id: uuid.UUID, action_id: uuid.UUID
) -> InvestigationRazorpayAction | None:
    action = db.get(InvestigationRazorpayAction, action_id)
    if action is None or action.investigation_id != investigation_id:
        return None
    return action


def get_action_for_decision(
    db: Session, *, investigation_id: uuid.UUID, decision_id: uuid.UUID
) -> InvestigationRazorpayAction | None:
    action = _existing_action(db, decision_id=decision_id)
    if action is None or action.investigation_id != investigation_id:
        return None
    return action


def list_actions(
    db: Session, *, investigation_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> tuple[list[InvestigationRazorpayAction], int]:
    stmt = select(InvestigationRazorpayAction).where(
        InvestigationRazorpayAction.investigation_id == investigation_id
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = (
        stmt.order_by(InvestigationRazorpayAction.created_at.desc()).limit(limit).offset(offset)
    )
    items = list(db.scalars(stmt))
    return items, total
