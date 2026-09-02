#!/usr/bin/env bash
# Phase 5 verification script (Deterministic Consequence Simulation:
# SCENARIO -> DETERMINISTIC SIMULATOR -> CONSEQUENCE RESULT, over an
# existing Phase 3 investigation) + the Phase 1-4 regression suite.
#
# Run from the repository root on deterministic-consequence-simulation,
# with the Phase 1 .venv and apps/web/node_modules already in place:
#
#   bash scripts/verify-phase-5.sh 2>&1 | tee phase5-verification-output.txt
#
# The simulator is pure deterministic Python -- no LLM call, no network
# dependency, no random behavior anywhere in app.domain.simulation. This
# script deliberately does NOT set ANTHROPIC_API_KEY (same as
# verify-phase-4.sh); Phase 5 does not read it at all, and section 7 proves
# a simulation can be run and produce a "completed" result with no
# reasoning provider configured -- a valid investigation must be
# simulatable even when Phase 4 reasoning is unavailable.
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
echo "2. Alembic upgrade (0004 -> 0005)"
echo "=================================================="
alembic upgrade head

echo "=================================================="
echo "3. Alembic downgrade to 0004, then back to head"
echo "=================================================="
alembic downgrade 0004
alembic upgrade head

echo "=================================================="
echo "4. pytest (full suite: Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 5)"
echo "=================================================="
pytest -v

echo "=================================================="
echo "5. ruff"
echo "=================================================="
ruff check .

echo "=================================================="
echo "6. mypy"
echo "=================================================="
mypy app

echo "=================================================="
echo "7. Live backend checks against a running server"
echo "=================================================="
uvicorn app.main:app --port 8000 &
API_PID=$!
sleep 3

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

echo "--- POST /v1/merchants (expect 201) ---"
request -X POST http://localhost:8000/v1/merchants \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"name":"Phase 5 Verification Merchant","segment":"retail"}'
echo "$RESPONSE_BODY"
assert_status 201 "merchant creation"
MERCHANT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$MERCHANT_ID" "merchant id"

echo "--- Ingesting 4 payment_failed events (75.00 INR each) within the last 20 minutes ---"
RUN_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
read -r T5 T10 T15 T20 <<EOF_TS
$(python3 -c "
from datetime import datetime, UTC, timedelta
now = datetime.now(UTC)
print((now-timedelta(minutes=5)).isoformat(), (now-timedelta(minutes=10)).isoformat(), (now-timedelta(minutes=15)).isoformat(), (now-timedelta(minutes=20)).isoformat())
")
EOF_TS
i=1
for OCCURRED_AT in "$T5" "$T10" "$T15" "$T20"; do
  request -X POST http://localhost:8000/v1/events \
    -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
    -d "{\"merchant_id\":\"$MERCHANT_ID\",\"event_type\":\"payment_failed\",\"source\":\"manual\",\"external_reference\":\"verify-sim-evt-$i-$RUN_ID\",\"amount\":\"75.00\",\"currency\":\"INR\",\"occurred_at\":\"$OCCURRED_AT\"}"
  assert_status 201 "fresh event $i creation"
  i=$((i + 1))
done

echo "--- POST /v1/investigations (expect 201, incident_detected=true) ---"
NOW_TS=$(python3 -c "from datetime import datetime, UTC; print(datetime.now(UTC).isoformat())")
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"as_of\":\"$NOW_TS\"}"
assert_status 201 "detected investigation creation"
assert_json_field incident_detected true "incident_detected"
INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$INVESTIGATION_ID" "investigation id"

echo "--- POST .../simulations DO_NOTHING (expect 201, completed, zero delta, no ANTHROPIC_API_KEY needed) ---"
request -X POST "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations" \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"scenario":"DO_NOTHING"}'
echo "$RESPONSE_BODY"
assert_status 201 "DO_NOTHING simulation"
assert_json_field status completed "DO_NOTHING status"
DELTA=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['result']['delta']['failed_event_count_delta'])" "$RESPONSE_BODY")
if [ "$DELTA" != "0" ]; then
  echo "FAIL: DO_NOTHING failed_event_count_delta expected 0, got $DELTA" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: DO_NOTHING produces zero delta"

echo "--- POST .../simulations RETRY_AFFECTED_PAYMENTS with override (expect deterministic 2 successes / 150.00 INR recovered) ---"
request -X POST "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations" \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"scenario":"RETRY_AFFECTED_PAYMENTS","assumptions":{"success_rate":"0.5","scope_fraction":"1.0"}}'
echo "$RESPONSE_BODY"
assert_status 201 "RETRY_AFFECTED_PAYMENTS simulation"
SUCCESS_COUNT=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['result']['projected']['success_event_count'])" "$RESPONSE_BODY")
RECOVERED=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(next(i['amount'] for i in d['result']['estimated_recovery_by_currency'] if i['currency']=='INR'))" "$RESPONSE_BODY")
if [ "$SUCCESS_COUNT" != "2" ] || [ "$RECOVERED" != "150.00" ]; then
  echo "FAIL: expected success_event_count=2 and recovered INR=150.00, got success_event_count=$SUCCESS_COUNT recovered=$RECOVERED" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: RETRY_AFFECTED_PAYMENTS deterministic result matches hand-computed expectation"
RETRY_SIM_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
FIRST_RESULT=$(python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1])['result'], sort_keys=True))" "$RESPONSE_BODY")

echo "--- Re-running the same scenario+assumptions produces an identical result (determinism) ---"
request -X POST "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations" \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"scenario":"RETRY_AFFECTED_PAYMENTS","assumptions":{"success_rate":"0.5","scope_fraction":"1.0"}}'
RERUN_SIM_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
RERUN_RESULT=$(python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1])['result'], sort_keys=True))" "$RESPONSE_BODY")
if [ "$RERUN_SIM_ID" == "$RETRY_SIM_ID" ]; then
  echo "FAIL: re-running a simulation returned the same id -- expected a new append-only row" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
if [ "$RERUN_RESULT" != "$FIRST_RESULT" ]; then
  echo "FAIL: re-running the same scenario+assumptions produced a different result -- not deterministic" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: re-run persisted as a new row ($RETRY_SIM_ID -> $RERUN_SIM_ID), identical result -- deterministic"

echo "--- GET .../simulations (expect 200, list includes both DO_NOTHING and RETRY_AFFECTED_PAYMENTS runs) ---"
request -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations"
COUNT=$(python3 -c "import json,sys; print(len(json.loads(sys.argv[1])['items']))" "$RESPONSE_BODY")
assert_status 200 "simulation list"
if [ "$COUNT" -lt 3 ]; then
  echo "FAIL: expected at least 3 persisted simulation rows for this investigation, got $COUNT" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: simulation history contains $COUNT append-only rows"

echo "--- GET .../simulations/{id} (expect 200, matches the RETRY_AFFECTED_PAYMENTS run above) ---"
request -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations/$RETRY_SIM_ID"
assert_status 200 "simulation detail fetch"
assert_json_field id "$RETRY_SIM_ID" "simulation detail matches the run above"

echo "--- POST .../simulations, no incident (expect 201, status=insufficient_evidence) ---"
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"as_of\":\"$(python3 -c 'from datetime import datetime, UTC, timedelta; print((datetime.now(UTC)-timedelta(days=2)).isoformat())')\"}"
assert_json_field incident_detected false "no-incident investigation"
NO_INCIDENT_INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
request -X POST "http://localhost:8000/v1/investigations/$NO_INCIDENT_INVESTIGATION_ID/simulations" \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"scenario":"RETRY_AFFECTED_PAYMENTS"}'
echo "$RESPONSE_BODY"
assert_status 201 "simulation on a no-incident investigation"
assert_json_field status insufficient_evidence "simulation status when no incident was detected"

echo "--- POST .../simulations, unsupported scenario (expect 422) ---"
request -X POST "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations" \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"scenario":"NOT_A_REAL_SCENARIO"}'
assert_status 422 "unsupported scenario rejected"

echo "--- POST .../simulations, out-of-bounds assumption (expect 422) ---"
request -X POST "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations" \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"scenario":"RETRY_AFFECTED_PAYMENTS","assumptions":{"success_rate":"2.0"}}'
assert_status 422 "out-of-bounds success_rate rejected"

echo "--- POST .../simulations/{random-uuid} on a valid investigation for isolation (expect 404) ---"
request -X POST http://localhost:8000/v1/merchants \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"name":"Phase 5 Isolation Merchant"}'
OTHER_MERCHANT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$OTHER_MERCHANT_ID\"}"
OTHER_INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
request -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/investigations/$OTHER_INVESTIGATION_ID/simulations/$RETRY_SIM_ID"
assert_status 404 "a simulation belonging to a different investigation is not found"

echo "--- POST .../{random-uuid}/simulations (expect 404) ---"
request -X POST "http://localhost:8000/v1/investigations/00000000-0000-0000-0000-000000000000/simulations" \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"scenario":"DO_NOTHING"}'
assert_status 404 "simulation on unknown investigation"

echo "--- POST .../simulations, no key (expect 401) ---"
request -X POST "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations" \
  -H "Content-Type: application/json" -d '{"scenario":"DO_NOTHING"}'
assert_status 401 "unauthenticated POST simulations"

echo "--- GET .../simulations, no key (expect 401) ---"
request "http://localhost:8000/v1/investigations/$INVESTIGATION_ID/simulations"
assert_status 401 "unauthenticated GET simulations"

kill "$API_PID"
wait "$API_PID" 2>/dev/null || true
cd "$REPO_ROOT"

echo "=================================================="
echo "8. Frontend: TypeScript check, lint, build"
echo "=================================================="
cd apps/web
npx tsc --noEmit
npm run lint
npm run build
cd "$REPO_ROOT"

echo "=================================================="
echo "9. Frontend <-> backend end-to-end (manual step)"
echo "=================================================="
echo "In one terminal: source .venv/bin/activate && cd apps/api && uvicorn app.main:app --reload --port 8000"
echo "  (unset any stale API_KEY/DATABASE_URL/REDIS_URL exported in this shell first if reused)"
echo "In another:      cd apps/web && npm run dev"
echo "Then open the frontend URL the Next.js dev server printed, go to /investigations, open an"
echo "incident investigation's detail page, and confirm:"
echo "  - a new 'Consequence simulation' section appears below Reasoning, labeled PROJECTED"
echo "  - a scenario dropdown lists Do nothing / Retry affected payments / Reroute provider /"
echo "    Target affected event type"
echo "  - running a scenario shows a scope description, an ASSUMPTION note (success rate + scope),"
echo "    a Baseline (FACT) card and a Projected (PROJECTED) card side by side, an estimated"
echo "    recovery amount, and a delta line -- all clearly labeled as simulated, never presented as"
echo "    an actual financial outcome"
echo "  - running DO_NOTHING shows baseline == projected with a zero delta"
echo "  - simulation history below the current result lists prior runs for this investigation"
echo "  - this all works with no ANTHROPIC_API_KEY configured -- the simulator never depends on the"
echo "    Phase 4 reasoning provider being available"
echo "  - Phase 1-4 flows (create merchant, ingest event, run investigation, run reasoning) all still"
echo "    work exactly as before, and the Reasoning section is visually unchanged"

echo "=================================================="
echo "10. Security / git hygiene checks"
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
  && echo "FAIL: unexpected vendor/tool reference found above" \
  || echo "OK: no unexpected vendor/tool attribution references (legitimate provider implementation/configuration locations, and the verification scripts' own test instructions, are excluded from this check on purpose)"
echo "--- confirm the simulator has no LLM/provider import ---"
grep -niE 'anthropic|openai|httpx|providers\.reasoning' apps/api/app/domain/simulation.py \
  && echo "FAIL: app.domain.simulation appears to import or reference a reasoning/LLM provider" \
  || echo "OK: app.domain.simulation has no LLM/provider dependency"

echo "=================================================="
echo "11. Docker Compose teardown"
echo "=================================================="
docker compose -f infra/docker-compose.yml down

echo "=================================================="
echo "DONE. Review all sections above for PASS/FAIL before reporting back."
echo "=================================================="
