import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal


def _create_merchant(client, api_key, name="Decision Test Merchant"):
    response = client.post(
        "/v1/merchants",
        json={"name": f"{name} {uuid.uuid4()}"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ingest(
    client,
    api_key,
    merchant_id,
    event_type,
    occurred_at,
    amount=None,
    currency=None,
    source="manual",
):
    response = client.post(
        "/v1/events",
        json={
            "merchant_id": merchant_id,
            "event_type": event_type,
            "source": source,
            "external_reference": f"dec-evt-{uuid.uuid4()}",
            "amount": str(amount) if amount is not None else None,
            "currency": currency,
            "occurred_at": occurred_at.isoformat(),
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ago(reference: datetime, minutes: int) -> datetime:
    return reference - timedelta(minutes=minutes)


def _run_investigation(client, api_key, merchant_id, as_of):
    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant_id, "as_of": as_of.isoformat()},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _simulate(client, api_key, investigation_id, scenario, assumptions=None):
    payload = {"scenario": scenario}
    if assumptions is not None:
        payload["assumptions"] = assumptions
    response = client.post(
        f"/v1/investigations/{investigation_id}/simulations",
        json=payload,
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _decide(client, api_key, investigation_id):
    return client.post(
        f"/v1/investigations/{investigation_id}/decisions",
        headers={"X-API-Key": api_key},
    )


def _incident_investigation_with_failed_payments(client, api_key, count=3, amount="100.00"):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in range(5, 5 + count * 5, 5):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal(amount), currency="INR",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["incident_detected"] is True
    return investigation


# --- no candidates / insufficient evidence / no eligible scenario ---------


def test_no_incident_is_insufficient_evidence(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["incident_detected"] is False

    response = _decide(client, api_key, investigation["id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["policy_decision"] is None
    assert body["policy_reasons"] == []
    assert body["evaluation_result"] == {}
    assert body["candidate_simulation_ids"] == []
    assert body["failure_reason"]


def test_incident_with_no_simulations_yet_is_no_eligible_scenario(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key)

    response = _decide(client, api_key, investigation["id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "no_eligible_scenario"
    assert body["policy_decision"] is None
    assert "no completed simulation" in body["failure_reason"]


# --- one / multiple candidates, latest-per-scenario ------------------------


def test_single_completed_simulation_is_the_only_candidate(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key)
    _simulate(client, api_key, investigation["id"], "DO_NOTHING")

    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    assert body["status"] == "completed"
    assert body["evaluation_result"]["preferred_scenario"] == "DO_NOTHING"
    assert len(body["evaluation_result"]["candidates"]) == 1


def test_uses_latest_completed_simulation_per_scenario(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="10.00")
    first = _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.1", "scope_fraction": "1.0"},
    )
    second = _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.9", "scope_fraction": "1.0"},
    )
    assert first["id"] != second["id"]

    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    candidate_ids = {c["simulation_id"] for c in body["evaluation_result"]["candidates"]}
    assert candidate_ids == {second["id"]}  # the newer run, not the older one


def test_insufficient_evidence_simulation_is_not_a_candidate(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["incident_detected"] is False
    do_nothing = _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    assert do_nothing["status"] == "completed"  # DO_NOTHING always completes

    response = _decide(client, api_key, investigation["id"])
    # incident_detected is False -> insufficient_evidence short-circuit,
    # never even looks at the DO_NOTHING simulation that exists.
    assert response.json()["status"] == "insufficient_evidence"


# --- comparison metrics ------------------------------------------------


def test_prefers_scenario_with_lowest_failed_event_count_delta(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key)
    _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )

    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    assert body["evaluation_result"]["preferred_scenario"] == "RETRY_AFFECTED_PAYMENTS"
    assert "lowest projected failed-event count" in body["evaluation_result"]["reason"]


def test_projected_exposure_is_surfaced_per_candidate(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="50.00")
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.5", "scope_fraction": "1.0"},
    )

    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    candidate = body["evaluation_result"]["candidates"][0]
    assert candidate["projected_exposure_by_currency"] == [{"currency": "INR", "amount": "75.00"}]


def test_multi_currency_isolation_in_evaluation_result(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("100.00"), currency="INR",
        )
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago + 1),
            amount=Decimal("20.00"), currency="USD",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )

    response = _decide(client, api_key, investigation["id"])
    candidate = response.json()["evaluation_result"]["candidates"][0]
    recovery = {i["currency"]: i["amount"] for i in candidate["estimated_recovery_by_currency"]}
    assert recovery == {"INR": "300.00", "USD": "60.00"}  # never summed into one number


# --- deterministic tie-break / repeated evaluation --------------------------


def test_tied_scenarios_break_by_fixed_priority(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key)
    _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    _simulate(
        client, api_key, investigation["id"], "TARGET_AFFECTED_EVENT_TYPE",
        assumptions={"success_rate": "0.000001", "scope_fraction": "1.0"},
    )
    # dominant_signal_event_type is "payment_failed" here, so
    # TARGET_AFFECTED_EVENT_TYPE is eligible, but a success_rate this small
    # rounds both its success_count and its recovered amount to zero --
    # its failed-event delta (0) and recovery ([]) end up identical to
    # DO_NOTHING's, a genuine tie that only the fixed priority order breaks.

    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    assert body["evaluation_result"]["preferred_scenario"] == "DO_NOTHING"


def test_repeated_decision_produces_new_row_with_identical_earlier_ones_unchanged(
    client, api_key
):
    investigation = _incident_investigation_with_failed_payments(client, api_key)
    _simulate(client, api_key, investigation["id"], "DO_NOTHING")

    first = _decide(client, api_key, investigation["id"]).json()
    second = _decide(client, api_key, investigation["id"]).json()
    assert first["id"] != second["id"]
    assert first["evaluation_result"] == second["evaluation_result"]

    # First decision is still readable and unchanged.
    detail = client.get(
        f"/v1/investigations/{investigation['id']}/decisions/{first['id']}",
        headers={"X-API-Key": api_key},
    )
    assert detail.status_code == 200
    assert detail.json() == first


# --- policy: ALLOWED / REQUIRES_HUMAN_APPROVAL / BLOCKED --------------------


def test_small_exposure_scenario_is_allowed(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="10.00")
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    assert body["policy_decision"] == "ALLOWED"


def test_unknown_amount_requires_human_approval(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, 5))  # amount=None
    for minutes_ago in (10, 15):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("10.00"), currency="INR",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["incident_detected"] is True
    _simulate(client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS")

    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    assert body["policy_decision"] == "REQUIRES_HUMAN_APPROVAL"
    assert any("unknown amount" in r for r in body["policy_reasons"])


def test_large_exposure_requires_human_approval(client, api_key):
    # Default autonomous INR threshold is a demonstration value (see
    # app.domain.policy.DEFAULT_POLICY_CONFIG) -- comfortably exceeded here.
    investigation = _incident_investigation_with_failed_payments(
        client, api_key, count=3, amount="5000.00"
    )
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.1", "scope_fraction": "1.0"},
    )
    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    assert body["policy_decision"] == "REQUIRES_HUMAN_APPROVAL"
    assert any("exceeds the autonomous threshold" in r for r in body["policy_reasons"])


def test_preferred_can_be_blocked_without_promoting_a_runner_up(client, api_key):
    # REROUTE_PROVIDER is not prohibited by default, so this test exercises
    # the mechanism through a scenario a policy config WOULD prohibit is
    # covered at the unit level (test_policy.py); here we confirm that a
    # non-ALLOWED policy decision does not change evaluation's own pick.
    investigation = _incident_investigation_with_failed_payments(
        client, api_key, count=3, amount="5000.00"
    )
    _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.5", "scope_fraction": "1.0"},
    )
    response = _decide(client, api_key, investigation["id"])
    body = response.json()
    # RETRY_AFFECTED_PAYMENTS has a strictly better failed-count delta, so
    # it remains preferred even though its remaining projected exposure
    # (7500.00 INR of the original 15000.00) trips REQUIRES_HUMAN_APPROVAL.
    assert body["evaluation_result"]["preferred_scenario"] == "RETRY_AFFECTED_PAYMENTS"
    assert body["policy_decision"] == "REQUIRES_HUMAN_APPROVAL"


# --- security / API ----------------------------------------------------


def test_decision_404_for_unknown_investigation(client, api_key):
    response = _decide(client, api_key, uuid.uuid4())
    assert response.status_code == 404


def test_decision_endpoints_require_api_key(client):
    investigation_id = uuid.uuid4()
    assert client.post(f"/v1/investigations/{investigation_id}/decisions").status_code == 401
    assert client.get(f"/v1/investigations/{investigation_id}/decisions").status_code == 401
    assert (
        client.get(f"/v1/investigations/{investigation_id}/decisions/{uuid.uuid4()}").status_code
        == 401
    )


def test_client_cannot_control_policy_decision_via_request_body(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="10.00")
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    # The endpoint takes no request body at all -- an attempted
    # policy_decision in the JSON body is simply never read by the
    # handler; it cannot influence the computed result.
    response = client.post(
        f"/v1/investigations/{investigation['id']}/decisions",
        json={"policy_decision": "ALLOWED", "evaluation_result": {"preferred_scenario": "X"}},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["evaluation_result"]["preferred_scenario"] == "RETRY_AFFECTED_PAYMENTS"
    assert body["policy_decision"] == "ALLOWED"  # computed server-side, matches this small case


def test_one_investigation_cannot_read_another_investigations_decision(client, api_key):
    investigation_a = _incident_investigation_with_failed_payments(client, api_key)
    investigation_b = _incident_investigation_with_failed_payments(client, api_key)
    _simulate(client, api_key, investigation_a["id"], "DO_NOTHING")
    decision_a = _decide(client, api_key, investigation_a["id"]).json()

    response = client.get(
        f"/v1/investigations/{investigation_b['id']}/decisions/{decision_a['id']}",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 404


# --- persistence / audit -------------------------------------------------


def test_post_persists_and_get_list_and_detail_return_it(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key)
    _simulate(client, api_key, investigation["id"], "DO_NOTHING")

    posted = _decide(client, api_key, investigation["id"]).json()
    assert posted["investigation_id"] == investigation["id"]
    assert posted["evaluation_version"]
    assert posted["candidate_simulation_ids"]

    list_response = client.get(
        f"/v1/investigations/{investigation['id']}/decisions",
        headers={"X-API-Key": api_key},
    )
    assert list_response.status_code == 200
    assert any(item["id"] == posted["id"] for item in list_response.json()["items"])

    detail_response = client.get(
        f"/v1/investigations/{investigation['id']}/decisions/{posted['id']}",
        headers={"X-API-Key": api_key},
    )
    assert detail_response.status_code == 200
    assert detail_response.json() == posted
