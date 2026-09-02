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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.config import get_settings
from app.db import get_db
from app.domain import investigations as investigation_domain
from app.domain import reasoning as reasoning_domain
from app.domain import simulation as simulation_domain
from app.providers.reasoning import HostedReasoningProvider, ReasoningProvider
from app.schemas.investigation import (
    InvestigationCreate,
    InvestigationListResponse,
    InvestigationRead,
)
from app.schemas.reasoning import InvestigationReasoningRead
from app.schemas.simulation import SimulationCreate, SimulationListResponse, SimulationRead

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
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    return HostedReasoningProvider(api_key=settings.anthropic_api_key)


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
