"""Deterministic decision evaluation: comparing SIMULATION results.

This module answers exactly one question: "given a set of already-computed
Phase 5 simulation results (one per scenario), which is preferable?" It is
NOT authorization -- see app.domain.policy for "are we allowed to choose
that candidate", a completely separate concern this module never touches.
No LLM call, no network dependency, no random behavior anywhere in this
module. Given the same candidates, evaluate_candidates always returns the
same EvaluationResult.

Financial-truth invariant this module upholds structurally: it never sums
an amount across currencies and never invents a weighted/percentage score
("Scenario A is 82% better"). Every comparison stage below is either
currency-free (a count) or restricted to a single common currency; when a
tie cannot be broken without comparing across currencies, this module says
so explicitly (see the `reason` text) and falls back to a fixed,
documented tie-break instead of scalarizing.

This module never queries a database and never imports a SQLAlchemy model
-- see app.domain.decisions for the orchestration that loads
InvestigationSimulation rows and reduces each to a CandidateInput via
build_candidate before calling evaluate_candidates.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

# Bumped whenever the comparison algorithm below changes in a way that
# could change which candidate is preferred for the same input -- see
# app.models.investigation_decision.InvestigationDecision.evaluation_version.
EVALUATION_VERSION = "1"

# Fixed, documented scenario priority used ONLY as the final deterministic
# tie-break in evaluate_candidates -- never as a primary ranking metric.
# Mirrors the frontend's own SCENARIO_ORDER constant
# (apps/web/app/investigations/[id]/page.tsx). Rationale: when outcomes are
# genuinely indistinguishable by the metrics below, prefer the least
# interventionist option -- DO_NOTHING is deliberately first.
SCENARIO_PRIORITY: tuple[str, ...] = (
    "DO_NOTHING",
    "RETRY_AFFECTED_PAYMENTS",
    "REROUTE_PROVIDER",
    "TARGET_AFFECTED_EVENT_TYPE",
)


@dataclass(frozen=True)
class CandidateInput:
    """One scenario's latest completed simulation, reduced to exactly the
    fields evaluate_candidates (and, downstream, app.domain.policy) need.
    Built by build_candidate from app.domain.simulation's own persisted
    result shape -- this module never re-derives these numbers itself, it
    only compares numbers Phase 5 already computed.
    """

    simulation_id: uuid.UUID
    scenario: str
    status: str
    failed_event_count_delta: int
    estimated_recovery_by_currency: dict[str, Decimal]
    # PROJECTED FINANCIAL EXPOSURE -- from Phase 5's result.projected
    # (SimulationScopeSnapshot.exposure_by_currency), never a proxy derived
    # from estimated_recovery_by_currency. See app.domain.policy for why
    # this specific field, not recovery, is what policy thresholds apply
    # to.
    projected_exposure_by_currency: dict[str, Decimal]
    projected_exposure_amount_unknown_count: int
    eligible_event_count: int


@dataclass(frozen=True)
class EvaluationResult:
    candidates: list[CandidateInput]
    preferred: CandidateInput | None
    reason: str


def build_candidate(
    *, simulation_id: uuid.UUID, scenario: str, status: str, result: dict
) -> CandidateInput:
    """Build a CandidateInput from one InvestigationSimulation row's own
    `scenario`, `status`, and `result` fields -- see
    app.schemas.simulation.SimulationResultDetail for the exact shape of
    `result`. Callers must only pass a `result` produced for
    status="completed" (result is `{}` otherwise, see
    app.domain.simulation.run_simulation); app.domain.decisions.run_decision
    only ever selects status="completed" simulations as candidates.

    Per the Phase 6 exposure-metric correction: exposure is read from
    `result["projected"]["exposure_by_currency"]` -- the PROJECTED
    FINANCIAL EXPOSURE Phase 5 already computes -- never approximated from
    `estimated_recovery_by_currency`. Recovery and exposure answer
    different questions: recovery is how much of the eligible exposure the
    scenario is projected to recover; exposure is what remains at risk
    afterward. Policy (app.domain.policy) reasons about exposure, not
    recovery.
    """
    projected = result["projected"]
    return CandidateInput(
        simulation_id=simulation_id,
        scenario=scenario,
        status=status,
        failed_event_count_delta=result["delta"]["failed_event_count_delta"],
        estimated_recovery_by_currency={
            item["currency"]: Decimal(item["amount"])
            for item in result["estimated_recovery_by_currency"]
        },
        projected_exposure_by_currency={
            item["currency"]: Decimal(item["amount"])
            for item in projected["exposure_by_currency"]
        },
        projected_exposure_amount_unknown_count=projected["exposure_amount_unknown_count"],
        eligible_event_count=result["eligible_event_count"],
    )


def _scenario_priority_index(scenario: str) -> int:
    try:
        return SCENARIO_PRIORITY.index(scenario)
    except ValueError:
        # Every scenario reaching this module has already passed Phase 5's
        # own SCENARIOS validation (see app.domain.simulation) -- this
        # should not be reachable via the API. Sorts last rather than
        # raising, so a future scenario added to Phase 5 but not yet to
        # SCENARIO_PRIORITY degrades to "always loses ties" instead of
        # crashing decision evaluation.
        return len(SCENARIO_PRIORITY)


def evaluate_candidates(candidates: list[CandidateInput]) -> EvaluationResult:
    """Compare `candidates` (one per scenario, already reduced to the
    metrics Phase 5 computed) and pick exactly one preferred candidate,
    deterministically and reproducibly. See module docstring for the
    currency-safety invariant this function upholds.

    Three ordered stages; stops at the first stage that produces a single
    winner:
      1. Fewest projected failed events remaining
         (`failed_event_count_delta`, ascending -- most negative wins).
         Currency-free, always computable, so it is checked first.
      2. Highest projected recovery -- ONLY evaluated when every
         still-tied candidate's nonzero recovery entries share a single
         common currency. If the tied set's recovery spans more than one
         currency, this stage is skipped entirely (never scalarized, never
         an invented exchange rate) and stage 3 decides instead.
      3. Fixed scenario priority (SCENARIO_PRIORITY) -- the least
         interventionist tied scenario wins. Never UUID order, row order,
         insertion timing, or hash order.
    """
    ordered = sorted(candidates, key=lambda c: _scenario_priority_index(c.scenario))

    if not ordered:
        return EvaluationResult(
            candidates=[],
            preferred=None,
            reason="no completed simulation was available for any scenario",
        )

    # --- Stage 1: failed-event-count delta (currency-free) ---
    min_delta = min(c.failed_event_count_delta for c in ordered)
    stage1 = [c for c in ordered if c.failed_event_count_delta == min_delta]

    if len(stage1) == 1:
        winner = stage1[0]
        return EvaluationResult(
            candidates=ordered,
            preferred=winner,
            reason=(
                f"{winner.scenario} has the lowest projected failed-event count "
                f"among evaluated scenarios (delta {min_delta})."
            ),
        )

    # --- Stage 2: recovery, only if safely comparable in one currency ---
    currencies = {
        currency
        for c in stage1
        for currency, amount in c.estimated_recovery_by_currency.items()
        if amount != 0
    }

    tied = stage1
    if len(currencies) == 1:
        (currency,) = currencies
        max_recovery = max(
            c.estimated_recovery_by_currency.get(currency, Decimal(0)) for c in stage1
        )
        stage2 = [
            c
            for c in stage1
            if c.estimated_recovery_by_currency.get(currency, Decimal(0)) == max_recovery
        ]
        if len(stage2) == 1:
            winner = stage2[0]
            return EvaluationResult(
                candidates=ordered,
                preferred=winner,
                reason=(
                    f"{winner.scenario} has the highest projected {currency} recovery "
                    f"({max_recovery}) among scenarios tied on failed-event count."
                ),
            )
        tied = stage2

    # --- Stage 3: fixed deterministic tie-break ---
    winner = min(tied, key=lambda c: _scenario_priority_index(c.scenario))
    if len(currencies) > 1:
        reason = (
            "Tied on failed-event count, and projected recovery spans incomparable "
            f"currencies {sorted(currencies)} -- {winner.scenario} selected by fixed "
            "scenario priority (least interventionist option), not a cross-currency "
            "comparison."
        )
    else:
        reason = (
            "Outcomes were indistinguishable by the evaluated metrics -- "
            f"{winner.scenario} selected by fixed scenario priority (least "
            "interventionist option)."
        )
    return EvaluationResult(candidates=ordered, preferred=winner, reason=reason)
