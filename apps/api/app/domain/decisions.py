"""Decision orchestration: EVALUATION -> POLICY -> persisted DECISION.

This module is the only place that touches the database for Phase 6 -- it
loads an investigation's own persisted simulations, reduces each to a
CandidateInput (app.domain.decision_evaluation.build_candidate), calls the
two pure domain functions in order, and persists exactly one outcome as a
new InvestigationDecision row.

Decision evaluation and policy answer two different questions and this
module keeps them structurally separate (see app.domain.decision_evaluation
and app.domain.policy module docstrings):
  - evaluate_candidates() answers "which candidate is preferable" and
    NEVER authorizes anything.
  - evaluate_policy() answers "are we allowed to choose that candidate"
    and NEVER re-ranks or substitutes a different candidate -- a BLOCKED
    preferred candidate is persisted as BLOCKED, never silently swapped
    for a runner-up. Phase 6 ends here; nothing in this module executes a
    financial action.

`status` (on the persisted row) is deliberately independent of
`policy_decision`: status says whether the Phase 6 pipeline itself
produced a decision at all (completed / insufficient_evidence /
no_eligible_scenario); policy_decision says what it concluded (ALLOWED /
REQUIRES_HUMAN_APPROVAL / BLOCKED). A BLOCKED policy outcome is still
status="completed" -- Phase 6 did its job correctly by blocking it.

Candidate discovery (Phase 6 MVP -- no client override): the LATEST
status="completed" simulation per distinct scenario for this investigation,
auto-discovered from app.models.investigation_simulation. A client cannot
name which simulations to compare, and the decision-creation endpoint (see
app.routers.investigations) accepts no request body at all.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.decision_evaluation import (
    EVALUATION_VERSION,
    CandidateInput,
    build_candidate,
    evaluate_candidates,
)
from app.domain.policy import DEFAULT_POLICY_CONFIG, evaluate_policy
from app.models.audit_log import AuditLog
from app.models.investigation import Investigation
from app.models.investigation_decision import InvestigationDecision
from app.models.investigation_simulation import InvestigationSimulation


class InvestigationNotFoundError(Exception):
    """Raised when a decision is requested for an investigation that does not exist."""


def _latest_completed_candidates(
    db: Session, investigation_id: uuid.UUID
) -> list[InvestigationSimulation]:
    """The latest status="completed" simulation row per distinct scenario
    for this investigation. Ordered newest-first -- the same ordering
    app.domain.simulation.list_simulations already uses -- so the first
    row seen per scenario in this loop is that scenario's latest.
    """
    stmt = (
        select(InvestigationSimulation)
        .where(
            InvestigationSimulation.investigation_id == investigation_id,
            InvestigationSimulation.status == "completed",
        )
        .order_by(InvestigationSimulation.created_at.desc())
    )
    latest_by_scenario: dict[str, InvestigationSimulation] = {}
    for row in db.scalars(stmt):
        latest_by_scenario.setdefault(row.scenario, row)
    return list(latest_by_scenario.values())


def _persist(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    status: str,
    evaluation_version: str,
    policy_version: str | None,
    candidate_simulation_ids: list[uuid.UUID],
    evaluation_result: dict,
    policy_decision: str | None,
    policy_reasons: list[str],
    input_snapshot: dict,
    failure_reason: str | None,
) -> InvestigationDecision:
    decision = InvestigationDecision(
        investigation_id=investigation_id,
        status=status,
        evaluation_version=evaluation_version,
        policy_version=policy_version,
        candidate_simulation_ids=[str(i) for i in candidate_simulation_ids],
        evaluation_result=evaluation_result,
        policy_decision=policy_decision,
        policy_reasons=policy_reasons,
        input_snapshot=input_snapshot,
        failure_reason=failure_reason,
    )
    db.add(decision)
    db.flush()

    # Outcome shape only -- never the full evaluation/candidate detail --
    # the same restraint investigation_reasoning_completed and
    # investigation_simulation_completed already apply. actor="system":
    # Phase 6 itself is fully deterministic even when an earlier reasoning
    # result was AI-generated (see module docstring) -- it never becomes
    # "ai" just because upstream data was AI-influenced.
    db.add(
        AuditLog(
            event_type="investigation_decision_completed",
            entity_type="investigation_decision",
            entity_id=str(decision.id),
            actor="system",
            payload={
                "investigation_id": str(investigation_id),
                "status": status,
                "policy_decision": policy_decision,
            },
        )
    )
    db.commit()
    db.refresh(decision)
    return decision


def run_decision(db: Session, *, investigation_id: uuid.UUID) -> InvestigationDecision:
    """Run EVALUATION -> POLICY over an investigation's own persisted
    simulations and persist the (always-persisted) result. Every call
    inserts a NEW row -- see app.models.investigation_decision.

    Raises InvestigationNotFoundError if the investigation does not exist.
    Never raises for "nothing to decide" -- that is a persisted status
    (insufficient_evidence / no_eligible_scenario), mirroring
    app.domain.reasoning.run_reasoning and
    app.domain.simulation.run_simulation's own short-circuit pattern.
    """
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise InvestigationNotFoundError(investigation_id)

    input_snapshot = {
        "merchant_id": str(investigation.merchant_id),
        "incident_detected": investigation.incident_detected,
    }

    if not investigation.incident_detected:
        return _persist(
            db,
            investigation_id=investigation_id,
            status="insufficient_evidence",
            evaluation_version=EVALUATION_VERSION,
            policy_version=None,
            candidate_simulation_ids=[],
            evaluation_result={},
            policy_decision=None,
            policy_reasons=[],
            input_snapshot=input_snapshot,
            failure_reason=(
                "no incident was detected for this investigation -- there is nothing to "
                "evaluate a decision over yet"
            ),
        )

    rows = _latest_completed_candidates(db, investigation_id)
    if not rows:
        return _persist(
            db,
            investigation_id=investigation_id,
            status="no_eligible_scenario",
            evaluation_version=EVALUATION_VERSION,
            policy_version=None,
            candidate_simulation_ids=[],
            evaluation_result={},
            policy_decision=None,
            policy_reasons=[],
            input_snapshot=input_snapshot,
            failure_reason=(
                "no completed simulation exists yet for this investigation -- run at "
                "least one scenario simulation before evaluating a decision"
            ),
        )

    candidates: list[CandidateInput] = [
        build_candidate(
            simulation_id=row.id, scenario=row.scenario, status=row.status, result=row.result
        )
        for row in rows
    ]
    evaluation = evaluate_candidates(candidates)
    # rows is non-empty (checked above), and evaluate_candidates always
    # picks a preferred candidate whenever it is given at least one.
    assert evaluation.preferred is not None

    policy_result = evaluate_policy(evaluation.preferred, DEFAULT_POLICY_CONFIG)

    evaluation_result = {
        "candidates": [
            {
                "simulation_id": str(c.simulation_id),
                "scenario": c.scenario,
                "failed_event_count_delta": c.failed_event_count_delta,
                "estimated_recovery_by_currency": [
                    {"currency": currency, "amount": str(amount)}
                    for currency, amount in sorted(c.estimated_recovery_by_currency.items())
                ],
                "projected_exposure_by_currency": [
                    {"currency": currency, "amount": str(amount)}
                    for currency, amount in sorted(c.projected_exposure_by_currency.items())
                ],
                "projected_exposure_amount_unknown_count": (
                    c.projected_exposure_amount_unknown_count
                ),
                "eligible_event_count": c.eligible_event_count,
            }
            for c in evaluation.candidates
        ],
        "preferred_scenario": evaluation.preferred.scenario,
        "preferred_simulation_id": str(evaluation.preferred.simulation_id),
        "reason": evaluation.reason,
    }

    return _persist(
        db,
        investigation_id=investigation_id,
        status="completed",
        evaluation_version=EVALUATION_VERSION,
        policy_version=policy_result.policy_version,
        candidate_simulation_ids=[c.simulation_id for c in evaluation.candidates],
        evaluation_result=evaluation_result,
        policy_decision=policy_result.decision,
        policy_reasons=policy_result.reasons,
        input_snapshot=input_snapshot,
        failure_reason=None,
    )


def list_decisions(
    db: Session, *, investigation_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> tuple[list[InvestigationDecision], int]:
    """Append-only decision history for one investigation, newest first."""
    stmt = select(InvestigationDecision).where(
        InvestigationDecision.investigation_id == investigation_id
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(InvestigationDecision.created_at.desc()).limit(limit).offset(offset)
    items = list(db.scalars(stmt))
    return items, total


def get_decision(
    db: Session, *, investigation_id: uuid.UUID, decision_id: uuid.UUID
) -> InvestigationDecision | None:
    """A single decision, scoped to `investigation_id` -- a decision
    belonging to a different investigation is treated as not found, never
    returned (see app.routers.investigations).
    """
    decision = db.get(InvestigationDecision, decision_id)
    if decision is None or decision.investigation_id != investigation_id:
        return None
    return decision
