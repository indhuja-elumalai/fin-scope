import uuid
from datetime import UTC, datetime, timedelta


def _create_merchant(client, api_key, name="Investigation Test Merchant"):
    response = client.post(
        "/v1/merchants",
        json={"name": f"{name} {uuid.uuid4()}"},
        headers={"X-API-Key": api_key},
    )
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
            "external_reference": f"evt-{uuid.uuid4()}",
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


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_investigation_detects_incident_with_enough_concerning_events(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago))

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["incident_detected"] is True
    assert body["evidence_event_count"] == 3
    assert body["event_type_counts"] == {"payment_failed": 3}


def test_investigation_no_incident_when_below_threshold(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10):
        _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago))

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["incident_detected"] is False
    assert body["evidence_event_count"] == 2
    assert body["dominant_signal_event_type"] is None
    assert body["dominant_signal_share"] is None


def test_investigation_ignores_events_outside_window(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (90, 120, 150):
        _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago))

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["incident_detected"] is False
    assert body["evidence_event_count"] == 0
    assert body["evidence"] == []


def test_investigation_ignores_non_concerning_event_types(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    non_concerning = (
        (5, "payment_succeeded"),
        (10, "refund_issued"),
        (15, "payment_succeeded"),
    )
    for minutes_ago, event_type in non_concerning:
        _ingest(client, api_key, merchant["id"], event_type, _ago(now, minutes_ago))

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["incident_detected"] is False
    assert body["evidence_event_count"] == 0


def test_investigation_dominant_signal_is_majority_type(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago))
    _ingest(client, api_key, merchant["id"], "settlement_delayed", _ago(now, 20))

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    body = response.json()
    assert body["evidence_event_count"] == 4
    assert body["dominant_signal_event_type"] == "payment_failed"
    assert body["dominant_signal_share"] == "0.7500"


def test_investigation_dominant_signal_tie_broken_by_earliest_occurrence(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    # Chronological order: settlement_delayed (earliest), payment_failed,
    # settlement_delayed, payment_failed -- a 2-2 tie broken by whichever
    # tied type's first occurrence came earliest: settlement_delayed.
    _ingest(client, api_key, merchant["id"], "settlement_delayed", _ago(now, 40))
    _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, 30))
    _ingest(client, api_key, merchant["id"], "settlement_delayed", _ago(now, 20))
    _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, 10))

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    body = response.json()
    assert body["dominant_signal_event_type"] == "settlement_delayed"
    assert body["dominant_signal_share"] == "0.5000"


def test_investigation_impact_is_currency_safe(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    _ingest(
        client, api_key, merchant["id"], "payment_failed", _ago(now, 5),
        amount="100.00", currency="INR",
    )
    _ingest(
        client, api_key, merchant["id"], "payment_failed", _ago(now, 10),
        amount="50.00", currency="INR",
    )
    _ingest(
        client, api_key, merchant["id"], "payment_failed", _ago(now, 15),
        amount="20.00", currency="USD",
    )
    _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, 20))  # amount unknown

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    body = response.json()
    assert body["evidence_event_count"] == 4
    assert body["impact_amount_unknown_count"] == 1
    breakdown = {item["currency"]: item for item in body["impact_breakdown"]}
    assert breakdown.keys() == {"INR", "USD"}
    assert breakdown["INR"]["total_amount"] == "150.00"
    assert breakdown["INR"]["event_count"] == 2
    assert breakdown["USD"]["total_amount"] == "20.00"
    assert breakdown["USD"]["event_count"] == 1


def test_investigation_evidence_is_ordered_timeline(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    third = _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, 5))
    first = _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, 15))
    second = _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, 10))

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    evidence_ids = [item["event_id"] for item in response.json()["evidence"]]
    assert evidence_ids == [first["id"], second["id"], third["id"]]


def test_investigation_persists_even_without_incident(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    investigation_id = response.json()["id"]

    url = f"/v1/investigations/{investigation_id}"
    fetched = client.get(url, headers={"X-API-Key": api_key})
    assert fetched.status_code == 200
    assert fetched.json()["incident_detected"] is False


def test_investigation_as_of_controls_the_window(client, api_key):
    merchant = _create_merchant(client, api_key)
    reference = datetime.now(UTC) - timedelta(days=2)
    for minutes_ago in (5, 10, 15):
        _ingest(client, api_key, merchant["id"], "payment_failed", _ago(reference, minutes_ago))

    # Without as_of (default "now"), these two-day-old events fall outside
    # the 60-minute window -- no incident.
    default_response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"]},
        headers={"X-API-Key": api_key},
    )
    assert default_response.json()["incident_detected"] is False

    # With as_of anchored near the events, the same events are in-window.
    as_of_response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(reference)},
        headers={"X-API-Key": api_key},
    )
    body = as_of_response.json()
    assert body["incident_detected"] is True
    assert body["evidence_event_count"] == 3


def test_investigation_unknown_merchant_404(client, api_key):
    response = client.post(
        "/v1/investigations",
        json={"merchant_id": str(uuid.uuid4())},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 404


def test_create_investigation_requires_api_key(client):
    response = client.post("/v1/investigations", json={"merchant_id": str(uuid.uuid4())})
    assert response.status_code == 401


def test_list_investigations_requires_api_key(client):
    response = client.get("/v1/investigations")
    assert response.status_code == 401


def test_list_investigations_filters_by_merchant(client, api_key):
    merchant = _create_merchant(client, api_key)
    other_merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )
    client.post(
        "/v1/investigations",
        json={"merchant_id": other_merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )

    response = client.get(
        "/v1/investigations",
        params={"merchant_id": merchant["id"]},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["merchant_id"] == merchant["id"] for item in body["items"])


def test_list_investigations_filters_by_incident_detected(client, api_key):
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    for minutes_ago in (5, 10, 15):
        _ingest(client, api_key, merchant["id"], "payment_failed", _ago(now, minutes_ago))
    client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": _iso(now)},
        headers={"X-API-Key": api_key},
    )

    response = client.get(
        "/v1/investigations",
        params={"merchant_id": merchant["id"], "incident_detected": True},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["incident_detected"] is True for item in body["items"])


def test_get_investigation_not_found(client, api_key):
    response = client.get(f"/v1/investigations/{uuid.uuid4()}", headers={"X-API-Key": api_key})
    assert response.status_code == 404
