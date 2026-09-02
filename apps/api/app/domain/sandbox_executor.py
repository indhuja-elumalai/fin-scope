"""Pure, deterministic sandbox executor for Phase 7 bounded actions.

This module answers one question only: "given a scenario that Phase 6 has
already authorized (ALLOWED), and the persisted Phase 5 simulation numbers
for it, what sandbox-only result should be recorded?" It is NOT
authorization -- see app.domain.actions for the orchestration that checks
a decision is ALLOWED before this module is ever called, and app.domain.policy
for where that authorization actually happens. This module trusts nothing
about authorization; it only shapes a result.

Structurally incapable of a real financial mutation: no database import, no
SQLAlchemy import, no app.models import (in particular no FinancialEvent),
no LLM/provider import, no httpx/requests import, no network call, no
filesystem write, no randomness. Given the same scenario and the same
already-persisted Phase 5 numbers, execute() always returns the same
result -- the same reproducibility discipline as
app.domain.decision_evaluation and app.domain.policy.

Financial-truth invariant this module upholds structurally: it never
recomputes exposure, recovery, or event counts -- every number in its
output is copied verbatim from the persisted Phase 5 simulation result
handed to it by app.domain.actions (itself read from
InvestigationSimulation.result, never re-derived here). This module only
relabels those already-computed numbers under a scenario-specific
action_kind plus an explicit SANDBOX-ONLY disclaimer; it never invents,
adjusts, or "improves" a single figure.
"""
from __future__ import annotations

# Bumped whenever the mapping/shape below changes in a way that could
# change the sandbox result for the same input -- see
# app.models.investigation_action.InvestigationAction.executor_version.
EXECUTOR_VERSION = "1"

# One sandbox-only disclaimer, reused verbatim in every result -- never
# reworded per call site, so it stays trivially greppable/auditable.
_SANDBOX_DISCLAIMER = (
    "SANDBOX-ONLY: this is a simulated action recorded for audit purposes. "
    "No real payment provider, bank, or financial system was contacted, and "
    "no financial_events row was modified."
)

# Fixed scenario -> action_kind mapping -- the ONLY vocabulary this module
# recognizes. Keys mirror app.domain.simulation.SCENARIOS exactly. A
# scenario outside this mapping should not be reachable in practice --
# app.domain.actions validates preferred_scenario against
# app.domain.simulation.SCENARIOS before this function is ever called --
# but this module does not trust that blindly either; see execute()'s own
# defensive check below.
SCENARIO_ACTION_KIND: dict[str, str] = {
    "DO_NOTHING": "NO_OP",
    "RETRY_AFFECTED_PAYMENTS": "SIMULATED_RETRY_PAYMENTS",
    "REROUTE_PROVIDER": "SIMULATED_REROUTE",
    "TARGET_AFFECTED_EVENT_TYPE": "SIMULATED_TARGETED_RETRY",
}


class UnsupportedScenarioError(Exception):
    """Raised for a scenario outside SCENARIO_ACTION_KIND.

    Should not be reachable via the API -- app.domain.actions only ever
    calls execute() with a scenario already validated against
    app.domain.simulation.SCENARIOS. This exists so the function is still
    safe if called directly by a future non-HTTP caller, the same
    rationale app.domain.simulation.UnsupportedScenarioError documents.
    """


def execute(
    *,
    scenario: str,
    eligible_event_ids: list[str],
    eligible_event_count: int,
    estimated_recovery_by_currency: list[dict],
) -> dict:
    """Produce a deterministic SANDBOX-ONLY result for `scenario`.

    `eligible_event_ids`, `eligible_event_count`, and
    `estimated_recovery_by_currency` must be copied verbatim from the
    already-persisted Phase 5 InvestigationSimulation.result this action is
    acting on (see app.domain.actions) -- this function performs no
    independent financial calculation of its own; it only relabels numbers
    Phase 5 already computed.

    DO_NOTHING always maps to NO_OP with empty/zeroed fields, regardless
    of what is passed in -- a sandbox action must never imply an
    intervention that did not happen (see module docstring). For the
    three executable scenarios, the eligible events and recovery figures
    are carried through unchanged under a scenario-specific action_kind.

    Raises UnsupportedScenarioError for a scenario outside
    SCENARIO_ACTION_KIND (see that class's docstring).
    """
    if scenario not in SCENARIO_ACTION_KIND:
        raise UnsupportedScenarioError(scenario)

    action_kind = SCENARIO_ACTION_KIND[scenario]

    if action_kind == "NO_OP":
        return {
            "action_kind": "NO_OP",
            "targeted_event_ids": [],
            "targeted_event_count": 0,
            "simulated_outcome_by_currency": [],
            "note": (
                "DO_NOTHING was the authorized sandbox action: an authorized "
                "sandbox no-op, not a financial intervention of any kind. "
                + _SANDBOX_DISCLAIMER
            ),
        }

    return {
        "action_kind": action_kind,
        "targeted_event_ids": list(eligible_event_ids),
        "targeted_event_count": eligible_event_count,
        "simulated_outcome_by_currency": list(estimated_recovery_by_currency),
        "note": (
            f"{scenario} was executed as a sandbox-simulated action over "
            f"{eligible_event_count} eligible event(s), reusing this "
            "investigation's own Phase 5 simulation numbers verbatim. "
            + _SANDBOX_DISCLAIMER
        ),
    }
