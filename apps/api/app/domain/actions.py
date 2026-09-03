"""Bounded sandbox action orchestration: AUTHORIZATION -> SANDBOX EXECUTION
-> persisted ACTION.

This module is the only place that touches the database for Phase 7 -- it
loads a single, already-persisted Phase 6 decision (never "the
investigation's latest decision" -- see
app.models.investigation_action module docstring for why decision_id is
the deliberate authorization anchor for this MVP), re-derives whether a
sandbox action may run entirely from that decision's own persisted fields,
calls the pure app.domain.sandbox_executor when (and only when)
authorization passes, and persists exactly one InvestigationAction row per
decision.

Phase 6 remains the sole authorization source: this module never
re-evaluates policy, never applies a different threshold or config, and
never consults anything other than the single persisted
decision.policy_decision value app.domain.policy already computed. There
is no second policy engine here, and none of this module's checks can ever
turn a REQUIRES_HUMAN_APPROVAL or BLOCKED decision into an executed
action -- only ALLOWED can.

Idempotency: `decision_id` is UNIQUE on investigation_actions (see the
0007 migration). This module always SELECTs for an existing row first and
returns it unchanged if found -- including a previously "rejected" row --
before doing any authorization work at all. A concurrent duplicate insert
is caught as an IntegrityError and resolved by re-reading the row the
other request created, never by raising it to the caller or attempting a
second execution.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import decisions as decision_domain
from app.domain import sandbox_executor
from app.domain.simulation import SCENARIOS
from app.models.audit_log import AuditLog
from app.models.investigation_action import InvestigationAction
from app.models.investigation_decision import InvestigationDecision
from app.models.investigation_simulation import InvestigationSimulation

EXECUTED = "executed"
REJECTED = "rejected"


class DecisionNotFoundError(Exception):
    """Raised when the decision does not exist, or does not belong to the
    given investigation_id -- both are "not found" at the API boundary,
    the same treatment app.domain.decisions.get_decision already applies.
    """


def _existing_action(db: Session, *, decision_id: uuid.UUID) -> InvestigationAction | None:
    return db.scalars(
        select(InvestigationAction).where(InvestigationAction.decision_id == decision_id)
    ).first()


def _persist(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    decision_id: uuid.UUID,
    status: str,
    rejection_reason: str | None,
    scenario: str | None,
    simulation_id: uuid.UUID | None,
    policy_decision_snapshot: str | None,
    sandbox_result: dict,
) -> tuple[InvestigationAction, bool]:
    """Insert a new InvestigationAction row, or -- if a concurrent request
    for the same decision_id won the UNIQUE(decision_id) race -- roll back
    and return the row that request created instead. Returns
    (action, created).
    """
    action = InvestigationAction(
        investigation_id=investigation_id,
        decision_id=decision_id,
        status=status,
        rejection_reason=rejection_reason,
        scenario=scenario,
        simulation_id=simulation_id,
        policy_decision_snapshot=policy_decision_snapshot,
        executor_version=sandbox_executor.EXECUTOR_VERSION,
        sandbox_result=sandbox_result,
    )
    db.add(action)
    try:
        db.flush()
    except IntegrityError:
        # Another request for the same decision_id committed first --
        # UNIQUE(decision_id) fired. Not an error: roll back this attempt
        # and return the winner's row, the same outcome as if this
        # request had simply arrived second (see module docstring).
        db.rollback()
        winner = _existing_action(db, decision_id=decision_id)
        assert winner is not None  # the constraint violation guarantees this
        return winner, False

    # Outcome shape only -- never the full sandbox_result -- the same
    # restraint every other Phase 1-6 _persist() already applies.
    db.add(
        AuditLog(
            event_type="investigation_action_completed",
            entity_type="investigation_action",
            entity_id=str(action.id),
            actor="system",
            payload={
                "investigation_id": str(investigation_id),
                "decision_id": str(decision_id),
                "status": status,
                "scenario": scenario,
                "policy_decision_snapshot": policy_decision_snapshot,
            },
        )
    )
    db.commit()
    db.refresh(action)
    return action, True


def run_action(
    db: Session, *, investigation_id: uuid.UUID, decision_id: uuid.UUID
) -> tuple[InvestigationAction, bool]:
    """Authorize (or reject) and, if authorized, execute a bounded sandbox
    action for `decision_id`. Returns (action, created) -- created is False
    for both an idempotent replay and the losing side of a concurrent
    insert race (see _persist).

    Raises DecisionNotFoundError for a decision that does not exist or
    does not belong to `investigation_id` (404 at the API boundary -- see
    app.routers.investigations, which checks investigation existence
    separately before calling this function). Never raises for an
    authorization failure -- that is a persisted status="rejected" row,
    the same "never raise for a legitimate business outcome" discipline
    app.domain.decisions.run_decision and
    app.domain.simulation.run_simulation already apply.
    """
    decision = decision_domain.get_decision(
        db, investigation_id=investigation_id, decision_id=decision_id
    )
    if decision is None:
        raise DecisionNotFoundError(decision_id)

    existing = _existing_action(db, decision_id=decision_id)
    if existing is not None:
        return existing, False

    return _authorize_and_execute(db, investigation_id=investigation_id, decision=decision)


def _authorize_and_execute(
    db: Session, *, investigation_id: uuid.UUID, decision: InvestigationDecision
) -> tuple[InvestigationAction, bool]:
    # --- 1. decision status: only a completed decision has anything to authorize ---
    if decision.status != "completed":
        return _persist(
            db,
            investigation_id=investigation_id,
            decision_id=decision.id,
            status=REJECTED,
            rejection_reason=(
                f"decision status is '{decision.status}' -- there is no completed "
                "decision evaluation to authorize a sandbox action from"
            ),
            scenario=None,
            simulation_id=None,
            policy_decision_snapshot=decision.policy_decision,
            sandbox_result={},
        )

    # --- 2. policy decision: the sole authorization source (app.domain.policy) ---
    if decision.policy_decision != "ALLOWED":
        reasons = "; ".join(decision.policy_reasons or ["(none recorded)"])
        return _persist(
            db,
            investigation_id=investigation_id,
            decision_id=decision.id,
            status=REJECTED,
            rejection_reason=(
                f"policy_decision is '{decision.policy_decision}', not ALLOWED -- a "
                "sandbox action may only run for an autonomously-authorized decision. "
                f"Policy reasons: {reasons}"
            ),
            scenario=None,
            simulation_id=None,
            policy_decision_snapshot=decision.policy_decision,
            sandbox_result={},
        )

    # --- 3. defense-in-depth: re-verify the preferred scenario/simulation shape.
    # Should always hold for a status="completed" decision (see
    # app.domain.decisions.run_decision) -- this module does not trust that
    # blindly, the same "defense in depth" discipline app.domain.policy
    # applies to candidate.status.
    evaluation_result = decision.evaluation_result or {}
    scenario = evaluation_result.get("preferred_scenario")
    simulation_id_str = evaluation_result.get("preferred_simulation_id")

    if not scenario or scenario not in SCENARIOS:
        return _persist(
            db,
            investigation_id=investigation_id,
            decision_id=decision.id,
            status=REJECTED,
            rejection_reason=(
                "decision has no valid preferred_scenario to act on -- rejected "
                "defensively rather than trusted"
            ),
            scenario=None,
            simulation_id=None,
            policy_decision_snapshot=decision.policy_decision,
            sandbox_result={},
        )

    if not simulation_id_str:
        return _persist(
            db,
            investigation_id=investigation_id,
            decision_id=decision.id,
            status=REJECTED,
            rejection_reason=(
                "decision has no preferred_simulation_id to act on -- rejected "
                "defensively rather than trusted"
            ),
            scenario=scenario,
            simulation_id=None,
            policy_decision_snapshot=decision.policy_decision,
            sandbox_result={},
        )

    try:
        simulation_id = uuid.UUID(simulation_id_str)
    except (ValueError, AttributeError, TypeError):
        return _persist(
            db,
            investigation_id=investigation_id,
            decision_id=decision.id,
            status=REJECTED,
            rejection_reason=(
                "decision's preferred_simulation_id is not a valid identifier -- "
                "rejected defensively rather than trusted"
            ),
            scenario=scenario,
            simulation_id=None,
            policy_decision_snapshot=decision.policy_decision,
            sandbox_result={},
        )
    simulation = db.get(InvestigationSimulation, simulation_id)
    if (
        simulation is None
        or simulation.investigation_id != investigation_id
        or simulation.status != "completed"
    ):
        return _persist(
            db,
            investigation_id=investigation_id,
            decision_id=decision.id,
            status=REJECTED,
            rejection_reason=(
                "the decision's preferred simulation could not be re-verified as a "
                "completed simulation belonging to this investigation -- rejected "
                "defensively rather than trusted"
            ),
            scenario=scenario,
            simulation_id=simulation_id,
            policy_decision_snapshot=decision.policy_decision,
            sandbox_result={},
        )

    # --- 4. execute: reuse Phase 5's own persisted numbers verbatim, never
    # recomputed here (see app.domain.sandbox_executor module docstring) ---
    result = simulation.result
    sandbox_result = sandbox_executor.execute(
        scenario=scenario,
        eligible_event_ids=result.get("eligible_event_ids", []),
        eligible_event_count=result.get("eligible_event_count", 0),
        estimated_recovery_by_currency=result.get("estimated_recovery_by_currency", []),
    )

    return _persist(
        db,
        investigation_id=investigation_id,
        decision_id=decision.id,
        status=EXECUTED,
        rejection_reason=None,
        scenario=scenario,
        simulation_id=simulation_id,
        policy_decision_snapshot=decision.policy_decision,
        sandbox_result=sandbox_result,
    )


def get_action(
    db: Session, *, investigation_id: uuid.UUID, action_id: uuid.UUID
) -> InvestigationAction | None:
    """A single action by its own id, scoped to `investigation_id` -- an
    action belonging to a different investigation is treated as not found,
    never returned. Added for Phase 8 (outcome verification), which
    addresses an action directly by `action_id` rather than by the
    decision_id it is idempotent on -- see app.domain.verifications, which
    anchors a verification to exactly one persisted action the same way
    this module anchors an action to exactly one persisted decision.
    """
    action = db.get(InvestigationAction, action_id)
    if action is None or action.investigation_id != investigation_id:
        return None
    return action


def get_action_for_decision(
    db: Session, *, investigation_id: uuid.UUID, decision_id: uuid.UUID
) -> InvestigationAction | None:
    """The single action for `decision_id`, scoped to `investigation_id` --
    an action belonging to a different investigation is treated as not
    found, never returned. app.routers.investigations already scopes the
    parent decision via app.domain.decisions.get_decision before calling
    this function; the investigation_id check here is a second, defensive
    layer, not the only one.
    """
    action = _existing_action(db, decision_id=decision_id)
    if action is None or action.investigation_id != investigation_id:
        return None
    return action


def list_actions(
    db: Session, *, investigation_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> tuple[list[InvestigationAction], int]:
    """Append-only sandbox action history for one investigation, across
    every decision it has ever acted on, newest first.
    """
    stmt = select(InvestigationAction).where(
        InvestigationAction.investigation_id == investigation_id
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(InvestigationAction.created_at.desc()).limit(limit).offset(offset)
    items = list(db.scalars(stmt))
    return items, total
