"""Controlled evaluation of Phase 4/9 reasoning output.

This is measurement only, never production reasoning execution: this
module is not imported by app.routers.investigations, app.domain.reasoning,
or app.providers.reasoning, and it never calls a reasoning provider,
queries the database, or mutates an InvestigationReasoning row. It exists
to answer one narrow question -- "did the actual, already-persisted
reasoning output for this controlled scenario behave the way it is
supposed to?" -- against a fixed, human-authored expectation, never a
computed/invented accuracy number.

Inputs:
  - ReasoningResultInput: the three fields this module reads off an
    already-produced reasoning result (status, hypotheses, failure_reason).
    Deliberately not a dependency on app.models.investigation_reasoning or
    SQLAlchemy -- from_persisted() below builds one from any object that
    exposes those three attributes (an ORM row, a
    schemas.reasoning.InvestigationReasoningRead, or a test double), so
    this module has no ORM/DB coupling in either direction.
  - EvaluationCase: the controlled, human-authored "expected answer" for
    one investigation scenario -- what a correct reasoning result for that
    scenario's known evidence should look like. Never derived from a live
    model call itself.

Output: EvaluationReport. `expected_status_matched` / `actual_status` are
the one cross-cutting, always-present comparison (whether the persisted
status was the one this scenario was expected to produce); `checks` is one
CheckResult per applicable category below -- a category is skipped (never
fabricated as a pass) when it does not apply to the result's actual
status, e.g. hypothesis-shape checks only run when status == "completed",
since every other status persists an empty hypotheses list by construction
(see app.domain.reasoning.run_reasoning). `passed` is true only when the
status matched AND every applicable check passed.

The categories below are the fixed vocabulary this module measures
against; each maps to an existing, already-implemented FIN-SCOPE
invariant -- this module re-verifies that the invariant actually held on
real output, it does not implement new reasoning/validation logic of its
own:
  - evidence_grounding: every supporting_evidence citation in a completed
    result's hypotheses is one of the case's own controlled
    valid_evidence_ids.
  - invalid_evidence_reference_handling: when a case is a known "this
    scenario contains a bad evidence reference" scenario (expected_status
    == "invalid_output"), the persisted status actually shows the
    whole-response rejection app.domain.reasoning._validate_hypotheses
    performs -- not a silently-accepted partial result. (Folded into
    expected_status_matched for that one case, since status alone is what
    this property is; see EvaluationCase docstring.)
  - unsupported_claim_handling: every persisted hypothesis carries at
    least one supporting_evidence citation (the measurable, deterministic
    proxy this codebase already uses for "not an unsupported claim" -- see
    app.domain.reasoning._validate_hypotheses).
  - hypothesis_structure: non-empty title/explanation, non-empty and
    unique hypothesis_id, positive and unique rank, and (for a
    non-completed status) that no hypotheses were persisted at all.
  - confidence_handling: every hypothesis's confidence is one of
    app.domain.reasoning.CONFIDENCE_LEVELS -- imported, never redefined
    here, so this module cannot silently drift from the real rule.
  - contradiction_handling: contradicting_evidence citations are grounded
    exactly like supporting_evidence citations -- a hypothesis cannot
    "contradict" evidence that does not exist either.
  - insufficient_evidence_handling: when a case expects
    "insufficient_evidence", the result actually persisted that status
    with no hypotheses. (Status match itself also folds into
    expected_status_matched; this check additionally re-verifies the
    "no hypotheses" shape.)
  - deterministic_reasoning_boundary: no hypothesis carries a field this
    codebase treats as deterministic-financial-authority data (amount,
    currency, simulation/decision/policy/action outcomes, ...) -- checked
    unconditionally, on every case, regardless of status. This is the one
    check standing in structurally for the Phase 9 invariant that Claude
    must never become a source of financial truth.
  - failure_behavior: for "unavailable"/"invalid_output", a sanitized,
    non-empty failure_reason is present and shows no sign of the specific
    upstream-detail leak app.providers.reasoning.HostedReasoningProvider
    already guards against (see apps/api/tests/test_reasoning_provider.py).
    For "completed"/"no_valid_hypotheses", failure_reason must be None
    (matches app.domain.reasoning.run_reasoning's actual persistence). For
    "insufficient_evidence", a failure_reason IS expected to be present
    (run_reasoning always sets one, a fixed non-secret explanatory
    string -- see its own module docstring) -- checked for leak markers if
    present, but never required to be absent.
  - uncertainty_articulation: every completed hypothesis's `uncertainty`
    field (see app.schemas.reasoning.Hypothesis, and the system prompt in
    app.providers.reasoning requiring the model to "name what would make
    this hypothesis more or less certain") is actually non-empty -- this
    goes beyond the "at minimum" category list because the Phase 9 testing
    requirements call it out explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.reasoning import CONFIDENCE_LEVELS

ReasoningStatus = Literal[
    "completed",
    "insufficient_evidence",
    "unavailable",
    "invalid_output",
    "no_valid_hypotheses",
]

EvaluationCategory = Literal[
    "evidence_grounding",
    "unsupported_claim_handling",
    "hypothesis_structure",
    "confidence_handling",
    "contradiction_handling",
    "insufficient_evidence_handling",
    "deterministic_reasoning_boundary",
    "failure_behavior",
    "uncertainty_articulation",
]

# Statuses whose failure_reason is expected to be a real, sanitized
# explanation of a genuine failure -- see app.domain.reasoning.run_reasoning
# and the leak-sanitization app.providers.reasoning.HostedReasoningProvider
# already performs.
_FAILURE_STATUSES = frozenset({"unavailable", "invalid_output"})

# insufficient_evidence also always carries a failure_reason in the real
# pipeline (a fixed, non-secret explanatory string), unlike "completed" /
# "no_valid_hypotheses" which always persist failure_reason=None -- see
# app.domain.reasoning.run_reasoning. Grouped separately from
# _FAILURE_STATUSES because it is not itself a failure mode.
_EXPLAINED_NON_FAILURE_STATUSES = frozenset({"insufficient_evidence"})

# Fields a hypothesis dict must never carry. If a provider's output ever
# smuggled one of these past app.domain.reasoning's validation, that would
# BE Claude becoming a source of financial truth -- the one Phase 9
# invariant that is never allowed to regress. Deliberately broader than
# what today's schema (app.schemas.reasoning.Hypothesis) even allows, so
# this check keeps working as a structural guard even if the schema
# changes later.
_FORBIDDEN_FINANCIAL_FIELDS = frozenset(
    {
        "amount",
        "currency",
        "financial_impact",
        "exposure",
        "recovery",
        "simulation_result",
        "decision",
        "authorized",
        "action",
        "policy",
    }
)

# Substrings that would indicate a sanitized failure_reason is not actually
# sanitized -- mirrors exactly what
# apps/api/tests/test_reasoning_provider.py already locks in for
# HostedReasoningProvider's own error handling; this module re-checks the
# same property one layer up, against the real persisted failure_reason.
_LEAK_MARKERS = ("api_key", "x-api-key", "sk-ant", "account (", "acct_")


@dataclass(frozen=True)
class ReasoningResultInput:
    """The subset of a persisted reasoning result this module reads."""

    status: str
    hypotheses: list[dict[str, Any]]
    failure_reason: str | None


def from_persisted(reasoning: Any) -> ReasoningResultInput:
    """Build a ReasoningResultInput from anything exposing status /
    hypotheses / failure_reason attributes -- an InvestigationReasoning ORM
    row, an InvestigationReasoningRead schema instance, or a test double.
    Read-only: never mutates `reasoning`.
    """
    return ReasoningResultInput(
        status=reasoning.status,
        hypotheses=list(reasoning.hypotheses),
        failure_reason=reasoning.failure_reason,
    )


@dataclass(frozen=True)
class EvaluationCase:
    """A controlled, human-authored expectation for one investigation
    scenario -- never derived from a live model call.

    `expected_status` alone carries "was this an invalid-evidence-reference
    scenario correctly rejected" / "was this correctly judged insufficient
    evidence" / etc. -- those are status values, so expecting one IS
    expecting that specific handling.
    """

    case_id: str
    description: str
    expected_status: ReasoningStatus
    valid_evidence_ids: frozenset[str] = field(default_factory=frozenset)
    min_hypotheses: int = 0


@dataclass(frozen=True)
class CheckResult:
    category: EvaluationCategory
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvaluationReport:
    case_id: str
    passed: bool
    expected_status_matched: bool
    actual_status: str
    checks: tuple[CheckResult, ...]

    def failed_checks(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)


def evaluate(result: ReasoningResultInput, case: EvaluationCase) -> EvaluationReport:
    """Run every applicable check for `case` against the actual
    already-produced `result`. Pure function -- no I/O, no provider call,
    no database access -- so it is safe to call from an offline test and
    from a later batch-evaluation script alike, and produces the same
    report for the same (result, case) every time.
    """
    checks: list[CheckResult] = [
        _check_deterministic_boundary(result),
        _check_failure_behavior(result),
    ]

    if result.status == "completed":
        checks.append(_check_hypothesis_structure(result, case))
        checks.append(_check_evidence_grounding(result, case))
        checks.append(_check_unsupported_claims(result))
        checks.append(_check_confidence_handling(result))
        checks.append(_check_contradiction_handling(result, case))
        checks.append(_check_uncertainty_articulated(result))
    else:
        checks.append(
            CheckResult(
                category="hypothesis_structure",
                passed=result.hypotheses == [],
                detail=(
                    "no hypotheses persisted for a non-completed status, as expected"
                    if not result.hypotheses
                    else f"status {result.status!r} unexpectedly carried hypotheses"
                ),
            )
        )

    if case.expected_status == "insufficient_evidence":
        checks.append(_check_insufficient_evidence(result))

    status_matched = result.status == case.expected_status
    passed = status_matched and all(c.passed for c in checks)
    return EvaluationReport(
        case_id=case.case_id,
        passed=passed,
        expected_status_matched=status_matched,
        actual_status=result.status,
        checks=tuple(checks),
    )


def _check_deterministic_boundary(result: ReasoningResultInput) -> CheckResult:
    offending: list[tuple[Any, list[str]]] = []
    for h in result.hypotheses:
        found = _FORBIDDEN_FINANCIAL_FIELDS.intersection(h.keys())
        if found:
            offending.append((h.get("hypothesis_id"), sorted(found)))
    passed = not offending
    detail = (
        "no hypothesis carries a deterministic-financial-authority field"
        if passed
        else f"hypothesis(es) carried forbidden financial fields: {offending}"
    )
    return CheckResult("deterministic_reasoning_boundary", passed, detail)


def _check_failure_behavior(result: ReasoningResultInput) -> CheckResult:
    if result.status in _FAILURE_STATUSES:
        if not result.failure_reason or not result.failure_reason.strip():
            return CheckResult(
                "failure_behavior",
                False,
                f"status {result.status!r} has no failure_reason recorded",
            )
        return _check_no_leak(result.failure_reason)

    if result.status in _EXPLAINED_NON_FAILURE_STATUSES:
        # A failure_reason is expected here (a fixed, non-secret string --
        # see app.domain.reasoning.run_reasoning), never required to be
        # absent; still worth a defensive leak check if one is present.
        if result.failure_reason:
            return _check_no_leak(result.failure_reason)
        return CheckResult(
            "failure_behavior", True, "no failure_reason set (not required for this status)"
        )

    # "completed" / "no_valid_hypotheses": run_reasoning always persists
    # failure_reason=None for both.
    if result.failure_reason is not None:
        return CheckResult(
            "failure_behavior",
            False,
            f"failure_reason was set on a non-failure status {result.status!r}",
        )
    return CheckResult("failure_behavior", True, "no failure_reason on a non-failure status")


def _check_no_leak(failure_reason: str) -> CheckResult:
    lowered = failure_reason.lower()
    leaked = [marker for marker in _LEAK_MARKERS if marker in lowered]
    if leaked:
        return CheckResult(
            "failure_behavior",
            False,
            f"failure_reason appears to leak upstream detail (markers: {leaked})",
        )
    return CheckResult(
        "failure_behavior",
        True,
        "failure_reason present and shows no sign of leaked upstream/account detail",
    )


def _check_hypothesis_structure(result: ReasoningResultInput, case: EvaluationCase) -> CheckResult:
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_ranks: set[int] = set()

    if len(result.hypotheses) < case.min_hypotheses:
        problems.append(
            f"expected at least {case.min_hypotheses} hypothesis(es), got {len(result.hypotheses)}"
        )

    for h in result.hypotheses:
        hid = h.get("hypothesis_id")
        if not hid or not str(hid).strip():
            problems.append("hypothesis_id missing or empty")
        elif hid in seen_ids:
            problems.append(f"duplicate hypothesis_id: {hid!r}")
        else:
            seen_ids.add(hid)

        rank = h.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            problems.append(f"invalid rank on hypothesis {hid!r}: {rank!r}")
        elif rank in seen_ranks:
            problems.append(f"duplicate rank: {rank!r}")
        else:
            seen_ranks.add(rank)

        if not h.get("title") or not str(h.get("title")).strip():
            problems.append(f"empty title on hypothesis {hid!r}")
        if not h.get("explanation") or not str(h.get("explanation")).strip():
            problems.append(f"empty explanation on hypothesis {hid!r}")

    passed = not problems
    detail = "hypothesis structure is well-formed" if passed else "; ".join(problems)
    return CheckResult("hypothesis_structure", passed, detail)


def _check_evidence_grounding(result: ReasoningResultInput, case: EvaluationCase) -> CheckResult:
    ungrounded: list[tuple[Any, str]] = []
    for h in result.hypotheses:
        for event_id in h.get("supporting_evidence", []):
            if str(event_id) not in case.valid_evidence_ids:
                ungrounded.append((h.get("hypothesis_id"), str(event_id)))
    passed = not ungrounded
    detail = (
        "every supporting_evidence citation is grounded in the case's valid_evidence_ids"
        if passed
        else f"ungrounded supporting_evidence citation(s): {ungrounded}"
    )
    return CheckResult("evidence_grounding", passed, detail)


def _check_unsupported_claims(result: ReasoningResultInput) -> CheckResult:
    unsupported = [
        h.get("hypothesis_id") for h in result.hypotheses if not h.get("supporting_evidence")
    ]
    passed = not unsupported
    detail = (
        "every hypothesis cites at least one supporting_evidence entry"
        if passed
        else f"hypothesis(es) with no supporting_evidence (unsupported claim): {unsupported}"
    )
    return CheckResult("unsupported_claim_handling", passed, detail)


def _check_confidence_handling(result: ReasoningResultInput) -> CheckResult:
    invalid = [
        (h.get("hypothesis_id"), h.get("confidence"))
        for h in result.hypotheses
        if h.get("confidence") not in CONFIDENCE_LEVELS
    ]
    passed = not invalid
    detail = (
        f"every hypothesis confidence is one of {sorted(CONFIDENCE_LEVELS)}"
        if passed
        else f"hypothesis(es) with invalid confidence: {invalid}"
    )
    return CheckResult("confidence_handling", passed, detail)


def _check_contradiction_handling(
    result: ReasoningResultInput, case: EvaluationCase
) -> CheckResult:
    ungrounded: list[tuple[Any, str]] = []
    for h in result.hypotheses:
        for event_id in h.get("contradicting_evidence", []):
            if str(event_id) not in case.valid_evidence_ids:
                ungrounded.append((h.get("hypothesis_id"), str(event_id)))
    passed = not ungrounded
    detail = (
        "every contradicting_evidence citation is grounded in the case's valid_evidence_ids"
        if passed
        else f"ungrounded contradicting_evidence citation(s): {ungrounded}"
    )
    return CheckResult("contradiction_handling", passed, detail)


def _check_insufficient_evidence(result: ReasoningResultInput) -> CheckResult:
    passed = result.status == "insufficient_evidence" and result.hypotheses == []
    detail = (
        "insufficient_evidence persisted with no hypotheses, as expected"
        if passed
        else f"expected insufficient_evidence with no hypotheses, got status={result.status!r} "
        f"hypotheses={result.hypotheses!r}"
    )
    return CheckResult("insufficient_evidence_handling", passed, detail)


def _check_uncertainty_articulated(result: ReasoningResultInput) -> CheckResult:
    unarticulated = [
        h.get("hypothesis_id")
        for h in result.hypotheses
        if not h.get("uncertainty") or not str(h.get("uncertainty")).strip()
    ]
    passed = not unarticulated
    detail = (
        "every hypothesis articulates a non-empty uncertainty"
        if passed
        else f"hypothesis(es) with no articulated uncertainty: {unarticulated}"
    )
    return CheckResult("uncertainty_articulation", passed, detail)
