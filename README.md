# FIN-SCOPE

Financial Intelligence, Simulation & Controlled Decision Engine

## 1. Problem

Financial systems generate a constant stream of events — payment failures,
refunds, settlement changes, gateway degradation. Dashboards can say *that*
something changed; they cannot say *why*, *how much it matters financially*,
*what to do about it*, or *whether an intervention actually worked*.

## 2. What FIN-SCOPE does

FIN-SCOPE is a decision-control layer that sits around a financial workflow
and detects anomalies, investigates their likely root cause, estimates
financial impact, simulates candidate interventions, checks any proposed
action against a deterministic policy engine, executes only bounded and
approved actions, and verifies the outcome.

## 3. Core loop

```
FIND -> INVESTIGATE -> ROOT CAUSE -> IMPACT -> SIMULATE -> DECIDE -> POLICY -> ACT -> VERIFY -> LEARN
```

None of these stages are implemented yet. This repository currently
implements only the foundation described in section 12.

## 4. Why AI is used

Claude is used where ambiguity and reasoning exist: hypothesis generation,
evidence interpretation, root-cause ranking, incident summarization, and
proposing bounded interventions with rationale. This begins in the
Investigation phase (not yet implemented).

## 5. Where AI is deliberately avoided

Claude is never used for financial arithmetic, anomaly thresholds, policy
enforcement, authorization, idempotency, execution, or audit logging. Those
are deterministic by design, and AI has no path to directly executing a
financial action — every AI output passes through schema validation and a
deterministic policy engine before anything can be executed.

## 6. Architecture

```
Frontend (Next.js)
        |
Backend (FastAPI)
        |
  +-----+-----+-----+
  |           |      |
Event      Investi-  Simulation      (not yet implemented)
Engine     gation
  |           |      |
Anomaly/   Claude    Financial
Stats      AI        Model
  |           |      |
  +-----+-----+-----+
        |
  Decision Engine        (not yet implemented)
        |
  Policy Engine (deterministic)   (not yet implemented)
        |
  Execution Layer        (not yet implemented)
        |
  Razorpay API            (not yet implemented)
        |
  Verification            (not yet implemented)
        |
  Audit Log
```

Phase 1 establishes the backend/frontend skeleton, the database (`merchants`,
`audit_log`), API-key auth, and health checks that everything above will be
built on.

## 7. Technology stack

- Frontend: Next.js, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, Pydantic
- Database: PostgreSQL (local Docker for development; Neon later)
- Cache/queue: Redis (local Docker for development; managed Redis later)
- AI: Anthropic Claude (not yet integrated)
- Payments: Razorpay Test Mode (not yet integrated)

## 8. Sandbox

Not yet implemented. Will provide a controlled synthetic event generator and
incident injector used as the primary benchmark/stress-test environment.

## 9. Razorpay integration

Not yet implemented. `.env.example` reserves `RAZORPAY_KEY_ID`,
`RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` for the adapter that
will be built in its designated phase.

## 10. Evaluation methodology

Not yet implemented. Will compare FIN-SCOPE's output against golden answers
for a benchmark set of synthetic scenarios.

## 11. Metrics

Not yet implemented.

## 12. Development roadmap

| Phase | Goal | Key Deliverable | Status |
|------|------|-----------------|--------|
| 1 | Foundation | Working project skeleton | ✅ COMPLETE |
| 2 | Event Engine | Financial event ingestion | ⬜ |
| 3 | FIND | Anomaly detection | ⬜ |
| 4 | Investigation | Evidence + hypotheses | ⬜ |
| 5 | Root Cause | Evidence-backed ranking | ⬜ |
| 6 | Simulation | Controlled financial sandbox | ⬜ |
| 7 | Decision | Intervention selection | ⬜ |
| 8 | Policy + ACT | Bounded execution | ⬜ |
| 9 | VERIFY | Outcome verification | ⬜ |
| 10 | Evaluation | Benchmark + metrics | ⬜ |
| 11 | Product UI | Investigation experience | ⬜ |
| 12 | Integration | Provider/test-mode integration | ⬜ |
| 13 | Hardening | Reliability + security | ⬜ |
| 14 | Submission | Documentation + demo | ⬜ |

### Phase 1 — Foundation

Goal: a working, professionally structured project skeleton with no business
logic yet (no detection, AI, simulation, or execution).

Delivered:
- FastAPI backend (`apps/api`) with config, DB session, Redis client,
  API-key auth dependency, `/health`, and a protected `/v1/ping`
- `merchants` and `audit_log` tables with an Alembic migration
- Next.js frontend (`apps/web`) with a page that displays live backend health
- `infra/docker-compose.yml` for local Postgres + Redis
- pytest suite, ruff and mypy configuration
- `docs/verification/phase-01.md`

Verification: all 18 automated checks in `docs/verification/phase-01.md`
were executed and passed on the project owner's machine (Python 3.13.7,
Node v25.6.1, Docker 28.4.0) -- backend test suite (9 passed), ruff (all
checks passed), mypy (no issues in 12 source files), both Alembic
directions, live health/auth checks against real Postgres/Redis, and the
full frontend build. Two real issues were found and fixed during
verification -- a test-isolation bug in the API-key test fixture, and a
Docker healthcheck race condition in the verification script -- both
documented in `docs/verification/phase-01.md` rather than worked around.

Status: COMPLETE

## 13. Phase completion status

Phase 1 is COMPLETE (implemented, verified, documented). No later phase has any implementation yet.

## 14. Verification results

See `docs/verification/phase-01.md` for the full checklist, exact commands,
and the two issues found and fixed during verification. Summary: 9/9
backend tests passed, ruff clean, mypy clean, both Alembic directions
verified, live DB/Redis health and API-key auth checks all passed, full
frontend build succeeded.

## 15. Local setup

Requires Python 3.11+, Node 20+, and Docker.

```bash
cp .env.example .env   # fill in API_KEY at minimum; DB/Redis defaults match docker-compose

python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt

docker compose -f infra/docker-compose.yml up -d
cd apps/api
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# in another terminal
cd apps/web
npm install
cp .env.local.example .env.local
npm run dev
```

Or run `bash scripts/verify-phase-1.sh` to do all of the above plus the full
verification suite in one pass.

## 16. Environment variables

See `.env.example` for the complete list and comments. `API_KEY` is required
by the backend at startup; `DATABASE_URL` and `REDIS_URL` default to the
local docker-compose services. Razorpay and Anthropic keys are reserved for
later phases and are optional until then. `.env` is never committed.

## 17. Testing

Backend: `pytest` (unit tests for config/auth, integration tests for
`/health` against real and simulated-failure Postgres/Redis). Frontend:
`npx tsc --noEmit`, `npm run lint`, `npm run build`.

## 18. Known limitations

- No business logic exists yet — FIND through LEARN are all future phases.
- The API-key auth model is intentionally minimal (single shared key); it is
  not a substitute for real multi-tenant auth if that becomes necessary.
- Phase 1's automated verification (installs, tests, docker compose, builds)
  was authored and written from an environment without package-registry or
  Docker access, and was executed by the project owner locally — see
  `docs/verification/phase-01.md` for exactly what ran, where, and the two
  issues that were found and fixed in the process.

## 19. Future architecture

See the approved Phase 0 architecture review (development conversation) for
the full target architecture, database schema, evaluation design, and
Razorpay integration plan across all 14 phases.
