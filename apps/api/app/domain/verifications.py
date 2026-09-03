"""Phase 8 outcome verification orchestration: LOAD -> DERIVE -> COMPARE
-> persisted VERIFICATION.

This module is the only place that touches the database for Phase 8 -- it
loads a single, already-persisted Phase 7 action (never "the
investigation's latest action" -- see
app.models.investigation_outcome_verification module docstring), walks the
existing chain action -> decision -> preferred simulation exactly as
app.domain.actions already established for action -> decision, builds the
EXPECTED snapshot from that simulation's own persisted result and the
OBSERVED snapshot from the action's own persisted sandbox_result (both via
the pure builders in app.domain.outcome_verification -- this module never
computes a financial number itself), calls the pure verifier, and persists
exactly one InvestigationOutcomeVerification row per action.

This module never re-runs Phase 5's simulator or Phase 7's sandbox
executor, and never re-evaluates Phase 6 policy -- it only reads what they
already persisted. There is no second verification engine anywhere else;
app.domain.outcome_verification.verify() is the sole comparison authority.

Idempotency: `action_id` is UNIQUE on investigation_outcome_verifications
(see the 0008 migration). This module always SELECTs for an existing row
first and returns it unchanged if found before doing any comparison work
at all -- the exact same discipline app.domain.actions already applies to
decision_id. A concurrent duplicate insert is caught as an IntegrityError
and resolved by re-reading the row the other request created, never by
raising it to the caller or attempting a second comparison.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import actions as action_domain
from app.domain import decisions as decision_domain
from app.domain import outcome_verification
from app.models.audit_log import AuditLog
from app.models.investigation_action import InvestigationAction
from app.models.investigation_outcome_verification import InvestigationOutcomeVerification
from app.models.investigation_simulation import InvestigationSimulation


class ActionNotFoundError(Exception):
    """Raised when the action does not exist, or does not belong to the
    given investigation_id -- both are "not found" at the API boundary,
    the same treatment app.domain.actions.DecisionNotFoundError already
    applies for a missing/mismatched decision.
    """


def _existing_verification(
    db: Session, *, action_id: uuid.UUID
) -> InvestigationOutcomeVerification | None:
    return db.scalars(
        select(InvestigationOutcomeVerification).where(
            InvestigationOutcomeVerification.action_id == action_id
        )
    ).first()


def _persist(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    action_id: uuid.UUID,
    decision_id: uuid.UUID | None,
    simulation_id: uuid.UUID | None,
    expected_snapshot: dict,
    observed_snapshot: dict,
    comparison: dict,
) -> tuple[InvestigationOutcomeVerification, bool]:
    """Insert a new InvestigationOutcomeVerification row, or -- if a
    concurrent request for the same action_id won the UNIQUE(action_id)
    race -- roll back and return the row that request created instead.
    Returns (verification, created). Mirrors app.domain.actions._persist
    exactly.
    """
    evidence = {
        "action_id": str(action_id),
        "decision_id": str(decision_id) if decision_id else None,
        "simulation_id": str(simulation_id) if simulation_id else None,
        "executor_version": observed_snapshot.get("executor_version"),
        "observation_version": outcome_verification.VERIFIER_VERSION,
        "sandbox_observation_model_version": observed_snapshot.get("observation_model_version"),
    }
    verification = InvestigationOutcomeVerification(
        investigation_id=investigation_id,
        action_id=action_id,
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
        # Another request for the same action_id committed first --
        # UNIQUE(action_id) fired. Not an error: roll back this attempt
        # and return the winner's row (see module docstring).
        db.rollback()
        winner = _existing_verification(db, action_id=action_id)
        assert winner is not None  # the constraint violation guarantees this
        return winner, False

    # Outcome shape only -- never the full expected/observed snapshots --
    # the same restraint every other Phase 1-7 _persist() already applies.
    db.add(
        AuditLog(
            event_type="investigation_outcome_verified",
            entity_type="investigation_outcome_verification",
            entity_id=str(verification.id),
            actor="system",
            payload={
                "investigation_id": str(investigation_id),
                "action_id": str(action_id),
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


def run_verification(
    db: Session, *, investigation_id: uuid.UUID, action_id: uuid.UUID
) -> tuple[InvestigationOutcomeVerification, bool]:
    """Verify (or persist a deterministic INSUFFICIENT_OBSERVATION for)
    the outcome of `action_id`. Returns (verification, created) -- created
    is False for both an idempotent replay and the losing side of a
    concurrent insert race (see _persist).

    Raises ActionNotFoundError for an action that does not exist or does
    not belong to `investigation_id` (404 at the API boundary -- see
    app.routers.investigations). Never raises for a rejected action or an
    action whose chain cannot be fully re-verified -- those are persisted
    status="INSUFFICIENT_OBSERVATION" rows, the same "never raise for a
    legitimate business outcome" discipline every earlier phase's domain
    module already applies.
    """
    action = action_domain.get_action(db, investigation_id=investigation_id, action_id=action_id)
    if action is None:
        raise ActionNotFoundError(action_id)

    existing = _existing_verification(db, action_id=action_id)
    if existing is not None:
        return existing, False

    expected_snapshot, simulation_id = _load_expected_snapshot(db, action=action)
    observed_snapshot = outcome_verification.derive_observed_snapshot(
        action_id=str(action.id), sandbox_result=action.sandbox_result, action_status=action.status
    )
    if observed_snapshot.get("available"):
        observed_snapshot = {**observed_snapshot, "executor_version": action.executor_version}

    comparison = outcome_verification.verify(expected=expected_snapshot, observed=observed_snapshot)

    return _persist(
        db,
        investigation_id=investigation_id,
        action_id=action.id,
        decision_id=action.decision_id,
        simulation_id=simulation_id,
        expected_snapshot=expected_snapshot,
        observed_snapshot=observed_snapshot,
        comparison=comparison,
    )


def _load_expected_snapshot(
    db: Session, *, action: InvestigationAction
) -> tuple[dict, uuid.UUID | None]:
    """Re-derive the EXPECTED snapshot from the action's own persisted
    decision -> preferred simulation chain, re-verifying each hop rather
    than trusting the action's own stored fields blindly -- the same
    defense-in-depth discipline app.domain.actions._authorize_and_execute
    already applies when it re-verifies a decision's preferred simulation
    before executing. A rejected action (or any hop that fails to
    re-verify) yields an unavailable expected snapshot rather than a
    guess; the caller derives INSUFFICIENT_OBSERVATION from that.
    """
    if action.status != "executed":
        return (
            {
                "available": False,
                "reason": f"action status is '{action.status}', not 'executed' -- "
                "there is no completed sandbox action to establish an expected outcome for",
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


def get_verification_for_action(
    db: Session, *, investigation_id: uuid.UUID, action_id: uuid.UUID
) -> InvestigationOutcomeVerification | None:
    """The single verification for `action_id`, scoped to
    `investigation_id` -- a verification belonging to a different
    investigation is treated as not found, never returned. Mirrors
    app.domain.actions.get_action_for_decision exactly.
    """
    verification = _existing_verification(db, action_id=action_id)
    if verification is None or verification.investigation_id != investigation_id:
        return None
    return verification


def list_verifications(
    db: Session, *, investigation_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> tuple[list[InvestigationOutcomeVerification], int]:
    """Append-only outcome-verification history for one investigation,
    across every action it has ever verified, newest first. Mirrors
    app.domain.actions.list_actions exactly.
    """
    stmt = select(InvestigationOutcomeVerification).where(
        InvestigationOutcomeVerification.investigation_id == investigation_id
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = (
        stmt.order_by(InvestigationOutcomeVerification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt))
    return items, total
