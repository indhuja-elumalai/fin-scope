"""Phase 10, Milestone 3 (Part 5) real Razorpay TEST outcome verification
result model.

A razorpay verification is a persisted, point-in-time record of comparing
a persisted Phase 5 simulation's EXPECTED (projected) outcome against an
OBSERVED outcome derived from REAL, persisted Razorpay webhook evidence --
never from Phase 5's own simulation, Phase 7's sandbox result, LLM output,
or a client-submitted value. See app.domain.razorpay_verification for the
orchestration that produces the row this model persists, and
app.domain.outcome_verification for the pure, deterministic comparison
itself (reused UNMODIFIED from Phase 8 -- see that module and Part 6 of
the Milestone 3 spec).

Authorization/anchor: a razorpay verification is anchored to exactly one
persisted InvestigationRazorpayAction via `razorpay_action_id`, never "the
investigation's latest razorpay action" -- the same anchoring discipline
app.models.investigation_outcome_verification already applies to
`action_id` for Phase 7/8. The chain is always
razorpay_action -> decision -> preferred simulation -> expected outcome,
and razorpay_action -> razorpay_order_id -> (via FinancialEvent/
RazorpayWebhookEvent linkage) -> observed outcome; this module never
independently reconstructs Phase 5 numbers or fabricates a webhook
observation.

Idempotent, NOT append-only-per-retry: `razorpay_action_id` is UNIQUE. At
most one InvestigationRazorpayVerification row can ever exist for a given
razorpay action -- the same "show me what already happened, never try
again" discipline app.models.investigation_outcome_verification already
documents for `action_id`.

`expected_snapshot` / `observed_snapshot` / `comparison` / `evidence` are
immutable JSONB snapshots, frozen at verification time -- see module
docstring in app.domain.razorpay_verification for exactly what each
snapshot contains and where OBSERVED's provenance is proven to originate
from real webhook evidence, never a copied expected value.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestigationRazorpayVerification(Base):
    __tablename__ = "investigation_razorpay_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )

    # UNIQUE -- the idempotency anchor, exactly the role action_id plays
    # on investigation_outcome_verifications. See module docstring and
    # app.domain.razorpay_verification for the SELECT-then-insert-or-return
    # flow this enforces at the database level.
    razorpay_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_razorpay_actions.id"),
        nullable=False,
        unique=True,
    )

    # Provenance only (see InvestigationOutcomeVerification.decision_id's
    # own rationale for why a self-contained copy is kept alongside the
    # FK chain rather than requiring a join).
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Deliberately not a SQLAlchemy ForeignKey -- mirrors
    # InvestigationOutcomeVerification.simulation_id: null whenever the
    # razorpay action was rejected (no preferred simulation was ever
    # established / re-verifiable), present when the action executed.
    simulation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # One of app.domain.outcome_verification.STATUSES -- the SAME status
    # vocabulary Phase 8 already defines, reused verbatim (Part 6: no
    # second comparison algorithm, no second status vocabulary).
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Version tag of app.domain.outcome_verification.VERIFIER_VERSION at
    # the time this row was produced -- same reproducibility discipline as
    # InvestigationOutcomeVerification.verifier_version.
    verifier_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- EXPECTED (from the persisted Phase 5 simulation's PROJECTED
    # result, via the razorpay action's own decision -> simulation chain)
    # --- {"available": False, "reason": ...} when unavailable.
    expected_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # --- OBSERVED (derived from REAL, persisted Razorpay webhook
    # evidence -- see app.domain.razorpay_verification's observation
    # linkage) --- {"available": False, "reason": ...} when no matching
    # webhook observation has been ingested yet for this action's Order.
    observed_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # The pure verifier's own output -- app.domain.outcome_verification
    # .verify()'s return shape, unmodified.
    comparison: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Compact ID references only (razorpay_action_id, decision_id,
    # simulation_id, razorpay_order_id, observation_financial_event_id,
    # executor_version, observation_version) -- never a copy of the full
    # snapshots. See app.domain.razorpay_verification for exactly what
    # this holds.
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
