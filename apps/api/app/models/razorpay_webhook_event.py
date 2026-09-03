"""Razorpay webhook idempotency ledger -- Phase 10, Milestone 2.

A row is written exactly once processing of one Razorpay webhook delivery
reaches a terminal, deterministic outcome (see `outcome` below). This is
NOT a mirror of FinancialEvent and never competes with its own
(source, external_reference) dedup (app.models.financial_event) -- this
table's only job is answering "have we already finished handling this
razorpay_event_id" so a redelivered webhook (Razorpay's own retry
behavior, or an accidental duplicate) can never re-run processing, per
Phase 10 safety rule 7 (preserve append-only auditability and
idempotency).

Deliberately NOT written for a transient failure (a DB error, a
misconfigured merchant mapping): those are not deterministic -- retrying
after the underlying problem is fixed should actually reprocess the
event, not be silently swallowed by this ledger. See
app.domain.razorpay_webhooks.process_webhook for exactly which outcomes
are terminal (ledger-recorded) vs transient (not recorded, safe to
retry).

`raw_payload` preserves the full verified, parsed webhook body -- the
original Razorpay identifiers and shape are never discarded, satisfying
Phase 10 safety rule 6 (preserve identifiers for traceability) even for
event types this phase does not act on.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RazorpayWebhookEvent(Base):
    __tablename__ = "razorpay_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # UNIQUE -- the idempotency anchor, exactly the role decision_id plays
    # on investigation_actions (see that model's own docstring for the
    # same discipline). Sourced from the x-razorpay-event-id header only
    # -- Razorpay's webhook JSON body does not itself carry an event id.
    razorpay_event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # The raw Razorpay `event` field verbatim (e.g. "payment.captured"),
    # recorded even for an event type this phase does not support -- see
    # `outcome` below.
    razorpay_event_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # One of "accepted" | "ignored_unsupported_event" |
    # "rejected_malformed_payload". Always a terminal, deterministic
    # outcome -- see module docstring for why transient failures never
    # produce a row at all.
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)

    # Set only when outcome == "accepted" -- the FinancialEvent this
    # webhook delivery produced (or matched via FinancialEvent's own
    # dedup). Never set for "ignored"/"rejected".
    financial_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
