"""Tests for investigation reasoning (Phase 4).

No test in this file ever calls the real hosted reasoning API -- every test
injects a FakeReasoningProvider via FastAPI's dependency_overrides, so this
suite needs no network access and no real provider credentials, exactly
like every other test in this project needs no external services beyond
the local Postgres/Redis docker-compose stack.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.main import app
from app.providers.reasoning import RawHypothesis, RawReasoningResult, ReasoningProviderError
from app.routers.investigations import get_reasoning_provider


class FakeReasoningProvider:
    """Test double for ReasoningProvider. Records whether it was called."""

    def __init__(self, result: RawReasoningResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.called = False
        self.last_context = None

    def generate_hypotheses(self, context):
        self.called = True
        self.last_context = context
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.fixture(autouse=True)
def _clear_provider_override():
    # Every test sets its own override (or leaves none = "not configured").
    # This guarantees no override leaks between tests regardless of pass/fail.
    yield
    app.dependency_overrides.pop(get_reasoning_provider, None)


def _override_provider(provider) -> None:
    app.dependency_overrides[get_reasoning_provider] = lambda: provider


def _create_merchant(client, api_key, name="Reasoning Test Merchant"):
    response = client.post(
        "/v1/merchants",
        json={"name": f"{name} {uuid.uuid4()}"},
        headers={"X-API-Key": api_key},
    )
    return response.json()


def _ingest(client, api_key, merchant_id, event_type, occurred_at, amount=None, currency=None):
    response = client.post(
        "/v1/events",
        json={
            "merchant_id": merchant_id,
            "event_type": event_type,
            "source": "manual",
            "external_reference": f"evt-{uuid.uuid4()}",
            "amount": str(amount) if amount is not None else None,
            "currency": currency,
            "occurred_at": occurred_at.isoformat(),
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_detected_investigation(client, api_key):
    """A merchant with 3 payment_failed events -> incident_detected=True."""
    merchant = _create_merchant(client, api_key)
    now = datetime.now(UTC)
    event_ids = []
    for minutes_ago in (5, 10, 15):
        event = _ingest(
            client, api_key, merchant["id"], "payment_failed", now - timedelta(minutes=minutes_ago),
            amount="100.00", currency="INR",
        )
        event_ids.append(event["id"])

    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"], "as_of": now.isoformat()},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["incident_detected"] is True
    return body["id"], event_ids


def _create_no_incident_investigation(client, api_key):
    merchant = _create_merchant(client, api_key)
    response = client.post(
        "/v1/investigations",
        json={"merchant_id": merchant["id"]},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    assert response.json()["incident_detected"] is False
    return response.json()["id"]


def _valid_hypothesis(hypothesis_id, rank, supporting_evidence, confidence="high"):
    return RawHypothesis(
        hypothesis_id=hypothesis_id,
        rank=rank,
        title=f"Hypothesis {hypothesis_id}",
        explanation="A plausible, evidence-grounded explanation.",
        confidence=confidence,
        supporting_evidence=list(supporting_evidence),
        contradicting_evidence=[],
        uncertainty="Cannot rule out an unrelated upstream gateway issue.",
    )


# --- Reasoning success ---------------------------------------------------


def test_reasoning_completed_with_ranked_hypotheses_and_evidence_refs(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(
        result=RawReasoningResult(
            hypotheses=[
                _valid_hypothesis("h2", 2, [event_ids[1]], confidence="low"),
                _valid_hypothesis("h1", 1, [event_ids[0], event_ids[2]], confidence="high"),
            ]
        )
    )
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert provider.called is True
    assert [h["hypothesis_id"] for h in body["hypotheses"]] == ["h1", "h2"]  # sorted by rank
    assert body["hypotheses"][0]["confidence"] == "high"
    assert set(body["hypotheses"][0]["supporting_evidence"]) == {event_ids[0], event_ids[2]}
    assert body["failure_reason"] is None

    # Persists: GET returns the same result back.
    fetched = client.get(
        f"/v1/investigations/{investigation_id}/reasoning", headers={"X-API-Key": api_key}
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_reasoning_does_not_call_provider_or_mutate_investigation_facts(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    before = client.get(
        f"/v1/investigations/{investigation_id}", headers={"X-API-Key": api_key}
    ).json()

    provider = FakeReasoningProvider(
        result=RawReasoningResult(hypotheses=[_valid_hypothesis("h1", 1, [event_ids[0]])])
    )
    _override_provider(provider)
    client.post(f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key})

    after = client.get(
        f"/v1/investigations/{investigation_id}", headers={"X-API-Key": api_key}
    ).json()
    # Safety invariant: reasoning must never alter the deterministic
    # investigation facts it read (impact, evidence, dominant signal, ...).
    assert before == after


# --- Evidence grounding ----------------------------------------------------


def test_reasoning_rejects_hallucinated_evidence_reference(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    fabricated_event_id = str(uuid.uuid4())
    assert fabricated_event_id not in event_ids
    provider = FakeReasoningProvider(
        result=RawReasoningResult(
            hypotheses=[_valid_hypothesis("h1", 1, [fabricated_event_id])]
        )
    )
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "invalid_output"
    assert body["hypotheses"] == []
    assert body["failure_reason"] is not None


def test_reasoning_accepts_valid_evidence_references(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(
        result=RawReasoningResult(
            hypotheses=[_valid_hypothesis("h1", 1, [event_ids[0]])]
        )
    )
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.json()["status"] == "completed"


def test_reasoning_rejects_hypothesis_with_no_supporting_evidence(client, api_key):
    investigation_id, _event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(
        result=RawReasoningResult(hypotheses=[_valid_hypothesis("h1", 1, [])])
    )
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.json()["status"] == "invalid_output"


# --- Invalid reasoning output ----------------------------------------------


def test_reasoning_rejects_duplicate_hypothesis_id(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(
        result=RawReasoningResult(
            hypotheses=[
                _valid_hypothesis("h1", 1, [event_ids[0]]),
                _valid_hypothesis("h1", 2, [event_ids[1]]),
            ]
        )
    )
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.json()["status"] == "invalid_output"


def test_reasoning_rejects_duplicate_rank(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(
        result=RawReasoningResult(
            hypotheses=[
                _valid_hypothesis("h1", 1, [event_ids[0]]),
                _valid_hypothesis("h2", 1, [event_ids[1]]),
            ]
        )
    )
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.json()["status"] == "invalid_output"


def test_reasoning_rejects_invalid_rank(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(
        result=RawReasoningResult(hypotheses=[_valid_hypothesis("h1", 0, [event_ids[0]])])
    )
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.json()["status"] == "invalid_output"


def test_reasoning_rejects_invalid_confidence(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(
        result=RawReasoningResult(
            hypotheses=[_valid_hypothesis("h1", 1, [event_ids[0]], confidence="87%")]
        )
    )
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.json()["status"] == "invalid_output"


def test_reasoning_no_valid_hypotheses_when_provider_returns_empty_list(client, api_key):
    investigation_id, _event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(result=RawReasoningResult(hypotheses=[]))
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "no_valid_hypotheses"
    assert body["hypotheses"] == []
    assert body["failure_reason"] is None


# --- Failure handling -------------------------------------------------------


def test_reasoning_unavailable_when_provider_not_configured(client, api_key):
    investigation_id, _event_ids = _create_detected_investigation(client, api_key)
    _override_provider(None)  # simulates get_reasoning_provider() returning None

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["failure_reason"] is not None


def test_reasoning_unavailable_on_provider_error(client, api_key):
    investigation_id, _event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(error=ReasoningProviderError("reasoning provider timed out"))
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "unavailable"
    assert "timed out" in body["failure_reason"]


def test_reasoning_insufficient_evidence_when_no_incident_detected(client, api_key):
    investigation_id = _create_no_incident_investigation(client, api_key)
    provider = FakeReasoningProvider(result=RawReasoningResult(hypotheses=[]))
    _override_provider(provider)

    response = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["hypotheses"] == []
    # The provider must not be called at all when there is nothing to reason about.
    assert provider.called is False


def test_reasoning_unknown_investigation_404(client, api_key):
    _override_provider(FakeReasoningProvider(result=RawReasoningResult(hypotheses=[])))
    response = client.post(
        f"/v1/investigations/{uuid.uuid4()}/reason", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 404


# --- Auditability / re-run semantics ---------------------------------------


def test_reasoning_reruns_create_new_persisted_rows(client, api_key):
    investigation_id, event_ids = _create_detected_investigation(client, api_key)
    provider = FakeReasoningProvider(
        result=RawReasoningResult(hypotheses=[_valid_hypothesis("h1", 1, [event_ids[0]])])
    )
    _override_provider(provider)

    first = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    ).json()
    second = client.post(
        f"/v1/investigations/{investigation_id}/reason", headers={"X-API-Key": api_key}
    ).json()

    assert first["id"] != second["id"]  # each run is a new, separately-audited row

    latest = client.get(
        f"/v1/investigations/{investigation_id}/reasoning", headers={"X-API-Key": api_key}
    ).json()
    assert latest["id"] == second["id"]  # GET always returns the most recent


# --- GET /reasoning ----------------------------------------------------------


def test_get_latest_reasoning_404_when_never_run(client, api_key):
    investigation_id, _event_ids = _create_detected_investigation(client, api_key)
    response = client.get(
        f"/v1/investigations/{investigation_id}/reasoning", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 404


def test_get_latest_reasoning_404_when_investigation_unknown(client, api_key):
    response = client.get(
        f"/v1/investigations/{uuid.uuid4()}/reasoning", headers={"X-API-Key": api_key}
    )
    assert response.status_code == 404


# --- Auth --------------------------------------------------------------------


def test_reason_requires_api_key(client, api_key):
    investigation_id, _event_ids = _create_detected_investigation(client, api_key)
    response = client.post(f"/v1/investigations/{investigation_id}/reason")
    assert response.status_code == 401


def test_get_latest_reasoning_requires_api_key(client, api_key):
    investigation_id, _event_ids = _create_detected_investigation(client, api_key)
    response = client.get(f"/v1/investigations/{investigation_id}/reasoning")
    assert response.status_code == 401
