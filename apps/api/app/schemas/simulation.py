"""Pydantic request/response schemas for deterministic consequence simulation.

Mirrors the separation app.schemas.investigation (FACT) and
app.schemas.reasoning (INFERENCE) already establish: everything this module
shapes is a SIMULATION ASSUMPTION or a PROJECTED RESULT, never an observed
fact. See app.domain.simulation for exactly how each field is computed.

`estimated_recovery_by_currency` and every `*_by_currency` list here follow
the same rule app.schemas.investigation.ImpactBreakdownItem already
enforces: one entry per currency, amounts never summed across currencies.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SimulationScenario = Literal[
    "DO_NOTHING",
    "RETRY_AFFECTED_PAYMENTS",
    "REROUTE_PROVIDER",
    "TARGET_AFFECTED_EVENT_TYPE",
]

# See app.domain.simulation module docstring for exactly when each status
# is produced.
SimulationStatus = Literal["completed", "insufficient_evidence"]


class SimulationAssumptionsOverride(BaseModel):
    """Optional caller-supplied override of the scenario's default
    assumptions. Both bounded to (0, 1] -- a rate/fraction of zero or below
    is not a meaningful intervention, and anything above 1 is not a valid
    probability or scope fraction. DO_NOTHING accepts no override (see
    SimulationCreate) because it applies no assumptions at all.
    """

    success_rate: Decimal | None = Field(default=None, gt=0, le=1)
    scope_fraction: Decimal | None = Field(default=None, gt=0, le=1)


class SimulationCreate(BaseModel):
    scenario: SimulationScenario
    assumptions: SimulationAssumptionsOverride | None = None

    @model_validator(mode="after")
    def _do_nothing_accepts_no_assumptions(self) -> SimulationCreate:
        if self.scenario == "DO_NOTHING" and self.assumptions is not None:
            has_override = (
                self.assumptions.success_rate is not None
                or self.assumptions.scope_fraction is not None
            )
            if has_override:
                raise ValueError("DO_NOTHING does not accept assumption overrides")
        return self


class SimulationAssumptions(BaseModel):
    """The assumptions actually used for this run, always explicit and
    persisted -- never left implicit in code alone. Both null only for
    DO_NOTHING, which applies no intervention and therefore no assumption.
    """

    success_rate: Decimal | None
    scope_fraction: Decimal | None


class SimulationCurrencyAmount(BaseModel):
    currency: str
    amount: Decimal


class SimulationScopeSnapshot(BaseModel):
    """One side of the baseline/projected comparison, scoped to the events
    this scenario is actually eligible to affect (see
    SimulationResultDetail.eligible_event_ids) -- not the investigation's
    full evidence set.
    """

    failed_event_count: int
    success_event_count: int
    exposure_by_currency: list[SimulationCurrencyAmount]
    exposure_amount_unknown_count: int


class SimulationDelta(BaseModel):
    failed_event_count_delta: int
    financial_delta_by_currency: list[SimulationCurrencyAmount]


class SimulationResultDetail(BaseModel):
    # A short, deterministic description of how eligible_event_ids was
    # derived for this scenario (e.g. which event_type(s) qualify, and for
    # REROUTE_PROVIDER, which `source` value was treated as the affected
    # provider). See app.domain.simulation for the exact rule per scenario.
    scope_description: str
    eligible_event_count: int
    eligible_event_ids: list[uuid.UUID]

    baseline: SimulationScopeSnapshot
    projected: SimulationScopeSnapshot
    estimated_recovery_by_currency: list[SimulationCurrencyAmount]
    delta: SimulationDelta


class SimulationRead(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    scenario: SimulationScenario
    status: SimulationStatus
    simulator_version: str

    # --- OBSERVED FACT (frozen at simulation time) ---
    input_snapshot: dict

    # --- SIMULATION ASSUMPTION ---
    assumptions: SimulationAssumptions

    # --- PROJECTED RESULT --- empty for status != "completed".
    result: SimulationResultDetail | dict

    failure_reason: str | None

    created_at: datetime

    model_config = {"from_attributes": True}


class SimulationListResponse(BaseModel):
    items: list[SimulationRead]
    total: int
    limit: int
    offset: int
