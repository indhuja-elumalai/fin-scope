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
from app.providers.reasoning import HostedReasoningProvider, ReasoningProvider
from app.schemas.investigation import (
    InvestigationCreate,
    InvestigationListResponse,
    InvestigationRead,
)
from app.schemas.reasoning import InvestigationReasoningRead

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
