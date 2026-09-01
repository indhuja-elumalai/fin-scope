"""Financial event ingestion and retrieval API."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.domain import events as event_domain
from app.schemas.event import EventCreate, EventListResponse, EventRead

router = APIRouter(
    prefix="/v1/events",
    tags=["events"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=EventRead)
def ingest_event(
    payload: EventCreate, response: Response, db: Session = Depends(get_db)
) -> EventRead:
    try:
        event, created = event_domain.ingest_event(
            db,
            merchant_id=payload.merchant_id,
            event_type=payload.event_type,
            source=payload.source,
            external_reference=payload.external_reference,
            amount=payload.amount,
            currency=payload.currency,
            status=payload.status,
            payload=payload.payload,
            occurred_at=payload.occurred_at,
        )
    except event_domain.MerchantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Merchant {exc} not found"
        ) from exc
    except event_domain.InvalidEventTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown event_type: {exc}",
        ) from exc

    # 201 for a newly created event, 200 when an identical
    # (source, external_reference) already existed -- ingestion is
    # idempotent, so a replay is not an error.
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return EventRead.model_validate(event)


@router.get("", response_model=EventListResponse)
def list_events(
    merchant_id: uuid.UUID | None = None,
    event_type: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> EventListResponse:
    events, total = event_domain.list_events(
        db,
        merchant_id=merchant_id,
        event_type=event_type,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )
    return EventListResponse(
        items=[EventRead.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}", response_model=EventRead)
def get_event(event_id: uuid.UUID, db: Session = Depends(get_db)) -> EventRead:
    event = event_domain.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return EventRead.model_validate(event)
