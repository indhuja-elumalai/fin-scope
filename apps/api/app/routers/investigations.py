"""Incident investigation API: FIND -> ROOT CAUSE -> IMPACT, on demand."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.domain import investigations as investigation_domain
from app.schemas.investigation import (
    InvestigationCreate,
    InvestigationListResponse,
    InvestigationRead,
)

router = APIRouter(
    prefix="/v1/investigations",
    tags=["investigations"],
    dependencies=[Depends(require_api_key)],
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
