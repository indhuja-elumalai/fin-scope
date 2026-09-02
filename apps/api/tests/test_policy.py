"""Unit tests for app.domain.policy -- pure, no DB, no client."""
import uuid
from decimal import Decimal

from app.domain.policy import (
    ALLOWED,
    BLOCKED,
    REQUIRES_HUMAN_APPROVAL,
    CandidateInput,
    PolicyConfig,
    evaluate_policy,
)

CONFIG = PolicyConfig(
    version="test-1",
    autonomous_exposure_threshold_by_currency={"INR": Decimal("1000"), "USD": Decimal("50")},
    max_autonomous_eligible_event_count=10,
    prohibited_scenarios=frozenset({"REROUTE_PROVIDER"}),
)


def _candidate(
    scenario="RETRY_AFFECTED_PAYMENTS",
    *,
    status="completed",
    exposure=None,
    unknown_count=0,
    eligible_count=1,
):
    return CandidateInput(
        simulation_id=uuid.uuid4(),
        scenario=scenario,
        status=status,
        failed_event_count_delta=0,
        estimated_recovery_by_currency={},
        projected_exposure_by_currency=exposure or {},
        projected_exposure_amount_unknown_count=unknown_count,
        eligible_event_count=eligible_count,
    )


# --- ALLOWED -----------------------------------------------------------


def test_allowed_when_every_condition_passes():
    candidate = _candidate(exposure={"INR": Decimal("500")}, eligible_count=3)
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == ALLOWED
    assert result.policy_version == "test-1"


# --- exposure threshold: below / at / above ------------------------------


def test_exposure_below_threshold_is_allowed():
    candidate = _candidate(exposure={"INR": Decimal("999.99")})
    assert evaluate_policy(candidate, CONFIG).decision == ALLOWED


def test_exposure_exactly_at_threshold_is_allowed():
    candidate = _candidate(exposure={"INR": Decimal("1000")})
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == ALLOWED, result.reasons


def test_exposure_above_threshold_requires_human_approval():
    candidate = _candidate(exposure={"INR": Decimal("1000.01")})
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == REQUIRES_HUMAN_APPROVAL
    assert any("exceeds the autonomous threshold" in r for r in result.reasons)


# --- unknown amounts ------------------------------------------------------


def test_unknown_amount_requires_human_approval():
    candidate = _candidate(exposure={"INR": Decimal("10")}, unknown_count=1)
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == REQUIRES_HUMAN_APPROVAL
    assert any("unknown amount" in r for r in result.reasons)


# --- unconfigured currency -------------------------------------------------


def test_unconfigured_currency_requires_human_approval_never_allowed():
    candidate = _candidate(exposure={"EUR": Decimal("1")})
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == REQUIRES_HUMAN_APPROVAL
    assert any(
        "no autonomous exposure threshold is configured for EUR" in r for r in result.reasons
    )


# --- scope threshold --------------------------------------------------------


def test_eligible_event_count_above_limit_requires_human_approval():
    candidate = _candidate(eligible_count=11)
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == REQUIRES_HUMAN_APPROVAL
    assert any("intervention scope" in r for r in result.reasons)


def test_eligible_event_count_at_limit_is_not_a_scope_violation():
    candidate = _candidate(eligible_count=10, exposure={"INR": Decimal("1")})
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == ALLOWED


# --- prohibited scenario ----------------------------------------------------


def test_prohibited_scenario_is_blocked():
    candidate = _candidate(scenario="REROUTE_PROVIDER")
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == BLOCKED
    assert any("prohibited" in r for r in result.reasons)


def test_empty_prohibited_scenarios_blocks_nothing():
    from app.domain.policy import DEFAULT_POLICY_CONFIG

    assert DEFAULT_POLICY_CONFIG.prohibited_scenarios == frozenset()


# --- invalid/incomplete candidate -------------------------------------------


def test_non_completed_candidate_is_blocked_defensively():
    candidate = _candidate(status="insufficient_evidence")
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == BLOCKED
    assert any("not in a completed state" in r for r in result.reasons)


# --- precedence: BLOCKED > REQUIRES_HUMAN_APPROVAL > ALLOWED ---------------


def test_blocked_takes_precedence_over_approval_conditions():
    # A prohibited scenario that ALSO exceeds the exposure threshold --
    # must be BLOCKED, not REQUIRES_HUMAN_APPROVAL.
    candidate = _candidate(scenario="REROUTE_PROVIDER", exposure={"INR": Decimal("99999")})
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == BLOCKED


def test_multiple_approval_conditions_are_all_collected():
    candidate = _candidate(
        exposure={"INR": Decimal("50000")}, unknown_count=2, eligible_count=999
    )
    result = evaluate_policy(candidate, CONFIG)
    assert result.decision == REQUIRES_HUMAN_APPROVAL
    assert len(result.reasons) == 3


# --- client policy bypass attempt (structural, not this module's job) -----


def test_policy_result_has_no_client_settable_path():
    # evaluate_policy takes only a CandidateInput and a PolicyConfig -- there
    # is no parameter through which a caller can pass a desired decision.
    import inspect

    params = list(inspect.signature(evaluate_policy).parameters)
    assert params == ["candidate", "config"]


# --- determinism -------------------------------------------------------------


def test_repeated_evaluation_is_identical():
    candidate = _candidate(exposure={"INR": Decimal("500")})
    first = evaluate_policy(candidate, CONFIG)
    second = evaluate_policy(candidate, CONFIG)
    assert first.decision == second.decision
    assert first.reasons == second.reasons
