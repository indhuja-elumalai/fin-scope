"""Incident investigation API: FIND -> DOMINANT SIGNAL -> IMPACT, on demand,
plus reasoning over an existing investigation's evidence.

Reasoning is a dedicated sub-resource (`POST/GET /{id}/reason(ing)`) rather
than a parameter on investigation creation: an investigation is a
deterministic, standalone fact the moment it is created (Phase 3), while
reasoning about it is a separate, optional, independently-repeatable act
that must never block or corrupt the underlying investigation if it fails.
Keeping them as separate routes/tables makes that failure isolation
structural, not just a runtime check.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.config import get_settings
from app.db import get_db
from app.domain import actions as action_domain
from app.domain import decisions as decision_domain
from app.domain import investigations as investigation_domain
from app.domain import reasoning as reasoning_domain
from app.domain import simulation as simulation_domain
from app.domain import verifications as verification_domain
from app.providers.reasoning import HostedReasoningProvider, ReasoningProvider
from app.schemas.action import ActionListResponse, ActionRead
from app.schemas.decision import DecisionListResponse, DecisionRead
from app.schemas.investigation import (
    InvestigationCreate,
    InvestigationListResponse,
    InvestigationRead,
)
from app.schemas.reasoning import InvestigationReasoningRead
from app.schemas.simulation import SimulationCreate, SimulationListResponse, SimulationRead
from app.schemas.verification import VerificationListResponse, VerificationRead

router = APIRouter(
    prefix="/v1/investigations",
    tags=["investigations"],
    dependencies=[Depends(require_api_key)],
)


def get_reasoning_provider() -> ReasoningProvider | None:
    """The configured reasoning provider, or None if unconfigured.

    A FastAPI dependency specifically so tests can override it with a fake
    provider via `app.dependency_overrides` -- no test in this codebase
    exercises the real hosted reasoning API (no test should ever spend real
    provider credits or depend on network access). Returning None (rather
    than constructing HostedReasoningProvider with an empty key) is what
    lets app.domain.reasoning.run_reasoning short-circuit to
    status="unavailable" without attempting a doomed HTTP call.

    Model and timeout are read from Settings (Phase 9:
    ANTHROPIC_MODEL / ANTHROPIC_TIMEOUT_SECONDS, both optional with
    defaults -- see app.config.Settings) and passed through explicitly
    rather than relying on HostedReasoningProvider's own constructor
    defaults, so the configured values are always what a real request
    actually uses. ANTHROPIC_WORKSPACE_ID is also optional and, when
    unset, is passed through as None -- HostedReasoningProvider only sends
    the anthropic-workspace-id header when it is actually configured.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    return HostedReasoningProvider(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        timeout_seconds=settings.anthropic_timeout_seconds,
        workspace_id=settings.anthropic_workspace_id,
    )


@router.post("", response_model=InvestigationRead, status_code=status.HTTP_201_CREATED)
def create_investigation(
    payload: InvestigationCreate, db: Session = Depends(get_db)
) -> InvestigationRead:
    try:
        investigation = investigation_domain.run_investigation(
            db, merchant_id=payload.merchant_id, as_of=payload.as_of
        )
    except investigation_domain.MerchantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Merchant {exc} not found"
        ) from exc
    return InvestigationRead.model_validate(investigation)


@router.get("", response_model=InvestigationListResponse)
def list_investigations(
    merchant_id: uuid.UUID | None = None,
    incident_detected: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> InvestigationListResponse:
    items, total = investigation_domain.list_investigations(
        db,
        merchant_id=merchant_id,
        incident_detected=incident_detected,
        limit=limit,
        offset=offset,
    )
    return InvestigationListResponse(
        items=[InvestigationRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{investigation_id}", response_model=InvestigationRead)
def get_investigation(
    investigation_id: uuid.UUID, db: Session = Depends(get_db)
) -> InvestigationRead:
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    return InvestigationRead.model_validate(investigation)


@router.post(
    "/{investigation_id}/reason",
    response_model=InvestigationReasoningRead,
    status_code=status.HTTP_201_CREATED,
)
def reason_about_investigation(
    investigation_id: uuid.UUID,
    db: Session = Depends(get_db),
    provider: ReasoningProvider | None = Depends(get_reasoning_provider),
) -> InvestigationReasoningRead:
    """Run reasoning over an existing investigation's persisted evidence.

    Always returns 201 with a persisted result, even when reasoning did not
    produce hypotheses -- see InvestigationReasoningRead.status for why (the
    investigation itself is never affected by a reasoning failure). 404 only
    when the investigation itself does not exist.
    """
    try:
        reasoning = reasoning_domain.run_reasoning(
            db, investigation_id=investigation_id, provider=provider
        )
    except reasoning_domain.InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Investigation {exc} not found"
        ) from exc
    return InvestigationReasoningRead.model_validate(reasoning)


@router.get("/{investigation_id}/reasoning", response_model=InvestigationReasoningRead)
def get_latest_reasoning(
    investigation_id: uuid.UUID, db: Session = Depends(get_db)
) -> InvestigationReasoningRead:
    """The most recent reasoning result for this investigation.

    404 if the investigation does not exist, or if reasoning has never been
    run for it yet -- both are "not found", but for different resources
    (the distinction is in the detail message, not the status code).
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    reasoning = reasoning_domain.get_latest_reasoning(db, investigation_id)
    if reasoning is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reasoning has been run for this investigation yet",
        )
    return InvestigationReasoningRead.model_validate(reasoning)


@router.post(
    "/{investigation_id}/simulations",
    response_model=SimulationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_simulation(
    investigation_id: uuid.UUID,
    payload: SimulationCreate,
    db: Session = Depends(get_db),
) -> SimulationRead:
    """Run a deterministic consequence simulation for a scenario over an
    existing investigation's persisted evidence.

    Always returns 201 with a persisted result, even when there is nothing
    to simulate (status="insufficient_evidence") -- see
    app.domain.simulation.run_simulation. 404 only when the investigation
    itself does not exist. Never depends on Phase 4 reasoning being
    available.
    """
    override = None
    if payload.assumptions is not None:
        override = {
            key: value
            for key, value in (
                ("success_rate", payload.assumptions.success_rate),
                ("scope_fraction", payload.assumptions.scope_fraction),
            )
            if value is not None
        }
    try:
        simulation = simulation_domain.run_simulation(
            db,
            investigation_id=investigation_id,
            scenario=payload.scenario,
            assumptions_override=override,
        )
    except simulation_domain.InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Investigation {exc} not found"
        ) from exc
    except simulation_domain.UnsupportedScenarioError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported scenario: {exc}"
        ) from exc
    return SimulationRead.model_validate(simulation)


@router.get("/{investigation_id}/simulations", response_model=SimulationListResponse)
def list_simulations(
    investigation_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> SimulationListResponse:
    """Append-only simulation history for one investigation, newest first.
    404 if the investigation itself does not exist.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    items, total = simulation_domain.list_simulations(
        db, investigation_id=investigation_id, limit=limit, offset=offset
    )
    return SimulationListResponse(
        items=[SimulationRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{investigation_id}/simulations/{simulation_id}", response_model=SimulationRead
)
def get_simulation(
    investigation_id: uuid.UUID,
    simulation_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> SimulationRead:
    """A single simulation result. 404 if the investigation does not exist,
    or if `simulation_id` does not exist, or if it belongs to a different
    investigation -- app.domain.simulation.get_simulation treats the last
    case as not found, never returning another investigation's simulation.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    simulation = simulation_domain.get_simulation(
        db, investigation_id=investigation_id, simulation_id=simulation_id
    )
    if simulation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found"
        )
    return SimulationRead.model_validate(simulation)


@router.post(
    "/{investigation_id}/decisions",
    response_model=DecisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_decision(
    investigation_id: uuid.UUID, db: Session = Depends(get_db)
) -> DecisionRead:
    """Run Phase 6 EVALUATION -> POLICY over this investigation's own
    persisted simulations and persist the result.

    Takes no request body -- candidate simulations are always the latest
    status="completed" simulation per scenario, auto-discovered server-side
    (see app.domain.decisions). There is no field anywhere in this request
    a client could use to submit an evaluation result or a policy decision;
    both are always computed entirely server-side.

    Always returns 201 with a persisted result, even when there is nothing
    to decide (status="insufficient_evidence" or "no_eligible_scenario").
    404 only when the investigation itself does not exist.
    """
    try:
        decision = decision_domain.run_decision(db, investigation_id=investigation_id)
    except decision_domain.InvestigationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Investigation {exc} not found"
        ) from exc
    return DecisionRead.model_validate(decision)


@router.get("/{investigation_id}/decisions", response_model=DecisionListResponse)
def list_decisions(
    investigation_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> DecisionListResponse:
    """Append-only decision history for one investigation, newest first.
    404 if the investigation itself does not exist.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    items, total = decision_domain.list_decisions(
        db, investigation_id=investigation_id, limit=limit, offset=offset
    )
    return DecisionListResponse(
        items=[DecisionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{investigation_id}/decisions/{decision_id}", response_model=DecisionRead)
def get_decision(
    investigation_id: uuid.UUID,
    decision_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DecisionRead:
    """A single decision result. 404 if the investigation does not exist,
    or if `decision_id` does not exist, or if it belongs to a different
    investigation -- app.domain.decisions.get_decision treats the last
    case as not found, never returning another investigation's decision.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    decision = decision_domain.get_decision(
        db, investigation_id=investigation_id, decision_id=decision_id
    )
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")
    return DecisionRead.model_validate(decision)


@router.post(
    "/{investigation_id}/decisions/{decision_id}/actions",
    response_model=ActionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_action(
    investigation_id: uuid.UUID,
    decision_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
) -> ActionRead:
    """Authorize (or reject) and, if authorized, execute a bounded Phase 7
    sandbox action for a single persisted Phase 6 decision.

    Takes no request body -- the decision named by `decision_id` is the
    entire authorization context. There is no field anywhere in this
    request a client could use to submit a policy decision, a scenario, a
    simulation, or an authorization/approval; all of it is re-derived
    entirely server-side from the persisted decision (see
    app.domain.actions).

    `decision_id` is the idempotency anchor: at most one action row exists
    per decision. 201 the first time a decision is acted on -- whether the
    outcome is "executed" or "rejected"; a rejection is itself a
    persisted, auditable outcome, never an HTTP error. 200 on every
    subsequent call against the same decision_id. 404 only when the
    investigation or the decision itself does not exist, or the decision
    belongs to a different investigation.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    try:
        action, created = action_domain.run_action(
            db, investigation_id=investigation_id, decision_id=decision_id
        )
    except action_domain.DecisionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision {exc} not found"
        ) from exc
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return ActionRead.model_validate(action)


@router.get("/{investigation_id}/decisions/{decision_id}/actions", response_model=ActionRead)
def get_action_for_decision(
    investigation_id: uuid.UUID,
    decision_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ActionRead:
    """The sandbox action attempted for a single decision, if any. 404 if
    the investigation or decision does not exist (or the decision belongs
    to a different investigation), or if no action has been attempted for
    this decision yet.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    decision = decision_domain.get_decision(
        db, investigation_id=investigation_id, decision_id=decision_id
    )
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")
    action = action_domain.get_action_for_decision(
        db, investigation_id=investigation_id, decision_id=decision_id
    )
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sandbox action has been attempted for this decision yet",
        )
    return ActionRead.model_validate(action)


@router.get("/{investigation_id}/actions", response_model=ActionListResponse)
def list_actions(
    investigation_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> ActionListResponse:
    """Append-only sandbox action history for one investigation, across
    every decision it has ever acted on, newest first. 404 if the
    investigation itself does not exist.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found"
        )
    items, total = action_domain.list_actions(
        db, investigation_id=investigation_id, limit=limit, offset=offset
    )
    return ActionListResponse(
        items=[ActionRead.model_validate(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{investigation_id}/actions/{action_id}/verification",
    response_model=VerificationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_verification(
    investigation_id: uuid.UUID,
    action_id: uuid.UUID,
    response: Response,
    db: Session = Depends(get_db),
) -> VerificationRead:
    """Deterministically verify a single persisted Phase 7 sandbox action
    against the persisted Phase 5 simulation that justified it.

    Takes no request body -- the action named by `action_id` is the
    entire context. There is no field anywhere in this request a client
    could use to submit an expected value, an observed value, or a
    verification status/result; every one of those is re-derived entirely
    server-side from the persisted action -> decision -> simulation chain
    (see app.domain.verifications).

    `action_id` is the idempotency anchor: at most one verification row
    exists per action. 201 the first time an action is verified, 200 on
    every subsequent call against the same action_id -- always returning
    the exact same persisted result, never re-comparing. 404 only when the
    investigation or the action itself does not exist, or the action
    belongs to a different investigation. A rejected action (never
    executed) is still verifiable -- it deterministically persists as
    INSUFFICIENT_OBSERVATION, never an HTTP error and never a pretended
    outcome.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    try:
        verification, created = verification_domain.run_verification(
            db, investigation_id=investigation_id, action_id=action_id
        )
    except verification_domain.ActionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Action {exc} not found"
        ) from exc
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return VerificationRead.model_validate(verification)


@router.get("/{investigation_id}/actions/{action_id}/verification", response_model=VerificationRead)
def get_verification_for_action(
    investigation_id: uuid.UUID,
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> VerificationRead:
    """The outcome verification for a single action, if any. 404 if the
    investigation or action does not exist (or the action belongs to a
    different investigation), or if this action has not been verified yet.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    action = action_domain.get_action(db, investigation_id=investigation_id, action_id=action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")
    verification = verification_domain.get_verification_for_action(
        db, investigation_id=investigation_id, action_id=action_id
    )
    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This action has not been verified yet",
        )
    return VerificationRead.model_validate(verification)


@router.get("/{investigation_id}/verifications", response_model=VerificationListResponse)
def list_verifications(
    investigation_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> VerificationListResponse:
    """Append-only outcome-verification history for one investigation,
    across every action it has ever verified, newest first. 404 if the
    investigation itself does not exist.
    """
    investigation = investigation_domain.get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    items, total = verification_domain.list_verifications(
        db, investigation_id=investigation_id, limit=limit, offset=offset
    )
    return VerificationListResponse(
        items=[VerificationRead.model_validate(v) for v in items],
        total=total,
        limit=limit,
        offset=offset,
    )
