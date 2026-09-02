"""Pydantic response schemas for investigation reasoning.

Mirrors the FACT/INFERENCE separation app.schemas.investigation already
establishes for Phase 3: everything in this module is inference (a
hypothesis), never a fact. A hypothesis's `confidence` is a bounded,
model-derived qualitative judgment -- "high" | "medium" | "low" -- and is
NEVER a calibrated statistical probability; nothing in this codebase
computes it from historical accuracy. Treat it as "how strongly the model
itself asserted this", not "P(this hypothesis is correct)".
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ConfidenceLevel = Literal["high", "medium", "low"]

# See app.domain.reasoning module docstring for exactly when each status is
# produced.
ReasoningStatus = Literal[
    "completed",
    "insufficient_evidence",
    "unavailable",
    "invalid_output",
    "no_valid_hypotheses",
]


class Hypothesis(BaseModel):
    """One ranked, evidence-grounded candidate explanation.

    This is inference, not fact -- see the FACT/INFERENCE/UNCERTAINTY
    distinction in README section 5. Every id in supporting_evidence /
    contradicting_evidence is guaranteed (by app.domain.reasoning, before
    this object is ever constructed) to reference an event_id that exists
    in the parent investigation's own evidence -- this schema does not
    re-validate that itself, it only shapes already-validated data.
    """

    hypothesis_id: str
    rank: int
    title: str
    explanation: str
    confidence: ConfidenceLevel
    supporting_evidence: list[uuid.UUID]
    contradicting_evidence: list[uuid.UUID]
    uncertainty: str


class InvestigationReasoningRead(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID

    # --- INFERENCE, and its outcome ---
    status: ReasoningStatus
    hypotheses: list[Hypothesis]

    # --- UNCERTAINTY / failure context ---
    # Set only when status is "unavailable" or "invalid_output". A short,
    # sanitized, human-readable reason -- never a raw provider error or raw
    # provider output (see app.domain.reasoning).
    failure_reason: str | None

    created_at: datetime

    model_config = {"from_attributes": True}
