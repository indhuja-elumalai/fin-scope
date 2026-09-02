"""Deterministic policy evaluation for Phase 6 decisions.

Policy answers a different question from decision evaluation (see
app.domain.decision_evaluation): not "which candidate is preferable" but
"are we allowed to autonomously choose the already-selected candidate".
This module never re-ranks candidates and never substitutes a runner-up
after blocking the preferred one -- app.domain.decisions calls
evaluate_policy exactly once, on exactly the single candidate
app.domain.decision_evaluation already selected. A scenario can be
PREFERRED and simultaneously BLOCKED; Phase 6 ends at that boundary and
performs no financial action.

No LLM call, no network dependency, no random behavior, no hidden mutable
state anywhere in this module. Given the same candidate and the same
PolicyConfig, evaluate_policy always returns the same PolicyResult.

Policy configuration is centralized here as one versioned, immutable
PolicyConfig -- never a magic number scattered across the router, other
domain modules, schemas, or the frontend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.decision_evaluation import CandidateInput

POLICY_VERSION = "1"

ALLOWED = "ALLOWED"
REQUIRES_HUMAN_APPROVAL = "REQUIRES_HUMAN_APPROVAL"
BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class PolicyConfig:
    """Centralized, versioned policy configuration -- see module
    docstring. The threshold/limit values in DEFAULT_POLICY_CONFIG below
    are DEMONSTRATION values, not statistically validated production
    safety limits -- the same caveat app.domain.simulation._DEFAULT_ASSUMPTIONS
    documents for success_rate/scope_fraction. They exist so the policy
    MECHANISM (a real, testable, versioned threshold engine) is genuine,
    not because these exact numbers have been calibrated against real
    merchant data.
    """

    version: str
    autonomous_exposure_threshold_by_currency: dict[str, Decimal]
    max_autonomous_eligible_event_count: int
    prohibited_scenarios: frozenset[str]


# See PolicyConfig docstring -- demonstration values only, not
# production-calibrated. INR/USD are the two currencies exercised by the
# existing Phase 1-5 test fixtures and README examples.
DEFAULT_POLICY_CONFIG = PolicyConfig(
    version=POLICY_VERSION,
    autonomous_exposure_threshold_by_currency={
        "INR": Decimal("5000"),
        "USD": Decimal("100"),
    },
    max_autonomous_eligible_event_count=25,
    # Empty by design: no scenario is prohibited yet. The mechanism exists
    # for a future, explicitly-approved addition -- not populated here
    # merely to have an example (see Phase 6 correction #8).
    prohibited_scenarios=frozenset(),
)


@dataclass(frozen=True)
class PolicyResult:
    decision: str  # ALLOWED | REQUIRES_HUMAN_APPROVAL | BLOCKED
    reasons: list[str] = field(default_factory=list)
    policy_version: str = POLICY_VERSION


def evaluate_policy(
    candidate: CandidateInput, config: PolicyConfig = DEFAULT_POLICY_CONFIG
) -> PolicyResult:
    """Authorize (or not) the single already-selected `candidate`.

    Precedence, most to least restrictive -- BLOCKED > REQUIRES_HUMAN_APPROVAL
    > ALLOWED, first-match-wins for BLOCKED:

      BLOCKED -- categorically prohibited or structurally invalid; a human
      approving would not make these acceptable, so REQUIRES_HUMAN_APPROVAL
      is never offered for these:
        - candidate.status != "completed" (defense in depth --
          app.domain.decisions only ever builds candidates from completed
          simulations, but this function never trusts that blindly)
        - candidate.scenario in config.prohibited_scenarios

      REQUIRES_HUMAN_APPROVAL -- a legitimate, complete candidate, but a
      configured consequential-risk condition applies. Every applicable
      reason is collected, not just the first:
        - candidate.projected_exposure_amount_unknown_count > 0 (an
          unknown amount is never guessed as zero -- see
          app.domain.simulation -- so it can never be proven to be within
          threshold either)
        - candidate.eligible_event_count exceeds
          config.max_autonomous_eligible_event_count (intervention scope)
        - any currency in candidate.projected_exposure_by_currency exceeds
          its configured autonomous threshold, OR has no configured
          threshold at all -- an unconfigured currency is never treated as
          autonomously safe (Phase 6 correction #7); exactly-at-threshold
          is treated as within bounds (a strict `>` comparison), never
          triggering approval on its own.

      ALLOWED -- only when every configured safety condition above passes.
    """
    if candidate.status != "completed":
        return PolicyResult(
            decision=BLOCKED,
            reasons=["candidate simulation is not in a completed state"],
            policy_version=config.version,
        )
    if candidate.scenario in config.prohibited_scenarios:
        return PolicyResult(
            decision=BLOCKED,
            reasons=[f"scenario {candidate.scenario} is prohibited by policy"],
            policy_version=config.version,
        )

    reasons: list[str] = []

    if candidate.projected_exposure_amount_unknown_count > 0:
        reasons.append(
            "projected exposure includes "
            f"{candidate.projected_exposure_amount_unknown_count} event(s) with an "
            "unknown amount"
        )

    if candidate.eligible_event_count > config.max_autonomous_eligible_event_count:
        reasons.append(
            f"intervention scope ({candidate.eligible_event_count} eligible events) "
            f"exceeds the autonomous limit ({config.max_autonomous_eligible_event_count})"
        )

    for currency, amount in sorted(candidate.projected_exposure_by_currency.items()):
        threshold = config.autonomous_exposure_threshold_by_currency.get(currency)
        if threshold is None:
            reasons.append(f"no autonomous exposure threshold is configured for {currency}")
        elif amount > threshold:
            reasons.append(
                f"projected {currency} exposure ({amount}) exceeds the autonomous "
                f"threshold ({threshold})"
            )

    if reasons:
        return PolicyResult(
            decision=REQUIRES_HUMAN_APPROVAL, reasons=reasons, policy_version=config.version
        )

    return PolicyResult(
        decision=ALLOWED,
        reasons=["all configured autonomous safety conditions were satisfied"],
        policy_version=config.version,
    )
