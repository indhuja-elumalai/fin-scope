"""Pydantic response schemas for Phase 6 decision evaluation + policy.

Mirrors app.schemas.simulation's OBSERVED-FACT/ASSUMPTION/PROJECTED
separation, extended with two more sections: DECISION (which candidate
evaluation preferred, and why) and POLICY (whether we are allowed to
choose it -- ALLOWED / REQUIRES_HUMAN_APPROVAL / BLOCKED).

There is no request schema in this module: decision creation (see
app.routers.investigations) takes no client-supplied body at all, the same
shape as reason_about_investigation's POST /reason. Evaluation and policy
are always computed entirely server-side from the investigation's own
persisted simulations -- there is structurally no field a client could use
to submit "policy_decision": "ALLOWED" even if it tried.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

DecisionStatus = Literal["completed", "insufficient_evidence", "no_eligible_scenario"]
PolicyDecision = Literal["ALLOWED", "REQUIRES_HUMAN_APPROVAL", "BLOCKED"]


class DecisionCurrencyAmount(BaseModel):
    currency: str
    amount: Decimal


class EvaluatedCandidate(BaseModel):
    """One scenario's contribution to the comparison -- see
    app.domain.decision_evaluation.CandidateInput for where these numbers
    come from (Phase 5's own simulation result, never re-derived here).
    `projected_exposure_by_currency` is the PROJECTED FINANCIAL EXPOSURE
    Phase 5 already computed, the same field policy thresholds apply to --
    not a value derived from `estimated_recovery_by_currency`.
    """

    simulation_id: uuid.UUID
    scenario: str
    failed_event_count_delta: int
    estimated_recovery_by_currency: list[DecisionCurrencyAmount]
    projected_exposure_by_currency: list[DecisionCurrencyAmount]
    projected_exposure_amount_unknown_count: int
    eligible_event_count: int


class EvaluationResultDetail(BaseModel):
    candidates: list[EvaluatedCandidate]
    preferred_scenario: str
    preferred_simulation_id: uuid.UUID
    reason: str


class DecisionRead(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID

    # --- did the Phase 6 pipeline itself produce a decision? ---
    status: DecisionStatus
    evaluation_version: str
    policy_version: str | None

    # --- reproducibility anchor: which simulations were compared ---
    candidate_simulation_ids: list[uuid.UUID]

    # --- DECISION EVALUATION --- {} when status != "completed"
    evaluation_result: EvaluationResultDetail | dict

    # --- POLICY --- null / [] when status != "completed". Computed
    # exclusively server-side by app.domain.policy.
    policy_decision: PolicyDecision | None
    policy_reasons: list[str]

    input_snapshot: dict
    failure_reason: str | None

    created_at: datetime

    model_config = {"from_attributes": True}


class DecisionListResponse(BaseModel):
    items: list[DecisionRead]
    total: int
    limit: int
    offset: int
