import uuid
from datetime import UTC, datetime


def _create_merchant(client, api_key, name="Event Test Merchant"):
    response = client.post(
        "/v1/merchants",
        json={"name": f"{name} {uuid.uuid4()}"},
        headers={"X-API-Key": api_key},
    )
    return response.json()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def test_ingest_event_success(client, api_key):
    merchant = _create_merchant(client, api_key)
    response = client.post(
        "/v1/events",
        json={
            "merchant_id": merchant["id"],
            "event_type": "payment_failed",
            "source": "manual",
            "external_reference": f"evt-{uuid.uuid4()}",
            "amount": "199.99",
            "currency": "INR",
            "status": "failed",
            "payload": {"reason": "insufficient_funds"},
            "occurred_at": _now(),
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["event_type"] == "payment_failed"
    assert body["merchant_id"] == merchant["id"]
    assert float(body["amount"]) == 199.99
    assert body["payload"] == {"reason": "insufficient_funds"}


def test_ingest_event_unknown_merchant(client, api_key):
    response = client.post(
        "/v1/events",
        json={
            "merchant_id": str(uuid.uuid4()),
            "event_type": "payment_failed",
            "source": "manual",
            "occurred_at": _now(),
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 404


def test_ingest_event_invalid_event_type(client, api_key):
    merchant = _create_merchant(client, api_key)
    response = client.post(
        "/v1/events",
        json={
            "merchant_id": merchant["id"],
            "event_type": "not_a_real_type",
            "source": "manual",
            "occurred_at": _now(),
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 422


def test_ingest_event_is_idempotent(client, api_key):
    merchant = _create_merchant(client, api_key)
    body = {
        "merchant_id": merchant["id"],
        "event_type": "refund_issued",
        "source": "manual",
        "external_reference": f"evt-idempotent-{uuid.uuid4()}",
        "occurred_at": _now(),
    }
    first = client.post("/v1/events", json=body, headers={"X-API-Key": api_key})
    second = client.post("/v1/events", json=body, headers={"X-API-Key": api_key})
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_ingest_event_nullable_amount(client, api_key):
    merchant = _create_merchant(client, api_key)
    response = client.post(
        "/v1/events",
        json={
            "merchant_id": merchant["id"],
            "event_type": "gateway_degraded",
            "source": "manual",
            "occurred_at": _now(),
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    assert response.json()["amount"] is None
    assert response.json()["currency"] is None


def test_ingest_event_requires_api_key(client):
    response = client.post(
        "/v1/events",
        json={
            "merchant_id": str(uuid.uuid4()),
            "event_type": "payment_failed",
            "source": "manual",
            "occurred_at": _now(),
        },
    )
    assert response.status_code == 401


def test_list_events_filters_by_merchant(client, api_key):
    merchant = _create_merchant(client, api_key)
    other_merchant = _create_merchant(client, api_key)
    client.post(
        "/v1/events",
        json={
            "merchant_id": merchant["id"],
            "event_type": "payment_failed",
            "source": "manual",
            "external_reference": f"evt-{uuid.uuid4()}",
            "occurred_at": _now(),
        },
        headers={"X-API-Key": api_key},
    )
    client.post(
        "/v1/events",
        json={
            "merchant_id": other_merchant["id"],
            "event_type": "payment_failed",
            "source": "manual",
            "external_reference": f"evt-{uuid.uuid4()}",
            "occurred_at": _now(),
        },
        headers={"X-API-Key": api_key},
    )
    response = client.get(
        "/v1/events", params={"merchant_id": merchant["id"]}, headers={"X-API-Key": api_key}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["merchant_id"] == merchant["id"] for item in body["items"])


def test_list_events_filters_by_event_type(client, api_key):
    merchant = _create_merchant(client, api_key)
    client.post(
        "/v1/events",
        json={
            "merchant_id": merchant["id"],
            "event_type": "settlement_delayed",
            "source": "manual",
            "external_reference": f"evt-{uuid.uuid4()}",
            "occurred_at": _now(),
        },
        headers={"X-API-Key": api_key},
    )
    response = client.get(
        "/v1/events",
        params={"merchant_id": merchant["id"], "event_type": "settlement_delayed"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(item["event_type"] == "settlement_delayed" for item in body["items"])


def test_list_events_requires_api_key(client):
    response = client.get("/v1/events")
    assert response.status_code == 401


def test_get_event(client, api_key):
    merchant = _create_merchant(client, api_key)
    created = client.post(
        "/v1/events",
        json={
            "merchant_id": merchant["id"],
            "event_type": "payment_succeeded",
            "source": "manual",
            "external_reference": f"evt-{uuid.uuid4()}",
            "occurred_at": _now(),
        },
        headers={"X-API-Key": api_key},
    ).json()
    response = client.get(f"/v1/events/{created['id']}", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_event_not_found(client, api_key):
    response = client.get(f"/v1/events/{uuid.uuid4()}", headers={"X-API-Key": api_key})
    assert response.status_code == 404
