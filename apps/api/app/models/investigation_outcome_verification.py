"""Phase 8 outcome verification result model.

A verification is a persisted, point-in-time record of comparing a
persisted Phase 5 simulation's EXPECTED (projected) outcome against a
derived Phase 7 sandbox action's OBSERVED outcome -- see
app.domain.verifications for the orchestration that produces the row this
model persists, and app.domain.outcome_verification for the pure,
deterministic comparison itself.

Authorization/anchor: a verification is anchored to exactly one persisted
InvestigationAction via `action_id`, never "the investigation's latest
action" -- the same anchoring discipline app.models.investigation_action
already applies to `decision_id`. The chain is always
action -> decision -> preferred simulation -> expected outcome, and
action -> sandbox_result -> observed outcome; this module never
independently reconstructs Phase 5 or Phase 7 numbers, it only stores the
already-computed comparison.

Idempotent, NOT append-only-per-retry: `action_id` is UNIQUE. At most one
InvestigationOutcomeVerification row can ever exist for a given action --
the same "show me what already happened, never try again" discipline
app.models.investigation_action already documents for `decision_id`. A
verification is never mutated in place after it is created; re-verifying
with a different observation is an explicit future requirement, not
something this MVP invents.

`expected_snapshot` / `observed_snapshot` / `comparison` / `evidence` are
immutable JSONB snapshots, frozen at verification time -- a verification
must remain reproducible even if later, unrelated events are ingested for
the same merchant (see module docstring in app.domain.verifications for
exactly what each snapshot contains).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestigationOutcomeVerification(Base):
    __tablename__ = "investigation_outcome_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )

    # UNIQUE -- the idempotency anchor, exactly the role decision_id plays
    # on investigation_actions. See module docstring and
    # app.domain.verifications for the SELECT-then-insert-or-return flow
    # this enforces at the database level.
    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigation_actions.id"), nullable=False, unique=True
    )

    # Provenance only (see app.models.investigation_action's own
    # policy_decision_snapshot rationale for why a self-contained copy is
    # kept alongside the FK rather than requiring a join). Null only in
    # the defensive case where the action itself never reached a decision
    # (should not be reachable in practice, since every InvestigationAction
    # row is itself anchored to a decision_id).
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Deliberately not a SQLAlchemy ForeignKey -- mirrors
    # InvestigationAction.simulation_id: null whenever the action was
    # rejected (no preferred simulation was ever established), present
    # when the action executed.
    simulation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # One of app.domain.outcome_verification.STATUSES. Plain validated
    # String, not a Postgres ENUM -- same rationale as
    # InvestigationSimulation.scenario/InvestigationAction.status.
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Version tag of app.domain.outcome_verification.VERIFIER_VERSION at
    # the time this row was produced -- same reproducibility discipline as
    # InvestigationAction.executor_version / InvestigationSimulation.simulator_version.
    verifier_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- EXPECTED (from the persisted Phase 5 simulation's PROJECTED
    # result) --- {"available": False, "reason": ...} when no completed
    # simulation could be established (e.g. the action was rejected).
    expected_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # --- OBSERVED (derived from the persisted Phase 7 sandbox_result) ---
    # {"available": False, "reason": ...} when the action produced no
    # sandbox outcome (rejected).
    observed_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # The pure verifier's own output -- see
    # app.domain.outcome_verification.verify()'s return shape.
    comparison: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Compact ID references only (action_id, decision_id, simulation_id,
    # executor_version, observation_version) -- never a copy of the full
    # snapshots. See app.domain.verifications for exactly what this holds.
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
