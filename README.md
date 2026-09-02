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

This repository currently implements the foundation, the deterministic
event-ingestion layer, and a deterministic FIND -> dominant-signal ->
IMPACT slice (rule-based incident detection, a frequency-based "dominant
signal" heuristic, and a currency-safe impact estimate -- not causal
root-causing, and no AI/LLM call anywhere in this slice) described in
section 12. ROOT CAUSE (causal reasoning), SIMULATE, DECIDE, POLICY, ACT,
VERIFY, and LEARN have not started.

## 4. Why AI is used

A reasoning model is used where ambiguity and reasoning exist: hypothesis generation,
evidence interpretation, causal root-cause ranking, incident summarization,
and proposing bounded interventions with rationale. This begins in a later,
not-yet-implemented phase that reasons over the deterministic evidence
Phase 3 collects. Phase 3 itself makes no AI/LLM call anywhere -- its
"dominant signal" is a deterministic event-type frequency heuristic, not a
causal claim, and must not be confused with the AI-driven root-cause
reasoning described here.

## 5. Where AI is deliberately avoided

A reasoning model is never used for financial arithmetic, anomaly thresholds, policy
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
Anomaly/   AI-driven  Financial
Stats      reasoning  Model
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
built on. Phase 2 adds the `financial_events` table and the ingestion/
retrieval API that feeds the Event Engine. Phase 3 adds a deterministic
FIND rule (a concerning-event count threshold within a rolling window), a
deterministic "dominant signal" frequency heuristic, and a currency-safe
impact calculation, persisted as `investigations` -- this is rule-based
detection, not the AI-driven root-cause reasoning shown in the
architecture diagram above; that remains a later, unimplemented phase.

## 7. Technology stack

- Frontend: Next.js, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, Pydantic
- Database: PostgreSQL (local Docker for development; Neon later)
- Cache/queue: Redis (local Docker for development; managed Redis later)
- AI: a hosted reasoning model (not yet integrated)
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
| 2 | Event Engine | Financial event ingestion | ✅ COMPLETE |
| 3 | Incident Investigation | FIND + dominant-signal heuristic + impact | ✅ COMPLETE |
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

### Phase 2 — Event Engine (Financial Event Ingestion)

Goal: the deterministic domain layer that later phases (FIND, Investigation,
Simulation, ...) read from -- merchants and financial events, with a
controlled vocabulary, idempotent ingestion, merchant-existence enforcement,
retrieval/filtering, and an append-only audit trail. Per the project's
vertical-slice development principle, this phase also adds the minimum
functional frontend surface needed to exercise it end to end -- not the
final Product UI, which remains Phase 11. Still no anomaly detection, AI,
simulation, or Razorpay integration.

Delivered:
- `financial_events` table (Alembic `0002`), FK to `merchants`, unique
  `(source, external_reference)` for idempotency
- `POST/GET /v1/merchants`, `GET /v1/merchants/{id}`;
  `POST/GET /v1/events`, `GET /v1/events/{id}` (all API-key protected)
- Domain layer (`app/domain/`) separate from routers and schemas;
  event-type vocabulary validated in code, not a Postgres enum
- Every successful ingestion writes an `audit_log` row
- `apps/web/merchants`, `apps/web/events`, `apps/web/events/[id]`: minimal
  functional UI (create/list/filter/detail, loading/empty/error states)
  calling the real API through server-side Next.js Route Handlers, so the
  shared API key never reaches the browser
- CORS is now environment-driven: local dev ports allowed in development,
  nothing allowed by default outside it
- `docs/verification/phase-02.md`

Verification: all 29 automated checks in `docs/verification/phase-02.md`
were executed and passed on the project owner's machine -- backend test
suite (28 passed), ruff (all checks passed), mypy (no issues in 21 source
files), both Alembic directions, live CRUD/auth/idempotency/CORS checks
against real Postgres/Redis, frontend lint and production build, and the
full manual end-to-end flow through the browser. Four real issues were
found during development and verification -- an untracked `.env.local.example`
caused by an over-broad `.gitignore` pattern, a `react-hooks/set-state-in-effect`
lint violation fixed with a proper Effect/event-handler restructuring, a
backend `.env` path-resolution bug that was the actual root cause of a
frontend 401, and one false failure correctly traced to a stale local
process rather than a code defect -- all documented in
`docs/verification/phase-02.md` rather than worked around.

Status: COMPLETE

### Phase 3 — Incident Investigation (FIND + Dominant Signal + Impact)

Goal: the smallest coherent deterministic slice of FIND -> DOMINANT SIGNAL ->
IMPACT. Given a merchant, evaluate whether a rule-based incident is
currently (or, via an explicit `as_of`, was previously) active, reconstruct
the evidence timeline, surface a deterministic "dominant signal" frequency
heuristic over that evidence, and compute a currency-safe financial impact
estimate. This is explicitly not causal root-cause reasoning (that is a
later, AI-assisted phase -- see section 4) and not SIMULATE, DECIDE, POLICY,
ACT, VERIFY, or LEARN. No AI/LLM call is made anywhere in this phase.

Delivered:
- `investigations` table (Alembic `0003`), FK to `merchants`; every
  investigation run is persisted, including runs with no incident detected,
  the same auditable-by-default principle `audit_log` already follows
- `POST/GET /v1/investigations`, `GET /v1/investigations/{id}` (API-key
  protected), request body accepts an optional deterministic `as_of` to
  investigate a past window instead of only "now"
- Deterministic domain logic (`app/domain/investigations.py`): a rolling
  60-minute window, a >=3 concerning-event count threshold
  (`payment_failed`, `settlement_delayed`, `gateway_degraded`), a
  frequency-based dominant-signal heuristic with deterministic tie-breaking,
  and a currency-safe impact breakdown that never sums across currencies
  and tracks (never drops or zeroes) events with an unknown amount
- Every investigation writes an `audit_log` row
- `apps/web/investigations`, `apps/web/investigations/[id]`: minimal
  functional UI (trigger, list, filter, detail with timeline/signal/impact)
  through the same server-side Route Handler proxy pattern as Phase 2

Verification: all automated checks passed on the project owner's machine --
Docker Compose Postgres + Redis startup, Alembic upgrade `0002` -> `0003`,
Alembic downgrade `0003` -> `0002` -> `0003`, backend test suite (44
passed), ruff (all checks passed), mypy (no issues in 25 source files),
the live backend investigation flow (merchant creation, event ingestion,
investigation trigger/list/detail, auth, 404s), frontend `tsc`/lint/build,
security/git hygiene checks, and Docker Compose teardown. The manual
browser end-to-end walkthrough also passed, confirming: `/investigations`
loads; merchant selection and filtering work; a no-incident investigation
(no concerning events) is reported correctly; 3 concerning `payment_failed`
events for a merchant trigger a detected incident; the 60-minute detection
window is respected; the dominant signal displays correctly and is
explicitly labeled a heuristic, not a causal finding; currency-safe impact
is correct (100 INR + 75 INR + 50 INR = 225 INR); unknown-amount events are
handled correctly; the evidence timeline displays in chronological order
with working links to each event; and investigation detail/persistence
works.

Status: COMPLETE

## 13. Phase completion status

Phases 1, 2, and 3 are COMPLETE (implemented, verified, documented). No
later phase has any implementation yet.

## 14. Verification results

See `docs/verification/phase-01.md` and `docs/verification/phase-02.md`
for the full checklists, exact commands, and the issues found and fixed
during Phase 1 and Phase 2 verification. Phase 3's results are summarized
directly below, since no separate `docs/verification/phase-03.md` exists.

Phase 1 summary: 9/9 backend tests passed, ruff clean, mypy clean, both
Alembic directions verified, live DB/Redis health and API-key auth checks
all passed, full frontend build succeeded.

Phase 2 summary: 28/28 backend tests passed, ruff clean, mypy clean, both
Alembic directions verified, live merchant/event CRUD, auth, idempotency,
and CORS checks all passed against real Postgres/Redis, frontend lint and
production build both succeeded, full manual end-to-end flow confirmed
through the browser.

Phase 3 summary: 44/44 backend tests passed, ruff clean, mypy clean (25
source files), both Alembic directions verified, the live backend
investigation flow (merchant/event/investigation creation, detection,
dominant signal, impact, auth, 404s) all passed, frontend lint and
production build both succeeded, security/git hygiene checks passed, and
the manual browser end-to-end walkthrough also passed (detection, the
dominant-signal display labeled as a heuristic rather than a cause,
currency-safe impact, unknown-amount handling, evidence timeline ordering
and links, and investigation persistence all confirmed through the
browser).

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
cp .env.local.example .env.local   # set API_KEY to match the backend's
npm run dev
```

Then visit `http://localhost:3000` for backend health,
`http://localhost:3000/merchants` to create/list merchants,
`http://localhost:3000/events` to ingest and inspect financial events, and
`http://localhost:3000/investigations` to run and inspect incident
investigations.

Or run `bash scripts/verify-phase-1.sh` / `bash scripts/verify-phase-2.sh` /
`bash scripts/verify-phase-3.sh` to do all of the above plus each phase's
full verification suite in one pass.

## 16. Environment variables

See `.env.example` for the complete list and comments. `API_KEY` is required
by the backend at startup; `DATABASE_URL` and `REDIS_URL` default to the
local docker-compose services. `CORS_ALLOWED_ORIGINS` is only read outside
development (in development, `localhost:3000`/`:3001` are always allowed).
Razorpay and Anthropic keys are reserved for later phases and are optional
until then. `.env` is never committed.

The frontend reads two kinds of variables from `apps/web/.env.local`
(see `apps/web/.env.local.example`): `NEXT_PUBLIC_API_BASE_URL`, used
client-side only by the public `/health` page, and `API_BASE_URL`/`API_KEY`,
read only by server-side Next.js Route Handlers so the shared API key never
reaches the browser. `.env.local` is never committed.

## 17. Testing

Backend: `pytest` (unit tests for config/auth, integration tests for
`/health` against real and simulated-failure Postgres/Redis, for the
merchant/event API -- creation, listing, filtering, 404s, auth, invalid
input, and idempotent replay -- and for the investigation API -- detection
threshold, window boundaries, non-concerning event types, the dominant-
signal heuristic and its tie-breaking, currency-safe impact calculation,
unknown-amount tracking, evidence ordering, `as_of` handling, persistence
even without an incident, filtering, auth, and 404s). Frontend:
`npx tsc --noEmit`, `npm run lint`, `npm run build`.

## 18. Known limitations

- FIND detection is a fixed, code-level rule (>=3 concerning events in a
  rolling 60-minute window) — not statistical/adaptive anomaly detection,
  and not configurable via the API. The "dominant signal" is a frequency
  heuristic, explicitly not causal root-cause reasoning. ROOT CAUSE
  (causal), SIMULATE, DECIDE, POLICY, ACT, VERIFY, and LEARN are all future
  phases.
- Investigations are triggered only on demand via the API; there is no
  background job or automatic re-evaluation on event ingestion.
- The API-key auth model is intentionally minimal (single shared key); it is
  not a substitute for real multi-tenant auth if that becomes necessary.
- The event-type vocabulary is a fixed set in code, duplicated as a constant
  on the frontend rather than served from an endpoint; fine at this scale.
- Phases 1-3's automated verification (installs, tests, docker compose,
  builds) were authored and written from an environment without
  package-registry or Docker access, and were executed by the project owner
  locally — see `docs/verification/phase-01.md` and
  `docs/verification/phase-02.md` for Phase 1 and Phase 2; Phase 3's
  results are summarized in sections 12 and 14 above rather than a
  separate file, since `docs/verification/phase-03.md` was never created.

## 19. Future architecture

See the approved Phase 0 architecture review (development conversation) for
the full target architecture, database schema, evaluation design, and
Razorpay integration plan across all 14 phases.
