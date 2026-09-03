"""Pydantic response schemas for Phase 8 outcome verification.

Mirrors app.schemas.action's shape: no request schema exists in this
module at all -- verification creation (see app.routers.investigations)
takes no client-supplied body, the same bodyless-POST convention
create_action/create_decision already establish. There is structurally no
field a client could use to submit "status": "VERIFIED_SUCCESS" or an
expected/observed value even if it tried -- every field here is always
derived server-side from the persisted action/decision/simulation chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

VerificationStatus = Literal[
    "VERIFIED_SUCCESS", "PARTIALLY_VERIFIED", "FAILED", "INSUFFICIENT_OBSERVATION"
]


class VerificationCurrencyAmount(BaseModel):
    currency: str
    amount: str


class VerificationRead(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    action_id: uuid.UUID
    decision_id: uuid.UUID | None
    simulation_id: uuid.UUID | None

    status: VerificationStatus
    verifier_version: str

    # --- EXPECTED / PROJECTED --- from the persisted Phase 5 simulation.
    # {"available": False, "reason": ...} when unavailable (e.g. the
    # action was rejected). See app.domain.verifications.
    expected_snapshot: dict

    # --- OBSERVED / SANDBOX --- derived from the persisted Phase 7
    # sandbox_result. {"available": False, "reason": ...} when unavailable.
    observed_snapshot: dict

    # The pure verifier's own structured comparison -- see
    # app.domain.outcome_verification.verify().
    comparison: dict

    # Compact evidence references (action_id, decision_id, simulation_id,
    # executor_version, observation_version).
    evidence: dict

    created_at: datetime

    model_config = {"from_attributes": True}


class VerificationListResponse(BaseModel):
    items: list[VerificationRead]
    total: int
    limit: int
    offset: int
