"""Deterministic decision evaluation + policy result model.

A decision is a persisted, point-in-time record of Phase 6's own two-step
pipeline over an investigation's already-persisted simulations:
  1. app.domain.decision_evaluation compares the latest completed
     simulation per scenario and picks exactly one preferred candidate.
  2. app.domain.policy authorizes (or not) that single preferred
     candidate -- ALLOWED / REQUIRES_HUMAN_APPROVAL / BLOCKED.

Both steps are pure, deterministic Python -- no LLM call, no network
dependency, no random behavior anywhere in either module. See
app.domain.decisions for the orchestration that produces the row this model
persists.

Append-only, exactly like InvestigationReasoning and InvestigationSimulation:
every call to app.domain.decisions.run_decision() inserts a NEW row.
Nothing here is ever updated in place -- rerunning after new simulations
exist produces Decision #2, #3, ..., never an overwrite of Decision #1.

`evaluation_result` and `input_snapshot` are deliberately small: the
candidate simulations referenced by `candidate_simulation_ids` are
themselves immutable and already carry their own frozen
`input_snapshot`/`assumptions`/`result` (see
app.models.investigation_simulation) -- this table stores only the compact
numbers actually compared and the resulting decision, not a third copy of
the underlying evidence.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestigationDecision(Base):
    __tablename__ = "investigation_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )

    # One of "completed", "insufficient_evidence", "no_eligible_scenario".
    # Whether the Phase 6 pipeline itself produced a decision -- NOT what
    # it decided; a BLOCKED policy_decision is still status="completed"
    # (see app.domain.decisions module docstring for why these stay
    # deliberately separate concepts).
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    evaluation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    policy_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Which of this investigation's own persisted simulation rows were
    # actually compared -- [uuid-string, ...]. The reproducibility anchor:
    # each referenced row is itself immutable, so this list alone is
    # sufficient to reconstruct exactly what Phase 6 looked at.
    candidate_simulation_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Compact per-candidate comparison numbers plus the preferred pick and
    # why -- see app.schemas.decision.EvaluationResultDetail for the exact
    # shape. {} when status != "completed".
    evaluation_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # One of "ALLOWED", "REQUIRES_HUMAN_APPROVAL", "BLOCKED". Null when
    # status != "completed" -- policy only ever runs after a valid
    # evaluation produced a preferred candidate. Computed exclusively by
    # app.domain.policy; never accepted from a client request (see
    # app.routers.investigations -- the decision-creation endpoint takes no
    # client body at all).
    policy_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    policy_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Minimal context, not a re-duplication of investigation.evidence --
    # {"merchant_id", "incident_detected"}.
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Set only for "insufficient_evidence" / "no_eligible_scenario".
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
