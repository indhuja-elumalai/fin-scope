"""Investigation reasoning: evidence-grounded hypothesis generation.

This module is the one place in the codebase that turns a reasoning
provider's free-form output into something FIN-SCOPE is willing to persist
and show a user. Everything a provider returns is treated as an untrusted
claim until validated here -- never as a fact.

Where this sits relative to app.domain.investigations (Phase 3):
Phase 3 (FIND -> DOMINANT SIGNAL -> IMPACT) is fully deterministic and
produces the *evidence* this module reasons about. This module produces
*hypotheses* -- plausible, ranked, evidence-grounded explanations for that
evidence -- and is explicitly NOT causal root-cause detection. A hypothesis
is "a plausible explanation the model proposed and could ground in the
evidence it was given", never "the confirmed cause". See README section 5
for the FACT / INFERENCE / UNCERTAINTY distinction this module exists to
preserve:
  - FACT lives entirely in Investigation (Phase 3) and is never touched,
    recomputed, or overridden here.
  - INFERENCE is exactly the hypotheses this module produces.
  - UNCERTAINTY is both the per-hypothesis `uncertainty` field and, at the
    whole-result level, `status` / `failure_reason` below.

Evidence grounding (non-negotiable): a hypothesis may only cite
event_ids that already exist in the parent investigation's own persisted
evidence snapshot. `_validate_hypotheses` checks every single citation
against that set; if even one hypothesis in a response cites an event_id
that is not in that set, the ENTIRE response is rejected
(status="invalid_output") -- not silently dropped down to the hypotheses
that happened to be clean. A response that fabricated one reference is not
trustworthy evidence that its other references are real.

Status taxonomy (exactly one of these five, always distinguishable):
  - "completed": one or more validated, evidence-grounded hypotheses were
    produced and persisted.
  - "insufficient_evidence": the investigation did not detect an incident
    (see Investigation.incident_detected) -- there is nothing to explain
    yet, so no provider call is made at all. Deterministic, provider-
    independent, mirrors Phase 3's own FIND boundary rather than inventing
    a second threshold.
  - "unavailable": no provider is configured, or the provider could not be
    reached / timed out / returned a non-2xx / returned a non-JSON body.
    An infrastructure-level failure, not a judgment about the evidence.
    Retrying later may succeed.
  - "invalid_output": the provider responded, but its structured output
    failed validation (malformed shape, missing/invalid field, duplicate
    hypothesis_id or rank, invalid confidence, or an evidence reference
    that does not exist in this investigation). Rejected outright, per the
    evidence-grounding rule above.
  - "no_valid_hypotheses": the provider responded with a *validly shaped*
    but empty hypotheses list (the provider itself judged the evidence too
    ambiguous to hypothesize about -- see the system prompt in
    app.providers.reasoning). Distinct from "invalid_output": this is a
    well-formed "I don't have one", not a rejected claim.

Idempotency / re-run semantics: every call to run_reasoning() inserts a new
InvestigationReasoning row; nothing is ever updated in place. See
app.models.investigation_reasoning for why (evidence can change between
runs, and Investigation itself follows the same append-only pattern). The
API's GET endpoint (app.routers.investigations) returns the most recent row
for a given investigation.

Financial-truth / AI-boundary invariant this module upholds structurally,
not just by convention: this module never imports FinancialEvent or
Investigation's mutation path, never calls db.add/db.merge on either, and
never recomputes amounts, currencies, counts, or timestamps -- it only
reads an already-persisted Investigation and writes new
InvestigationReasoning / AuditLog rows. There is no code path here that can
alter deterministic financial state, execute an action, or bypass policy.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.investigation import Investigation
from app.models.investigation_reasoning import InvestigationReasoning
from app.providers.reasoning import (
    EvidenceRef,
    RawHypothesis,
    ReasoningContext,
    ReasoningProvider,
    ReasoningProviderError,
)

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})


class InvestigationNotFoundError(Exception):
    """Raised when reasoning is requested for an investigation that does not exist."""


class _HypothesisValidationError(Exception):
    """Internal only: raised by _validate_hypotheses, caught by run_reasoning."""


def build_context(investigation: Investigation) -> ReasoningContext:
    """The controlled, read-only view of an investigation a provider may see.

    Built exclusively from fields already persisted on `investigation` --
    this function does not query financial_events or any other table, which
    is what makes the "no arbitrary database access" guarantee in
    app.providers.reasoning true in practice, not just in the docstring.
    """
    return ReasoningContext(
        investigation_id=str(investigation.id),
        incident_detected=investigation.incident_detected,
        evidence_event_count=investigation.evidence_event_count,
        event_type_counts=dict(investigation.event_type_counts),
        dominant_signal_event_type=investigation.dominant_signal_event_type,
        dominant_signal_share=(
            str(investigation.dominant_signal_share)
            if investigation.dominant_signal_share is not None
            else None
        ),
        impact_breakdown=list(investigation.impact_breakdown),
        impact_amount_unknown_count=investigation.impact_amount_unknown_count,
        evidence=[
            EvidenceRef(
                event_id=item["event_id"],
                event_type=item["event_type"],
                source=item["source"],
                amount=item["amount"],
                currency=item["currency"],
                occurred_at=item["occurred_at"],
            )
            for item in investigation.evidence
        ],
    )


def _validate_hypotheses(
    raw_hypotheses: list[RawHypothesis], valid_evidence_ids: set[str]
) -> list[dict]:
    """Validate and shape raw provider hypotheses, or reject the whole batch.

    Raises _HypothesisValidationError (rejecting the entire response) if any
    single hypothesis violates any rule below -- see the module docstring
    for why this is whole-response rejection rather than per-hypothesis
    filtering. Returns [] (not an error) when given an empty, validly-shaped
    list -- the caller distinguishes that as "no_valid_hypotheses".
    """
    seen_ids: set[str] = set()
    seen_ranks: set[int] = set()
    validated: list[dict] = []

    for h in raw_hypotheses:
        if not h.hypothesis_id or not h.hypothesis_id.strip():
            raise _HypothesisValidationError("hypothesis_id must be non-empty")
        if h.hypothesis_id in seen_ids:
            raise _HypothesisValidationError(f"duplicate hypothesis_id: {h.hypothesis_id!r}")
        seen_ids.add(h.hypothesis_id)

        if isinstance(h.rank, bool) or not isinstance(h.rank, int) or h.rank < 1:
            raise _HypothesisValidationError(
                f"rank must be a positive integer, got {h.rank!r}"
            )
        if h.rank in seen_ranks:
            raise _HypothesisValidationError(f"duplicate rank: {h.rank!r}")
        seen_ranks.add(h.rank)

        if not h.title or not h.title.strip():
            raise _HypothesisValidationError("title must be non-empty")
        if not h.explanation or not h.explanation.strip():
            raise _HypothesisValidationError("explanation must be non-empty")

        if h.confidence not in CONFIDENCE_LEVELS:
            raise _HypothesisValidationError(
                f"confidence must be one of {sorted(CONFIDENCE_LEVELS)}, got {h.confidence!r}"
            )

        # Evidence grounding -- the non-negotiable rule. Any reference that
        # is not one of this investigation's own evidence event_ids
        # invalidates the entire response.
        for event_id in (*h.supporting_evidence, *h.contradicting_evidence):
            if event_id not in valid_evidence_ids:
                raise _HypothesisValidationError(
                    f"hypothesis {h.hypothesis_id!r} cites an evidence event_id that does not "
                    "exist in this investigation"
                )

        if not h.supporting_evidence:
            raise _HypothesisValidationError(
                f"hypothesis {h.hypothesis_id!r} has no supporting_evidence -- every hypothesis "
                "must be grounded in at least one observed evidence event"
            )

        validated.append(
            {
                "hypothesis_id": h.hypothesis_id,
                "rank": h.rank,
                "title": h.title,
                "explanation": h.explanation,
                "confidence": h.confidence,
                "supporting_evidence": list(h.supporting_evidence),
                "contradicting_evidence": list(h.contradicting_evidence),
                "uncertainty": h.uncertainty,
            }
        )

    validated.sort(key=lambda item: item["rank"])
    return validated


def _persist(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    status: str,
    hypotheses: list[dict],
    failure_reason: str | None,
    actor: str,
) -> InvestigationReasoning:
    reasoning = InvestigationReasoning(
        investigation_id=investigation_id,
        status=status,
        hypotheses=hypotheses,
        failure_reason=failure_reason,
    )
    db.add(reasoning)
    db.flush()

    # Deliberately excludes raw provider output/prompts from the audit
    # trail (see app.models.audit_log and README section on auditability) --
    # only the outcome shape is recorded, the same restraint
    # investigation_completed already applies to Investigation.
    db.add(
        AuditLog(
            event_type="investigation_reasoning_completed",
            entity_type="investigation_reasoning",
            entity_id=str(reasoning.id),
            actor=actor,
            payload={
                "investigation_id": str(investigation_id),
                "status": status,
                "hypothesis_count": len(hypotheses),
            },
        )
    )
    db.commit()
    db.refresh(reasoning)
    return reasoning


def run_reasoning(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    provider: ReasoningProvider | None,
) -> InvestigationReasoning:
    """Run reasoning over one investigation's persisted evidence and persist
    the (possibly empty, possibly failed) result. Always persists -- a
    reasoning attempt is itself an auditable act, the same principle
    Investigation already follows for its own runs.

    `provider` is injected by the caller (see
    app.routers.investigations.get_reasoning_provider) rather than
    constructed here, specifically so tests can supply a fake provider
    without any network access or real credentials -- this function never
    imports or constructs app.providers.reasoning.HostedReasoningProvider
    itself. `provider=None` means "no provider is configured" and always
    yields status="unavailable" without attempting any call.

    Raises InvestigationNotFoundError if the investigation does not exist.
    Never raises for any reasoning-specific failure -- those are always
    represented as a persisted status, per the project's failure-handling
    requirement that reasoning failures must never destroy or block access
    to the underlying (Phase 3) investigation data.
    """
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise InvestigationNotFoundError(investigation_id)

    if not investigation.incident_detected:
        return _persist(
            db,
            investigation_id=investigation_id,
            status="insufficient_evidence",
            hypotheses=[],
            failure_reason=(
                "no incident was detected for this investigation -- there is no evidence "
                "pattern to reason about yet"
            ),
            actor="system",
        )

    if provider is None:
        return _persist(
            db,
            investigation_id=investigation_id,
            status="unavailable",
            hypotheses=[],
            failure_reason="reasoning provider is not configured",
            actor="system",
        )

    context = build_context(investigation)
    valid_evidence_ids = {item["event_id"] for item in investigation.evidence}

    try:
        raw_result = provider.generate_hypotheses(context)
    except ReasoningProviderError as exc:
        return _persist(
            db,
            investigation_id=investigation_id,
            status="unavailable",
            hypotheses=[],
            failure_reason=str(exc),
            actor="ai",
        )

    try:
        validated = _validate_hypotheses(raw_result.hypotheses, valid_evidence_ids)
    except _HypothesisValidationError as exc:
        return _persist(
            db,
            investigation_id=investigation_id,
            status="invalid_output",
            hypotheses=[],
            failure_reason=str(exc),
            actor="ai",
        )

    if not validated:
        return _persist(
            db,
            investigation_id=investigation_id,
            status="no_valid_hypotheses",
            hypotheses=[],
            failure_reason=None,
            actor="ai",
        )

    return _persist(
        db,
        investigation_id=investigation_id,
        status="completed",
        hypotheses=validated,
        failure_reason=None,
        actor="ai",
    )


def get_latest_reasoning(
    db: Session, investigation_id: uuid.UUID
) -> InvestigationReasoning | None:
    """The most recent reasoning result for an investigation, if any has run."""
    stmt = (
        select(InvestigationReasoning)
        .where(InvestigationReasoning.investigation_id == investigation_id)
        .order_by(InvestigationReasoning.created_at.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()
