#!/usr/bin/env bash
# Phase 3 verification script (Incident Investigation: FIND -> dominant
# signal -> impact).
#
# Run from the repository root on incident-investigation, with the Phase 1
# .venv and apps/web/node_modules already in place (no new dependencies
# were added in Phase 3):
#
#   bash scripts/verify-phase-3.sh 2>&1 | tee phase3-verification-output.txt
#
# Review the full output, then share it back so docs/verification/phase-03.md
# can be updated to reflect what actually happened.
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
export DATABASE_URL="postgresql+psycopg://finscope:finscope@localhost:5432/finscope"
export REDIS_URL="redis://localhost:6379/0"
export API_KEY="local-dev-key"

cd apps/api

echo "=================================================="
echo "2. Alembic upgrade (0002 -> 0003)"
echo "=================================================="
alembic upgrade head

echo "=================================================="
echo "3. Alembic downgrade to 0002, then back to head"
echo "=================================================="
alembic downgrade 0002
alembic upgrade head

echo "=================================================="
echo "4. pytest (full suite: Phase 1 + Phase 2 + Phase 3)"
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

# Runs curl, capturing the HTTP status code and response body separately
# (via a temp file + -w '%{http_code}') so status codes can be asserted
# rather than just eyeballed. Sets HTTP_STATUS and RESPONSE_BODY.
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
  -d '{"name":"Phase 3 Verification Merchant","segment":"retail"}'
echo "$RESPONSE_BODY"
assert_status 201 "merchant creation"
MERCHANT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$MERCHANT_ID" "merchant id"
echo "merchant id: $MERCHANT_ID (this exact id is reused for every event/investigation call below)"

echo "--- POST /v1/investigations, merchant with no events yet (expect 201, incident_detected=false) ---"
NOW_TS=$(python3 -c "from datetime import datetime, UTC; print(datetime.now(UTC).isoformat())")
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"as_of\":\"$NOW_TS\"}"
echo "$RESPONSE_BODY"
assert_status 201 "initial investigation creation (no events yet)"
assert_json_field incident_detected false "no-incident investigation with no events"

echo "--- Ingesting 3 payment_failed events within the last 15 minutes ---"
# external_reference must be unique per run, not just per event: financial_events
# has a real UniqueConstraint on (source, external_reference), and `docker compose
# down` (section 11) does not wipe the Postgres volume. A fixed literal like
# "verify-inv-evt-1" collides with the same row from a previous run of this
# script, so ingestion silently replays that OLD row -- tied to that OLD
# run's merchant -- instead of creating a NEW row for the merchant just
# created above. RUN_ID makes every run's external_reference values novel,
# the same way the pytest suite already avoids this via uuid4()-suffixed
# values (see apps/api/tests/test_events.py).
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
    -d "{\"merchant_id\":\"$MERCHANT_ID\",\"event_type\":\"payment_failed\",\"source\":\"manual\",\"external_reference\":\"verify-inv-evt-$i-$RUN_ID\",\"amount\":\"75.00\",\"currency\":\"INR\",\"occurred_at\":\"$OCCURRED_AT\"}"
  echo "$RESPONSE_BODY"
  assert_status 201 "fresh event $i creation"
done

echo "--- POST /v1/investigations, as_of just after those events (expect 201, incident_detected=true, evidence_event_count=3, dominant_signal_event_type=payment_failed) ---"
NOW_TS=$(python3 -c "from datetime import datetime, UTC; print(datetime.now(UTC).isoformat())")
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"as_of\":\"$NOW_TS\"}"
echo "$RESPONSE_BODY"
assert_status 201 "detected investigation creation"
assert_json_field incident_detected true "incident_detected after 3 concerning events"
assert_json_field evidence_event_count 3 "evidence_event_count"
assert_json_field dominant_signal_event_type payment_failed "dominant_signal_event_type"
assert_json_field dominant_signal_share 1.0000 "dominant_signal_share"

PAYMENT_FAILED_COUNT=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
print(d['event_type_counts'].get('payment_failed', 0))
" "$RESPONSE_BODY")
if [ "$PAYMENT_FAILED_COUNT" != "3" ]; then
  echo "FAIL: payment_failed count -- expected 3, got $PAYMENT_FAILED_COUNT" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: payment_failed count -- event_type_counts.payment_failed=$PAYMENT_FAILED_COUNT"

INR_TOTAL=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
entry = next(i for i in d['impact_breakdown'] if i['currency'] == 'INR')
print(entry['total_amount'])
" "$RESPONSE_BODY")
if [ "$INR_TOTAL" != "225.00" ]; then
  echo "FAIL: INR impact total -- expected 225.00, got $INR_TOTAL" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: INR impact total -- impact_breakdown[INR].total_amount=$INR_TOTAL"

EVIDENCE_ORDER_OK=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
times = [e['occurred_at'] for e in d['evidence']]
print('true' if times == sorted(times) else 'false')
" "$RESPONSE_BODY")
if [ "$EVIDENCE_ORDER_OK" != "true" ]; then
  echo "FAIL: evidence ordering -- evidence list is not sorted by occurred_at ascending" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: evidence ordering -- evidence items sorted ascending by occurred_at"

INVESTIGATION_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$RESPONSE_BODY")
require_uuid "$INVESTIGATION_ID" "investigation id"
echo "investigation id: $INVESTIGATION_ID"

echo "--- GET /v1/investigations/{id} (expect 200, evidence has 3 items in occurred_at order) ---"
request -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/investigations/$INVESTIGATION_ID"
echo "$RESPONSE_BODY"
assert_status 200 "investigation detail"

echo "--- GET /v1/investigations/{random-uuid} (expect 404) ---"
request -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/investigations/00000000-0000-0000-0000-000000000000"
echo "$RESPONSE_BODY"
assert_status 404 "random investigation lookup"

echo "--- GET /v1/investigations?merchant_id=...&incident_detected=true (expect 200, includes the investigation above) ---"
request -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/investigations?merchant_id=$MERCHANT_ID&incident_detected=true"
echo "$RESPONSE_BODY"
assert_status 200 "filtered investigation list"
LIST_CONTAINS_INVESTIGATION=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
print('true' if any(item['id'] == sys.argv[2] for item in d['items']) else 'false')
" "$RESPONSE_BODY" "$INVESTIGATION_ID")
if [ "$LIST_CONTAINS_INVESTIGATION" != "true" ]; then
  echo "FAIL: filtered investigation list -- does not contain investigation $INVESTIGATION_ID" >&2
  kill "$API_PID" 2>/dev/null || true
  exit 1
fi
echo "PASS: filtered investigation list -- contains investigation $INVESTIGATION_ID"

echo "--- POST /v1/investigations, unknown merchant (expect 404) ---"
request -X POST http://localhost:8000/v1/investigations \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"merchant_id":"00000000-0000-0000-0000-000000000000"}'
echo "$RESPONSE_BODY"
assert_status 404 "unknown merchant investigation"

echo "--- POST /v1/investigations, no key (expect 401) ---"
request -X POST http://localhost:8000/v1/investigations -d "{\"merchant_id\":\"$MERCHANT_ID\"}"
echo "$RESPONSE_BODY"
assert_status 401 "unauthenticated POST /v1/investigations"

echo "--- GET /v1/investigations, no key (expect 401) ---"
request http://localhost:8000/v1/investigations
echo "$RESPONSE_BODY"
assert_status 401 "unauthenticated GET /v1/investigations"

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
echo "Then open the frontend URL the Next.js dev server printed (e.g. http://localhost:3000 or http://localhost:3001 if 3000 was already in use), go to /investigations, and confirm:"
echo "  - the merchant dropdown is populated"
echo "  - running an investigation for a merchant with no recent concerning events reports 'No incident detected'"
echo "  - ingesting 3+ payment_failed/settlement_delayed/gateway_degraded events for a merchant on /events,"
echo "    then running an investigation for that merchant reports 'Incident detected' with a dominant signal"
echo "  - clicking an investigation opens /investigations/[id] and shows the window, dominant signal"
echo "    (labeled as a heuristic, not a cause), currency-safe impact breakdown, and evidence timeline"
echo "  - clicking an evidence item's event type opens its /events/[id] detail page"
echo "  - filtering the investigation list by merchant works"

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

echo "=================================================="
echo "11. Docker Compose teardown"
echo "=================================================="
docker compose -f infra/docker-compose.yml down

echo "=================================================="
echo "DONE. Review all sections above for PASS/FAIL before reporting back."
echo "=================================================="
