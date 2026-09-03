#!/usr/bin/env bash
#
# Phase 8 verification: Outcome Verification.
#
# Verifies that an outcome verification can ONLY be produced against an
# investigation when a persisted Phase 7 sandbox action exists -- the
# verifier is anchored strictly to action_id (never "the investigation's
# latest action"), and both the EXPECTED (Phase 5 projected simulation)
# and OBSERVED (Phase 7 sandbox result) snapshots are re-derived entirely
# server-side, never from anything the client sends. The verifier is pure
# and deterministic: it never contacts a real payment provider, never
# recomputes the simulation, and never mutates the action or its sandbox
# result. A verification is idempotent per action_id (at most one row
# ever, unlike the append-only Reasoning/Simulation/Decision history from
# earlier phases).
#
# Run from the repo root:
#   bash scripts/verify-phase-8.sh 2>&1 | tee phase8-verification-output.txt
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pick a genuinely free TCP port from the OS rather than a hardcoded one,
# so this script never collides with an unrelated server someone already
# has running on 8000 (same fix as Phase 6/7 -- do not go back to a fixed
# port).
API_PORT=$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('127.0.0.1', 0))
print(s.getsockname()[1])
s.close()
")
BASE_URL="http://127.0.0.1:$API_PORT"
echo "Starting uvicorn on $BASE_URL (port chosen dynamically to avoid colliding with any server already running on 8000)"

echo "=================================================="
echo "1. Docker Compose: Postgres + Redis startup"
echo "=================================================="
docker compose -f infra/docker-compose.yml up -d

echo "Waiting for Postgres and Redis to report healthy..."
for _ in $(seq 1 30); do
  postgres_status=$(docker compose -f infra/docker-compose.yml ps --format json postgres | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['Health'])" 2>/dev/null || echo "starting")
  redis_status=$(docker compose -f infra/docker-compose.yml ps --format json redis | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['Health'])" 2>/dev/null || echo "starting")
  if [ "$postgres_status" = "healthy" ] && [ "$redis_status" = "healthy" ]; then
    break
  fi
  sleep 1
done
docker compose -f infra/docker-compose.yml ps
if [ "$postgres_status" != "healthy" ] || [ "$redis_status" != "healthy" ]; then
  echo "FAIL: Postgres/Redis did not both report healthy after 30 attempts (postgres=$postgres_status, redis=$redis_status)" >&2
  exit 1
fi

source .venv/bin/activate
pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt --quiet
export DATABASE_URL="postgresql+psycopg://finscope:finscope@localhost:5432/finscope"
export REDIS_URL="redis://localhost:6379/0"
export API_KEY="local-dev-key"

cd apps/api

echo "=================================================="
echo "2. Alembic upgrade (0007 -> 0008)"
echo "=================================================="
alembic upgrade head

echo "=================================================="
echo "3. Alembic downgrade to 0007, then back to head"
echo "=================================================="
alembic downgrade 0007
alembic upgrade head

echo "=================================================="
echo "4. pytest -- targeted Phase 8 suites first"
echo "=================================================="
pytest tests/test_outcome_verification.py tests/test_verifications.py -v

echo "=================================================="
echo "5. pytest -- full suite (Phase 1-8 regression)"
echo "=================================================="
pytest -v

echo "=================================================="
echo "6. ruff"
echo "=================================================="
ruff check .

echo "=================================================="
echo "7. mypy"
echo "=================================================="
mypy app

echo "=================================================="
echo "8. Static purity check: outcome_verification.py has zero DB/LLM/"
echo "   network/FastAPI dependency (import-line grep, not whole-file --"
echo "   its own docstring intentionally describes this absence in prose)"
echo "=================================================="
grep -E '^\s*(import|from)\s' app/domain/outcome_verification.py \
  | grep -niE 'anthropic|openai|httpx|requests|urllib|socket|sqlalchemy|fastapi|app\.models|app\.db|app\.providers|razorpay' \
  && echo "FAIL: app.domain.outcome_verification imports an LLM/network/DB/FastAPI dependency -- it must remain pure" \
  || echo "OK: app.domain.outcome_verification has no LLM/provider/network/DB/FastAPI dependency"

echo "=================================================="
echo "9. Live backend checks against a running server"
echo "=================================================="

uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!

# Wait for OUR process to either start accepting connections or die.
# set -e does NOT catch a backgrounded job failing on its own -- a dead
# uvicorn here would otherwise go unnoticed and every curl call below
# would silently hit nothing (connection refused) or, on a shared port,
# someone else's server. Poll liveness AND health explicitly, and abort
# immediately -- never fall through to the live checks -- if either
# check fails.
SERVER_READY=""
for _ in $(seq 1 30); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "FAIL: uvicorn (pid $API_PID) exited before becoming ready on $BASE_URL -- see the startup output above for the actual error (e.g. a bind failure or an import error)" >&2
    exit 1
  fi
  HEALTH_STATUS=$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL/health" 2>/dev/null || echo "000")
  if [ "$HEALTH_STATUS" = "200" ]; then
    SERVER_READY="yes"
    break
  fi
  sleep 1
done
if [ -z "$SERVER_READY" ]; then
  echo "FAIL: server on $BASE_URL did not report healthy within 30s" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: server on $BASE_URL is up (pid $API_PID, /health = 200)"

request() {
  local tmp
  tmp=$(mktemp)
  HTTP_STATUS=$(curl -sS -o "$tmp" -w '%{http_code}' "$@")
  RESPONSE_BODY=$(cat "$tmp")
  rm -f "$tmp"
}

assert_status() {
  local expected="$1" label="$2"
  if [ "$HTTP_STATUS" != "$expected" ]; then
    echo "FAIL: $label -- expected HTTP $expected, got HTTP $HTTP_STATUS" >&2
    echo "Response body: $RESPONSE_BODY" >&2
    kill "$API_PID" 2>/dev/null || true
    exit 1
  fi
  echo "PASS: $label -- HTTP $HTTP_STATUS"
}

assert_json_field() {
  local field="$1" expected="$2" label="$3"
  local actual
  actual=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
value = d[sys.argv[2]]
print(str(value).lower() if isinstance(value, bool) else value)
" "$RESPONSE_BODY" "$field")
  if [ "$actual" != "$expected" ]; then
    echo "FAIL: $label -- expected $field=$expected, got $field=$actual" >&2
    kill "$API_PID" 2>/dev/null || true
    exit 1
  fi
  echo "PASS: $label -- $field=$actual"
}

require_uuid() {
  local value="$1" label="$2"
  if [ -z "$value" ] || ! [[ "$value" =~ ^[0-9a-fA-F]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    echo "FAIL: $label is not a valid UUID: '$value'" >&2
    kill "$API_PID" 2>/dev/null || true
    exit 1
  fi
}

request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/merchants?limit=1"
if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: server on $BASE_URL did not accept the configured API_KEY (GET /v1/merchants returned HTTP $HTTP_STATUS) -- this does not look like the server this script just started; aborting rather than continuing against an unknown server" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: server on $BASE_URL authenticates with the configured API_KEY -- safe to proceed"

# Sets LAST_* as a side effect rather than returning via stdout/command
# substitution -- command substitution forks a subshell, and a subshell's
# copy of RESPONSE_BODY/HTTP_STATUS (set inside `request`) is discarded
# when the subshell exits, silently breaking every assertion a caller
# might make against "the response from creating this X".
create_merchant() {
  local name="$1"
  request -X POST $BASE_URL/v1/merchants \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"name\":\"$name $(python3 -c 'import uuid; print(uuid.uuid4())')\"}"
  assert_status 201 "merchant creation ($name)"
  LAST_MERCHANT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
}

# Ingests enough payment_failed events inside a short recent window to
# make investigation/simulation/decision/action all reach a real, executed
# outcome -- mirrors the fixture shape test_actions.py's own
# _incident_investigation_with_failed_payments uses.
ingest_failed_events() {
  local merchant_id="$1" count="$2" amount="${3:-10.00}"
  local i
  for i in $(seq 1 "$count"); do
    request -X POST $BASE_URL/v1/events \
      -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
      -d "{\"merchant_id\":\"$merchant_id\",\"event_type\":\"payment_failed\",\"source\":\"verify-phase-8\",\"external_reference\":\"$(python3 -c 'import uuid; print(uuid.uuid4())')\",\"amount\":\"$amount\",\"currency\":\"INR\",\"occurred_at\":\"$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat())')\"}"
    assert_status 201 "ingest payment_failed event $i/$count"
  done
}

run_investigation_now() {
  local merchant_id="$1"
  request -X POST $BASE_URL/v1/investigations \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"merchant_id\":\"$merchant_id\",\"window_minutes\":30}"
  assert_status 201 "investigation creation"
  LAST_INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
}

simulate() {
  local investigation_id="$1" scenario="$2"
  request -X POST "$BASE_URL/v1/investigations/$investigation_id/simulations" \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"scenario\":\"$scenario\"}"
  assert_status 201 "simulation ($scenario)"
  LAST_SIMULATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
}

decide() {
  local investigation_id="$1"
  request -X POST "$BASE_URL/v1/investigations/$investigation_id/decisions" \
    -H "X-API-Key: $API_KEY"
  assert_status 201 "decision evaluation"
  LAST_DECISION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
}

act() {
  local investigation_id="$1" decision_id="$2"
  request -X POST "$BASE_URL/v1/investigations/$investigation_id/decisions/$decision_id/actions" \
    -H "X-API-Key: $API_KEY"
}

verify() {
  local investigation_id="$1" action_id="$2"
  request -X POST "$BASE_URL/v1/investigations/$investigation_id/actions/$action_id/verification" \
    -H "X-API-Key: $API_KEY"
}

echo "--- Build an EXECUTED action: merchant + failed payments + investigation + simulation + decision + action ---"
echo "--- (success_rate=1.0, scope_fraction=1.0 is NOT settable via this API -- the simulation uses"
echo "     app.domain.simulation's own default assumptions, so a real run may land on"
echo "     VERIFIED_SUCCESS, PARTIALLY_VERIFIED, or FAILED depending on those defaults. This script"
echo "     asserts the STATUS IS ONE OF THE FOUR VALID VALUES and that the comparison structure is"
echo "     well-formed, not a specific status -- the exact-match case is already covered"
echo "     deterministically by tests/test_outcome_verification.py and tests/test_verifications.py,"
echo "     which do control the assumptions.)"
create_merchant "phase8-executed"
MERCHANT_EXECUTED="$LAST_MERCHANT_ID"
ingest_failed_events "$MERCHANT_EXECUTED" 5
run_investigation_now "$MERCHANT_EXECUTED"
INVESTIGATION_EXECUTED="$LAST_INVESTIGATION_ID"
simulate "$INVESTIGATION_EXECUTED" "RETRY_AFFECTED_PAYMENTS"
decide "$INVESTIGATION_EXECUTED"
DECISION_EXECUTED="$LAST_DECISION_ID"
POLICY_DECISION_EXECUTED=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['policy_decision'])" "$RESPONSE_BODY")
if [ "$POLICY_DECISION_EXECUTED" != "ALLOWED" ]; then
  echo "FAIL: expected the fixture decision to be policy_decision=ALLOWED, got $POLICY_DECISION_EXECUTED -- adjust the fixture (event count/amount) rather than the assertion" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
act "$INVESTIGATION_EXECUTED" "$DECISION_EXECUTED"
assert_status 201 "sandbox action execution"
assert_json_field status executed "action status (ALLOWED decision)"
ACTION_ID_EXECUTED=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$ACTION_ID_EXECUTED" "executed action id"

echo "--- Snapshot the action row before any verification ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/decisions/$DECISION_EXECUTED/actions"
assert_status 200 "get action for decision before verification"
ACTION_BEFORE="$RESPONSE_BODY"

echo "--- POST .../actions/{action_id}/verification on an executed action (expect 201) ---"
verify "$INVESTIGATION_EXECUTED" "$ACTION_ID_EXECUTED"
echo "$RESPONSE_BODY"
assert_status 201 "first outcome verification"
VERIFICATION_STATUS_FIRST=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['status'])" "$RESPONSE_BODY")
case "$VERIFICATION_STATUS_FIRST" in
  VERIFIED_SUCCESS|PARTIALLY_VERIFIED|FAILED|INSUFFICIENT_OBSERVATION) ;;
  *)
    echo "FAIL: verification status '$VERIFICATION_STATUS_FIRST' is not one of the four contract values" >&2
    kill "$API_PID" 2>/dev/null || true
    exit 1
    ;;
esac
echo "PASS: verification status ($VERIFICATION_STATUS_FIRST) is a contract-valid value"
VERIFICATION_ID_FIRST=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$VERIFICATION_ID_FIRST" "first verification id"
assert_json_field action_id "$ACTION_ID_EXECUTED" "verification action_id anchor"

echo "--- expected_snapshot is PROJECTED-sourced, observed_snapshot is SANDBOX-sourced -- distinct provenance, not a copy ---"
EXPECTED_AVAILABLE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['expected_snapshot'].get('available'))" "$RESPONSE_BODY")
OBSERVED_AVAILABLE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['observed_snapshot'].get('available'))" "$RESPONSE_BODY")
if [ "$EXPECTED_AVAILABLE" != "True" ] || [ "$OBSERVED_AVAILABLE" != "True" ]; then
  echo "FAIL: expected an executed action against a completed simulation to yield available expected/observed snapshots (expected.available=$EXPECTED_AVAILABLE, observed.available=$OBSERVED_AVAILABLE)" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: both expected_snapshot and observed_snapshot are available for an executed action"

echo "--- FinancialEvent-adjacent state (the action row) is unchanged after verification ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/decisions/$DECISION_EXECUTED/actions"
assert_status 200 "get action for decision after verification"
if [ "$RESPONSE_BODY" != "$ACTION_BEFORE" ]; then
  echo "FAIL: the action row changed after running verification -- outcome verification must never mutate the action or its sandbox_result" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: the action row is byte-for-byte unchanged before vs. after verification"

echo "--- Second POST on the same action is an idempotent replay (expect 200, same verification id, same status) ---"
verify "$INVESTIGATION_EXECUTED" "$ACTION_ID_EXECUTED"
assert_status 200 "idempotent replay of outcome verification"
VERIFICATION_ID_REPLAY=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
VERIFICATION_STATUS_REPLAY=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['status'])" "$RESPONSE_BODY")
if [ "$VERIFICATION_ID_REPLAY" != "$VERIFICATION_ID_FIRST" ]; then
  echo "FAIL: idempotent replay returned a different verification id ($VERIFICATION_ID_REPLAY != $VERIFICATION_ID_FIRST) -- at most one verification row may exist per action_id" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
if [ "$VERIFICATION_STATUS_REPLAY" != "$VERIFICATION_STATUS_FIRST" ]; then
  echo "FAIL: idempotent replay returned a different status ($VERIFICATION_STATUS_REPLAY != $VERIFICATION_STATUS_FIRST) -- a replay must never re-compare, only re-read" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: idempotent replay returns the same verification id and status ($VERIFICATION_ID_REPLAY, $VERIFICATION_STATUS_REPLAY)"

echo "--- No duplicate AuditLog row was written on replay ---"
AUDIT_COUNT=$(PGPASSWORD=finscope psql -h localhost -U finscope -d finscope -tA -c \
  "select count(*) from audit_log where entity_type = 'investigation_outcome_verification' and entity_id = '$VERIFICATION_ID_FIRST'")
AUDIT_COUNT="$(echo "$AUDIT_COUNT" | tr -d '[:space:]')"
if [ "$AUDIT_COUNT" != "1" ]; then
  echo "FAIL: expected exactly 1 audit_log row for verification $VERIFICATION_ID_FIRST after 2 POSTs, found $AUDIT_COUNT" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: exactly 1 audit_log row exists for verification $VERIFICATION_ID_FIRST after an idempotent replay"

echo "--- GET .../actions/{action_id}/verification returns the same persisted result ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/actions/$ACTION_ID_EXECUTED/verification"
assert_status 200 "get verification for action"
assert_json_field id "$VERIFICATION_ID_FIRST" "get verification for action returns the same id"

echo "--- Forged request body cannot override the verification result (expect the real, ignored result) ---"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/actions/$ACTION_ID_EXECUTED/verification" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"status":"VERIFIED_SUCCESS","expected_snapshot":{"available":false,"reason":"FORGED"},"observed_snapshot":{"available":false,"reason":"FORGED"}}'
FORGED_REASON_CHECK=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('expected_snapshot',{}).get('reason'))" "$RESPONSE_BODY")
if [ "$FORGED_REASON_CHECK" = "FORGED" ]; then
  echo "FAIL: a forged request body field (expected_snapshot.reason=FORGED) was reflected back -- the endpoint must ignore the request body entirely" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: forged request body fields were ignored -- the real, server-derived (and already-idempotent) result was returned"

echo "--- Rejected action yields INSUFFICIENT_OBSERVATION, not an HTTP error, not a pretended success ---"
create_merchant "phase8-rejected"
MERCHANT_REJECTED="$LAST_MERCHANT_ID"
run_investigation_now "$MERCHANT_REJECTED"
INVESTIGATION_REJECTED="$LAST_INVESTIGATION_ID"
decide "$INVESTIGATION_REJECTED"
DECISION_REJECTED="$LAST_DECISION_ID"
assert_json_field status insufficient_evidence "decision status (no evidence fixture)"
act "$INVESTIGATION_REJECTED" "$DECISION_REJECTED"
assert_status 201 "action against an insufficient_evidence decision (still 201 -- a rejected action is a normal, persisted, auditable outcome)"
assert_json_field status rejected "action status (insufficient_evidence decision)"
ACTION_ID_REJECTED=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
verify "$INVESTIGATION_REJECTED" "$ACTION_ID_REJECTED"
assert_status 201 "verification against a rejected action (still 201 -- never an HTTP error)"
assert_json_field status INSUFFICIENT_OBSERVATION "verification status for a rejected action"
echo "PASS: a rejected action deterministically yields INSUFFICIENT_OBSERVATION, never a pretended successful outcome"

echo "--- Unknown action returns 404 ---"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/actions/00000000-0000-0000-0000-000000000000/verification" \
  -H "X-API-Key: $API_KEY"
assert_status 404 "verification of unknown action"

echo "--- Unknown investigation returns 404 ---"
request -X POST "$BASE_URL/v1/investigations/00000000-0000-0000-0000-000000000000/actions/$ACTION_ID_EXECUTED/verification" \
  -H "X-API-Key: $API_KEY"
assert_status 404 "verification against unknown investigation"

echo "--- Cross-investigation action returns 404 ---"
create_merchant "phase8-cross"
MERCHANT_CROSS="$LAST_MERCHANT_ID"
run_investigation_now "$MERCHANT_CROSS"
INVESTIGATION_CROSS="$LAST_INVESTIGATION_ID"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_CROSS/actions/$ACTION_ID_EXECUTED/verification" \
  -H "X-API-Key: $API_KEY"
assert_status 404 "action from a different investigation"

echo "--- Malformed action_id is safely rejected, not a 500 ---"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/actions/not-a-uuid/verification" \
  -H "X-API-Key: $API_KEY"
if [ "$HTTP_STATUS" = "500" ]; then
  echo "FAIL: a malformed action_id caused an HTTP 500 -- it must be safely rejected (404/422), never crash the server" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: malformed action_id was safely rejected (HTTP $HTTP_STATUS, not 500)"

echo "--- Unauthenticated requests (expect 401) ---"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/actions/$ACTION_ID_EXECUTED/verification"
assert_status 401 "unauthenticated POST verification"
request "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/actions/$ACTION_ID_EXECUTED/verification"
assert_status 401 "unauthenticated GET verification for action"
request "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/verifications"
assert_status 401 "unauthenticated GET verification history"

echo "--- Verification history for the investigation includes the persisted verification ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/investigations/$INVESTIGATION_EXECUTED/verifications"
assert_status 200 "verification history"
HISTORY_CONTAINS_VERIFICATION=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('yes' if any(i['id']==sys.argv[2] for i in d['items']) else 'no')" "$RESPONSE_BODY" "$VERIFICATION_ID_FIRST")
if [ "$HISTORY_CONTAINS_VERIFICATION" != "yes" ]; then
  echo "FAIL: verification history for investigation $INVESTIGATION_EXECUTED does not contain verification $VERIFICATION_ID_FIRST" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: verification history contains the persisted verification"

echo "--- Confirming the server is still the one this script started before tearing it down ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/merchants?limit=1"
assert_status 200 "final liveness check before shutdown"

kill "$API_PID"
wait "$API_PID" 2>/dev/null || true
cd "$REPO_ROOT"

echo "=================================================="
echo "10. Frontend: TypeScript check, lint, build"
echo "=================================================="
cd apps/web
npx tsc --noEmit
npm run lint
npm run build
cd "$REPO_ROOT"

echo "=================================================="
echo "11. Frontend <-> backend end-to-end -- MANUAL BROWSER CHECK REQUIRED"
echo "=================================================="
echo "Everything above this section is AUTOMATED PASS/FAIL. The following is NOT automated by this"
echo "script and has NOT been performed unless a human actually opened a browser and did it:"
echo "In one terminal: source .venv/bin/activate && cd apps/api && uvicorn app.main:app --reload --port 8000"
echo "  (unset any stale API_KEY/DATABASE_URL/REDIS_URL exported in this shell first if reused)"
echo "In another:      cd apps/web && npm run dev"
echo "Then open the frontend URL the Next.js dev server printed, go to /investigations, open an"
echo "incident investigation's detail page, run a simulation, a decision evaluation, and a sandbox"
echo "action until you have an executed action, and confirm:"
echo "  - a new 'Outcome verification' section appears below Sandbox action, labeled VERIFICATION"
echo "  - with no executed action yet, it shows an empty state and no button"
echo "  - with a rejected action, it explains there is nothing to verify and does NOT show a button"
echo "  - with an executed action, clicking 'Verify outcome' sends a bodyless POST and shows the"
echo "    VERIFICATION badge, the status badge (Verified success / Partially verified / Failed /"
echo "    Insufficient observation), an EXPECTED/PROJECTED (purple) panel and an OBSERVED/SANDBOX"
echo "    (teal) panel that are visually distinct, a per-dimension match/mismatch comparison, and"
echo "    the text 'Deterministic comparison only -- no financial data mutated, no external systems"
echo "    contacted.'"
echo "  - re-visiting the page (or re-clicking 'Re-run verification') shows the SAME verification,"
echo "    not a new one"
echo "  - a small append-only verification history is visible below the current result"
echo "  - Phase 1-7 flows (create merchant, ingest event, run investigation, reasoning, simulation,"
echo "    decision evaluation, sandbox action) all still work exactly as before, and those sections"
echo "    are visually unchanged"
echo "THIS SCRIPT DOES NOT CLAIM THE ABOVE WAS PERFORMED. Record separately whether a human actually"
echo "carried out this manual browser check before treating Phase 8 as owner-verified."

echo "=================================================="
echo "12. Security / git hygiene checks"
echo "=================================================="
echo "--- confirm .env is not tracked ---"
git ls-files | grep -E '^\.env$' && echo "FAIL: .env is tracked" || echo "OK: .env not tracked"
echo "--- confirm apps/web/.env.local is not tracked ---"
git ls-files | grep -E '^apps/web/\.env\.local$' && echo "FAIL: .env.local is tracked" || echo "OK: .env.local not tracked"
echo "--- confirm .venv is not tracked ---"
git ls-files | grep -E '^\.venv/' && echo "FAIL: .venv is tracked" || echo "OK: .venv not tracked"
echo "--- confirm node_modules is not tracked ---"
git ls-files | grep -E 'node_modules/' && echo "FAIL: node_modules is tracked" || echo "OK: node_modules not tracked"
echo "--- confirm no vendor/tool attribution strings anywhere in the tracked tree ---"
git grep -niE 'claude|anthropic|copilot|chatgpt|generated with|co-authored-by' -- . \
  ':!.env.example' \
  ':!README.md' \
  ':!apps/api/app/config.py' \
  ':!.gitignore' \
  ':!apps/api/app/providers/**' \
  ':!apps/api/app/routers/investigations.py' \
  ':!scripts/verify-phase-4.sh' \
  ':!scripts/verify-phase-5.sh' \
  ':!scripts/verify-phase-6.sh' \
  ':!scripts/verify-phase-7.sh' \
  ':!scripts/verify-phase-8.sh' \
  ':!apps/api/tests/test_verifications.py' \
  && echo "FAIL: unexpected vendor/tool reference found above" \
  || echo "OK: no unexpected vendor/tool attribution references (legitimate provider implementation/configuration locations, the verification scripts' own test instructions, and test_verifications.py's static import-name dependency-absence check -- which legitimately checks outcome_verification.py's real AST-parsed imports against a vendor-name blocklist, the opposite of attribution -- are excluded from this check on purpose)"
echo "--- confirm the outcome verifier has no LLM/provider/network/DB dependency (import-line only) ---"
grep -E '^\s*(import|from)\s' apps/api/app/domain/outcome_verification.py \
  | grep -niE 'anthropic|openai|httpx|requests|urllib|socket|sqlalchemy|fastapi|app\.models|app\.db|app\.providers|razorpay' \
  && echo "FAIL: app.domain.outcome_verification imports an LLM/network/DB/FastAPI dependency -- it must remain pure" \
  || echo "OK: app.domain.outcome_verification has no LLM/provider/network/DB/FastAPI dependency"
echo "--- confirm no real Razorpay/payment-provider mutation code exists anywhere in Phase 8 files ---"
grep -niE 'razorpay' \
  apps/api/app/domain/outcome_verification.py apps/api/app/domain/verifications.py \
  apps/api/app/models/investigation_outcome_verification.py apps/api/app/schemas/verification.py \
  && echo "FAIL: a Phase 8 file references Razorpay -- Phase 8 must remain sandbox-only with no real payment provider integration" \
  || echo "OK: no Razorpay reference in any Phase 8 file"
echo "--- confirm the verification-creation endpoint accepts no client-controlled expected/observed/status field ---"
grep -n "def create_verification" apps/api/app/routers/investigations.py -A 8 | grep -qE "payload|body: |VerificationCreate" \
  && { echo "FAIL: create_verification appears to accept a request body -- Phase 8 requires expected/observed/status to be derived entirely server-side, with no client-controlled input" >&2; exit 1; } \
  || echo "OK: create_verification takes no request body (investigation_id + action_id path params, response + db dependency only)"

echo "=================================================="
echo "13. Docker Compose teardown"
echo "=================================================="
docker compose -f infra/docker-compose.yml down

echo "=================================================="
echo "DONE. Sections 1-9 and 12 above are AUTOMATED PASS/FAIL. Section 10 is AUTOMATED (tsc/eslint/"
echo "build). Section 11 is MANUAL BROWSER CHECK REQUIRED and was only described, not performed, by"
echo "this script. Review all sections above before reporting Phase 8 as owner-verified."
echo "=================================================="
