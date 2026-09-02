import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app.models.audit_log import AuditLog
from app.models.investigation_decision import InvestigationDecision

# --- helpers, mirroring test_decisions.py's own local-helper convention ---


def _create_merchant(client, api_key, name="Action Test Merchant"):
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
            "external_reference": f"act-evt-{uuid.uuid4()}",
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


def _act(client, api_key, investigation_id, decision_id, body=None):
    kwargs = {"headers": {"X-API-Key": api_key}}
    if body is not None:
        kwargs["json"] = body
    return client.post(
        f"/v1/investigations/{investigation_id}/decisions/{decision_id}/actions", **kwargs
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


def _allowed_decision(client, api_key, amount="10.00"):
    """A full incident -> simulation -> ALLOWED decision, ready to act on."""
    investigation = _incident_investigation_with_failed_payments(client, api_key, amount=amount)
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "ALLOWED", decision
    return investigation, decision


def _audit_log_count(entity_id: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(
            select(AuditLog.id).where(
                AuditLog.event_type == "investigation_action_completed",
                AuditLog.entity_id == entity_id,
            )
        ) and len(
            list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.event_type == "investigation_action_completed",
                        AuditLog.entity_id == entity_id,
                    )
                )
            )
        ) or 0
    finally:
        db.close()


# --- 1/8. executed ---------------------------------------------------------


def test_allowed_decision_executes(client, api_key):
    investigation, decision = _allowed_decision(client, api_key)
    response = _act(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "executed"
    assert body["rejection_reason"] is None
    assert body["scenario"] == "RETRY_AFFECTED_PAYMENTS"
    assert body["policy_decision_snapshot"] == "ALLOWED"
    assert body["sandbox_result"]["action_kind"] == "SIMULATED_RETRY_PAYMENTS"
    assert body["sandbox_result"]["targeted_event_count"] == 3
    assert "SANDBOX-ONLY" in body["sandbox_result"]["note"]


def test_do_nothing_allowed_decision_executes_as_no_op(client, api_key):
    # DO_NOTHING can only be *preferred* when nothing else was simulated,
    # or every simulated alternative did no better -- simulate only
    # DO_NOTHING so it is the sole (and therefore preferred) candidate.
    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="10.00")
    _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["evaluation_result"]["preferred_scenario"] == "DO_NOTHING"
    assert decision["policy_decision"] == "ALLOWED"

    response = _act(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "executed"
    assert body["scenario"] == "DO_NOTHING"
    assert body["sandbox_result"]["action_kind"] == "NO_OP"
    assert body["sandbox_result"]["targeted_event_count"] == 0
    assert body["sandbox_result"]["targeted_event_ids"] == []


# --- 2/3/4/5/6. rejected -----------------------------------------------


def test_requires_human_approval_decision_is_rejected(client, api_key):
    # Large exposure trips REQUIRES_HUMAN_APPROVAL -- see
    # test_decisions.py::test_large_exposure_requires_human_approval for
    # the same fixture shape.
    investigation = _incident_investigation_with_failed_payments(
        client, api_key, count=3, amount="5000.00"
    )
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.1", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "REQUIRES_HUMAN_APPROVAL"

    response = _act(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert body["policy_decision_snapshot"] == "REQUIRES_HUMAN_APPROVAL"
    assert "not ALLOWED" in body["rejection_reason"]
    assert body["sandbox_result"] == {}


def test_blocked_decision_is_rejected(client, api_key, monkeypatch):
    # BLOCKED is not reachable through the default policy config (empty
    # prohibited_scenarios) -- the same reason test_decisions.py's own
    # test_preferred_can_be_blocked_without_promoting_a_runner_up only
    # exercises REQUIRES_HUMAN_APPROVAL at the integration level and
    # leaves BLOCKED to test_policy.py's unit tests. Here we prove the
    # *action* layer's handling of a real BLOCKED decision end to end by
    # temporarily prohibiting the scenario this fixture will prefer --
    # app.domain.decisions reads DEFAULT_POLICY_CONFIG as a module-level
    # name at call time, so patching it here (and nowhere else) is
    # sufficient and fully reverted after this test.
    import app.domain.decisions as decision_domain
    from app.domain.policy import PolicyConfig

    prohibiting_config = PolicyConfig(
        version=decision_domain.DEFAULT_POLICY_CONFIG.version,
        autonomous_exposure_threshold_by_currency=(
            decision_domain.DEFAULT_POLICY_CONFIG.autonomous_exposure_threshold_by_currency
        ),
        max_autonomous_eligible_event_count=(
            decision_domain.DEFAULT_POLICY_CONFIG.max_autonomous_eligible_event_count
        ),
        prohibited_scenarios=frozenset({"RETRY_AFFECTED_PAYMENTS"}),
    )
    monkeypatch.setattr(decision_domain, "DEFAULT_POLICY_CONFIG", prohibiting_config)

    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="10.00")
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "BLOCKED"

    response = _act(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert body["policy_decision_snapshot"] == "BLOCKED"
    assert body["sandbox_result"] == {}


def test_insufficient_evidence_decision_is_rejected(client, api_key):
    merchant = _create_merchant(client, api_key)
    investigation = _run_investigation(client, api_key, merchant["id"], datetime.now(UTC))
    assert investigation["incident_detected"] is False

    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["status"] == "insufficient_evidence"
    assert decision["policy_decision"] is None

    response = _act(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "insufficient_evidence" in body["rejection_reason"]
    assert body["policy_decision_snapshot"] is None


def test_no_eligible_scenario_decision_is_rejected(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key)
    # No simulation run yet.
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["status"] == "no_eligible_scenario"

    response = _act(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "no_eligible_scenario" in body["rejection_reason"]


# --- 7. defense in depth -------------------------------------------------


def test_defensive_rejection_for_corrupted_preferred_simulation_id(client, api_key):
    investigation, decision = _allowed_decision(client, api_key)

    # Directly corrupt the persisted decision's preferred_simulation_id to
    # an id that does not exist -- not reachable via the real API
    # (app.domain.decisions always writes a real simulation id), but
    # app.domain.actions must never trust it blindly. See
    # app.domain.actions._authorize_and_execute.
    db = SessionLocal()
    try:
        row = db.get(InvestigationDecision, uuid.UUID(decision["id"]))
        row.evaluation_result = {
            **row.evaluation_result,
            "preferred_simulation_id": str(uuid.uuid4()),
        }
        db.commit()
    finally:
        db.close()

    response = _act(client, api_key, investigation["id"], decision["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert "preferred simulation" in body["rejection_reason"]


# --- 9/10. idempotency + audit -------------------------------------------


def test_idempotent_replay_returns_same_action_id(client, api_key):
    investigation, decision = _allowed_decision(client, api_key)
    first = _act(client, api_key, investigation["id"], decision["id"])
    assert first.status_code == 201
    second = _act(client, api_key, investigation["id"], decision["id"])
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json() == first.json()


def test_idempotent_replay_does_not_duplicate_audit_log(client, api_key):
    investigation, decision = _allowed_decision(client, api_key)
    first = _act(client, api_key, investigation["id"], decision["id"]).json()
    _act(client, api_key, investigation["id"], decision["id"])
    _act(client, api_key, investigation["id"], decision["id"])
    assert _audit_log_count(first["id"]) == 1


def test_rejected_action_is_also_idempotent(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key)
    decision = _decide(client, api_key, investigation["id"]).json()  # no_eligible_scenario
    first = _act(client, api_key, investigation["id"], decision["id"])
    assert first.status_code == 201
    second = _act(client, api_key, investigation["id"], decision["id"])
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert _audit_log_count(first.json()["id"]) == 1


# --- 11. concurrent-insert race (simulated deterministically) ------------


def test_concurrent_insert_race_resolves_to_one_row(client, api_key):
    # A genuine multi-threaded race against a single TestClient/SQLite-less
    # Postgres session is fragile to assert on reliably; instead this
    # deterministically reproduces the race app.domain.actions._persist is
    # built to survive: insert a second InvestigationAction row for the
    # same decision_id directly (bypassing the ORM-level idempotency
    # check app.domain.actions.run_action normally performs first), then
    # confirm the UNIQUE(decision_id) constraint itself refuses the
    # duplicate at the database level -- the actual safety net a
    # concurrent second HTTP request would also hit.
    from sqlalchemy.exc import IntegrityError

    from app.models.investigation_action import InvestigationAction

    investigation, decision = _allowed_decision(client, api_key)
    first = _act(client, api_key, investigation["id"], decision["id"]).json()

    db = SessionLocal()
    try:
        duplicate = InvestigationAction(
            investigation_id=uuid.UUID(investigation["id"]),
            decision_id=uuid.UUID(decision["id"]),
            status="executed",
            rejection_reason=None,
            scenario="RETRY_AFFECTED_PAYMENTS",
            simulation_id=None,
            policy_decision_snapshot="ALLOWED",
            executor_version="1",
            sandbox_result={},
        )
        db.add(duplicate)
        try:
            db.flush()
            raised = False
        except IntegrityError:
            raised = True
            db.rollback()
    finally:
        db.close()

    assert raised, "UNIQUE(decision_id) did not reject a second action row for the same decision"

    # And the original, legitimately-created row is still the only one a
    # client ever sees.
    replay = _act(client, api_key, investigation["id"], decision["id"])
    assert replay.status_code == 200
    assert replay.json()["id"] == first["id"]


# --- 12. forged body cannot authorize ------------------------------------


def test_forged_request_body_cannot_override_authorization(client, api_key):
    investigation = _incident_investigation_with_failed_payments(
        client, api_key, count=3, amount="5000.00"
    )
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.1", "scope_fraction": "1.0"},
    )
    decision = _decide(client, api_key, investigation["id"]).json()
    assert decision["policy_decision"] == "REQUIRES_HUMAN_APPROVAL"

    # The endpoint takes no request body at all -- an attempted status,
    # action_kind, or policy override in the JSON body is simply never
    # read by the handler; it cannot influence the computed result.
    response = _act(
        client,
        api_key,
        investigation["id"],
        decision["id"],
        body={
            "status": "executed",
            "policy_decision": "ALLOWED",
            "action_kind": "SIMULATED_RETRY_PAYMENTS",
            "sandbox_result": {"action_kind": "SIMULATED_RETRY_PAYMENTS"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert body["sandbox_result"] == {}


# --- 13/14. not found ------------------------------------------------------


def test_unknown_investigation_returns_404(client, api_key):
    response = _act(client, api_key, uuid.uuid4(), uuid.uuid4())
    assert response.status_code == 404


def test_cross_investigation_decision_returns_404(client, api_key):
    investigation_a, decision_a = _allowed_decision(client, api_key)
    investigation_b = _incident_investigation_with_failed_payments(client, api_key)

    response = _act(client, api_key, investigation_b["id"], decision_a["id"])
    assert response.status_code == 404

    get_response = client.get(
        f"/v1/investigations/{investigation_b['id']}/decisions/{decision_a['id']}/actions",
        headers={"X-API-Key": api_key},
    )
    assert get_response.status_code == 404


# --- 15. authentication ----------------------------------------------------


def test_action_endpoints_require_api_key(client):
    investigation_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    assert (
        client.post(
            f"/v1/investigations/{investigation_id}/decisions/{decision_id}/actions"
        ).status_code
        == 401
    )
    assert (
        client.get(
            f"/v1/investigations/{investigation_id}/decisions/{decision_id}/actions"
        ).status_code
        == 401
    )
    assert client.get(f"/v1/investigations/{investigation_id}/actions").status_code == 401


# --- 16. financial_events are never mutated -------------------------------


def test_financial_events_are_unchanged_by_a_sandbox_action(client, api_key):
    investigation, decision = _allowed_decision(client, api_key)

    before = client.get(
        f"/v1/events?merchant_id={investigation['merchant_id']}&limit=100",
        headers={"X-API-Key": api_key},
    ).json()

    action = _act(client, api_key, investigation["id"], decision["id"]).json()
    assert action["status"] == "executed"
    assert action["sandbox_result"]["targeted_event_count"] > 0

    after = client.get(
        f"/v1/events?merchant_id={investigation['merchant_id']}&limit=100",
        headers={"X-API-Key": api_key},
    ).json()

    assert before == after


# --- 17/18. provenance -----------------------------------------------------


def test_action_simulation_id_belongs_to_the_same_investigation(client, api_key):
    investigation, decision = _allowed_decision(client, api_key)
    action = _act(client, api_key, investigation["id"], decision["id"]).json()
    assert action["simulation_id"] == decision["evaluation_result"]["preferred_simulation_id"]

    simulation_response = client.get(
        f"/v1/investigations/{investigation['id']}/simulations/{action['simulation_id']}",
        headers={"X-API-Key": api_key},
    )
    assert simulation_response.status_code == 200
    assert simulation_response.json()["investigation_id"] == investigation["id"]


def test_policy_decision_snapshot_matches_the_authorizing_decision(client, api_key):
    investigation, decision = _allowed_decision(client, api_key)
    action = _act(client, api_key, investigation["id"], decision["id"]).json()
    assert action["policy_decision_snapshot"] == decision["policy_decision"] == "ALLOWED"


# --- 19. MVP authorization anchor: decision_id, not "latest decision" ----


def test_older_allowed_decision_remains_usable_after_a_newer_decision_exists(client, api_key):
    investigation, older_decision = _allowed_decision(client, api_key, amount="10.00")

    # Force a second, later decision for the same investigation with a
    # different outcome (large exposure -> REQUIRES_HUMAN_APPROVAL),
    # without changing the older decision at all -- decisions are
    # append-only (see app.domain.decisions).
    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "0.01", "scope_fraction": "1.0"},
    )
    newer_decision = _decide(client, api_key, investigation["id"]).json()
    assert newer_decision["id"] != older_decision["id"]
    assert newer_decision["created_at"] >= older_decision["created_at"]

    # This is intentional Phase 7 MVP behavior, not a latent bug: acting
    # on the OLDER decision_id must still succeed -- decision_id (never
    # "the investigation's current decision") is the authorization
    # anchor. See app.models.investigation_action module docstring.
    response = _act(client, api_key, investigation["id"], older_decision["id"])
    assert response.status_code == 201
    assert response.json()["status"] == "executed"


# --- 20. action history ordering -------------------------------------------


def test_action_history_is_newest_first_across_decisions(client, api_key):
    investigation = _incident_investigation_with_failed_payments(client, api_key, amount="10.00")

    _simulate(client, api_key, investigation["id"], "DO_NOTHING")
    decision_1 = _decide(client, api_key, investigation["id"]).json()
    action_1 = _act(client, api_key, investigation["id"], decision_1["id"]).json()

    _simulate(
        client, api_key, investigation["id"], "RETRY_AFFECTED_PAYMENTS",
        assumptions={"success_rate": "1.0", "scope_fraction": "1.0"},
    )
    decision_2 = _decide(client, api_key, investigation["id"]).json()
    action_2 = _act(client, api_key, investigation["id"], decision_2["id"]).json()

    response = client.get(
        f"/v1/investigations/{investigation['id']}/actions",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert ids.index(action_2["id"]) < ids.index(action_1["id"])
    assert body["total"] >= 2


# --- sandbox_executor has no externally-acting dependency ------------------


def test_sandbox_executor_module_has_no_network_or_db_dependency():
    import ast

    import app.domain.sandbox_executor as module

    tree = ast.parse(open(module.__file__).read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [n.name for n in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    forbidden = {
        "sqlalchemy",
        "httpx",
        "requests",
        "socket",
        "urllib",
        "app.models",
        "app.providers",
        "app.db",
        "random",
    }
    assert not (set(names) & forbidden), f"forbidden import(s) found: {set(names) & forbidden}"
