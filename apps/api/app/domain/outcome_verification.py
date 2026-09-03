"""Pure, deterministic Phase 8 outcome verifier.

This module answers exactly one question: "given the EXPECTED outcome a
persisted Phase 5 simulation projected, and the OBSERVED outcome recorded
after a persisted Phase 7 sandbox action ran, did the observation match
the expectation, and by how much?" It never loads anything from the
database itself (see app.domain.verifications for that), never calls an
LLM, never makes a network call, and never uses randomness or the current
time in its decision logic -- the same (expected, observed) pair, of the
same verifier_version, always produces the same VerificationOutcome
forever. This is post-action VERIFICATION, not prediction: it compares two
already-computed snapshots, it does not forecast or judge on its own
authority.

EXPECTED vs OBSERVED, and why they are never the same data:
- EXPECTED comes from app.domain.simulation's already-persisted
  PROJECTED result (see InvestigationSimulation.result) -- "what should
  happen if this scenario is applied", a probabilistic projection using
  Phase 5's own success_rate/scope_fraction assumptions.
- OBSERVED comes from app.domain.verifications' derive_observed_snapshot(),
  which independently re-derives a per-event outcome from the already-
  persisted Phase 7 InvestigationAction.sandbox_result's own
  targeted_event_ids -- a deterministic POST-ACTION sandbox observation
  (see that function's own docstring for the exact, versioned model). It
  is never a copy of EXPECTED and never reuses Phase 5's success_rate, so
  a real mismatch is possible -- and, under the sandbox's own ~85%
  observation rate, likely -- on the production path, not only when a
  test hand-mutates a fixture.

Comparable dimensions (Phase 8 MVP, exactly the fields the approved plan
names -- no invented metrics):
  - success_count   (expected.projected_success_count vs observed.observed_success_count)
  - failure_count   (expected.projected_failure_count vs observed.observed_failure_count)
  - recovery_by_currency (expected.estimated_recovery_by_currency vs
    observed.observed_recovery_by_currency, currency-by-currency, exact
    Decimal equality, never summed/converted across currencies)

`projected_exposure_by_currency` is carried in the expected snapshot for
context/display only -- Phase 7's sandbox action has no mechanism to
independently observe residual exposure (see module docstring in
app.domain.verifications), so it is NOT one of the three scored
dimensions. This is a documented Phase 8 MVP limitation, not an oversight.

Status contract (VERIFIER_VERSION = "1", exact-equality only, no fuzzy
tolerance):
  INSUFFICIENT_OBSERVATION -- expected or observed is unavailable
    (expected["available"] is False, e.g. no completed action/simulation
    to compare; or observed["available"] is False, e.g. the action was
    rejected and never produced a sandbox outcome). No per-dimension
    comparison is attempted in this case.
  VERIFIED_SUCCESS  -- expected and observed are both available, and all
    three dimensions match exactly.
  FAILED            -- expected and observed are both available, and NONE
    of the three dimensions match.
  PARTIALLY_VERIFIED -- expected and observed are both available, and one
    or two (not all three, not zero) dimensions match.

A dimension whose expected or observed value is individually missing/
unparseable (malformed input) counts as "not matched" for that one
dimension -- it does not by itself force INSUFFICIENT_OBSERVATION, and it
never raises. INSUFFICIENT_OBSERVATION is reserved for the whole
expected/observed side being unavailable, per the module docstring above.

Currency safety (non-negotiable, see module docstring): amounts are always
grouped and compared per currency, via Decimal, never summed or converted
across currencies. A currency present in expected but missing from
observed, or present in observed but not in expected, makes
recovery_by_currency mismatch and is surfaced explicitly (never silently
dropped) in that dimension's `missing_currencies`/`unexpected_currencies`.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

VERIFIER_VERSION = "1"

VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
FAILED = "FAILED"
INSUFFICIENT_OBSERVATION = "INSUFFICIENT_OBSERVATION"

STATUSES = frozenset({VERIFIED_SUCCESS, PARTIALLY_VERIFIED, FAILED, INSUFFICIENT_OBSERVATION})


def _parse_decimal(value: Any) -> Decimal | None:
    """Never raises. Returns None for anything that is not a valid
    decimal amount (missing, wrong type, malformed string) -- callers
    treat None as "this amount could not be established", never as zero.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _currency_map(entries: Any) -> dict[str, Decimal]:
    """Builds {currency: Decimal(amount)} from a list of
    {"currency": ..., "amount": ...} dicts, skipping (never raising on)
    any entry that is not a well-formed currency/amount pair -- a
    malformed entry is simply absent from the map, which then correctly
    surfaces as a missing/unexpected currency rather than crashing the
    whole comparison.
    """
    result: dict[str, Decimal] = {}
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        currency = entry.get("currency")
        amount = _parse_decimal(entry.get("amount"))
        if isinstance(currency, str) and currency and amount is not None:
            result[currency] = amount
    return result


def _compare_counts(expected_value: Any, observed_value: Any) -> dict:
    expected_int = expected_value if isinstance(expected_value, int) else None
    observed_int = observed_value if isinstance(observed_value, int) else None
    match = expected_int is not None and observed_int is not None and expected_int == observed_int
    return {"expected": expected_int, "observed": observed_int, "match": match}


def _compare_recovery(expected_entries: Any, observed_entries: Any) -> dict:
    expected_map = _currency_map(expected_entries)
    observed_map = _currency_map(observed_entries)

    missing_currencies = sorted(set(expected_map) - set(observed_map))
    unexpected_currencies = sorted(set(observed_map) - set(expected_map))
    amount_mismatches = sorted(
        currency
        for currency in set(expected_map) & set(observed_map)
        if expected_map[currency] != observed_map[currency]
    )

    match = not missing_currencies and not unexpected_currencies and not amount_mismatches

    return {
        "expected": [{"currency": c, "amount": str(a)} for c, a in sorted(expected_map.items())],
        "observed": [{"currency": c, "amount": str(a)} for c, a in sorted(observed_map.items())],
        "match": match,
        "missing_currencies": missing_currencies,
        "unexpected_currencies": unexpected_currencies,
        "amount_mismatches": amount_mismatches,
    }


def verify(*, expected: dict, observed: dict) -> dict:
    """Compare a Phase 8 expected snapshot against an observed snapshot.

    `expected` and `observed` are plain dicts (see app.domain.verifications
    for their exact producers) -- this function makes no assumption about
    where they came from beyond the shape documented in this module's
    docstring, and never mutates either input.

    Returns a dict:
      {
        "status": one of STATUSES,
        "verifier_version": VERIFIER_VERSION,
        "dimensions": {
          "success_count": {"expected", "observed", "match"},
          "failure_count": {"expected", "observed", "match"},
          "recovery_by_currency": {
              "expected", "observed", "match",
              "missing_currencies", "unexpected_currencies", "amount_mismatches",
          },
        },
        "matched_dimension_count": int,
        "reasons": [str, ...],
      }

    Never raises for malformed/missing input -- see module docstring for
    exactly how each kind of gap is represented instead.
    """
    if not isinstance(expected, dict) or not expected.get("available"):
        return {
            "status": INSUFFICIENT_OBSERVATION,
            "verifier_version": VERIFIER_VERSION,
            "dimensions": {},
            "matched_dimension_count": 0,
            "reasons": [
                (expected.get("reason") if isinstance(expected, dict) else None)
                or "expected outcome is unavailable -- there is no completed simulation to "
                "verify this action against"
            ],
        }

    if not isinstance(observed, dict) or not observed.get("available"):
        return {
            "status": INSUFFICIENT_OBSERVATION,
            "verifier_version": VERIFIER_VERSION,
            "dimensions": {},
            "matched_dimension_count": 0,
            "reasons": [
                (observed.get("reason") if isinstance(observed, dict) else None)
                or "observed outcome is unavailable -- this action produced no sandbox "
                "outcome to verify"
            ],
        }

    success_dim = _compare_counts(
        expected.get("projected_success_count"), observed.get("observed_success_count")
    )
    failure_dim = _compare_counts(
        expected.get("projected_failure_count"), observed.get("observed_failure_count")
    )
    recovery_dim = _compare_recovery(
        expected.get("estimated_recovery_by_currency"),
        observed.get("observed_recovery_by_currency"),
    )

    dimensions = {
        "success_count": success_dim,
        "failure_count": failure_dim,
        "recovery_by_currency": recovery_dim,
    }
    matched = sum(1 for d in dimensions.values() if d["match"])

    reasons = []
    for name, dim in dimensions.items():
        if dim["match"]:
            reasons.append(f"{name} matched: expected == observed")
        else:
            reasons.append(
                f"{name} did not match: expected={dim['expected']!r} observed={dim['observed']!r}"
            )
    if recovery_dim["missing_currencies"]:
        reasons.append(
            "recovery currencies expected but not observed: "
            f"{', '.join(recovery_dim['missing_currencies'])}"
        )
    if recovery_dim["unexpected_currencies"]:
        reasons.append(
            "recovery currencies observed but not expected: "
            f"{', '.join(recovery_dim['unexpected_currencies'])}"
        )

    if matched == 3:
        status = VERIFIED_SUCCESS
    elif matched == 0:
        status = FAILED
    else:
        status = PARTIALLY_VERIFIED

    return {
        "status": status,
        "verifier_version": VERIFIER_VERSION,
        "dimensions": dimensions,
        "matched_dimension_count": matched,
        "reasons": reasons,
    }


def derive_expected_snapshot(
    *, simulation_result: dict, scenario: str, simulator_version: str
) -> dict:
    """Build the EXPECTED snapshot from an already-persisted Phase 5
    InvestigationSimulation's own `result` field (see
    app.schemas.simulation.SimulationResultDetail) -- never independently
    recomputed. `projected_exposure_by_currency` is carried through for
    context/display only; it is not one of the three scored dimensions
    (see module docstring for why).

    Returns {"available": False, "reason": ...} if `simulation_result`
    does not look like a completed simulation's result (e.g. {} for a
    status != "completed" simulation) -- never guesses a value.
    """
    if not isinstance(simulation_result, dict) or not simulation_result:
        return {
            "available": False,
            "reason": "the originating simulation has no completed result to verify against",
        }
    projected = simulation_result.get("projected")
    if not isinstance(projected, dict):
        return {
            "available": False,
            "reason": "the originating simulation's result has no projected outcome",
        }
    return {
        "available": True,
        "scenario": scenario,
        "simulator_version": simulator_version,
        "eligible_event_count": simulation_result.get("eligible_event_count"),
        "projected_success_count": projected.get("success_event_count"),
        "projected_failure_count": projected.get("failed_event_count"),
        # Context only -- see module docstring; not scored.
        "projected_exposure_by_currency": projected.get("exposure_by_currency") or [],
        "estimated_recovery_by_currency": simulation_result.get("estimated_recovery_by_currency")
        or [],
    }


SANDBOX_OBSERVATION_MODEL_VERSION = "1"
# ~85% deterministic per-event observed-success rate (217/256 hash buckets).
_SANDBOX_OBSERVATION_SUCCESS_THRESHOLD = 217


def _observe_event(action_id: str, event_id: str) -> bool:
    """Deterministic, reproducible per-event sandbox observation: a pure
    function of (action_id, event_id) only -- no randomness, no wall-clock
    time, no dependency on Phase 5's success_rate. Same input always
    produces the same True (observed success) / False (observed failure)
    forever. This IS the "deterministic sandbox state transition" step:
    it is deliberately independent of EXPECTED, which is why a real
    mismatch is possible on the production path (see module docstring),
    not only when a test hand-mutates a fixture after the fact.
    """
    digest = hashlib.sha256(f"{action_id}:{event_id}".encode()).digest()
    return digest[0] < _SANDBOX_OBSERVATION_SUCCESS_THRESHOLD


def derive_observed_snapshot(*, action_id: str, sandbox_result: dict, action_status: str) -> dict:
    """Build the OBSERVED snapshot as an independent POST-ACTION sandbox
    observation -- never a copy of EXPECTED/projected numbers, and never a
    blind pass-through of `targeted_event_count` either: each id in
    `sandbox_result`'s own `targeted_event_ids` is independently
    re-observed via `_observe_event` (versioned by
    SANDBOX_OBSERVATION_MODEL_VERSION), so observed_failure_count is
    derived from that per-event sandbox state, never hardcoded. Recovery
    is scaled by the observed success fraction, per currency, from the
    sandbox's own `simulated_outcome_by_currency`. For a NO_OP
    (DO_NOTHING), nothing was targeted, so every observed count/amount is
    the true zero/empty Phase 7 already persists for that case -- not a
    fabricated zero, and no per-event observation runs.

    Returns {"available": False, "reason": ...} when `action_status` is
    not "executed" (a rejected action produced no sandbox outcome at all)
    -- never pretends a rejected action produced an outcome.
    """
    if action_status != "executed":
        return {
            "available": False,
            "reason": (
                f"action status is '{action_status}', not 'executed' -- "
                "no sandbox outcome exists to observe"
            ),
        }
    if not isinstance(sandbox_result, dict) or not sandbox_result:
        return {
            "available": False,
            "reason": (
                "the executed action's sandbox_result has no valid "
                "targeted_event_count/targeted_event_ids"
            ),
        }
    action_kind = sandbox_result.get("action_kind")
    targeted_event_count = sandbox_result.get("targeted_event_count")
    targeted_event_ids = sandbox_result.get("targeted_event_ids")
    if not isinstance(targeted_event_count, int) or not isinstance(targeted_event_ids, list):
        return {
            "available": False,
            "reason": (
                "the executed action's sandbox_result has no valid "
                "targeted_event_count/targeted_event_ids"
            ),
        }

    if targeted_event_count == 0:
        return {
            "available": True,
            "action_kind": action_kind,
            "observed_success_count": 0,
            "observed_failure_count": 0,
            "observed_recovery_by_currency": [],
            "observation_model_version": SANDBOX_OBSERVATION_MODEL_VERSION,
        }

    action_id_str = str(action_id)
    outcomes = [_observe_event(action_id_str, str(event_id)) for event_id in targeted_event_ids]
    observed_success_count = sum(1 for ok in outcomes if ok)
    observed_failure_count = len(outcomes) - observed_success_count
    success_fraction = Decimal(observed_success_count) / Decimal(len(outcomes))

    observed_recovery_by_currency = []
    for entry in sandbox_result.get("simulated_outcome_by_currency") or []:
        if not isinstance(entry, dict):
            continue
        currency = entry.get("currency")
        amount = _parse_decimal(entry.get("amount"))
        if not isinstance(currency, str) or not currency or amount is None:
            continue
        observed_amount = (amount * success_fraction).quantize(Decimal("0.01"))
        observed_recovery_by_currency.append({"currency": currency, "amount": str(observed_amount)})

    return {
        "available": True,
        "action_kind": action_kind,
        "observed_success_count": observed_success_count,
        "observed_failure_count": observed_failure_count,
        "observed_recovery_by_currency": observed_recovery_by_currency,
        "observation_model_version": SANDBOX_OBSERVATION_MODEL_VERSION,
    }
