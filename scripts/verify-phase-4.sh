#!/usr/bin/env bash
# Phase 4 verification script (Investigation Reasoning: evidence-grounded
# hypotheses over an existing Phase 3 investigation) + the Phase 1-3
# regression suite.
#
# Run from the repository root on investigation-reasoning, with the Phase 1
# .venv and apps/web/node_modules already in place:
#
#   bash scripts/verify-phase-4.sh 2>&1 | tee phase4-verification-output.txt
#
# This script deliberately does NOT set ANTHROPIC_API_KEY, so section 7's
# live checks exercise the "reasoning provider not configured" path
# (status="unavailable") deterministically, with no network call and no
# provider credentials spent. That is enough to verify the whole endpoint
# end to end -- auth, 404s, persistence, the insufficient-evidence path,
# and re-run semantics -- without depending on an external service. If you
# want to see a real "completed" result with actual generated hypotheses,
# set ANTHROPIC_API_KEY in .env first and try the reasoning button from the
# browser in section 9 -- that is optional and outside what this script
# checks automatically.
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
echo "2. Alembic upgrade (0003 -> 0004)"
echo "=================================================="
alembic upgrade head

echo "=================================================="
echo "3. Alembic downgrade to 0003, then back to head"
echo "=================================================="
alembic downgrade 0003
alembic upgrade head

echo "=================================================="
echo "4. pytest (full suite: Phase 1 + Phase 2 + Phase 3 + Phase 4)"
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
  -d '{"name":"Phase 4 Verification Merchant","segment":"retail"}'
echo "$RESPONSE_BODY"
assert_status 201 "merchant creation"
MERCHANT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$MERCHANT_ID" "merchant id"

echo "--- Ingesting 3 payment_failed events within the last 15 minutes ---"
RUN_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
read -r T5 T10 T15 <<EOF_TS
$(python3 -c "
from datetime import datetime, UTC, timedelta
now = datetime.now(UTC)
print((now-timedelta(minutes=5)).isoformat(), (now-timedelta(minutes=10)).isoformat(), (now-timedelta(minutes=15)).isoformat())
")
EOF_TS
for i in 1 2 3; do
  case $i in
    1) OCCURRED_AT=$T5 ;;
    2) OCCURRED_AT=$T10 ;;
    3) OCCURRED_AT=$T15 ;;
  esac
  request -X POST http://localhost:8000/v1/events \
    -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
    -d "{\"merchant_id\":\"$MERCHANT_ID\",\"event_type\":\"payment_failed\",\"source\":\"manual\",\"external_reference\":\"verify-reason-evt-$i-$RUN_ID\",\"amount\":\"75.00\",\"currency\":\"INR\",\"occurred_at\":\"$OCCURRED_AT\"}"
  assert_status 201 "fresh event $i creation"
done

echo "--- POST /v1/investigations (expect 201, incident_detected=true) ---"
NOW_TS=$(python3 -c "from datetime import datetime, UTC; print(datetime.now(UTC).isoformat())")
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"as_of\":\"$NOW_TS\"}"
assert_status 201 "detected investigation creation"
assert_json_field incident_detected true "incident_detected"
DETECTED_INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$DETECTED_INVESTIGATION_ID" "detected investigation id"

echo "--- POST /v1/investigations/{id}/reason, no ANTHROPIC_API_KEY configured (expect 201, status=unavailable) ---"
request -X POST "http://localhost:8000/v1/investigations/$DETECTED_INVESTIGATION_ID/reason" \
  -H "X-API-Key: local-dev-key"
echo "$RESPONSE_BODY"
assert_status 201 "reasoning run (provider not configured)"
assert_json_field status unavailable "reasoning status when provider is not configured"
REASONING_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$REASONING_ID" "reasoning id"

echo "--- GET /v1/investigations/{id}/reasoning (expect 200, same reasoning id -- persisted) ---"
request -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/investigations/$DETECTED_INVESTIGATION_ID/reasoning"
assert_status 200 "latest reasoning fetch"
assert_json_field id "$REASONING_ID" "latest reasoning matches the run above"

echo "--- POST /v1/investigations (no events, expect 201, incident_detected=false) ---"
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"as_of\":\"$(python3 -c 'from datetime import datetime, UTC, timedelta; print((datetime.now(UTC)-timedelta(days=2)).isoformat())')\"}"
assert_status 201 "no-incident investigation creation"
assert_json_field incident_detected false "no-incident investigation"
NO_INCIDENT_INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")

echo "--- POST /v1/investigations/{id}/reason on a no-incident investigation (expect 201, status=insufficient_evidence) ---"
request -X POST "http://localhost:8000/v1/investigations/$NO_INCIDENT_INVESTIGATION_ID/reason" \
  -H "X-API-Key: local-dev-key"
echo "$RESPONSE_BODY"
assert_status 201 "reasoning run (no incident detected)"
assert_json_field status insufficient_evidence "reasoning status when no incident was detected"

echo "--- GET /v1/investigations/{id}/reasoning, reasoning never run for this investigation (expect 404) ---"
request -X POST http://localhost:8000/v1/merchants \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"name":"Phase 4 Verification Merchant (no reasoning run)"}'
OTHER_MERCHANT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$OTHER_MERCHANT_ID\"}"
NEVER_REASONED_INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
request -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/investigations/$NEVER_REASONED_INVESTIGATION_ID/reasoning"
assert_status 404 "reasoning fetch before any run"

echo "--- POST /v1/investigations/{random-uuid}/reason (expect 404) ---"
request -X POST "http://localhost:8000/v1/investigations/00000000-0000-0000-0000-000000000000/reason" \
  -H "X-API-Key: local-dev-key"
assert_status 404 "reasoning on unknown investigation"

echo "--- POST /v1/investigations/{id}/reason, no key (expect 401) ---"
request -X POST "http://localhost:8000/v1/investigations/$DETECTED_INVESTIGATION_ID/reason"
assert_status 401 "unauthenticated POST reason"

echo "--- GET /v1/investigations/{id}/reasoning, no key (expect 401) ---"
request "http://localhost:8000/v1/investigations/$DETECTED_INVESTIGATION_ID/reasoning"
assert_status 401 "unauthenticated GET reasoning"

echo "--- Re-running reasoning creates a new row rather than overwriting (expect a different id) ---"
request -X POST "http://localhost:8000/v1/investigations/$DETECTED_INVESTIGATION_ID/reason" \
  -H "X-API-Key: local-dev-key"
RERUN_REASONING_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
if [ "$RERUN_REASONING_ID" == "$REASONING_ID" ]; then
  echo "FAIL: re-running reasoning returned the same id -- expected a new persisted row" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: re-run persisted as a new row ($REASONING_ID -> $RERUN_REASONING_ID)"

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
echo "Then open the frontend URL the Next.js dev server printed, go to /investigations, and confirm:"
echo "  - triggering an investigation that detects an incident, then opening its detail page, shows"
echo "    Incident -> Dominant signal -> Impact -> Evidence -> Reasoning, in that order"
echo "  - each factual section (Incident/Dominant signal/Impact/Evidence) is visibly labeled FACT"
echo "  - the Reasoning section starts in an idle 'not run yet' state with a 'Run reasoning' button"
echo "  - clicking it (with no ANTHROPIC_API_KEY set in .env) shows a clear 'Reasoning unavailable'"
echo "    state -- the page around it (incident/impact/evidence) stays fully intact and readable"
echo "  - if you set ANTHROPIC_API_KEY in .env and restart the backend, running reasoning instead"
echo "    shows ranked hypothesis cards with a confidence badge, an explanation, supporting/"
echo "    contradicting evidence links back into the evidence timeline above, and an uncertainty note"
echo "    -- and every hypothesis is clearly labeled INFERENCE, distinct from the FACT sections"
echo "  - the navbar's active page is clearly highlighted and every nav item is readable (the"
echo "    previous white-text-on-hover contrast bug is gone)"
echo "  - dropdowns/inputs across /merchants, /events, and /investigations look and behave"
echo "    consistently, with visible focus/hover/disabled states"
echo "  - Phase 1-3 flows (create merchant, ingest event, run investigation, filter lists) all still"
echo "    work exactly as before"

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
  && echo "FAIL: unexpected vendor/tool reference found above" \
  || echo "OK: no unexpected vendor/tool attribution references (legitimate provider implementation/configuration locations are excluded from this check on purpose)"

echo "=================================================="
echo "11. Docker Compose teardown"
echo "=================================================="
docker compose -f infra/docker-compose.yml down

echo "=================================================="
echo "DONE. Review all sections above for PASS/FAIL before reporting back."
echo "=================================================="
