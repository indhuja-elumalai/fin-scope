"""Pydantic response schemas for Phase 10, Milestone 3's real Razorpay
TEST action.

Mirrors app.schemas.action's shape exactly: no request schema exists in
this module at all -- action creation (see app.routers.investigations)
takes no client-supplied body, the same bodyless-POST convention
create_action/create_decision/create_verification already establish.
Authorization is always re-derived entirely server-side from the
persisted decision named by decision_id in the URL; there is structurally
no field a client could use to submit "status": "executed", an amount, a
currency, an order id, or an authorization/policy decision, even if it
tried -- see app.domain.razorpay_action.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

RazorpayActionStatus = Literal["pending", "executed", "rejected"]


class RazorpayActionRead(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID
    decision_id: uuid.UUID

    # "pending" | "executed" | "rejected" -- see
    # app.models.investigation_razorpay_action for exactly what each
    # means, and app.domain.razorpay_action module docstring for why
    # "pending" is a real, persistable, at-rest status (not just a
    # transient in-memory state) for this action, unlike Phase 7's
    # sandbox ActionStatus which has no such state.
    status: RazorpayActionStatus
    rejection_reason: str | None

    scenario: str | None
    simulation_id: uuid.UUID | None

    # Frozen copy of the authorizing decision's own policy_decision --
    # mirrors app.schemas.action.ActionRead.policy_decision_snapshot
    # exactly.
    policy_decision_snapshot: str | None

    # --- REAL RAZORPAY TEST ORDER LINKAGE --- None until status ==
    # "executed". This is a NEW, independent Razorpay TEST Order --
    # never a retry of any specific existing payment (see module
    # docstring in app.domain.razorpay_action for the semantic-honesty
    # rule this field's presence must never be allowed to violate).
    razorpay_order_id: str | None
    razorpay_receipt: str | None

    executor_version: str

    # --- MINIMAL, ALLOWLISTED RAZORPAY RESPONSE FIELDS --- {} when
    # status != "executed". Never the full raw Razorpay response, and
    # never a credential/header-shaped value -- see
    # app.domain.razorpay_action.run_razorpay_action.
    raw_response: dict

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RazorpayActionListResponse(BaseModel):
    items: list[RazorpayActionRead]
    total: int
    limit: int
    offset: int
