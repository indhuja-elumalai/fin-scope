"""Bounded sandbox action result model.

An action is a persisted, point-in-time record of Phase 7's attempt to act
on a single Phase 6 decision: either the deterministic sandbox executor
ran ("executed"), or authorization did not pass ("rejected"). See
app.domain.actions for the orchestration that produces the row this model
persists, and app.domain.sandbox_executor for the pure, deterministic
executor itself.

Authorization anchor (MVP contract, intentional -- do not "fix" this into
a latest-decision-only rule without an explicit design change): an action
is authorized by exactly the immutable InvestigationDecision row named by
`decision_id`, never by "the investigation's current/latest decision".
Decisions are themselves append-only (see
app.models.investigation_decision), so an older ALLOWED decision remains a
valid, independently-authorized target for a sandbox action even after a
newer decision exists for the same investigation with a different
(possibly BLOCKED) outcome. Each decision row is its own complete
authorization context; Phase 7 never tries to guess which one the caller
"really meant".

Idempotent, NOT append-only-per-retry: `decision_id` is UNIQUE. At most one
InvestigationAction row can ever exist for a given decision -- a repeated
POST against the same decision_id returns the existing row (whether
"executed" or "rejected") rather than creating a second attempt. This is a
deliberate difference from InvestigationDecision/InvestigationSimulation
(which insert a new row on every call): a sandbox action is a single
consequential attempt tied to one specific authorization, not a
repeatable query -- "attempt it again" must mean "show me what already
happened", never "try again and maybe get a different answer" or "execute
twice".

`sandbox_result` and `rejection_reason` are deliberately small: this table
never recomputes or re-stores Phase 5's simulation numbers, only the
compact scenario-specific action_kind/targeted-event/outcome shape
app.domain.sandbox_executor.execute() returns (see that module's own
verbatim-copy discipline).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestigationAction(Base):
    __tablename__ = "investigation_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )

    # UNIQUE -- the idempotency anchor. See module docstring and
    # app.domain.actions for the SELECT-then-insert-or-return flow this
    # enforces at the database level, not just in application code.
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigation_decisions.id"), nullable=False, unique=True
    )

    # One of "executed", "rejected". "executed" means authorization passed
    # and app.domain.sandbox_executor.execute() ran -- including the
    # DO_NOTHING -> NO_OP case, which is still "executed", just with no
    # targeted events. "rejected" means authorization or a defense-in-depth
    # precondition failed; the executor was never called. See
    # app.domain.actions module docstring for the exact precedence.
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Set only when status == "rejected". Never a raw exception message --
    # mirrors InvestigationSimulation.failure_reason /
    # InvestigationDecision.failure_reason.
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Copied from the decision's own evaluation_result.preferred_scenario
    # at the moment this action was attempted. Null only when rejected
    # before a preferred scenario could be established (e.g. decision
    # status was insufficient_evidence/no_eligible_scenario).
    scenario: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Copied from the decision's own evaluation_result.preferred_simulation_id.
    # Null under the same conditions as `scenario`. Deliberately not a
    # SQLAlchemy ForeignKey -- the referenced InvestigationSimulation may
    # not exist/qualify at all for a rejected attempt; this column is
    # provenance, not a join target.
    simulation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Frozen copy of decision.policy_decision at the moment this action was
    # attempted -- makes this row self-describing (why was this
    # executed/rejected?) without a join back to investigation_decisions,
    # the same self-containment rationale
    # InvestigationSimulation.input_snapshot documents. The
    # InvestigationDecision row itself is immutable and remains the source
    # of truth; this is a read-time snapshot, never re-derived later.
    policy_decision_snapshot: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Version tag of app.domain.sandbox_executor.EXECUTOR_VERSION at the
    # time this row was produced -- same reproducibility discipline as
    # InvestigationSimulation.simulator_version /
    # InvestigationDecision.evaluation_version.
    executor_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # The executor's own structured result -- see
    # app.schemas.action.SandboxResultDetail for the exact shape. {} when
    # status == "rejected".
    sandbox_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
