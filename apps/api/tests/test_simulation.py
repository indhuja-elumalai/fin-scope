import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal


def _create_merchant(client, api_key, name="Simulation Test Merchant"):
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
            "external_reference": f"sim-evt-{uuid.uuid4()}",
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
    return client.post(
        f"/v1/investigations/{investigation_id}/simulations",
        json=payload,
        headers={"X-API-Key": api_key},
    )


def _by_currency(items):
    return {item["currency"]: item["amount"] for item in items}


# --- A. DO_NOTHING -----------------------------------------------------


def test_do_nothing_is_deterministic_baseline_with_no_delta(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("100.00"), currency="INR",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["incident_detected"] is True

    response = _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["scenario"] == "DO_NOTHING"
    assert body["status"] == "completed"
    assert body["assumptions"] == {"success_rate": None, "scope_fraction": None}
    result = body["result"]
    assert result["eligible_event_count"] == 0
    assert result["eligible_event_ids"] == []
    assert result["baseline"] == result["projected"]
    assert result["delta"]["failed_event_count_delta"] == 0
    assert result["delta"]["financial_delta_by_currency"] == []
    assert result["estimated_recovery_by_currency"] == []


def test_do_nothing_completes_even_without_an_incident(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["incident_detected"] is False

    response = _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "completed"


# --- B. RETRY_AFFECTED_PAYMENTS -----------------------------------------


def test_retry_affected_payments_applies_assumptions_deterministically(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15, 20):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("100.00"), currency="INR",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["evidence_event_count"] == 4

    response = _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.5", "scope_fraction": "1.0"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "completed"
    assert body["assumptions"] == {"success_rate": "0.5", "scope_fraction": "1.0"}
    result = body["result"]
    assert result["eligible_event_count"] == 4
    assert result["baseline"]["failed_event_count"] == 4
    assert _by_currency(result["baseline"]["exposure_by_currency"]) == {"INR": "400.00"}
    assert result["projected"]["failed_event_count"] == 2
    assert result["projected"]["success_event_count"] == 2
    assert _by_currency(result["projected"]["exposure_by_currency"]) == {"INR": "200.00"}
    assert _by_currency(result["estimated_recovery_by_currency"]) == {"INR": "200.00"}
    assert result["delta"]["failed_event_count_delta"] == -2
    assert _by_currency(result["delta"]["financial_delta_by_currency"]) == {"INR": "-200.00"}


# --- C. REROUTE_PROVIDER -------------------------------------------------


def test_reroute_provider_scopes_to_the_affected_source_only(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(
            client, api_key, merchant["id"], "gateway_degraded", _ago(now, minutes_ago),
            amount=Decimal("50.00"), currency="USD", source="provider_a",
        )
    _ingest(
        client, api_key, merchant["id"], "gateway_degraded", _ago(now, 20),
        amount=Decimal("50.00"), currency="USD", source="provider_b",
    )
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["evidence_event_count"] == 4

    response = _simulate(client, api_key, investigation["id"], "REROUTE_PROVIDER")
    assert response.status_code == 201, response.text
    body = response.json()
    result = body["result"]

    assert result["eligible_event_count"] == 3
    assert "provider_a" in result["scope_description"]
    assert _by_currency(result["baseline"]["exposure_by_currency"]) == {"USD": "150.00"}
    # default reroute_success_rate = 0.65: scoped=3, success=round(3*0.65)=2
    assert result["projected"]["success_event_count"] == 2
    assert result["projected"]["failed_event_count"] == 1
    assert _by_currency(result["estimated_recovery_by_currency"]) == {"USD": "97.50"}


# --- D. TARGET_AFFECTED_EVENT_TYPE ----------------------------------------


def test_target_affected_event_type_scopes_to_the_dominant_signal_only(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    _ingest(
        client, api_key, merchant["id"], "settlement_delayed", _ago(now, 5),
        amount=Decimal("80.00"), currency="INR",
    )
    _ingest(
        client, api_key, merchant["id"], "settlement_delayed", _ago(now, 10),
        amount=Decimal("80.00"), currency="INR",
    )
    _ingest(
        client, api_key, merchant["id"], "payment_failed", _ago(now, 15),
        amount=Decimal("80.00"), currency="INR",
    )
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["dominant_signal_event_type"] == "settlement_delayed"

    event_type_response = _simulate(
        client, api_key, investigation["id"], "TARGET_AFFECTED_EVENT_TYPE"
    )
    assert event_type_response.status_code == 201, event_type_response.text
    event_type_result = event_type_response.json()["result"]
    assert event_type_result["eligible_event_count"] == 2
    assert "settlement_delayed" in event_type_result["scope_description"]

    # A different scenario over the SAME investigation scopes differently --
    # RETRY_AFFECTED_PAYMENTS only ever targets payment_failed, regardless
    # of which signal is dominant.
    retry_response = _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS"
    )
    retry_result = retry_response.json()["result"]
    assert retry_result["eligible_event_count"] == 1


def test_target_affected_event_type_insufficient_when_no_dominant_signal(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["dominant_signal_event_type"] is None
    # incident_detected is False here too, so this also exercises the
    # incident_detected gate -- see test_insufficient_evidence_when_no_incident.
    response = _simulate(client, api_key, investigation["id"], "TARGET_AFFECTED_EVENT_TYPE")
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "insufficient_evidence"


# --- E. Same input twice --------------------------------------------------


def test_same_input_produces_identical_result_twice(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("100.00"), currency="INR",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)

    first = _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.5", "scope_fraction": "1.0"},
    ).json()
    second = _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.5", "scope_fraction": "1.0"},
    ).json()

    assert first["id"] != second["id"]  # append-only: distinct rows
    assert first["result"] == second["result"]
    assert first["assumptions"] == second["assumptions"]
    assert first["input_snapshot"] == second["input_snapshot"]


# --- F. Currency separation ------------------------------------------------


def test_currencies_are_never_mixed(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("100.00"), currency="INR",
        )
    for minutes_ago in (15, 20):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("20.00"), currency="USD",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)

    response = _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    result = response.json()["result"]

    assert _by_currency(result["baseline"]["exposure_by_currency"]) == {
        "INR": "200.00",
        "USD": "40.00",
    }
    assert _by_currency(result["estimated_recovery_by_currency"]) == {
        "INR": "200.00",
        "USD": "40.00",
    }
    assert _by_currency(result["projected"]["exposure_by_currency"]) == {
        "INR": "0.00",
        "USD": "0.00",
    }


# --- G. Missing amount -------------------------------------------------


def test_missing_amount_is_never_fabricated_as_zero(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, 5))  # amount=None
    for minutes_ago in (10, 15):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("50.00"), currency="INR",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)

    response = _simulate(client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS")
    result = response.json()["result"]

    assert result["eligible_event_count"] == 3
    assert result["baseline"]["exposure_amount_unknown_count"] == 1
    assert _by_currency(result["baseline"]["exposure_by_currency"]) == {"INR": "100.00"}
    assert result["projected"]["exposure_amount_unknown_count"] == 1


# --- H. Invalid scenario -------------------------------------------------


def test_invalid_scenario_is_rejected(client, api_key):
    response = client.post(
        f"/v1/investigations/{uuid.uuid4()}/simulations",
        json={"scenario": "DELETE_EVERYTHING"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 422


# --- I. Invalid parameters -------------------------------------------------


def test_out_of_bounds_success_rate_is_rejected(client, api_key):
    response = client.post(
        f"/v1/investigations/{uuid.uuid4()}/simulations",
        json={
            "scenario": "RETRY_AFFECTED_PAYMENTS",
            "assumptions": {"success_rate": "1.5"},
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 422


def test_do_nothing_rejects_assumption_overrides(client, api_key):
    response = client.post(
        f"/v1/investigations/{uuid.uuid4()}/simulations",
        json={"scenario": "DO_NOTHING", "assumptions": {"success_rate": "0.5"}},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 422


# --- J. Insufficient evidence -------------------------------------------


def test_insufficient_evidence_when_no_incident(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    _ingest(
        client, api_key, merchant["id"], "payment_failed", _ago(now, 5),
        amount=Decimal("10.00"), currency="INR",
    )  # only 1 event -- below DETECTION_THRESHOLD
    investigation = _run_investigation(client, api_key, merchant["id"], now)
    assert investigation["incident_detected"] is False

    response = _simulate(client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["result"] == {}
    assert body["failure_reason"]


def test_simulation_404_for_unknown_investigation(client, api_key):
    response = _simulate(client, api_key, uuid.uuid4(), "DO_NOTHING")
    assert response.status_code == 404


# --- K. Append-only persistence -------------------------------------------


def test_repeated_simulations_create_separate_rows(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago))
    investigation = _run_investigation(client, api_key, merchant["id"], now)

    first = _simulate(client, api_key, investigation["id"], "DO_NOTHING").json()
    second = _simulate(client, api_key, investigation["id"], "DO_NOTHING").json()
    assert first["id"] != second["id"]

    list_response = client.get(
        f"/v1/investigations/{investigation['id']}/simulations",
        headers={"X-API-Key": api_key},
    )
    assert list_response.status_code == 200
    body = list_response.json()
    ids = {item["id"] for item in body["items"]}
    assert {first["id"], second["id"]} <= ids
    assert body["total"] >= 2


# --- L. Investigation isolation -------------------------------------------


def test_one_investigation_cannot_read_another_investigations_simulation(client, api_key):
    merchant_a = _create_merchant(client, api_key)
    merchant_b = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(client, api_key, merchant_a["id"], "payment_failed", _ago(now, minutes_ago))
        _ingest(client, api_key, merchant_b["id"], "payment_failed", _ago(now, minutes_ago))
    investigation_a = _run_investigation(client, api_key, merchant_a["id"], now)
    investigation_b = _run_investigation(client, api_key, merchant_b["id"], now)

    simulation_a = _simulate(client, api_key, investigation_a["id"], "DO_NOTHING").json()

    response = client.get(
        f"/v1/investigations/{investigation_b['id']}/simulations/{simulation_a['id']}",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 404


# --- M. Authentication -----------------------------------------------------


def test_simulation_endpoints_require_api_key(client):
    investigation_id = uuid.uuid4()
    assert client.post(
        f"/v1/investigations/{investigation_id}/simulations", json={"scenario": "DO_NOTHING"}
    ).status_code == 401
    assert client.get(
        f"/v1/investigations/{investigation_id}/simulations"
    ).status_code == 401
    assert client.get(
        f"/v1/investigations/{investigation_id}/simulations/{uuid.uuid4()}"
    ).status_code == 401


# --- N. API integration: POST persists, GET list/detail return it --------


def test_post_persists_and_get_list_and_detail_return_it(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(
            client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago),
            amount=Decimal("60.00"), currency="INR",
        )
    investigation = _run_investigation(client, api_key, merchant["id"], now)

    post_response = _simulate(client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS")
    assert post_response.status_code == 201
    posted = post_response.json()
    assert posted["investigation_id"] == investigation["id"]
    assert posted["simulator_version"]

    list_response = client.get(
        f"/v1/investigations/{investigation['id']}/simulations",
        headers={"X-API-Key": api_key},
    )
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert any(item["id"] == posted["id"] for item in list_body["items"])

    detail_response = client.get(
        f"/v1/investigations/{investigation['id']}/simulations/{posted['id']}",
        headers={"X-API-Key": api_key},
    )
    assert detail_response.status_code == 200
    assert detail_response.json() == posted
