"""Pydantic request/response schemas for incident investigations.

Response schemas deliberately keep observed evidence (`evidence`, the
reconstructed timeline) separate from deterministic signals
(`dominant_signal_event_type`, `dominant_signal_share`, `impact_breakdown`)
so a caller can never mistake a derived heuristic for an observed fact.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class InvestigationCreate(BaseModel):
    merchant_id: uuid.UUID
    # Defaults to the current UTC time when omitted -- investigates "is
    # there an incident right now". Set explicitly to investigate a past
    # point in time instead.
    as_of: datetime | None = None


class EvidenceItem(BaseModel):
    """One observed financial event that fell inside the investigation window."""

    event_id: uuid.UUID
    event_type: str
    source: str
    external_reference: str | None
    amount: Decimal | None
    currency: str | None
    occurred_at: datetime


class ImpactBreakdownItem(BaseModel):
    """Total impact for one currency. Never mixed with another currency's total."""

    currency: str
    total_amount: Decimal
    event_count: int


class InvestigationRead(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    window_start: datetime
    window_end: datetime

    # --- FIND: observed evidence ---
    incident_detected: bool
    evidence_event_count: int
    event_type_counts: dict[str, int]
    evidence: list[EvidenceItem]

    # --- Deterministic signals (heuristics, not causal findings) ---
    dominant_signal_event_type: str | None
    dominant_signal_share: Decimal | None

    # --- IMPACT ---
    impact_breakdown: list[ImpactBreakdownItem]
    impact_amount_unknown_count: int

    created_at: datetime

    model_config = {"from_attributes": True}


class InvestigationListResponse(BaseModel):
    items: list[InvestigationRead]
    total: int
    limit: int
    offset: int
