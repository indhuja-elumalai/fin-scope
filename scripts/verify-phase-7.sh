#!/usr/bin/env bash
#
# Phase 7 verification: Bounded Sandbox Action.
#
# Verifies that a sandbox action can ONLY be executed against an
# investigation when a persisted, completed, ALLOWED Phase 6 decision
# authorizes it -- authorization is re-derived entirely server-side from
# investigation_id + decision_id in the URL, never from anything the
# client sends. The sandbox executor is pure and deterministic: it never
# contacts a real payment provider, never mutates FinancialEvent rows, and
# never recomputes financial numbers independently of the decision's own
# persisted preferred simulation. An action is idempotent per decision_id
# (at most one row ever, unlike the append-only Reasoning/Simulation/
# Decision history from earlier phases).
#
# Run from the repo root:
#   bash scripts/verify-phase-7.sh 2>&1 | tee phase7-verification-output.txt
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pick a genuinely free TCP port from the OS rather than a hardcoded one,
# so this script never collides with an unrelated server someone already
# has running on 8000 (this is the fix for the Phase 6 port-collision bug
# -- do not go back to a fixed port).
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
echo "2. Alembic upgrade (0006 -> 0007)"
echo "=================================================="
alembic upgrade head

echo "=================================================="
echo "3. Alembic downgrade to 0006, then back to head"
echo "=================================================="
alembic downgrade 0006
alembic upgrade head

echo "=================================================="
echo "4. pytest -- targeted Phase 7 suites first"
echo "=================================================="
pytest tests/test_sandbox_executor.py tests/test_actions.py -v

echo "=================================================="
echo "5. pytest -- full suite (Phase 1 + 2 + 3 + 4 + 5 + 6 + 7 regression)"
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
echo "8. Live backend checks against a running server"
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

# Sets LAST_MERCHANT_ID as a side effect rather than returning the id via
# stdout/command-substitution -- command substitution forks a subshell, and
# a subshell's copy of RESPONSE_BODY/HTTP_STATUS (set inside `request`) is
# discarded when the subshell exits, silently breaking every assertion a
# caller might make against "the response from creating this merchant".
create_merchant() {
  local name="$1"
  request -X POST $BASE_URL/v1/merchants \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"name\":\"$name $(python3 -c 'import uuid; print(uuid.uuid4())')\"}"
  assert_status 201 "merchant creation ($name)"
  LAST_MERCHANT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
}

# Ingests enough payment_failed events (and a smaller number of successes)
# inside a short recent window to make investigation/simulation/decision
# all reach a real ALLOWED outcome -- mirrors the fixture shape
# test_actions.py's own _incident_investigation_with_failed_payments uses.
ingest_failed_events() {
  local merchant_id="$1" count="$2" amount="${3:-10.00}"
  local i
  for i in $(seq 1 "$count"); do
    request -X POST $BASE_URL/v1/events \
      -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
      -d "{\"merchant_id\":\"$merchant_id\",\"event_type\":\"payment_failed\",\"source\":\"verify-phase-7\",\"external_reference\":\"$(python3 -c 'import uuid; print(uuid.uuid4())')\",\"amount\":\"$amount\",\"currency\":\"INR\",\"occurred_at\":\"$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat())')\"}"
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

echo "--- Build an ALLOWED decision: merchant + failed payments + investigation + simulation + decision ---"
create_merchant "phase7-allowed"
MERCHANT_ALLOWED="$LAST_MERCHANT_ID"
ingest_failed_events "$MERCHANT_ALLOWED" 5
run_investigation_now "$MERCHANT_ALLOWED"
INVESTIGATION_ALLOWED="$LAST_INVESTIGATION_ID"
simulate "$INVESTIGATION_ALLOWED" "RETRY_AFFECTED_PAYMENTS"
decide "$INVESTIGATION_ALLOWED"
DECISION_ALLOWED="$LAST_DECISION_ID"
echo "$RESPONSE_BODY"
assert_json_field status completed "decision status (ALLOWED fixture)"
POLICY_DECISION_ALLOWED=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['policy_decision'])" "$RESPONSE_BODY")
if [ "$POLICY_DECISION_ALLOWED" != "ALLOWED" ]; then
  echo "FAIL: expected the fixture decision to be policy_decision=ALLOWED, got $POLICY_DECISION_ALLOWED -- adjust the fixture (event count/amount) rather than the assertion" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: fixture decision is policy_decision=ALLOWED"

echo "--- Snapshot FinancialEvent state before any sandbox action ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/events?merchant_id=$MERCHANT_ALLOWED&limit=100"
assert_status 200 "list events before sandbox action"
EVENTS_BEFORE="$RESPONSE_BODY"

echo "--- POST .../decisions/.../actions on an ALLOWED decision (expect 201, executed) ---"
act "$INVESTIGATION_ALLOWED" "$DECISION_ALLOWED"
echo "$RESPONSE_BODY"
assert_status 201 "first sandbox action execution"
assert_json_field status executed "action status (ALLOWED decision)"
assert_json_field policy_decision_snapshot ALLOWED "action policy_decision_snapshot"
ACTION_ID_FIRST=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$ACTION_ID_FIRST" "first action id"
ACTION_KIND_FIRST=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['sandbox_result']['action_kind'])" "$RESPONSE_BODY")
if [ "$ACTION_KIND_FIRST" != "SIMULATED_RETRY_PAYMENTS" ]; then
  echo "FAIL: expected action_kind=SIMULATED_RETRY_PAYMENTS for a RETRY_AFFECTED_PAYMENTS scenario, got $ACTION_KIND_FIRST" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: action_kind=SIMULATED_RETRY_PAYMENTS for the RETRY_AFFECTED_PAYMENTS scenario"

echo "--- FinancialEvent rows are unchanged after the sandbox action ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/events?merchant_id=$MERCHANT_ALLOWED&limit=100"
assert_status 200 "list events after sandbox action"
if [ "$RESPONSE_BODY" != "$EVENTS_BEFORE" ]; then
  echo "FAIL: /v1/events response changed after a sandbox action -- the sandbox executor must never mutate financial event state" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: FinancialEvent rows are byte-for-byte unchanged before vs. after the sandbox action"

echo "--- Second POST on the same decision is an idempotent replay (expect 200, same action id) ---"
act "$INVESTIGATION_ALLOWED" "$DECISION_ALLOWED"
assert_status 200 "idempotent replay of sandbox action"
ACTION_ID_REPLAY=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
if [ "$ACTION_ID_REPLAY" != "$ACTION_ID_FIRST" ]; then
  echo "FAIL: idempotent replay returned a different action id ($ACTION_ID_REPLAY != $ACTION_ID_FIRST) -- at most one action row may exist per decision_id" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: idempotent replay returns the same action id ($ACTION_ID_REPLAY)"

echo "--- No duplicate AuditLog row was written on replay ---"
AUDIT_COUNT=$(PGPASSWORD=finscope psql -h localhost -U finscope -d finscope -tA -c \
  "select count(*) from audit_log where entity_type = 'investigation_action' and entity_id = '$ACTION_ID_FIRST'")
AUDIT_COUNT="$(echo "$AUDIT_COUNT" | tr -d '[:space:]')"
if [ "$AUDIT_COUNT" != "1" ]; then
  echo "FAIL: expected exactly 1 audit_log row for action $ACTION_ID_FIRST after 2 POSTs, found $AUDIT_COUNT" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: exactly 1 audit_log row exists for action $ACTION_ID_FIRST after an idempotent replay"

echo "--- Forged request body cannot override authorization (expect the real, ignored result) ---"
create_merchant "phase7-forged"
MERCHANT_FORGED="$LAST_MERCHANT_ID"
ingest_failed_events "$MERCHANT_FORGED" 5
run_investigation_now "$MERCHANT_FORGED"
INVESTIGATION_FORGED="$LAST_INVESTIGATION_ID"
simulate "$INVESTIGATION_FORGED" "RETRY_AFFECTED_PAYMENTS"
decide "$INVESTIGATION_FORGED"
DECISION_FORGED="$LAST_DECISION_ID"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_FORGED/decisions/$DECISION_FORGED/actions" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"status":"executed","policy_decision":"ALLOWED","action_kind":"SIMULATED_REROUTE","sandbox_result":{"action_kind":"FORGED"}}'
echo "$RESPONSE_BODY"
ACTUAL_ACTION_KIND=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['sandbox_result'].get('action_kind'))" "$RESPONSE_BODY")
if [ "$ACTUAL_ACTION_KIND" = "FORGED" ]; then
  echo "FAIL: a forged request body field (sandbox_result.action_kind=FORGED) was reflected back -- the endpoint must ignore the request body entirely" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: forged request body fields were ignored -- the real, server-derived result was returned"

echo "--- Unknown investigation returns 404 ---"
request -X POST "$BASE_URL/v1/investigations/00000000-0000-0000-0000-000000000000/decisions/$DECISION_ALLOWED/actions" \
  -H "X-API-Key: $API_KEY"
assert_status 404 "action on unknown investigation"

echo "--- Cross-investigation decision returns 404 ---"
create_merchant "phase7-cross"
MERCHANT_CROSS="$LAST_MERCHANT_ID"
run_investigation_now "$MERCHANT_CROSS"
INVESTIGATION_CROSS="$LAST_INVESTIGATION_ID"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_CROSS/decisions/$DECISION_ALLOWED/actions" \
  -H "X-API-Key: $API_KEY"
assert_status 404 "decision from a different investigation"

echo "--- Unauthenticated requests (expect 401) ---"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_ALLOWED/decisions/$DECISION_ALLOWED/actions"
assert_status 401 "unauthenticated POST action"
request "$BASE_URL/v1/investigations/$INVESTIGATION_ALLOWED/decisions/$DECISION_ALLOWED/actions"
assert_status 401 "unauthenticated GET action-for-decision"
request "$BASE_URL/v1/investigations/$INVESTIGATION_ALLOWED/actions"
assert_status 401 "unauthenticated GET action history"

echo "--- DO_NOTHING + ALLOWED decision executes as an authorized NO_OP ---"
create_merchant "phase7-donothing"
MERCHANT_NOOP="$LAST_MERCHANT_ID"
ingest_failed_events "$MERCHANT_NOOP" 5
run_investigation_now "$MERCHANT_NOOP"
INVESTIGATION_NOOP="$LAST_INVESTIGATION_ID"
simulate "$INVESTIGATION_NOOP" "DO_NOTHING"
decide "$INVESTIGATION_NOOP"
DECISION_NOOP="$LAST_DECISION_ID"
POLICY_DECISION_NOOP=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['policy_decision'])" "$RESPONSE_BODY")
if [ "$POLICY_DECISION_NOOP" = "ALLOWED" ]; then
  act "$INVESTIGATION_NOOP" "$DECISION_NOOP"
  assert_status 201 "DO_NOTHING sandbox action"
  assert_json_field status executed "DO_NOTHING action status"
  NOOP_ACTION_KIND=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['sandbox_result']['action_kind'])" "$RESPONSE_BODY")
  if [ "$NOOP_ACTION_KIND" != "NO_OP" ]; then
    echo "FAIL: expected action_kind=NO_OP for a DO_NOTHING scenario, got $NOOP_ACTION_KIND" >&2
    kill "$API_PID" 2>/dev/null || true
    exit 1
  fi
  echo "PASS: DO_NOTHING scenario executes as action_kind=NO_OP"
else
  echo "SKIP: this run's DO_NOTHING candidate was not the preferred/ALLOWED scenario ($POLICY_DECISION_NOOP) -- the deterministic mapping itself is already covered by tests/test_sandbox_executor.py and tests/test_actions.py::test_do_nothing_allowed_decision_executes_as_no_op"
fi

echo "--- insufficient_evidence decision is rejected, not a 500 ---"
create_merchant "phase7-insufficient"
MERCHANT_INSUFFICIENT="$LAST_MERCHANT_ID"
run_investigation_now "$MERCHANT_INSUFFICIENT"
INVESTIGATION_INSUFFICIENT="$LAST_INVESTIGATION_ID"
decide "$INVESTIGATION_INSUFFICIENT"
DECISION_INSUFFICIENT="$LAST_DECISION_ID"
assert_json_field status insufficient_evidence "decision status (no evidence fixture)"
act "$INVESTIGATION_INSUFFICIENT" "$DECISION_INSUFFICIENT"
assert_status 201 "action against an insufficient_evidence decision (still 201 -- a rejected action is a normal, persisted, auditable outcome, never an HTTP error)"
assert_json_field status rejected "action status (insufficient_evidence decision)"

echo "--- Action history for the ALLOWED investigation includes the executed action ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/investigations/$INVESTIGATION_ALLOWED/actions"
assert_status 200 "action history"
HISTORY_CONTAINS_ACTION=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('yes' if any(i['id']==sys.argv[2] for i in d['items']) else 'no')" "$RESPONSE_BODY" "$ACTION_ID_FIRST")
if [ "$HISTORY_CONTAINS_ACTION" != "yes" ]; then
  echo "FAIL: action history for investigation $INVESTIGATION_ALLOWED does not contain action $ACTION_ID_FIRST" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: action history contains the executed action"

echo "--- Confirming the server is still the one this script started before tearing it down ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/merchants?limit=1"
assert_status 200 "final liveness check before shutdown"

kill "$API_PID"
wait "$API_PID" 2>/dev/null || true
cd "$REPO_ROOT"

echo "=================================================="
echo "9. Frontend: TypeScript check, lint, build"
echo "=================================================="
cd apps/web
npx tsc --noEmit
npm run lint
npm run build
cd "$REPO_ROOT"

echo "=================================================="
echo "10. Frontend <-> backend end-to-end (manual step)"
echo "=================================================="
echo "In one terminal: source .venv/bin/activate && cd apps/api && uvicorn app.main:app --reload --port 8000"
echo "  (unset any stale API_KEY/DATABASE_URL/REDIS_URL exported in this shell first if reused)"
echo "In another:      cd apps/web && npm run dev"
echo "Then open the frontend URL the Next.js dev server printed, go to /investigations, open an"
echo "incident investigation's detail page, run a simulation and then a decision evaluation until"
echo "you have an ALLOWED decision, and confirm:"
echo "  - a new 'Sandbox action' section appears below Decision evaluation, labeled SANDBOX"
echo "  - with no decision yet, it shows an empty state and no button"
echo "  - with a decision that is REQUIRES_HUMAN_APPROVAL or BLOCKED, it shows the policy outcome"
echo "    and reasons, and does NOT show an 'Execute in sandbox' button"
echo "  - with an ALLOWED decision, clicking 'Execute in sandbox' sends a bodyless POST and shows"
echo "    the SANDBOX badge, action status, action kind, targeted-event count, simulated outcome,"
echo "    and the text 'Sandbox-only -- no real payment provider contacted.'"
echo "  - re-visiting the page (or re-clicking) shows the SAME action, not a new one"
echo "  - a small append-only sandbox action history is visible below the current result"
echo "  - Phase 1-6 flows (create merchant, ingest event, run investigation, reasoning, simulation,"
echo "    decision evaluation) all still work exactly as before, and those sections are visually"
echo "    unchanged"

echo "=================================================="
echo "11. Security / git hygiene checks"
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
  && echo "FAIL: unexpected vendor/tool reference found above" \
  || echo "OK: no unexpected vendor/tool attribution references (legitimate provider implementation/configuration locations, and the verification scripts' own test instructions, are excluded from this check on purpose)"
echo "--- confirm the sandbox executor and action orchestration have no LLM/provider/network/DB dependency ---"
# Restricted to actual import statements, not the whole file: both modules'
# own docstrings intentionally *describe* the absence of these dependencies
# in prose (e.g. "no SQLAlchemy import, no httpx/requests import"), which
# would otherwise trip a whole-file keyword grep on its own documentation.
# Checking imports is also the more correct signal for "has a dependency".
grep -E '^\s*(import|from)\s' apps/api/app/domain/sandbox_executor.py \
  | grep -niE 'anthropic|openai|httpx|requests|urllib|socket|sqlalchemy|app\.models|app\.db|app\.providers|razorpay' \
  && echo "FAIL: app.domain.sandbox_executor imports an LLM/network/DB/provider dependency -- it must remain pure" \
  || echo "OK: app.domain.sandbox_executor has no LLM/provider/network/DB dependency"
# actions.py legitimately imports sqlalchemy (it is the DB orchestration
# layer, not the pure executor) -- that is expected and excluded here.
grep -E '^\s*(import|from)\s' apps/api/app/domain/actions.py \
  | grep -niE 'anthropic|openai|httpx|requests|urllib|razorpay|app\.providers' \
  && echo "FAIL: app.domain.actions imports an LLM/network/payment-provider dependency" \
  || echo "OK: app.domain.actions has no LLM/network/payment-provider dependency"
echo "--- confirm no real Razorpay/payment-provider mutation code exists anywhere in Phase 7 files ---"
grep -niE 'razorpay' \
  apps/api/app/domain/sandbox_executor.py apps/api/app/domain/actions.py apps/api/app/models/investigation_action.py apps/api/app/schemas/action.py \
  && echo "FAIL: a Phase 7 file references Razorpay -- Phase 7 must remain sandbox-only with no real payment provider integration" \
  || echo "OK: no Razorpay reference in any Phase 7 file"
echo "--- confirm the action-creation endpoint accepts no client-controlled authorization/outcome field ---"
grep -n "def create_action" apps/api/app/routers/investigations.py -A 8 | grep -qE "payload|body: |ActionCreate" \
  && { echo "FAIL: create_action appears to accept a request body -- Phase 7 requires authorization and outcome to be derived entirely server-side, with no client-controlled input" >&2; exit 1; } \
  || echo "OK: create_action takes no request body (investigation_id + decision_id path params, response + db dependency only)"

echo "=================================================="
echo "12. Docker Compose teardown"
echo "=================================================="
docker compose -f infra/docker-compose.yml down

echo "=================================================="
echo "DONE. Review all sections above for PASS/FAIL before reporting back."
echo "=================================================="
