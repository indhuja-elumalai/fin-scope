#!/usr/bin/env bash
# Phase 2 verification script (Event Engine: merchants + financial events).
#
# Run from the repository root on feat/core-domain, with the Phase 1 .venv
# and apps/web/node_modules already in place (no new dependencies were
# added in Phase 2):
#
#   bash scripts/verify-phase-2.sh 2>&1 | tee phase2-verification-output.txt
#
# Review the full output, then share it back so docs/verification/phase-02.md
# can be updated to reflect what actually happened.
set -uo pipefail

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

source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://finscope:finscope@localhost:5432/finscope"
export REDIS_URL="redis://localhost:6379/0"
export API_KEY="local-dev-key"

cd apps/api

echo "=================================================="
echo "2. Alembic upgrade (0001 -> 0002)"
echo "=================================================="
alembic upgrade head

echo "=================================================="
echo "3. Alembic downgrade to 0001, then back to head"
echo "=================================================="
alembic downgrade 0001
alembic upgrade head

echo "=================================================="
echo "4. pytest (full suite: Phase 1 + Phase 2)"
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

echo "--- POST /v1/merchants (expect 201) ---"
MERCHANT_JSON=$(curl -sS -X POST http://localhost:8000/v1/merchants \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"name":"Verification Merchant","segment":"retail"}')
echo "$MERCHANT_JSON"
MERCHANT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$MERCHANT_JSON")
echo "merchant id: $MERCHANT_ID"

echo "--- POST /v1/merchants, no key (expect 401) ---"
curl -sS -i -X POST http://localhost:8000/v1/merchants -d '{"name":"x"}'; echo

echo "--- GET /v1/merchants (expect 200, includes the merchant above) ---"
curl -sS -i -H "X-API-Key: local-dev-key" http://localhost:8000/v1/merchants; echo

echo "--- GET /v1/merchants/{id} (expect 200) ---"
curl -sS -i -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/merchants/$MERCHANT_ID"; echo

echo "--- GET /v1/merchants/{random-uuid} (expect 404) ---"
curl -sS -i -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/merchants/00000000-0000-0000-0000-000000000000"; echo

echo "--- POST /v1/events, unknown merchant (expect 404) ---"
curl -sS -i -X POST http://localhost:8000/v1/events \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"merchant_id":"00000000-0000-0000-0000-000000000000","event_type":"payment_failed","source":"manual","occurred_at":"2026-09-01T00:00:00Z"}'; echo

echo "--- POST /v1/events, invalid event_type (expect 422) ---"
curl -sS -i -X POST http://localhost:8000/v1/events \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"event_type\":\"not_real\",\"source\":\"manual\",\"occurred_at\":\"2026-09-01T00:00:00Z\"}"; echo

echo "--- POST /v1/events, valid (expect 201) ---"
EVENT_JSON=$(curl -sS -X POST http://localhost:8000/v1/events \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"event_type\":\"payment_failed\",\"source\":\"manual\",\"external_reference\":\"verify-evt-1\",\"amount\":\"49.50\",\"currency\":\"INR\",\"occurred_at\":\"2026-09-01T00:00:00Z\"}")
echo "$EVENT_JSON"
EVENT_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$EVENT_JSON")
echo "event id: $EVENT_ID"

echo "--- POST /v1/events, same (source, external_reference) again (expect 200, same id) ---"
curl -sS -i -X POST http://localhost:8000/v1/events \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d "{\"merchant_id\":\"$MERCHANT_ID\",\"event_type\":\"payment_failed\",\"source\":\"manual\",\"external_reference\":\"verify-evt-1\",\"amount\":\"49.50\",\"currency\":\"INR\",\"occurred_at\":\"2026-09-01T00:00:00Z\"}"; echo

echo "--- GET /v1/events?merchant_id=... (expect 200, includes the event above) ---"
curl -sS -i -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/events?merchant_id=$MERCHANT_ID"; echo

echo "--- GET /v1/events/{id} (expect 200) ---"
curl -sS -i -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/events/$EVENT_ID"; echo

echo "--- GET /v1/events/{random-uuid} (expect 404) ---"
curl -sS -i -H "X-API-Key: local-dev-key" "http://localhost:8000/v1/events/00000000-0000-0000-0000-000000000000"; echo

echo "--- GET /v1/events, no key (expect 401) ---"
curl -sS -i http://localhost:8000/v1/events; echo

echo "--- CORS preflight from http://localhost:3000 (expect allow-origin echoed) ---"
curl -sS -i -X OPTIONS http://localhost:8000/v1/merchants \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: X-API-Key"; echo

echo "--- CORS preflight from http://localhost:3001 (expect allow-origin echoed too) ---"
curl -sS -i -X OPTIONS http://localhost:8000/v1/merchants \
  -H "Origin: http://localhost:3001" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: X-API-Key"; echo

echo "--- CORS preflight from an unrelated origin (expect NOT echoed back) ---"
curl -sS -i -X OPTIONS http://localhost:8000/v1/merchants \
  -H "Origin: http://evil.example.com" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: X-API-Key"; echo

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
echo "  (env_file now resolves to the repo-root .env regardless of this cwd --"
echo "   if you previously had a stale API_KEY exported in this shell from an"
echo "   earlier session, unset it first: unset API_KEY DATABASE_URL REDIS_URL)"
echo "In another:      cd apps/web && cp .env.local.example .env.local"
echo "                 (edit .env.local: set API_KEY to the same value the backend uses)"
echo "                 npm run dev"
echo "Then open http://localhost:3000/merchants and http://localhost:3000/events and confirm:"
echo "  - creating a merchant on /merchants shows it in the list immediately"
echo "  - ingesting an event on /events with a merchant selected succeeds and appears in the list"
echo "  - re-submitting the same external reference reports the idempotent-replay message"
echo "  - submitting with no merchant selected is blocked by the disabled submit button"
echo "  - clicking an event opens /events/[id] and shows its full detail, including payload"
echo "  - filtering by merchant and by event type narrows the list correctly"

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
