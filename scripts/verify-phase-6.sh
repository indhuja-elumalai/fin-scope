#!/usr/bin/env bash
# Phase 6 verification script (Deterministic Decision Evaluation + Policy:
# INVESTIGATION -> REASONING -> CONSEQUENCE SIMULATIONS -> DECISION
# EVALUATION -> POLICY -> ALLOWED / REQUIRES_HUMAN_APPROVAL / BLOCKED) + the
# Phase 1-5 regression suite.
#
# Run from the repository root on decision-evaluation-policy, with the
# Phase 1 .venv and apps/web/node_modules already in place:
#
#   bash scripts/verify-phase-6.sh 2>&1 | tee phase6-verification-output.txt
#
# app.domain.decision_evaluation and app.domain.policy are pure
# deterministic Python -- no LLM call, no network dependency, no random
# behavior. This script deliberately does NOT set ANTHROPIC_API_KEY (same
# as verify-phase-4.sh and verify-phase-5.sh); Phase 6 does not read it at
# all, and section 8 proves a decision can be evaluated and produce a
# "completed" result with no reasoning provider configured -- a decision
# never depends on Phase 4 reasoning or on any particular Phase 5 scenario
# assumption having been used.
#
# Phase 6 never executes a financial action and never lets a client
# control the computed policy_decision -- section 8 proves both: the
# decision-creation endpoint takes no request body at all (an attempted
# "policy_decision" field in a POST body is simply never read), and no
# step in this script performs a refund, retry, or any mutation of
# financial_events.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

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
echo "2. Alembic upgrade (0005 -> 0006)"
echo "=================================================="
alembic upgrade head

echo "=================================================="
echo "3. Alembic downgrade to 0005, then back to head"
echo "=================================================="
alembic downgrade 0005
alembic upgrade head

echo "=================================================="
echo "4. pytest -- targeted Phase 6 suites first"
echo "=================================================="
pytest tests/test_decision_evaluation.py tests/test_policy.py tests/test_decisions.py -v

echo "=================================================="
echo "5. pytest -- full suite (Phase 1 + 2 + 3 + 4 + 5 + 6 regression)"
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
# Pick a genuinely free TCP port from the OS rather than a hardcoded one,
# so this script never collides with an unrelated server someone already
# has running on 8000 (exactly what caused the previous run to silently
# test the wrong server under the wrong API key).
API_PORT=$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('127.0.0.1', 0))
print(s.getsockname()[1])
s.close()
")
BASE_URL="http://127.0.0.1:$API_PORT"
echo "Starting uvicorn on $BASE_URL (port chosen dynamically to avoid colliding with any server already running on 8000)"

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

assert_policy_reason_contains() {
  local substring="$1" label="$2"
  local found
  found=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
print('yes' if any(sys.argv[2] in r for r in d.get('policy_reasons', [])) else 'no')
" "$RESPONSE_BODY" "$substring")
  if [ "$found" != "yes" ]; then
    echo "FAIL: $label -- expected a policy_reasons entry containing '$substring'" >&2
    echo "policy_reasons: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['policy_reasons'])" "$RESPONSE_BODY")" >&2
    kill "$API_PID" 2>/dev/null || true
    exit 1
  fi
  echo "PASS: $label"
}

require_uuid() {
  local value="$1" label="$2"
  if [ -z "$value" ] || ! [[ "$value" =~ ^[0-9a-fA-F]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    echo "FAIL: $label is not a valid UUID: '$value'" >&2
    kill "$API_PID" 2>/dev/null || true
    exit 1
  fi
}

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

# Ingests $2 payment_failed events at $3 (amount) $4 (currency), 5/10/15
# minutes ago, for merchant $1. Pass amount="" to ingest an unknown amount.
ingest_payment_failed_events() {
  local merchant_id="$1" count="$2" amount="$3" currency="$4"
  local run_id offsets amount_json currency_json
  run_id=$(python3 -c "import uuid; print(uuid.uuid4())")
  read -r -a offsets <<< "$(python3 -c "print(' '.join(str(5*(i+1)) for i in range($count)))")"
  if [ -z "$amount" ]; then amount_json="null"; currency_json="null"; else amount_json="\"$amount\""; currency_json="\"$currency\""; fi
  local i=1
  for minutes_ago in "${offsets[@]}"; do
    local occurred_at
    occurred_at=$(python3 -c "from datetime import datetime, UTC, timedelta; print((datetime.now(UTC)-timedelta(minutes=$minutes_ago)).isoformat())")
    request -X POST $BASE_URL/v1/events \
      -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
      -d "{\"merchant_id\":\"$merchant_id\",\"event_type\":\"payment_failed\",\"source\":\"manual\",\"external_reference\":\"verify-dec-evt-$i-$run_id\",\"amount\":$amount_json,\"currency\":$currency_json,\"occurred_at\":\"$occurred_at\"}"
    assert_status 201 "payment_failed event $i creation ($merchant_id)"
    i=$((i + 1))
  done
}

# Sets LAST_INVESTIGATION_ID as a side effect -- see create_merchant's
# comment above for why this cannot be a "return via stdout" function.
run_investigation_now() {
  local merchant_id="$1"
  local now_ts
  now_ts=$(python3 -c "from datetime import datetime, UTC; print(datetime.now(UTC).isoformat())")
  request -X POST $BASE_URL/v1/investigations \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
    -d "{\"merchant_id\":\"$merchant_id\",\"as_of\":\"$now_ts\"}"
  assert_status 201 "investigation creation ($merchant_id)"
  LAST_INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
}

simulate() {
  local investigation_id="$1" scenario="$2" assumptions_json="${3:-}"
  local payload
  if [ -n "$assumptions_json" ]; then
    payload="{\"scenario\":\"$scenario\",\"assumptions\":$assumptions_json}"
  else
    payload="{\"scenario\":\"$scenario\"}"
  fi
  request -X POST "$BASE_URL/v1/investigations/$investigation_id/simulations" \
    -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d "$payload"
  assert_status 201 "$scenario simulation ($investigation_id)"
}

decide() {
  local investigation_id="$1" body="${2:-}"
  if [ -n "$body" ]; then
    request -X POST "$BASE_URL/v1/investigations/$investigation_id/decisions" \
      -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d "$body"
  else
    request -X POST "$BASE_URL/v1/investigations/$investigation_id/decisions" \
      -H "X-API-Key: $API_KEY"
  fi
}

# Belt-and-suspenders beyond the health check above: confirm the server on
# $BASE_URL actually authenticates with the API_KEY this script exported,
# not just that something is listening and healthy. This is what would
# catch the pathological case the dynamic-port pick already makes
# extremely unlikely -- a different FIN-SCOPE instance, configured with a
# different key, happening to be freshly bound to the exact port the OS
# just handed us.
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/merchants?limit=1"
if [ "$HTTP_STATUS" != "200" ]; then
  echo "FAIL: server on $BASE_URL did not accept the configured API_KEY (GET /v1/merchants returned HTTP $HTTP_STATUS) -- this does not look like the server this script just started; aborting rather than continuing against an unknown server" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: server on $BASE_URL authenticates with the configured API_KEY -- safe to proceed"

echo "--- Scenario A: incident, small exposure, full recovery -> completed / ALLOWED ---"
create_merchant "Phase 6 Small Exposure Merchant"
MERCHANT_A="$LAST_MERCHANT_ID"
require_uuid "$MERCHANT_A" "merchant A id"
ingest_payment_failed_events "$MERCHANT_A" 3 "100.00" "INR"
run_investigation_now "$MERCHANT_A"
INVESTIGATION_A="$LAST_INVESTIGATION_ID"
require_uuid "$INVESTIGATION_A" "investigation A id"

echo "--- POST .../decisions before any simulation exists (expect 201, no_eligible_scenario) ---"
decide "$INVESTIGATION_A"
echo "$RESPONSE_BODY"
assert_status 201 "decision with no simulations yet"
assert_json_field status no_eligible_scenario "decision status before any simulation"
assert_json_field policy_decision None "policy_decision before any simulation"

simulate "$INVESTIGATION_A" "DO_NOTHING"
simulate "$INVESTIGATION_A" "RETRY_AFFECTED_PAYMENTS" '{"success_rate":"1.0","scope_fraction":"1.0"}'

echo "--- POST .../decisions with DO_NOTHING + RETRY_AFFECTED_PAYMENTS candidates ---"
decide "$INVESTIGATION_A"
echo "$RESPONSE_BODY"
assert_status 201 "decision with two candidates"
assert_json_field status completed "decision A status"
assert_json_field policy_decision ALLOWED "decision A policy_decision (fully recovered, exposure=0, within threshold)"
PREFERRED_A=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['evaluation_result']['preferred_scenario'])" "$RESPONSE_BODY")
if [ "$PREFERRED_A" != "RETRY_AFFECTED_PAYMENTS" ]; then
  echo "FAIL: expected preferred_scenario=RETRY_AFFECTED_PAYMENTS (strictly better failed-event delta), got $PREFERRED_A" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: preferred_scenario=RETRY_AFFECTED_PAYMENTS"
CANDIDATE_COUNT=$(python3 -c "import json,sys; print(len(json.loads(sys.argv[1])['evaluation_result']['candidates']))" "$RESPONSE_BODY")
if [ "$CANDIDATE_COUNT" != "2" ]; then
  echo "FAIL: expected 2 evaluated candidates (DO_NOTHING, RETRY_AFFECTED_PAYMENTS), got $CANDIDATE_COUNT" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: 2 candidates evaluated"
DECISION_A_FIRST_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
DECISION_A_FIRST_EVAL=$(python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1])['evaluation_result'], sort_keys=True))" "$RESPONSE_BODY")

echo "--- Re-running the decision over the same simulations is append-only and reproducible ---"
decide "$INVESTIGATION_A"
DECISION_A_SECOND_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
DECISION_A_SECOND_EVAL=$(python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1])['evaluation_result'], sort_keys=True))" "$RESPONSE_BODY")
if [ "$DECISION_A_SECOND_ID" == "$DECISION_A_FIRST_ID" ]; then
  echo "FAIL: re-running a decision returned the same id -- expected a new append-only row" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
if [ "$DECISION_A_SECOND_EVAL" != "$DECISION_A_FIRST_EVAL" ]; then
  echo "FAIL: re-running the decision over unchanged candidates produced a different evaluation_result -- not deterministic" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: re-run persisted as a new row ($DECISION_A_FIRST_ID -> $DECISION_A_SECOND_ID), identical evaluation_result -- deterministic"

echo "--- GET .../decisions (expect 200, list includes both decision runs) ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/investigations/$INVESTIGATION_A/decisions"
assert_status 200 "decision list"
COUNT=$(python3 -c "import json,sys; print(len(json.loads(sys.argv[1])['items']))" "$RESPONSE_BODY")
if [ "$COUNT" -lt 3 ]; then
  echo "FAIL: expected at least 3 persisted decision rows for investigation A, got $COUNT" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: decision history contains $COUNT append-only rows"

echo "--- GET .../decisions/{id} (expect 200, matches the first decision above) ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/investigations/$INVESTIGATION_A/decisions/$DECISION_A_FIRST_ID"
assert_status 200 "decision detail fetch"
assert_json_field id "$DECISION_A_FIRST_ID" "decision detail matches the run above"

echo "--- POST .../decisions with a client-supplied policy_decision in the body -- must be ignored ---"
decide "$INVESTIGATION_A" '{"policy_decision":"BLOCKED","evaluation_result":{"preferred_scenario":"DO_NOTHING"}}'
assert_status 201 "decision with an attempted client-controlled body"
assert_json_field policy_decision ALLOWED "policy_decision is computed server-side, not taken from the request body"
PREFERRED_BYPASS_ATTEMPT=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['evaluation_result']['preferred_scenario'])" "$RESPONSE_BODY")
if [ "$PREFERRED_BYPASS_ATTEMPT" != "RETRY_AFFECTED_PAYMENTS" ]; then
  echo "FAIL: a client-supplied evaluation_result in the request body appears to have influenced the response" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: client-supplied policy_decision/evaluation_result in the request body had no effect"

echo "--- Scenario B: incident, large exposure, partial recovery -> completed / REQUIRES_HUMAN_APPROVAL ---"
create_merchant "Phase 6 Large Exposure Merchant"
MERCHANT_B="$LAST_MERCHANT_ID"
ingest_payment_failed_events "$MERCHANT_B" 3 "5000.00" "INR"
run_investigation_now "$MERCHANT_B"
INVESTIGATION_B="$LAST_INVESTIGATION_ID"
simulate "$INVESTIGATION_B" "DO_NOTHING"
simulate "$INVESTIGATION_B" "RETRY_AFFECTED_PAYMENTS" '{"success_rate":"0.5","scope_fraction":"1.0"}'
decide "$INVESTIGATION_B"
echo "$RESPONSE_BODY"
assert_status 201 "decision B (large exposure)"
assert_json_field status completed "decision B status"
assert_json_field policy_decision REQUIRES_HUMAN_APPROVAL "decision B policy_decision (7500.00 INR remaining exposure > configured threshold)"
assert_policy_reason_contains "exceeds the autonomous threshold" "decision B reason cites the exposure threshold"
PREFERRED_B=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['evaluation_result']['preferred_scenario'])" "$RESPONSE_BODY")
if [ "$PREFERRED_B" != "RETRY_AFFECTED_PAYMENTS" ]; then
  echo "FAIL: expected preferred_scenario=RETRY_AFFECTED_PAYMENTS even though it requires approval -- policy must never re-rank or substitute a runner-up, got $PREFERRED_B" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: preferred_scenario stays RETRY_AFFECTED_PAYMENTS -- REQUIRES_HUMAN_APPROVAL did not promote DO_NOTHING"

echo "--- Scenario C: incident, unconfigured currency -> completed / REQUIRES_HUMAN_APPROVAL ---"
create_merchant "Phase 6 Unconfigured Currency Merchant"
MERCHANT_C="$LAST_MERCHANT_ID"
ingest_payment_failed_events "$MERCHANT_C" 3 "10.00" "EUR"
run_investigation_now "$MERCHANT_C"
INVESTIGATION_C="$LAST_INVESTIGATION_ID"
simulate "$INVESTIGATION_C" "RETRY_AFFECTED_PAYMENTS" '{"success_rate":"1.0","scope_fraction":"1.0"}'
decide "$INVESTIGATION_C"
echo "$RESPONSE_BODY"
assert_status 201 "decision C (unconfigured currency)"
assert_json_field policy_decision REQUIRES_HUMAN_APPROVAL "decision C policy_decision (EUR has no configured autonomous threshold)"
assert_policy_reason_contains "no autonomous exposure threshold is configured for EUR" "decision C reason cites the unconfigured currency"

echo "--- Scenario D: incident, one event with an unknown amount -> completed / REQUIRES_HUMAN_APPROVAL ---"
create_merchant "Phase 6 Unknown Amount Merchant"
MERCHANT_D="$LAST_MERCHANT_ID"
ingest_payment_failed_events "$MERCHANT_D" 1 "" ""
ingest_payment_failed_events "$MERCHANT_D" 2 "10.00" "INR"
run_investigation_now "$MERCHANT_D"
INVESTIGATION_D="$LAST_INVESTIGATION_ID"
simulate "$INVESTIGATION_D" "RETRY_AFFECTED_PAYMENTS"
decide "$INVESTIGATION_D"
echo "$RESPONSE_BODY"
assert_status 201 "decision D (unknown amount)"
assert_json_field policy_decision REQUIRES_HUMAN_APPROVAL "decision D policy_decision (an eligible event has an unknown amount)"
assert_policy_reason_contains "unknown amount" "decision D reason cites the unknown amount"

echo "--- Scenario E: no incident -> completed pipeline short-circuits to insufficient_evidence ---"
create_merchant "Phase 6 No Incident Merchant"
MERCHANT_E="$LAST_MERCHANT_ID"
run_investigation_now "$MERCHANT_E"
INVESTIGATION_E="$LAST_INVESTIGATION_ID"
assert_json_field incident_detected false "investigation E has no incident"
decide "$INVESTIGATION_E"
echo "$RESPONSE_BODY"
assert_status 201 "decision E (no incident)"
assert_json_field status insufficient_evidence "decision E status"
assert_json_field policy_decision None "decision E policy_decision"

echo "--- Cross-investigation isolation: investigation E cannot read investigation A's decision (expect 404) ---"
request -H "X-API-Key: $API_KEY" "$BASE_URL/v1/investigations/$INVESTIGATION_E/decisions/$DECISION_A_FIRST_ID"
assert_status 404 "a decision belonging to a different investigation is not found"

echo "--- POST .../{random-uuid}/decisions (expect 404) ---"
decide "00000000-0000-0000-0000-000000000000"
assert_status 404 "decision on unknown investigation"

echo "--- Unauthenticated requests (expect 401) ---"
request -X POST "$BASE_URL/v1/investigations/$INVESTIGATION_A/decisions"
assert_status 401 "unauthenticated POST decisions"
request "$BASE_URL/v1/investigations/$INVESTIGATION_A/decisions"
assert_status 401 "unauthenticated GET decisions list"
request "$BASE_URL/v1/investigations/$INVESTIGATION_A/decisions/$DECISION_A_FIRST_ID"
assert_status 401 "unauthenticated GET decision detail"

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
echo "incident investigation's detail page (run at least one simulation first), and confirm:"
echo "  - a new 'Decision evaluation' section appears below Consequence simulation, labeled DECISION"
echo "  - clicking 'Evaluate scenarios' shows a candidates table (scenario / failed delta / recovery /"
echo "    exposure), a DECISION callout naming the preferred scenario and why, and a POLICY callout"
echo "    showing ALLOWED / REQUIRES HUMAN APPROVAL / BLOCKED with its reasons"
echo "  - a preferred scenario that requires approval or is blocked is still shown as preferred --"
echo "    the UI never silently swaps in a different scenario"
echo "  - evaluating with no simulations run yet shows the 'no eligible scenario' empty state"
echo "  - decision history below the current result lists prior evaluations for this investigation"
echo "  - this all works with no ANTHROPIC_API_KEY configured -- decision evaluation never depends on"
echo "    the Phase 4 reasoning provider being available"
echo "  - Phase 1-5 flows (create merchant, ingest event, run investigation, run reasoning, run a"
echo "    simulation) all still work exactly as before, and those sections are visually unchanged"

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
  && echo "FAIL: unexpected vendor/tool reference found above" \
  || echo "OK: no unexpected vendor/tool attribution references (legitimate provider implementation/configuration locations, and the verification scripts' own test instructions, are excluded from this check on purpose)"
echo "--- confirm decision evaluation + policy have no LLM/provider/network dependency ---"
grep -niE 'anthropic|openai|httpx|requests|providers\.reasoning|urllib|socket' \
  apps/api/app/domain/decision_evaluation.py apps/api/app/domain/policy.py apps/api/app/domain/decisions.py \
  && echo "FAIL: a Phase 6 domain module appears to import or reference a reasoning/LLM/network dependency" \
  || echo "OK: app.domain.decision_evaluation, app.domain.policy, and app.domain.decisions have no LLM/provider/network dependency"
echo "--- confirm the decision-creation endpoint accepts no policy-controlling request body field ---"
grep -n "def create_decision" apps/api/app/routers/investigations.py -A 3 | grep -q "payload" \
  && { echo "FAIL: create_decision appears to accept a request body -- Phase 6 requires policy to be computed entirely server-side with no client-controlled input" >&2; exit 1; } \
  || echo "OK: create_decision takes no request body (investigation_id + db dependency only)"

echo "=================================================="
echo "12. Docker Compose teardown"
echo "=================================================="
docker compose -f infra/docker-compose.yml down

echo "=================================================="
echo "DONE. Review all sections above for PASS/FAIL before reporting back."
echo "=================================================="
