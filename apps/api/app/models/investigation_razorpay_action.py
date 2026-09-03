"""Real Razorpay TEST-mode bounded action model -- Phase 10, Milestone 3.

A parallel, additive record to app.models.investigation_action (Phase 7's
SANDBOX-ONLY action) -- Phase 7's own endpoint, model, and semantics are
completely unmodified by this. Where Phase 7's action is a pure,
in-process, no-network simulation, this row records the outcome of an
actual (TEST-mode) call to Razorpay's Orders API -- see
app.domain.razorpay_action for the orchestration that produces this row,
and app.providers.razorpay.RazorpayClient for the only code in the
codebase permitted to make that call.

SEMANTIC HONESTY (Phase 10 M3 critical rule): this row NEVER represents
"payment X was retried". Razorpay's Orders API has no mechanism to retry
a specific existing payment -- creating an Order is a new, independent
TEST payment artifact. `razorpay_order_id` is that new artifact's id,
never a reference to any FinancialEvent's own external_reference. Any
UI/API text describing this row must say "a bounded Razorpay TEST payment
artifact was created", never "retried".

Authorization anchor, identical discipline to InvestigationAction: exactly
the single, immutable InvestigationDecision named by `decision_id`, never
"the investigation's latest decision". Only a decision with
status="completed" AND policy_decision="ALLOWED" ever authorizes a real
Razorpay call -- see app.domain.razorpay_action for the full,
defense-in-depth re-verification (never trusting the decision's stored
fields blindly, exactly as app.domain.actions._authorize_and_execute does
for Phase 7).

Idempotency / the "pending" status: `decision_id` is UNIQUE, exactly like
investigation_actions.decision_id. Unlike Phase 7, the action this module
authorizes has a REAL external side effect (a genuine, if TEST-mode,
Razorpay API call) -- a same-transaction "insert placeholder row first,
call Razorpay second, update the row third" pattern is used specifically
so two concurrent requests for the same decision_id can never both reach
Razorpay (the loser's INSERT fails on the UNIQUE constraint before it
ever calls the client). "pending" is the transient status between steps
one and two/three; see app.domain.razorpay_action's module docstring for
the one failure window this cannot close (a process crash between a real
Razorpay success and the local commit that would have recorded it) --
this is disclosed there deliberately rather than silently claimed to be
impossible.

`raw_response` is deliberately NOT the full arbitrary Razorpay API
response -- only the specific, already-typed fields
app.providers.razorpay.RazorpayOrder exposes (id, status, amount,
currency, receipt, amount_paid, amount_due) are copied in, by
app.domain.razorpay_action, never the provider's full `.raw` dict. No
credential, header, or upstream error body is ever persisted here (see
that module for the same sanitization discipline app.providers.razorpay
already applies at the client boundary).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestigationRazorpayAction(Base):
    __tablename__ = "investigation_razorpay_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )

    # UNIQUE -- the idempotency anchor. See module docstring: this is the
    # database-level lock that stops two concurrent requests from both
    # reaching Razorpay for the same decision.
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigation_decisions.id"), nullable=False, unique=True
    )

    # One of "pending" | "executed" | "rejected". "pending" is transient
    # within a single request (see module docstring); a row observed at
    # rest in "pending" status means the process crashed mid-flight --
    # see app.domain.razorpay_action for how a caller should treat that.
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Set only when status == "rejected". Never raw upstream text -- the
    # same sanitized-string discipline as InvestigationAction.rejection_reason
    # and app.providers.razorpay's own error handling.
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Copied from the decision's own evaluation_result.preferred_scenario /
    # preferred_simulation_id at authorization time -- mirrors
    # InvestigationAction.scenario / .simulation_id exactly, needed by
    # app.domain.razorpay_verification to re-derive the EXPECTED snapshot
    # the same way app.domain.verifications already does for Phase 7/8.
    scenario: Mapped[str | None] = mapped_column(String(100), nullable=True)
    simulation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Frozen copy of the authorizing decision's own policy_decision --
    # same snapshot discipline as InvestigationAction.policy_decision_snapshot.
    policy_decision_snapshot: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # The real Razorpay Order this action created. Set only when
    # status == "executed". This is a NEW artifact, never a reference to
    # an existing payment -- see module docstring's semantic-honesty note.
    razorpay_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The idempotency-key value sent to Razorpay's own receipt field,
    # deterministically derived from decision_id (see
    # app.domain.razorpay_action) -- Razorpay's own duplicate-receipt
    # rejection is the second, provider-side layer behind this table's
    # own UNIQUE(decision_id), for the one failure window neither layer
    # alone closes (see module docstring).
    razorpay_receipt: Mapped[str | None] = mapped_column(String(40), nullable=True)

    executor_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Minimal, explicitly-allowlisted fields only -- see module docstring.
    # {} when status != "executed".
    raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
