import uuid


def test_create_merchant(client, api_key):
    response = client.post(
        "/v1/merchants",
        json={"name": "Acme Retail", "segment": "retail"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Retail"
    assert body["segment"] == "retail"
    assert uuid.UUID(body["id"])


def test_create_merchant_requires_api_key(client):
    response = client.post("/v1/merchants", json={"name": "Acme Retail"})
    assert response.status_code == 401


def test_create_merchant_rejects_empty_name(client, api_key):
    response = client.post(
        "/v1/merchants", json={"name": ""}, headers={"X-API-Key": api_key}
    )
    assert response.status_code == 422


def test_list_merchants_includes_newly_created(client, api_key):
    created = client.post(
        "/v1/merchants", json={"name": "List Test Merchant"}, headers={"X-API-Key": api_key}
    ).json()
    response = client.get("/v1/merchants", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    ids = [m["id"] for m in response.json()]
    assert created["id"] in ids


def test_list_merchants_requires_api_key(client):
    response = client.get("/v1/merchants")
    assert response.status_code == 401


def test_get_merchant_not_found(client, api_key):
    response = client.get(f"/v1/merchants/{uuid.uuid4()}", headers={"X-API-Key": api_key})
    assert response.status_code == 404


def test_get_merchant(client, api_key):
    created = client.post(
        "/v1/merchants", json={"name": "Merchant C"}, headers={"X-API-Key": api_key}
    ).json()
    response = client.get(f"/v1/merchants/{created['id']}", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert response.json()["name"] == "Merchant C"
