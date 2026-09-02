"""Pydantic response schemas for Phase 7 bounded sandbox actions.

Mirrors app.schemas.decision's separation: no request schema exists in
this module at all -- action creation (see app.routers.investigations)
takes no client-supplied body, the same shape as
create_decision/reason_about_investigation. Authorization is always
re-derived entirely server-side from the persisted Phase 6 decision named
by decision_id in the URL; there is structurally no field a client could
use to submit "status": "executed" or "action_kind": "..." even if it
tried.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ActionStatus = Literal["executed", "rejected"]


class ActionCurrencyAmount(BaseModel):
    currency: str
    amount: str


class SandboxResultDetail(BaseModel):
    """The deterministic sandbox executor's own output -- see
    app.domain.sandbox_executor.execute(). Every field here is copied
    verbatim from this action's own Phase 5 simulation, never
    independently recalculated. Empty/zeroed for a NO_OP.
    """

    action_kind: str
    targeted_event_ids: list[uuid.UUID]
    targeted_event_count: int
    simulated_outcome_by_currency: list[ActionCurrencyAmount]
    note: str


class ActionRead(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    decision_id: uuid.UUID

    # "executed" | "rejected" -- see app.models.investigation_action for
    # exactly what each means.
    status: ActionStatus
    rejection_reason: str | None

    scenario: str | None
    simulation_id: uuid.UUID | None

    # Frozen copy of the authorizing decision's own policy_decision -- see
    # app.models.investigation_action module docstring for why this is a
    # snapshot, not a live join.
    policy_decision_snapshot: str | None

    executor_version: str

    # --- SANDBOX RESULT --- {} when status == "rejected".
    sandbox_result: SandboxResultDetail | dict

    created_at: datetime

    model_config = {"from_attributes": True}


class ActionListResponse(BaseModel):
    items: list[ActionRead]
    total: int
    limit: int
    offset: int
