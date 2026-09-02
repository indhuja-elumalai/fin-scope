"""Unit tests for app.domain.decision_evaluation -- pure, no DB, no client."""
import uuid
from decimal import Decimal

from app.domain.decision_evaluation import (
    SCENARIO_PRIORITY,
    CandidateInput,
    build_candidate,
    evaluate_candidates,
)


def _candidate(
    scenario,
    *,
    failed_delta=0,
    recovery=None,
    exposure=None,
    unknown_count=0,
    eligible_count=0,
    status="completed",
):
    return CandidateInput(
        simulation_id=uuid.uuid4(),
        scenario=scenario,
        status=status,
        failed_event_count_delta=failed_delta,
        estimated_recovery_by_currency=recovery or {},
        projected_exposure_by_currency=exposure or {},
        projected_exposure_amount_unknown_count=unknown_count,
        eligible_event_count=eligible_count,
    )


# --- no / one / many candidates --------------------------------------------


def test_no_candidates_yields_no_preferred():
    result = evaluate_candidates([])
    assert result.preferred is None
    assert result.candidates == []
    assert "no completed simulation" in result.reason


def test_one_candidate_is_trivially_preferred():
    only = _candidate("DO_NOTHING")
    result = evaluate_candidates([only])
    assert result.preferred is only


def test_multiple_candidates_returns_all_in_priority_order():
    a = _candidate("TARGET_AFFECTED_EVENT_TYPE", failed_delta=-1)
    b = _candidate("DO_NOTHING", failed_delta=0)
    c = _candidate("RETRY_AFFECTED_PAYMENTS", failed_delta=-1)
    result = evaluate_candidates([a, b, c])
    assert [cand.scenario for cand in result.candidates] == [
        "DO_NOTHING",
        "RETRY_AFFECTED_PAYMENTS",
        "TARGET_AFFECTED_EVENT_TYPE",
    ]


# --- stage 1: failed-event-count delta -------------------------------------


def test_lowest_failed_count_delta_wins_outright():
    worse = _candidate("DO_NOTHING", failed_delta=0)
    better = _candidate("RETRY_AFFECTED_PAYMENTS", failed_delta=-3)
    result = evaluate_candidates([worse, better])
    assert result.preferred is better
    assert "lowest projected failed-event count" in result.reason


# --- stage 2: recovery, single currency -------------------------------------


def test_recovery_breaks_a_failed_count_tie_in_one_currency():
    low = _candidate(
        "RETRY_AFFECTED_PAYMENTS", failed_delta=-2, recovery={"INR": Decimal("100")}
    )
    high = _candidate(
        "REROUTE_PROVIDER", failed_delta=-2, recovery={"INR": Decimal("250")}
    )
    result = evaluate_candidates([low, high])
    assert result.preferred is high
    assert "highest projected INR recovery" in result.reason


def test_recovery_tie_falls_through_to_scenario_priority():
    a = _candidate(
        "TARGET_AFFECTED_EVENT_TYPE", failed_delta=-1, recovery={"INR": Decimal("50")}
    )
    b = _candidate("RETRY_AFFECTED_PAYMENTS", failed_delta=-1, recovery={"INR": Decimal("50")})
    result = evaluate_candidates([a, b])
    assert result.preferred.scenario == "RETRY_AFFECTED_PAYMENTS"  # earlier in SCENARIO_PRIORITY


# --- multi-currency incomparability -----------------------------------------


def test_multi_currency_recovery_is_never_scalarized_and_falls_back_to_priority():
    inr_only = _candidate(
        "RETRY_AFFECTED_PAYMENTS", failed_delta=-1, recovery={"INR": Decimal("500")}
    )
    usd_only = _candidate(
        "REROUTE_PROVIDER", failed_delta=-1, recovery={"USD": Decimal("500")}
    )
    result = evaluate_candidates([inr_only, usd_only])
    # Never compares 500 INR against 500 USD -- falls back to fixed priority.
    assert result.preferred.scenario == "RETRY_AFFECTED_PAYMENTS"
    assert "incomparable currencies" in result.reason


def test_zero_recovery_entries_do_not_count_as_a_currency_for_comparability():
    # A candidate with only a zero-amount recovery entry (which Phase 5
    # itself never actually emits -- estimated_recovery_by_currency excludes
    # zero amounts -- but this must not crash or falsely trigger the
    # multi-currency fallback if ever encountered).
    a = _candidate("DO_NOTHING", failed_delta=0, recovery={})
    b = _candidate("RETRY_AFFECTED_PAYMENTS", failed_delta=0, recovery={"INR": Decimal("0")})
    result = evaluate_candidates([a, b])
    assert result.preferred.scenario == "DO_NOTHING"


# --- deterministic tie-break -------------------------------------------------


def test_full_tie_falls_back_to_scenario_priority_least_interventionist_first():
    ordered_scenarios = list(SCENARIO_PRIORITY)
    candidates = [_candidate(s, failed_delta=0) for s in reversed(ordered_scenarios)]
    result = evaluate_candidates(candidates)
    assert result.preferred.scenario == ordered_scenarios[0]


def test_tie_break_is_not_based_on_list_order():
    a = _candidate("REROUTE_PROVIDER", failed_delta=0)
    b = _candidate("DO_NOTHING", failed_delta=0)
    result_ab = evaluate_candidates([a, b])
    result_ba = evaluate_candidates([b, a])
    assert result_ab.preferred.scenario == "DO_NOTHING"
    assert result_ba.preferred.scenario == "DO_NOTHING"


# --- determinism / no mutation ----------------------------------------------


def test_repeated_evaluation_of_identical_input_is_identical():
    candidates = [
        _candidate("DO_NOTHING", failed_delta=0),
        _candidate("RETRY_AFFECTED_PAYMENTS", failed_delta=-2, recovery={"INR": Decimal("80")}),
    ]
    first = evaluate_candidates(list(candidates))
    second = evaluate_candidates(list(candidates))
    assert first.preferred.scenario == second.preferred.scenario
    assert first.reason == second.reason


def test_evaluate_candidates_does_not_mutate_inputs():
    original = _candidate("DO_NOTHING", failed_delta=0)
    before = (original.scenario, original.failed_event_count_delta)
    evaluate_candidates([original])
    assert (original.scenario, original.failed_event_count_delta) == before


# --- build_candidate: reads the actual Phase 5 fields -----------------------


def test_build_candidate_reads_projected_exposure_not_recovery():
    result = {
        "eligible_event_count": 4,
        "eligible_event_ids": [],
        "scope_description": "x",
        "baseline": {
            "failed_event_count": 4,
            "success_event_count": 0,
            "exposure_by_currency": [{"currency": "INR", "amount": "400.00"}],
            "exposure_amount_unknown_count": 1,
        },
        "projected": {
            "failed_event_count": 2,
            "success_event_count": 2,
            "exposure_by_currency": [{"currency": "INR", "amount": "150.00"}],
            "exposure_amount_unknown_count": 1,
        },
        "estimated_recovery_by_currency": [{"currency": "INR", "amount": "250.00"}],
        "delta": {
            "failed_event_count_delta": -2,
            "financial_delta_by_currency": [{"currency": "INR", "amount": "-250.00"}],
        },
    }
    candidate = build_candidate(
        simulation_id=uuid.uuid4(), scenario="RETRY_AFFECTED_PAYMENTS", status="completed",
        result=result,
    )
    # Exposure must come from result["projected"], NOT from
    # estimated_recovery_by_currency -- these are deliberately different
    # values in this fixture (150.00 vs 250.00) to prove that.
    assert candidate.projected_exposure_by_currency == {"INR": Decimal("150.00")}
    assert candidate.estimated_recovery_by_currency == {"INR": Decimal("250.00")}
    assert candidate.projected_exposure_amount_unknown_count == 1
    assert candidate.failed_event_count_delta == -2
    assert candidate.eligible_event_count == 4
