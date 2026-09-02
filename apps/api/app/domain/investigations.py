"""Deterministic incident investigation: FIND -> DOMINANT SIGNAL -> IMPACT.

This module is the FIND/DOMINANT-SIGNAL/IMPACT slice of the FIN-SCOPE core loop.
Everything here is deterministic and rule-based -- no AI/LLM call is made or
needed. The dominant signal is a deterministic frequency heuristic over the
observed evidence, not causal root-cause inference. Per the project's AI/non-AI
boundary (see README section 4/5), ambiguity-and-reasoning work like true
root-cause analysis belongs to a later, explicitly-scoped Investigation phase;
this phase only builds the deterministic substrate that phase will read.

Three things this module deliberately does NOT claim:
  - `dominant_signal_event_type` is a frequency heuristic over the evidence,
    not a causal finding. It answers "what recurred most", not "what caused
    this". The API/schema/model all name it accordingly.
  - Evidence (the events actually observed) is kept separate from signals
    (the deterministic conclusions derived from that evidence) at every
    layer, so a caller can always tell which is which.
  - Impact is a currency-safe sum: amounts are never added across different
    currencies, and events with no amount are counted, not silently ignored
    or treated as zero.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.financial_event import FinancialEvent
from app.models.investigation import Investigation
from app.models.merchant import Merchant

# Event types that indicate a possible incident. payment_succeeded and
# refund_issued are normal-operation signals, not incident evidence, so they
# are excluded from detection even though they are valid KNOWN_EVENT_TYPES.
CONCERNING_EVENT_TYPES = frozenset(
    {"payment_failed", "settlement_delayed", "gateway_degraded"}
)

# How far back from `as_of` to look for concerning events, and how many are
# required within that window to consider an incident detected. Plain
# module-level constants, not DB/API-configurable -- same rationale as
# KNOWN_EVENT_TYPES in app.domain.events: tunable in code as the detection
# model matures, without an Alembic migration or a config surface.
DETECTION_WINDOW = timedelta(minutes=60)
DETECTION_THRESHOLD = 3


class MerchantNotFoundError(Exception):
    """Raised when an investigation is requested for a merchant that does not exist."""


def _event_snapshot(event: FinancialEvent) -> dict:
    """An immutable, JSON-safe snapshot of one evidence event."""
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "source": event.source,
        "external_reference": event.external_reference,
        "amount": str(event.amount) if event.amount is not None else None,
        "currency": event.currency,
        "occurred_at": event.occurred_at.isoformat(),
    }


def _dominant_signal(
    events: list[FinancialEvent],
) -> tuple[str | None, Decimal | None]:
    """Deterministic "dominant recurring signal" heuristic.

    Not causal inference: this only reports which concerning event_type
    recurred most often in the evidence window, and what share of the
    evidence it represents. Ties are broken by whichever type's first
    occurrence in the (chronologically ordered) evidence came earliest, so
    the result is fully deterministic for identical input.
    """
    if not events:
        return None, None

    counts = Counter(event.event_type for event in events)
    max_count = max(counts.values())
    tied_types = [t for t, c in counts.items() if c == max_count]
    if len(tied_types) == 1:
        dominant_type = tied_types[0]
    else:
        # `events` is already ordered by occurred_at ascending -- the first
        # event whose type is among the tied types determines the winner.
        dominant_type = next(e.event_type for e in events if e.event_type in tied_types)

    share = Decimal(max_count) / Decimal(len(events))
    return dominant_type, share


def _impact_breakdown(events: list[FinancialEvent]) -> tuple[list[dict], int]:
    """Currency-safe impact: per-currency totals, never summed together.

    Returns (breakdown, amount_unknown_count). `breakdown` is ordered by
    currency code for deterministic output.
    """
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    unknown_count = 0

    for event in events:
        if event.amount is None or event.currency is None:
            unknown_count += 1
            continue
        totals[event.currency] = totals.get(event.currency, Decimal(0)) + event.amount
        counts[event.currency] = counts.get(event.currency, 0) + 1

    breakdown = [
        {
            "currency": currency,
            "total_amount": str(totals[currency]),
            "event_count": counts[currency],
        }
        for currency in sorted(totals)
    ]
    return breakdown, unknown_count


def run_investigation(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    as_of: datetime | None = None,
) -> Investigation:
    """Run FIND -> ROOT CAUSE -> IMPACT for a merchant and persist the result.

    Always persists, including when no incident is detected -- the
    investigation itself is an auditable act. Raises MerchantNotFoundError
    if the merchant does not exist.
    """
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise MerchantNotFoundError(merchant_id)

    window_end = as_of if as_of is not None else datetime.now(UTC)
    window_start = window_end - DETECTION_WINDOW

    # FIND: evidence retrieval. Ordered by occurred_at ascending so it
    # doubles as the reconstructed timeline.
    events = list(
        db.scalars(
            select(FinancialEvent)
            .where(
                FinancialEvent.merchant_id == merchant_id,
                FinancialEvent.event_type.in_(CONCERNING_EVENT_TYPES),
                FinancialEvent.occurred_at >= window_start,
                FinancialEvent.occurred_at <= window_end,
            )
            .order_by(FinancialEvent.occurred_at.asc())
        )
    )

    incident_detected = len(events) >= DETECTION_THRESHOLD
    event_type_counts = dict(Counter(event.event_type for event in events))

    if incident_detected:
        dominant_type, dominant_share = _dominant_signal(events)
    else:
        dominant_type, dominant_share = None, None
    impact_breakdown, impact_amount_unknown_count = _impact_breakdown(events)
    evidence = [_event_snapshot(event) for event in events]

    investigation = Investigation(
        merchant_id=merchant_id,
        window_start=window_start,
        window_end=window_end,
        incident_detected=incident_detected,
        evidence_event_count=len(events),
        event_type_counts=event_type_counts,
        dominant_signal_event_type=dominant_type,
        dominant_signal_share=dominant_share,
        impact_breakdown=impact_breakdown,
        impact_amount_unknown_count=impact_amount_unknown_count,
        evidence=evidence,
    )
    db.add(investigation)
    db.flush()

    db.add(
        AuditLog(
            event_type="investigation_completed",
            entity_type="investigation",
            entity_id=str(investigation.id),
            actor="system",
            payload={
                "merchant_id": str(merchant_id),
                "incident_detected": incident_detected,
                "evidence_event_count": len(events),
                "dominant_signal_event_type": dominant_type,
            },
        )
    )
    db.commit()
    db.refresh(investigation)
    return investigation


def list_investigations(
    db: Session,
    *,
    merchant_id: uuid.UUID | None = None,
    incident_detected: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Investigation], int]:
    """List investigations with optional filters. Returns (items, total_count)."""
    stmt = select(Investigation)
    if merchant_id is not None:
        stmt = stmt.where(Investigation.merchant_id == merchant_id)
    if incident_detected is not None:
        stmt = stmt.where(Investigation.incident_detected == incident_detected)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(Investigation.created_at.desc()).limit(limit).offset(offset)
    items = list(db.scalars(stmt))
    return items, total


def get_investigation(db: Session, investigation_id: uuid.UUID) -> Investigation | None:
    return db.get(Investigation, investigation_id)
