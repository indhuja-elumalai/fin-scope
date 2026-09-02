"""Unit tests for app.domain.sandbox_executor -- pure, no DB, no client."""
import pytest

from app.domain.sandbox_executor import (
    EXECUTOR_VERSION,
    SCENARIO_ACTION_KIND,
    UnsupportedScenarioError,
    execute,
)


def test_do_nothing_maps_to_no_op():
    result = execute(
        scenario="DO_NOTHING",
        eligible_event_ids=[],
        eligible_event_count=0,
        estimated_recovery_by_currency=[],
    )
    assert result["action_kind"] == "NO_OP"
    assert result["targeted_event_ids"] == []
    assert result["targeted_event_count"] == 0
    assert result["simulated_outcome_by_currency"] == []
    assert "SANDBOX-ONLY" in result["note"]


def test_do_nothing_ignores_nonempty_input_and_still_produces_a_true_no_op():
    # Defensive: even if a caller mistakenly passed nonzero eligible data
    # alongside scenario="DO_NOTHING", the result must never imply an
    # intervention that did not happen.
    result = execute(
        scenario="DO_NOTHING",
        eligible_event_ids=["evt-1", "evt-2"],
        eligible_event_count=2,
        estimated_recovery_by_currency=[{"currency": "INR", "amount": "500.00"}],
    )
    assert result["action_kind"] == "NO_OP"
    assert result["targeted_event_ids"] == []
    assert result["targeted_event_count"] == 0
    assert result["simulated_outcome_by_currency"] == []


def test_retry_affected_payments_maps_to_simulated_retry_payments():
    ids = ["evt-1", "evt-2", "evt-3"]
    recovery = [{"currency": "INR", "amount": "8250.00"}]
    result = execute(
        scenario="RETRY_AFFECTED_PAYMENTS",
        eligible_event_ids=ids,
        eligible_event_count=3,
        estimated_recovery_by_currency=recovery,
    )
    assert result["action_kind"] == "SIMULATED_RETRY_PAYMENTS"
    assert result["targeted_event_ids"] == ids
    assert result["targeted_event_count"] == 3
    assert result["simulated_outcome_by_currency"] == recovery
    assert "SANDBOX-ONLY" in result["note"]


def test_reroute_provider_maps_to_simulated_reroute():
    result = execute(
        scenario="REROUTE_PROVIDER",
        eligible_event_ids=["evt-1"],
        eligible_event_count=1,
        estimated_recovery_by_currency=[{"currency": "INR", "amount": "100.00"}],
    )
    assert result["action_kind"] == "SIMULATED_REROUTE"


def test_target_affected_event_type_maps_to_simulated_targeted_retry():
    result = execute(
        scenario="TARGET_AFFECTED_EVENT_TYPE",
        eligible_event_ids=["evt-1"],
        eligible_event_count=1,
        estimated_recovery_by_currency=[{"currency": "USD", "amount": "10.00"}],
    )
    assert result["action_kind"] == "SIMULATED_TARGETED_RETRY"


def test_unsupported_scenario_raises():
    with pytest.raises(UnsupportedScenarioError):
        execute(
            scenario="NOT_A_REAL_SCENARIO",
            eligible_event_ids=[],
            eligible_event_count=0,
            estimated_recovery_by_currency=[],
        )


def test_output_is_deterministic_for_identical_input():
    kwargs = dict(
        scenario="RETRY_AFFECTED_PAYMENTS",
        eligible_event_ids=["evt-1", "evt-2"],
        eligible_event_count=2,
        estimated_recovery_by_currency=[{"currency": "INR", "amount": "50.00"}],
    )
    assert execute(**kwargs) == execute(**kwargs)


def test_output_never_mutates_or_aliases_caller_lists():
    # targeted_event_ids / simulated_outcome_by_currency must be copies, not
    # the same list objects the caller passed in -- app.domain.actions
    # passes the persisted Phase 5 result's own lists directly, and this
    # module must never let a later in-place mutation of its output reach
    # back into that persisted data.
    ids = ["evt-1"]
    recovery = [{"currency": "INR", "amount": "1.00"}]
    result = execute(
        scenario="RETRY_AFFECTED_PAYMENTS",
        eligible_event_ids=ids,
        eligible_event_count=1,
        estimated_recovery_by_currency=recovery,
    )
    assert result["targeted_event_ids"] is not ids
    assert result["simulated_outcome_by_currency"] is not recovery
    result["targeted_event_ids"].append("mutated")
    assert ids == ["evt-1"]


def test_never_recomputes_financial_numbers_it_is_given():
    # The executor must carry the caller's numbers through completely
    # unchanged -- it performs no independent financial recomputation of
    # its own (see module docstring). This deliberately passes numbers
    # that would be "wrong" under Phase 5's own formulas, to prove the
    # executor never second-guesses or recalculates them.
    recovery = [{"currency": "INR", "amount": "999999.99"}]
    result = execute(
        scenario="REROUTE_PROVIDER",
        eligible_event_ids=["evt-1"],
        eligible_event_count=1,
        estimated_recovery_by_currency=recovery,
    )
    assert result["simulated_outcome_by_currency"] == recovery


def test_every_executable_result_states_sandbox_only():
    for scenario in SCENARIO_ACTION_KIND:
        result = execute(
            scenario=scenario,
            eligible_event_ids=["evt-1"],
            eligible_event_count=1,
            estimated_recovery_by_currency=[{"currency": "INR", "amount": "1.00"}],
        )
        assert "SANDBOX-ONLY" in result["note"]
        assert (
            "no real payment provider" in result["note"].lower()
            or "no real" in result["note"].lower()
        )

def test_executor_version_is_a_nonempty_string():
    assert isinstance(EXECUTOR_VERSION, str)
    assert EXECUTOR_VERSION


def test_scenario_action_kind_covers_exactly_the_four_known_scenarios():
    assert set(SCENARIO_ACTION_KIND) == {
        "DO_NOTHING",
        "RETRY_AFFECTED_PAYMENTS",
        "REROUTE_PROVIDER",
        "TARGET_AFFECTED_EVENT_TYPE",
    }
