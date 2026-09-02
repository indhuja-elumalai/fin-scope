"""Investigation model.

An investigation is a persisted, point-in-time analysis of a merchant's
recent financial events: whether an incident was detected (FIND), a
deterministic dominant-signal heuristic over the evidence, and a
currency-safe financial impact estimate. Every run is persisted, including
runs where no incident was detected -- the investigation itself is an
auditable act, the same principle app.models.audit_log already follows.

`dominant_signal_event_type` / `dominant_signal_share` are a deterministic
"dominant recurring signal" heuristic based on event-type frequency in the
evidence window. They are NOT a causal claim and must not be read as
root-causing -- see app.domain.investigations for the exact rule and
rationale. True root-cause reasoning belongs to a later phase.

`evidence` is an immutable snapshot of the financial_events rows this
investigation actually looked at, taken at run time -- financial_events
themselves are never mutated by an investigation.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    incident_detected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    dominant_signal_event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dominant_signal_share: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    # [{"currency": "INR", "total_amount": "199.99", "event_count": 3}, ...]
    # Amounts are never summed across different currencies.
    impact_breakdown: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    impact_amount_unknown_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # Ordered (by occurred_at) snapshot of the evidence events -- the
    # reconstructed timeline: [{"event_id", "event_type", "source",
    # "external_reference", "amount", "currency", "occurred_at"}, ...]
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
