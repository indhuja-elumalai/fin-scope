"""Unit tests for the pure Phase 8 deterministic outcome verifier
(app.domain.outcome_verification). No DB, no FastAPI, no network -- every
test calls the real functions directly with hand-built dicts.
"""

from __future__ import annotations

import copy

from app.domain import outcome_verification as ov


def _expected(success=3, failure=0, recovery=None, exposure=None, available=True):
    if not available:
        return {"available": False, "reason": "no completed simulation"}
    return {
        "available": True,
        "scenario": "RETRY_AFFECTED_PAYMENTS",
        "simulator_version": "1",
        "eligible_event_count": 3,
        "projected_success_count": success,
        "projected_failure_count": failure,
        "projected_exposure_by_currency": exposure if exposure is not None else [],
        "estimated_recovery_by_currency": recovery
        if recovery is not None
        else [{"currency": "INR", "amount": "30.00"}],
    }


def _observed(success=3, failure=0, recovery=None, available=True):
    if not available:
        return {"available": False, "reason": "action was rejected"}
    return {
        "available": True,
        "action_kind": "SIMULATED_RETRY_PAYMENTS",
        "observed_success_count": success,
        "observed_failure_count": failure,
        "observed_recovery_by_currency": recovery
        if recovery is not None
        else [{"currency": "INR", "amount": "30.00"}],
    }


# --- 1. exact match -> VERIFIED_SUCCESS ---------------------------------
def test_exact_match_is_verified_success():
    result = ov.verify(expected=_expected(), observed=_observed())
    assert result["status"] == ov.VERIFIED_SUCCESS
    assert result["matched_dimension_count"] == 3
    assert all(d["match"] for d in result["dimensions"].values())


# --- 2. partial mismatch -> PARTIALLY_VERIFIED --------------------------
def test_partial_mismatch_is_partially_verified():
    # success/failure counts differ (2 vs 3, 1 vs 0) but recovery amount matches.
    result = ov.verify(
        expected=_expected(success=3, failure=0),
        observed=_observed(success=2, failure=1),
    )
    assert result["status"] == ov.PARTIALLY_VERIFIED
    assert result["matched_dimension_count"] == 1
    assert result["dimensions"]["recovery_by_currency"]["match"] is True
    assert result["dimensions"]["success_count"]["match"] is False
    assert result["dimensions"]["failure_count"]["match"] is False


# --- 3. complete mismatch -> FAILED --------------------------------------
def test_complete_mismatch_is_failed():
    # Every one of the 3 scored dimensions must genuinely differ -- 0 == 0
    # would trivially "match" on failure_count, so the observed failure
    # count is deliberately nonzero and different from expected here too.
    result = ov.verify(
        expected=_expected(success=3, failure=0, recovery=[{"currency": "INR", "amount": "30.00"}]),
        observed=_observed(success=0, failure=3, recovery=[]),
    )
    assert result["status"] == ov.FAILED
    assert result["matched_dimension_count"] == 0


# --- 4. missing observation -> INSUFFICIENT_OBSERVATION ------------------
def test_unavailable_observed_is_insufficient_observation():
    result = ov.verify(expected=_expected(), observed=_observed(available=False))
    assert result["status"] == ov.INSUFFICIENT_OBSERVATION
    assert result["dimensions"] == {}
    assert "action was rejected" in result["reasons"][0]


def test_unavailable_expected_is_insufficient_observation():
    result = ov.verify(expected=_expected(available=False), observed=_observed())
    assert result["status"] == ov.INSUFFICIENT_OBSERVATION
    assert result["dimensions"] == {}


# --- 5. missing expected amount ------------------------------------------
def test_missing_expected_success_count_does_not_match_but_does_not_raise():
    expected = _expected()
    expected["projected_success_count"] = None
    result = ov.verify(expected=expected, observed=_observed())
    assert result["status"] != ov.INSUFFICIENT_OBSERVATION  # both sides still "available"
    assert result["dimensions"]["success_count"]["match"] is False
    assert result["dimensions"]["success_count"]["expected"] is None


# --- 6. missing observed amount -------------------------------------------
def test_missing_observed_recovery_amount_is_a_mismatch_not_a_crash():
    observed = _observed(recovery=[{"currency": "INR", "amount": None}])
    result = ov.verify(expected=_expected(), observed=observed)
    assert result["dimensions"]["recovery_by_currency"]["match"] is False


# --- 7. currency isolation (never sum/convert across currencies) --------
def test_currency_isolation_inr_and_usd_never_aggregated():
    expected = _expected(
        recovery=[{"currency": "INR", "amount": "30.00"}, {"currency": "USD", "amount": "5.00"}]
    )
    observed = _observed(
        recovery=[{"currency": "INR", "amount": "30.00"}, {"currency": "USD", "amount": "5.00"}]
    )
    result = ov.verify(expected=expected, observed=observed)
    dim = result["dimensions"]["recovery_by_currency"]
    assert dim["match"] is True
    currencies = {e["currency"] for e in dim["expected"]}
    assert currencies == {"INR", "USD"}
    # each currency kept as its own entry, never summed into one scalar
    assert len(dim["expected"]) == 2


def test_currency_amount_mismatch_isolated_to_its_own_currency():
    expected = _expected(
        recovery=[{"currency": "INR", "amount": "30.00"}, {"currency": "USD", "amount": "5.00"}]
    )
    observed = _observed(
        recovery=[{"currency": "INR", "amount": "30.00"}, {"currency": "USD", "amount": "4.00"}]
    )
    result = ov.verify(expected=expected, observed=observed)
    dim = result["dimensions"]["recovery_by_currency"]
    assert dim["match"] is False
    assert dim["amount_mismatches"] == ["USD"]
    assert dim["missing_currencies"] == []
    assert dim["unexpected_currencies"] == []


# --- 8. unexpected observed currency --------------------------------------
def test_unexpected_observed_currency_is_surfaced_not_ignored():
    expected = _expected(recovery=[{"currency": "INR", "amount": "30.00"}])
    observed = _observed(
        recovery=[{"currency": "INR", "amount": "30.00"}, {"currency": "USD", "amount": "1.00"}]
    )
    result = ov.verify(expected=expected, observed=observed)
    dim = result["dimensions"]["recovery_by_currency"]
    assert dim["match"] is False
    assert dim["unexpected_currencies"] == ["USD"]
    assert any("USD" in r for r in result["reasons"])


def test_missing_expected_currency_is_surfaced():
    expected = _expected(
        recovery=[{"currency": "INR", "amount": "30.00"}, {"currency": "USD", "amount": "5.00"}]
    )
    observed = _observed(recovery=[{"currency": "INR", "amount": "30.00"}])
    result = ov.verify(expected=expected, observed=observed)
    dim = result["dimensions"]["recovery_by_currency"]
    assert dim["match"] is False
    assert dim["missing_currencies"] == ["USD"]


# --- 9. no cross-currency aggregation (structural: no summed field exists) --
def test_no_summed_scalar_field_exists_anywhere_in_the_comparison_output():
    result = ov.verify(
        expected=_expected(
            recovery=[{"currency": "INR", "amount": "30.00"}, {"currency": "USD", "amount": "5.00"}]
        ),
        observed=_observed(
            recovery=[{"currency": "INR", "amount": "30.00"}, {"currency": "USD", "amount": "5.00"}]
        ),
    )
    import json

    serialized = json.dumps(result)
    assert "35.00" not in serialized  # 30.00 + 5.00 would be a currency-unsafe sum


# --- 10. deterministic repeatability --------------------------------------
def test_same_input_always_produces_the_same_result():
    expected = _expected(success=2, failure=1)
    observed = _observed(success=1, failure=0)
    r1 = ov.verify(expected=expected, observed=observed)
    r2 = ov.verify(expected=copy.deepcopy(expected), observed=copy.deepcopy(observed))
    assert r1 == r2


# --- 11. Decimal/money-safe comparison (never float) -----------------------
def test_decimal_precision_is_exact_not_float_fuzzy():
    # 0.1 + 0.2 != 0.3 in float -- must not leak into this comparison.
    expected = _expected(recovery=[{"currency": "INR", "amount": "0.30"}])
    observed = _observed(recovery=[{"currency": "INR", "amount": "0.1"}])  # deliberately not equal
    result = ov.verify(expected=expected, observed=observed)
    assert result["dimensions"]["recovery_by_currency"]["match"] is False

    exact_expected = _expected(recovery=[{"currency": "INR", "amount": "10.10"}])
    exact_observed = _observed(recovery=[{"currency": "INR", "amount": "10.10"}])
    exact_result = ov.verify(expected=exact_expected, observed=exact_observed)
    assert exact_result["dimensions"]["recovery_by_currency"]["match"] is True


# --- 12. malformed input rejection (never raises) ---------------------------
def test_malformed_expected_type_does_not_raise():
    result = ov.verify(expected="not-a-dict", observed=_observed())
    assert result["status"] == ov.INSUFFICIENT_OBSERVATION


def test_malformed_recovery_entries_are_skipped_not_fatal():
    expected = _expected(
        recovery=[{"currency": "INR", "amount": "30.00"}, {"not": "a currency entry"}, "garbage"]
    )
    result = ov.verify(expected=expected, observed=_observed())
    assert result["status"] in ov.STATUSES  # never raises
    assert (
        result["dimensions"]["recovery_by_currency"]["match"] is True
    )  # garbage entries simply ignored


def test_non_int_count_does_not_raise():
    expected = _expected()
    expected["projected_success_count"] = "three"
    result = ov.verify(expected=expected, observed=_observed())
    assert result["dimensions"]["success_count"]["match"] is False
    assert result["dimensions"]["success_count"]["expected"] is None


# --- 13. verify() never mutates its inputs (snapshot immutability) --------
def test_verify_does_not_mutate_its_inputs():
    expected = _expected()
    observed = _observed()
    expected_copy = copy.deepcopy(expected)
    observed_copy = copy.deepcopy(observed)
    ov.verify(expected=expected, observed=observed)
    assert expected == expected_copy
    assert observed == observed_copy


# --- 14. all four status values are reachable ------------------------------
def test_all_four_statuses_reachable():
    statuses = {
        ov.verify(expected=_expected(), observed=_observed())["status"],
        ov.verify(expected=_expected(success=3), observed=_observed(success=1, failure=2))[
            "status"
        ],
        ov.verify(
            expected=_expected(
                success=3, failure=0, recovery=[{"currency": "INR", "amount": "30.00"}]
            ),
            observed=_observed(success=0, failure=3, recovery=[]),
        )["status"],
        ov.verify(expected=_expected(available=False), observed=_observed())["status"],
    }
    assert statuses == {
        ov.VERIFIED_SUCCESS,
        ov.PARTIALLY_VERIFIED,
        ov.FAILED,
        ov.INSUFFICIENT_OBSERVATION,
    }


# --- derive_expected_snapshot / derive_observed_snapshot -------------------
def test_derive_expected_snapshot_from_a_real_shaped_simulation_result():
    simulation_result = {
        "eligible_event_count": 5,
        "projected": {"failed_event_count": 2, "success_event_count": 3},
        "estimated_recovery_by_currency": [{"currency": "INR", "amount": "50.00"}],
    }
    snapshot = ov.derive_expected_snapshot(
        simulation_result=simulation_result,
        scenario="RETRY_AFFECTED_PAYMENTS",
        simulator_version="1",
    )
    assert snapshot["available"] is True
    assert snapshot["projected_success_count"] == 3
    assert snapshot["projected_failure_count"] == 2
    assert snapshot["estimated_recovery_by_currency"] == [{"currency": "INR", "amount": "50.00"}]


def test_derive_expected_snapshot_unavailable_for_empty_result():
    snapshot = ov.derive_expected_snapshot(
        simulation_result={}, scenario="DO_NOTHING", simulator_version="1"
    )
    assert snapshot["available"] is False


def test_derive_observed_snapshot_from_a_real_shaped_sandbox_result():
    sandbox_result = {
        "action_kind": "SIMULATED_RETRY_PAYMENTS",
        "targeted_event_ids": ["a", "b", "c"],
        "targeted_event_count": 3,
        "simulated_outcome_by_currency": [{"currency": "INR", "amount": "20.00"}],
        "note": "...",
    }
    snapshot = ov.derive_observed_snapshot(
        action_id="action-1", sandbox_result=sandbox_result, action_status="executed"
    )
    assert snapshot["available"] is True
    assert snapshot["observed_success_count"] + snapshot["observed_failure_count"] == 3
    assert snapshot["observation_model_version"] == ov.SANDBOX_OBSERVATION_MODEL_VERSION
    # Recovery must scale with the observed success fraction, never just echo
    # the sandbox's full simulated_outcome_by_currency verbatim (that would
    # be a disguised copy of Phase 7's own number, not an independent
    # observation).
    if snapshot["observed_success_count"] == 3:
        assert snapshot["observed_recovery_by_currency"] == [{"currency": "INR", "amount": "20.00"}]
    else:
        assert snapshot["observed_recovery_by_currency"] != [{"currency": "INR", "amount": "20.00"}]


def test_derive_observed_snapshot_unavailable_for_rejected_action():
    snapshot = ov.derive_observed_snapshot(
        action_id="action-1", sandbox_result={}, action_status="rejected"
    )
    assert snapshot["available"] is False
    assert "rejected" not in snapshot["reason"] or "'rejected'" in snapshot["reason"]


def test_derive_observed_snapshot_no_op_is_genuinely_zero_not_fabricated():
    sandbox_result = {
        "action_kind": "NO_OP",
        "targeted_event_ids": [],
        "targeted_event_count": 0,
        "simulated_outcome_by_currency": [],
        "note": "...",
    }
    snapshot = ov.derive_observed_snapshot(
        action_id="action-1", sandbox_result=sandbox_result, action_status="executed"
    )
    assert snapshot["available"] is True
    assert snapshot["observed_success_count"] == 0
    assert snapshot["observed_recovery_by_currency"] == []


# --- 5. observation is genuinely derived from post-action sandbox state ----
def test_observe_event_is_deterministic_same_input_same_output():
    results_a = [ov._observe_event("action-X", f"evt-{i}") for i in range(50)]
    results_b = [ov._observe_event("action-X", f"evt-{i}") for i in range(50)]
    assert results_a == results_b


def test_observe_event_outcome_depends_on_action_id_not_just_event_id():
    # Same 50 event ids, two different action_ids -- if OBSERVED were just
    # a disguised copy of some fixed per-event property, the two vectors
    # would be identical. They are not: the observation is anchored to the
    # specific (action_id, event_id) pair, i.e. to actual post-action
    # sandbox state for THIS action, not a global/static per-event fact.
    event_ids = [f"evt-{i}" for i in range(50)]
    vector_a = [ov._observe_event("action-A", eid) for eid in event_ids]
    vector_b = [ov._observe_event("action-B", eid) for eid in event_ids]
    assert vector_a != vector_b


def test_derive_observed_snapshot_failure_count_is_not_hardcoded_zero():
    # A large enough targeted set that, at the sandbox's own ~85% observed
    # per-event success rate, at least one observed failure is
    # overwhelmingly likely (deterministically guaranteed for this exact,
    # fixed action_id/event_id set -- not flaky, since _observe_event has
    # no randomness).
    sandbox_result = {
        "action_kind": "SIMULATED_RETRY_PAYMENTS",
        "targeted_event_ids": [f"evt-{i}" for i in range(40)],
        "targeted_event_count": 40,
        "simulated_outcome_by_currency": [{"currency": "INR", "amount": "400.00"}],
        "note": "...",
    }
    snapshot = ov.derive_observed_snapshot(
        action_id="failure-count-check", sandbox_result=sandbox_result, action_status="executed"
    )
    assert snapshot["observed_failure_count"] > 0


# --- 6. a production-path mismatch is possible without hand-mutating -------
def test_production_path_expected_vs_observed_can_genuinely_mismatch():
    # Build EXPECTED via the real derive_expected_snapshot() from a
    # simulation_result that projects 100% success (a legitimate,
    # unremarkable Phase 5 projection), and OBSERVED via the real
    # derive_observed_snapshot() from a large real sandbox_result -- never
    # hand-editing either snapshot afterward. The sandbox's own ~85%
    # per-event observation model makes an exact 100%-match astronomically
    # unlikely for 40 events, so this is a genuine, reproducible mismatch
    # produced entirely by the production code path.
    simulation_result = {
        "eligible_event_count": 40,
        "projected": {
            "success_event_count": 40,
            "failed_event_count": 0,
            "exposure_by_currency": [],
        },
        "estimated_recovery_by_currency": [{"currency": "INR", "amount": "400.00"}],
    }
    expected = ov.derive_expected_snapshot(
        simulation_result=simulation_result,
        scenario="RETRY_AFFECTED_PAYMENTS",
        simulator_version="1",
    )
    sandbox_result = {
        "action_kind": "SIMULATED_RETRY_PAYMENTS",
        "targeted_event_ids": [f"prod-evt-{i}" for i in range(40)],
        "targeted_event_count": 40,
        "simulated_outcome_by_currency": [{"currency": "INR", "amount": "400.00"}],
        "note": "...",
    }
    observed = ov.derive_observed_snapshot(
        action_id="production-path-action", sandbox_result=sandbox_result, action_status="executed"
    )
    comparison = ov.verify(expected=expected, observed=observed)
    assert comparison["status"] != ov.VERIFIED_SUCCESS
    assert comparison["dimensions"]["failure_count"]["match"] is False
