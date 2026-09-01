"""Financial event ingestion and retrieval.

Business rules live here, not in the router: validating the event-type
vocabulary, enforcing that the referenced merchant exists, deduplicating on
(source, external_reference), and recording the audit trail. Routers only
translate HTTP <-> these functions -- this is the boundary later phases
(FIND, Investigation, ...) will read events through as well, not just HTTP.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.financial_event import FinancialEvent
from app.models.merchant import Merchant

# The known event-type vocabulary. Deliberately a plain set validated in
# code, not a Postgres ENUM -- new event types can be added here without an
# Alembic migration as the catalog grows across later phases.
KNOWN_EVENT_TYPES = frozenset(
    {
        "payment_failed",
        "payment_succeeded",
        "refund_issued",
        "settlement_delayed",
        "gateway_degraded",
    }
)


class MerchantNotFoundError(Exception):
    """Raised when an event references a merchant that does not exist."""


class InvalidEventTypeError(Exception):
    """Raised when event_type is not in KNOWN_EVENT_TYPES.

    In practice the API layer's Pydantic schema rejects this before it
    reaches here (see app.schemas.event.EventCreate); this check exists so
    the domain function is still safe if called directly by a future
    non-HTTP caller (e.g. a background ingestion worker).
    """


def ingest_event(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    event_type: str,
    source: str,
    external_reference: str | None,
    amount: Decimal | None,
    currency: str | None,
    status: str | None,
    payload: dict,
    occurred_at: datetime,
) -> tuple[FinancialEvent, bool]:
    """Ingest a financial event. Returns (event, created).

    created is False when an event with the same (source, external_reference)
    already existed -- ingestion is idempotent, not an error, so a replayed
    event from an upstream source is always safe to resend.
    """
    if event_type not in KNOWN_EVENT_TYPES:
        raise InvalidEventTypeError(event_type)

    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise MerchantNotFoundError(merchant_id)

    if external_reference is not None:
        existing = db.scalars(
            select(FinancialEvent).where(
                FinancialEvent.source == source,
                FinancialEvent.external_reference == external_reference,
            )
        ).first()
        if existing is not None:
            return existing, False

    event = FinancialEvent(
        merchant_id=merchant_id,
        event_type=event_type,
        source=source,
        external_reference=external_reference,
        amount=amount,
        currency=currency,
        status=status,
        payload=payload,
        occurred_at=occurred_at,
    )
    db.add(event)
    db.flush()

    db.add(
        AuditLog(
            event_type="financial_event_ingested",
            entity_type="financial_event",
            entity_id=str(event.id),
            actor="system",
            payload={
                "merchant_id": str(merchant_id),
                "event_type": event_type,
                "source": source,
                "external_reference": external_reference,
            },
        )
    )
    db.commit()
    db.refresh(event)
    return event, True


def list_events(
    db: Session,
    *,
    merchant_id: uuid.UUID | None = None,
    event_type: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FinancialEvent], int]:
    """List events with optional filters. Returns (events, total_count)."""
    stmt = select(FinancialEvent)
    if merchant_id is not None:
        stmt = stmt.where(FinancialEvent.merchant_id == merchant_id)
    if event_type is not None:
        stmt = stmt.where(FinancialEvent.event_type == event_type)
    if occurred_from is not None:
        stmt = stmt.where(FinancialEvent.occurred_at >= occurred_from)
    if occurred_to is not None:
        stmt = stmt.where(FinancialEvent.occurred_at <= occurred_to)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(FinancialEvent.occurred_at.desc()).limit(limit).offset(offset)
    events = list(db.scalars(stmt))
    return events, total


def get_event(db: Session, event_id: uuid.UUID) -> FinancialEvent | None:
    return db.get(FinancialEvent, event_id)
