"""Deterministic consequence simulation: SCENARIO -> SIMULATION -> RESULT.

This module is the fifth link in the core loop:

    INVESTIGATION -> REASONING -> SCENARIO -> SIMULATION -> CONSEQUENCE RESULT

It answers one question only: "given this investigation's already-persisted
evidence, what would this scenario's deterministic assumptions project as
the consequence?" It is NOT causal root-cause analysis (that is out of
scope everywhere in this codebase) and it is NOT a forecast an LLM
generated -- there is no LLM call anywhere in this module, no network
dependency, and no random behavior. The same (investigation snapshot,
scenario, assumptions, SIMULATOR_VERSION) always produces the same result;
that reproducibility is the entire point of Phase 5.

Where this sits relative to Phase 3 (app.domain.investigations) and Phase 4
(app.domain.reasoning):
  - Phase 3 is FACT: the observed evidence and the deterministic
    dominant-signal/impact heuristics. This module reads that FACT and
    never recomputes, overrides, or re-derives it from financial_events --
    see build_input_snapshot below, which is built exclusively from an
    already-persisted Investigation row, the same discipline
    app.domain.reasoning.build_context already applies.
  - Phase 4 is INFERENCE: LLM-proposed, evidence-grounded hypotheses. A
    simulation never depends on reasoning having run or being available
    (see app.routers.investigations) -- reasoning may inform which
    scenario a human picks, but the simulator itself never reads
    InvestigationReasoning.
  - This module is neither FACT nor INFERENCE: it is a SIMULATION
    ASSUMPTION applied, deterministically, to FACT. See
    app.schemas.simulation for how the three are kept visibly distinct in
    the API response.

Financial-truth invariant this module upholds structurally: no LLM/provider
import anywhere in this file, no financial_events query, no mutation of
Investigation or FinancialEvent, and no currency is ever summed with
another (see _currency_totals). Every projected amount is derived from a
closed-form formula (eligible exposure * scope_fraction * success_rate),
never a Monte Carlo draw or an invented value -- an eligible event with an
unknown amount is counted in *_amount_unknown_count and excluded from every
sum, never coerced to zero.

Scenario eligibility (deterministic, computed only from the fields already
on Investigation -- see _eligible_events below for the exact rule per
scenario). `source` (see app.domain.events / app.models.financial_event) is
the event's own ingestion source, not a verified payment-provider/gateway
identity -- FIN-SCOPE does not persist a dedicated provider field.
REROUTE_PROVIDER uses `source` anyway, as an explicitly-labeled deterministic
proxy for "which upstream channel to route away from", because it is the
only evidence-level categorical dimension that exists for that purpose. This
is a documented modeling assumption, never presented as an observed
provider fact -- see SimulationResultDetail.scope_description, which always
spells out exactly which rule (and, for REROUTE_PROVIDER, which `source`
value) selected the eligible events for a given run, and
app.schemas.simulation for how OBSERVED FACT / SIMULATION ASSUMPTION /
PROJECTED RESULT stay visibly separate in the API response.
"""
from __future__ import annotations

import uuid
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.investigation import Investigation
from app.models.investigation_simulation import InvestigationSimulation

# Bumped whenever the calculation in _simulate below changes in a way that
# could change a result for the same input -- see
# InvestigationSimulation.simulator_version.
SIMULATOR_VERSION = "1"

SCENARIOS = frozenset(
    {"DO_NOTHING", "RETRY_AFFECTED_PAYMENTS", "REROUTE_PROVIDER", "TARGET_AFFECTED_EVENT_TYPE"}
)

# Conservative, explicitly-not-production-calibrated defaults (see module
# docstring and README) -- used whenever a caller does not override them.
# DO_NOTHING has no entry: it applies no assumption at all.
_DEFAULT_ASSUMPTIONS: dict[str, dict[str, Decimal]] = {
    "RETRY_AFFECTED_PAYMENTS": {
        "success_rate": Decimal("0.55"),
        "scope_fraction": Decimal("1.0"),
    },
    "REROUTE_PROVIDER": {
        "success_rate": Decimal("0.65"),
        "scope_fraction": Decimal("1.0"),
    },
    "TARGET_AFFECTED_EVENT_TYPE": {
        "success_rate": Decimal("0.50"),
        "scope_fraction": Decimal("1.0"),
    },
}

# Event types REROUTE_PROVIDER considers provider/gateway-related -- the
# only two evidence event types that plausibly originate from a specific
# provider/gateway rather than the merchant's own payment behavior.
_REROUTE_EVENT_TYPES = frozenset({"payment_failed", "gateway_degraded"})


class InvestigationNotFoundError(Exception):
    """Raised when a simulation is requested for an investigation that does not exist."""


class UnsupportedScenarioError(Exception):
    """Raised for a scenario value outside SCENARIOS.

    In practice app.schemas.simulation.SimulationScenario (a Literal)
    already rejects this at the API boundary with a 422 before it can
    reach here; this check exists so the domain function is still safe if
    called directly by a future non-HTTP caller, the same rationale
    app.domain.events.InvalidEventTypeError already documents.
    """


def _round_amount(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_count(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _currency_totals(events: list[dict]) -> tuple[dict[str, Decimal], int]:
    """Currency-safe totals over a list of evidence-snapshot dicts.

    Never sums across currencies. An event with a missing amount or
    currency is counted in the returned unknown-count and excluded from
    every total -- never coerced to zero (see module docstring).
    """
    totals: dict[str, Decimal] = {}
    unknown_count = 0
    for event in events:
        amount = event.get("amount")
        currency = event.get("currency")
        if amount is None or currency is None:
            unknown_count += 1
            continue
        totals[currency] = totals.get(currency, Decimal(0)) + Decimal(amount)
    return totals, unknown_count


def _affected_source(events: list[dict]) -> str | None:
    """Deterministic "most common source" among `events`, tie-broken by
    whichever tied source's first occurrence came earliest -- the same
    tie-break rule app.domain.investigations._dominant_signal uses for
    dominant_signal_event_type, applied here to `source` instead.
    """
    if not events:
        return None
    counts = Counter(e["source"] for e in events)
    max_count = max(counts.values())
    tied = [s for s, c in counts.items() if c == max_count]
    if len(tied) == 1:
        return tied[0]
    # `events` is already in occurred_at-ascending order (it is a slice of
    # Investigation.evidence, itself ordered that way -- see
    # app.domain.investigations.run_investigation).
    return next(e["source"] for e in events if e["source"] in tied)


def _eligible_events(
    scenario: str, investigation: Investigation
) -> tuple[list[dict], str]:
    """Returns (eligible_events, scope_description) for `scenario`.

    Every rule here reads only investigation.evidence /
    investigation.dominant_signal_event_type -- fields already persisted on
    the (immutable) Investigation row. Nothing here queries
    financial_events or any other table.
    """
    evidence: list[dict] = list(investigation.evidence)

    if scenario == "DO_NOTHING":
        return [], "no intervention -- no events are in scope"

    if scenario == "RETRY_AFFECTED_PAYMENTS":
        eligible = [e for e in evidence if e["event_type"] == "payment_failed"]
        return eligible, "event_type == 'payment_failed' (retryable failed payments)"

    if scenario == "REROUTE_PROVIDER":
        candidates = [e for e in evidence if e["event_type"] in _REROUTE_EVENT_TYPES]
        affected_source = _affected_source(candidates)
        eligible = [e for e in candidates if e["source"] == affected_source]
        description = (
            f"event_type in {sorted(_REROUTE_EVENT_TYPES)} and source == {affected_source!r} "
            "(the most frequent event source in that set. `source` is the event's own "
            "ingestion source -- see app.domain.events -- not a verified payment-provider/"
            "gateway identity; FIN-SCOPE does not persist one yet, so `source` is used here "
            "only as an explicitly-labeled deterministic proxy for 'which upstream channel "
            "this scenario would reroute traffic away from')"
            if affected_source is not None
            else f"event_type in {sorted(_REROUTE_EVENT_TYPES)}, but no such events exist"
        )
        return eligible, description

    if scenario == "TARGET_AFFECTED_EVENT_TYPE":
        dominant = investigation.dominant_signal_event_type
        if dominant is None:
            return (
    [],
    "no dominant signal on this investigation -- no affected event type to target",
)
        eligible = [e for e in evidence if e["event_type"] == dominant]
        return (
            eligible,
            f"event_type == {dominant!r} (this investigation's own dominant signal)",
        )

    raise UnsupportedScenarioError(scenario)


def _snapshot(events: list[dict], success_count: int, exposure_delta: dict[str, Decimal]) -> dict:
    """Build one SimulationScopeSnapshot-shaped dict (baseline or
    projected) over `events`, with `success_count` already-succeeded events
    and `exposure_delta` subtracted per currency (empty for baseline).
    """
    totals, unknown_count = _currency_totals(events)
    remaining = {
        currency: total - exposure_delta.get(currency, Decimal(0))
        for currency, total in totals.items()
    }
    return {
        "failed_event_count": len(events) - success_count,
        "success_event_count": success_count,
        "exposure_by_currency": [
            {"currency": currency, "amount": str(_round_amount(remaining[currency]))}
            for currency in sorted(remaining)
        ],
        "exposure_amount_unknown_count": unknown_count,
    }


def _simulate(
    scenario: str, investigation: Investigation, assumptions: dict[str, Decimal | None]
) -> dict:
    """The pure deterministic calculation. No DB access, no side effects --
    everything it needs is already in `investigation` and `assumptions`.
    """
    eligible_events, scope_description = _eligible_events(scenario, investigation)
    eligible_count = len(eligible_events)

    success_rate = assumptions.get("success_rate")
    scope_fraction = assumptions.get("scope_fraction")

    if eligible_count == 0 or success_rate is None or scope_fraction is None:
        # DO_NOTHING, or a scenario with nothing eligible: the trivial,
        # still-deterministic case -- baseline == projected, zero delta.
        baseline = _snapshot(eligible_events, success_count=0, exposure_delta={})
        projected = _snapshot(eligible_events, success_count=0, exposure_delta={})
        estimated_recovery: list[dict] = []
    else:
        eligible_exposure, _ = _currency_totals(eligible_events)
        scoped_count = _round_count(Decimal(eligible_count) * scope_fraction)
        success_count = _round_count(Decimal(scoped_count) * success_rate)

        recovery = {
            currency: _round_amount(amount * scope_fraction * success_rate)
            for currency, amount in eligible_exposure.items()
        }
        baseline = _snapshot(eligible_events, success_count=0, exposure_delta={})
        projected = _snapshot(eligible_events, success_count=success_count, exposure_delta=recovery)
        estimated_recovery = [
            {"currency": currency, "amount": str(amount)}
            for currency, amount in sorted(recovery.items())
            if amount != 0
        ]

    baseline_by_currency = {
        item["currency"]: Decimal(item["amount"]) for item in baseline["exposure_by_currency"]
    }
    projected_by_currency = {
        item["currency"]: Decimal(item["amount"]) for item in projected["exposure_by_currency"]
    }
    all_currencies = sorted(set(baseline_by_currency) | set(projected_by_currency))
    financial_delta = [
        {
            "currency": currency,
            "amount": str(
                projected_by_currency.get(currency, Decimal(0))
                - baseline_by_currency.get(currency, Decimal(0))
            ),
        }
        for currency in all_currencies
    ]

    return {
        "scope_description": scope_description,
        "eligible_event_count": eligible_count,
        "eligible_event_ids": [e["event_id"] for e in eligible_events],
        "baseline": baseline,
        "projected": projected,
        "estimated_recovery_by_currency": estimated_recovery,
        "delta": {
            "failed_event_count_delta": (
                projected["failed_event_count"] - baseline["failed_event_count"]
            ),
            "financial_delta_by_currency": financial_delta,
        },
    }


def _resolve_assumptions(
    scenario: str, override: dict[str, Decimal] | None
) -> dict[str, Decimal | None]:
    if scenario == "DO_NOTHING":
        return {"success_rate": None, "scope_fraction": None}
    defaults = _DEFAULT_ASSUMPTIONS[scenario]
    override = override or {}
    return {
        "success_rate": override.get("success_rate", defaults["success_rate"]),
        "scope_fraction": override.get("scope_fraction", defaults["scope_fraction"]),
    }


def build_input_snapshot(investigation: Investigation) -> dict:
    """A frozen, JSON-safe snapshot of the parent Investigation's own
    already-persisted fields -- never a re-query of financial_events. See
    module docstring.
    """
    return {
        "investigation_id": str(investigation.id),
        "merchant_id": str(investigation.merchant_id),
        "window_start": investigation.window_start.isoformat(),
        "window_end": investigation.window_end.isoformat(),
        "incident_detected": investigation.incident_detected,
        "evidence_event_count": investigation.evidence_event_count,
        "event_type_counts": dict(investigation.event_type_counts),
        "dominant_signal_event_type": investigation.dominant_signal_event_type,
        "dominant_signal_share": (
            str(investigation.dominant_signal_share)
            if investigation.dominant_signal_share is not None
            else None
        ),
        "impact_breakdown": list(investigation.impact_breakdown),
        "impact_amount_unknown_count": investigation.impact_amount_unknown_count,
        "evidence": list(investigation.evidence),
    }


def _persist(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    scenario: str,
    status: str,
    simulator_version: str,
    input_snapshot: dict,
    assumptions: dict,
    result: dict,
    failure_reason: str | None,
) -> InvestigationSimulation:
    simulation = InvestigationSimulation(
        investigation_id=investigation_id,
        scenario=scenario,
        status=status,
        simulator_version=simulator_version,
        input_snapshot=input_snapshot,
        assumptions=assumptions,
        result=result,
        failure_reason=failure_reason,
    )
    db.add(simulation)
    db.flush()

    # Deliberately excludes the full result payload from the audit trail --
    # only the outcome shape is recorded, the same restraint
    # investigation_reasoning_completed already applies (see
    # app.domain.reasoning._persist). The full result remains fully
    # reconstructable from this row itself, which is the actual audit
    # trail for a simulation.
    db.add(
        AuditLog(
            event_type="investigation_simulation_completed",
            entity_type="investigation_simulation",
            entity_id=str(simulation.id),
            actor="system",
            payload={
                "investigation_id": str(investigation_id),
                "scenario": scenario,
                "status": status,
                "simulator_version": simulator_version,
            },
        )
    )
    db.commit()
    db.refresh(simulation)
    return simulation


def run_simulation(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    scenario: str,
    assumptions_override: dict[str, Decimal] | None = None,
) -> InvestigationSimulation:
    """Run a deterministic simulation over one investigation's persisted
    evidence and persist the (always-persisted) result. Every call inserts
    a NEW row -- see app.models.investigation_simulation for why.

    A simulation never depends on Phase 4 reasoning: it reads nothing from
    InvestigationReasoning and works whether or not reasoning has ever run
    for this investigation, or whether a reasoning provider is configured.

    Raises InvestigationNotFoundError if the investigation does not exist,
    UnsupportedScenarioError for a scenario outside SCENARIOS (see that
    class's docstring for why this should not normally be reachable via
    the API). Never raises for "nothing to simulate" -- that is
    status="insufficient_evidence", a persisted result, not an exception,
    mirroring app.domain.reasoning.run_reasoning's own
    incident_detected == False short-circuit.
    """
    if scenario not in SCENARIOS:
        raise UnsupportedScenarioError(scenario)

    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise InvestigationNotFoundError(investigation_id)

    input_snapshot = build_input_snapshot(investigation)

    if scenario != "DO_NOTHING" and not investigation.incident_detected:
        return _persist(
            db,
            investigation_id=investigation_id,
            scenario=scenario,
            status="insufficient_evidence",
            simulator_version=SIMULATOR_VERSION,
            input_snapshot=input_snapshot,
            assumptions={"success_rate": None, "scope_fraction": None},
            result={},
            failure_reason=(
                "no incident was detected for this investigation -- there is no evidence "
                "to simulate a consequence over yet"
            ),
        )

    assumptions = _resolve_assumptions(scenario, assumptions_override)
    result = _simulate(scenario, investigation, assumptions)

    return _persist(
        db,
        investigation_id=investigation_id,
        scenario=scenario,
        status="completed",
        simulator_version=SIMULATOR_VERSION,
        input_snapshot=input_snapshot,
        assumptions={
            "success_rate": str(assumptions["success_rate"])
            if assumptions["success_rate"] is not None
            else None,
            "scope_fraction": str(assumptions["scope_fraction"])
            if assumptions["scope_fraction"] is not None
            else None,
        },
        result=result,
        failure_reason=None,
    )


def list_simulations(
    db: Session,
    *,
    investigation_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[InvestigationSimulation], int]:
    """Append-only simulation history for one investigation, newest first."""
    stmt = select(InvestigationSimulation).where(
        InvestigationSimulation.investigation_id == investigation_id
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(InvestigationSimulation.created_at.desc()).limit(limit).offset(offset)
    items = list(db.scalars(stmt))
    return items, total


def get_simulation(
    db: Session, *, investigation_id: uuid.UUID, simulation_id: uuid.UUID
) -> InvestigationSimulation | None:
    """A single simulation result, scoped to `investigation_id` -- a
    simulation belonging to a different investigation is treated as not
    found, never returned (see app.routers.investigations).
    """
    simulation = db.get(InvestigationSimulation, simulation_id)
    if simulation is None or simulation.investigation_id != investigation_id:
        return None
    return simulation
