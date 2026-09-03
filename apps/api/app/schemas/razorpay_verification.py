"""Pydantic response schemas for Phase 10, Milestone 3's real Razorpay
TEST outcome verification.

Mirrors app.schemas.verification's shape exactly: no request schema
exists in this module at all -- verification creation (see
app.routers.investigations) takes no client-supplied body. There is
structurally no field a client could use to submit a
"status": "VERIFIED_SUCCESS", an expected value, or an observed value,
even if it tried -- every field here is always derived server-side from
the persisted razorpay action / decision / simulation chain and REAL,
already-ingested Razorpay webhook evidence (see
app.domain.razorpay_verification).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

RazorpayVerificationStatus = Literal[
    "VERIFIED_SUCCESS", "PARTIALLY_VERIFIED", "FAILED", "INSUFFICIENT_OBSERVATION"
]


class RazorpayVerificationCurrencyAmount(BaseModel):
    currency: str
    amount: str


class RazorpayVerificationRead(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    razorpay_action_id: uuid.UUID
    decision_id: uuid.UUID | None
    simulation_id: uuid.UUID | None

    status: RazorpayVerificationStatus
    verifier_version: str

    # --- EXPECTED / PROJECTED --- from the persisted Phase 5 simulation,
    # via the razorpay action's own decision chain. {"available": False,
    # "reason": ...} when unavailable. See app.domain.razorpay_verification.
    expected_snapshot: dict

    # --- OBSERVED / REAL --- derived from a real, already-persisted,
    # webhook-verified FinancialEvent -- NEVER from Phase 5/7 or LLM
    # output. {"available": False, "reason": ...} when no matching
    # webhook observation has been ingested yet.
    observed_snapshot: dict

    # The pure verifier's own structured comparison -- see
    # app.domain.outcome_verification.verify() (reused unmodified from
    # Phase 8).
    comparison: dict

    # Compact evidence references (razorpay_action_id, decision_id,
    # simulation_id, razorpay_order_id, observation_financial_event_id,
    # executor_version, observation_version).
    evidence: dict

    created_at: datetime

    model_config = {"from_attributes": True}


class RazorpayVerificationListResponse(BaseModel):
    items: list[RazorpayVerificationRead]
    total: int
    limit: int
    offset: int
