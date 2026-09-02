"""Deterministic consequence-simulation result model.

A simulation result is a persisted, point-in-time deterministic calculation
of "what would happen under this scenario, given this investigation's
already-persisted evidence". It sits after Investigation (Phase 3, FACT)
and InvestigationReasoning (Phase 4, INFERENCE) in the core loop:

    INVESTIGATION -> REASONING -> SCENARIO -> SIMULATION -> CONSEQUENCE RESULT

Everything in this table is produced by app.domain.simulation, which is
pure deterministic Python -- no LLM call, no network dependency, no random
behavior. See that module's docstring for the exact calculation. This model
only shapes and persists its output, the same division of responsibility
app.models.investigation_reasoning already has with app.domain.reasoning.

Append-only, like InvestigationReasoning: every call to
app.domain.simulation.run_simulation() inserts a NEW row. Nothing here is
ever updated in place -- a simulation result must remain reproducible from
its own recorded input_snapshot/assumptions/simulator_version forever, even
if a later run against the same investigation (or a re-run of the same
scenario) produces a different number because assumptions or evidence
changed.

`input_snapshot` is captured from the parent Investigation's own persisted,
immutable fields at simulation time -- never from a live re-query of
financial_events. Investigation rows are themselves never updated after
creation (see app.domain.investigations), so this snapshot is safe to
treat as frozen history.

`result` never claims a projected number is an actual financial outcome.
See app.domain.simulation for the OBSERVED FACT / SIMULATION ASSUMPTION /
PROJECTED RESULT separation this table's columns are designed to keep
visible.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InvestigationSimulation(Base):
    __tablename__ = "investigation_simulations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )

    # One of app.domain.simulation.SCENARIOS -- "DO_NOTHING",
    # "RETRY_AFFECTED_PAYMENTS", "REROUTE_PROVIDER",
    # "TARGET_AFFECTED_EVENT_TYPE". A plain validated String, not a Postgres
    # ENUM, matching the KNOWN_EVENT_TYPES precedent in app.domain.events --
    # the scenario catalog can grow without an Alembic migration.
    scenario: Mapped[str] = mapped_column(String(50), nullable=False)

    # One of "completed", "insufficient_evidence". See
    # app.domain.simulation module docstring for the exact condition each
    # value represents -- deliberately not a bare success/failure boolean,
    # mirroring InvestigationReasoning.status.
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Version tag of the deterministic calculation in app.domain.simulation
    # at the time this row was produced (see SIMULATOR_VERSION there).
    # Persisted so a later change to the calculation logic never silently
    # makes an old row look like it was produced by the current rules.
    simulator_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Frozen snapshot of the parent Investigation's own fields at
    # simulation time (investigation_id, window, incident_detected,
    # evidence_event_count, event_type_counts, dominant_signal_event_type,
    # dominant_signal_share, impact_breakdown, impact_amount_unknown_count,
    # evidence). Never a re-query of financial_events -- see module
    # docstring.
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Resolved simulation assumptions actually used for this run
    # (success_rate, scope_fraction -- null for DO_NOTHING, which applies
    # none). Explicit and persisted per-run, even when only defaults were
    # used -- never silently implied by simulator_version alone.
    assumptions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # The full deterministic result: eligible scope, baseline, projected,
    # estimated recovery, and deltas -- see
    # app.schemas.simulation.SimulationResultDetail for the exact shape.
    # Empty ({}) when status != "completed".
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Short, human-readable reason set only when status is
    # "insufficient_evidence". Never a raw exception message.
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
