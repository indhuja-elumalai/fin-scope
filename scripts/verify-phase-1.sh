#!/usr/bin/env bash
# Phase 1 verification script.
#
# Run this from the repository root on a machine with real network access
# and Docker (this was authored and committed from an environment that has
# neither, so it could not be executed there -- see docs/verification/phase-01.md).
#
#   bash scripts/verify-phase-1.sh 2>&1 | tee phase1-verification-output.txt
#
# Review the full output, then share it back so the verification docs can be
# updated to reflect what actually happened.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=================================================="
echo "1. Python virtual environment + dependency install"
echo "=================================================="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt
echo "--- pip freeze ---"
pip freeze

echo "=================================================="
echo "2. Docker Compose: Postgres + Redis startup"
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

export DATABASE_URL="postgresql+psycopg://finscope:finscope@localhost:5432/finscope"
export REDIS_URL="redis://localhost:6379/0"
export API_KEY="local-dev-key"

cd apps/api

echo "=================================================="
echo "3. Alembic upgrade"
echo "=================================================="
alembic upgrade head

echo "=================================================="
echo "4. Alembic downgrade, then re-upgrade"
echo "=================================================="
alembic downgrade base
alembic upgrade head

echo "=================================================="
echo "5. pytest"
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
echo "8. Live health + auth checks against a running server"
echo "=================================================="
uvicorn app.main:app --port 8000 &
API_PID=$!
sleep 3
echo "--- GET /health (DB+Redis up, expect 200) ---"
curl -sS -i http://localhost:8000/health; echo
echo "--- GET /v1/ping, no key (expect 401) ---"
curl -sS -i http://localhost:8000/v1/ping; echo
echo "--- GET /v1/ping, wrong key (expect 401) ---"
curl -sS -i -H "X-API-Key: wrong-key" http://localhost:8000/v1/ping; echo
echo "--- GET /v1/ping, correct key (expect 200) ---"
curl -sS -i -H "X-API-Key: local-dev-key" http://localhost:8000/v1/ping; echo
kill "$API_PID"
wait "$API_PID" 2>/dev/null || true

cd "$REPO_ROOT"

echo "=================================================="
echo "9. Docker Compose: simulate DB/Redis being down"
echo "=================================================="
docker compose -f infra/docker-compose.yml stop postgres redis
cd apps/api
uvicorn app.main:app --port 8000 &
API_PID=$!
sleep 3
echo "--- GET /health with Postgres + Redis stopped (expect 503) ---"
curl -sS -i http://localhost:8000/health; echo
kill "$API_PID"
wait "$API_PID" 2>/dev/null || true
cd "$REPO_ROOT"
docker compose -f infra/docker-compose.yml start postgres redis
sleep 5

echo "=================================================="
echo "10. Frontend: scaffold (only if apps/web is still empty)"
echo "=================================================="
if [ ! -f apps/web/package.json ]; then
  npx --yes create-next-app@latest apps/web \
    --typescript --tailwind --eslint --app --no-src-dir \
    --import-alias "@/*" --use-npm --no-turbopack
fi

cat > apps/web/app/page.tsx <<'PAGEEOF'
"use client";

import { useEffect, useState } from "react";

type HealthCheck = { status: string; detail?: string };
type HealthResponse = { status: string; checks: Record<string, HealthCheck> };

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HealthStatusPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchHealth() {
      try {
        const response = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
        const body = (await response.json()) as HealthResponse;
        if (!cancelled) {
          setHealth(body);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("Could not reach the FIN-SCOPE API.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main style={{ maxWidth: 640, margin: "4rem auto", padding: "0 1.5rem", fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>FIN-SCOPE</h1>
      <p style={{ color: "#666", marginTop: "0.25rem" }}>System foundation status</p>

      <div style={{ marginTop: "2rem", border: "1px solid #e5e5e5", borderRadius: 8, padding: "1.25rem" }}>
        {loading && <p>Checking backend health…</p>}
        {error && <p style={{ color: "#b91c1c" }}>{error}</p>}
        {health && (
          <>
            <p style={{ fontWeight: 600, color: health.status === "ok" ? "#15803d" : "#b91c1c" }}>
              Overall: {health.status}
            </p>
            <ul style={{ marginTop: "0.75rem", paddingLeft: "1.25rem" }}>
              {Object.entries(health.checks).map(([name, check]) => (
                <li key={name}>
                  {name}: {check.status}
                  {check.detail ? ` — ${check.detail}` : ""}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </main>
  );
}
PAGEEOF

cat > apps/web/.env.local.example <<'ENVEOF'
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENVEOF

cd apps/web

echo "=================================================="
echo "11. Frontend: install"
echo "=================================================="
npm install

echo "=================================================="
echo "12. Frontend: TypeScript check"
echo "=================================================="
npx tsc --noEmit

echo "=================================================="
echo "13. Frontend: lint"
echo "=================================================="
npm run lint

echo "=================================================="
echo "14. Frontend: production build"
echo "=================================================="
npm run build

cd "$REPO_ROOT"

echo "=================================================="
echo "15. Frontend -> backend integration (manual step)"
echo "=================================================="
echo "In one terminal: cd apps/api && source ../../.venv/bin/activate && uvicorn app.main:app --port 8000"
echo "In another:      cd apps/web && cp .env.local.example .env.local && npm run dev"
echo "Then open http://localhost:3000 and confirm it shows live health status."

echo "=================================================="
echo "16. Security / git hygiene checks"
echo "=================================================="
echo "--- confirm .env is not tracked ---"
git ls-files | grep -E '^\.env$' && echo "FAIL: .env is tracked" || echo "OK: .env not tracked"
echo "--- confirm .venv is not tracked ---"
git ls-files | grep -E '^\.venv/' && echo "FAIL: .venv is tracked" || echo "OK: .venv not tracked"
echo "--- confirm node_modules is not tracked ---"
git ls-files | grep -E 'node_modules/' && echo "FAIL: node_modules is tracked" || echo "OK: node_modules not tracked"
echo "--- unauthenticated protected route (already covered above, repeated for the record) ---"
echo "See step 8: /v1/ping without a key returned 401 above."

echo "=================================================="
echo "17. Docker Compose teardown"
echo "=================================================="
docker compose -f infra/docker-compose.yml down

echo "=================================================="
echo "DONE. Review all sections above for PASS/FAIL before reporting back."
echo "=================================================="
