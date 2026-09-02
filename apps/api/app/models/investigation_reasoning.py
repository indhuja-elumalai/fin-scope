"""Investigation reasoning result model.

A reasoning result is a persisted, point-in-time attempt to generate
evidence-grounded hypotheses over one Investigation's already-persisted
evidence (see app.models.investigation). Every attempt is persisted --
successful or not -- following the same auditable-by-default principle
Investigation already follows for its own runs: a failed or empty reasoning
attempt is itself a fact worth keeping, not something to discard and retry
silently.

Each call to the reasoning endpoint inserts a NEW row rather than updating
one in place (see app.domain.reasoning.run_reasoning). Investigation
evidence can change between runs (new events keep arriving), so a rerun is
not "the same" investigation of "the same" evidence -- append-only history
mirrors how Investigation itself is never updated in place, and lets a
caller compare how reasoning about a merchant evolved as more evidence
came in, not just see the latest guess.

This table stores ONLY the validated, evidence-grounded output described in
app.domain.reasoning -- never a raw provider response and never a prompt.
`status` distinguishes a successful run from every way reasoning can
legitimately not produce hypotheses; see app.domain.reasoning for the exact
meaning of each value.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestigationReasoning(Base):
    __tablename__ = "investigation_reasoning"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )

    # One of: "completed", "insufficient_evidence", "unavailable",
    # "invalid_output", "no_valid_hypotheses". See app.domain.reasoning for
    # the exact condition each value represents. Never "success"/"failure"
    # as a bare boolean -- the whole point of this field is that "reasoning
    # did not produce hypotheses" has more than one distinguishable cause.
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Ranked, evidence-grounded hypotheses. Empty for every status other
    # than "completed". Each item:
    # {"hypothesis_id", "rank", "title", "explanation", "confidence",
    #  "supporting_evidence": [event_id, ...],
    #  "contradicting_evidence": [event_id, ...], "uncertainty"}
    # Every event_id referenced has already been verified (in
    # app.domain.reasoning) to be one of this investigation's own evidence
    # event IDs -- this table never stores an ungrounded reference.
    hypotheses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Short, sanitized, human-readable explanation set only for
    # "unavailable" and "invalid_output". Never a raw provider error
    # message or raw provider output -- see app.domain.reasoning.
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
