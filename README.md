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
event-ingestion layer, a deterministic FIND -> dominant-signal -> IMPACT
slice (rule-based incident detection, a frequency-based "dominant signal"
heuristic, and a currency-safe impact estimate -- not causal root-causing,
and no AI/LLM call anywhere in this slice), and, as of Phase 4, a reasoning
layer that proposes ranked, evidence-grounded hypotheses over that
deterministic evidence -- plausible explanations, never a confirmed ROOT
CAUSE. All of this is described in section 12. Causal ROOT CAUSE reasoning,
SIMULATE, DECIDE, POLICY, ACT, VERIFY, and LEARN have not started.

## 4. Why AI is used

A reasoning model is used where ambiguity and reasoning exist. As of Phase 4,
this means generating ranked, evidence-grounded hypotheses over an existing
investigation's Phase 3 evidence, interpreting that evidence, and
articulating uncertainty. Later phases will extend this to incident
summarization and proposing bounded interventions with rationale. Phase 3
itself still makes no AI/LLM call anywhere -- its "dominant signal" is a
deterministic event-type frequency heuristic, not a causal claim, and must
not be confused with the reasoning layer described here. Phase 4's
hypotheses are explicitly not causal root-cause detection either: every
hypothesis is a plausible, evidence-grounded explanation the model
proposed, ranked by how well it could ground itself in the observed
evidence, never a confirmed cause. See section 12 (Phase 4) for exactly
what is and is not claimed, the FACT/INFERENCE/UNCERTAINTY distinction the
UI preserves, and how a hypothesis's confidence (a bounded
"high"/"medium"/"low" label) differs from a calibrated statistical
probability.

## 5. Where AI is deliberately avoided

A reasoning model is never used for financial arithmetic, anomaly thresholds, policy
enforcement, authorization, idempotency, execution, or audit logging. Those
are deterministic by design, and AI has no path to directly executing a
financial action — every AI output passes through schema validation and a
deterministic policy engine before anything can be executed.

Concretely in Phase 4: the reasoning layer receives a read-only, already-
computed summary of one investigation (`app.providers.reasoning.
ReasoningContext`) -- it cannot query the database itself and cannot see
any evidence the investigation did not already record. Every hypothesis it
returns is validated before it is ever persisted or shown: a hypothesis
that cites an event not in the investigation's own evidence causes the
*entire* reasoning result to be rejected, not silently trimmed. Reasoning
failures (provider unavailable, malformed output, invalid evidence
references) are persisted as a distinct outcome and never affect, block, or
overwrite the underlying Phase 3 investigation.

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
- AI: a hosted reasoning model, integrated in Phase 4 behind a provider
  adapter (`app/providers/reasoning.py`) for investigation reasoning only
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
| 4 | Investigation Reasoning | Evidence-grounded hypotheses over Phase 3 evidence | ✅ COMPLETE |
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

### Phase 4 — Investigation Reasoning

Goal: move from "here is what happened" (Phase 3's deterministic evidence)
toward "given that evidence, what are the plausible explanations, which is
best supported, and why" -- without the reasoning layer ever becoming the
authority for a financial fact. Reasoning is a dedicated, repeatable
operation layered on top of an existing investigation, not a replacement
for one: Phase 3's FIND -> DOMINANT SIGNAL -> IMPACT stays fully
deterministic and untouched by this phase.

Delivered:
- `investigation_reasoning` table (Alembic `0004`), FK to `investigations`;
  every reasoning attempt is persisted -- success, an empty-but-valid
  result, or any failure mode -- the same auditable-by-default principle
  `investigations` already follows. Each run inserts a new row rather than
  updating one in place (evidence can change between runs); the API always
  returns the most recent row for an investigation.
- `POST /v1/investigations/{id}/reason` (runs reasoning over that
  investigation's persisted evidence and persists the result) and
  `GET /v1/investigations/{id}/reasoning` (the most recent result), both
  API-key protected, alongside the existing Phase 3 investigation routes.
- A small provider abstraction (`app/providers/reasoning.py`): the domain
  layer depends only on a `ReasoningProvider` protocol and plain
  `ReasoningContext`/`RawReasoningResult` data shapes, never a vendor SDK
  directly. The one concrete adapter (`HostedReasoningProvider`) is the
  only code in the repository that knows the shape of the underlying
  hosted reasoning API's request/response.
- Evidence grounding (`app/domain/reasoning.py`): the provider receives a
  read-only summary built solely from an investigation's own persisted
  fields (it cannot query the database itself), and every hypothesis is
  validated before it is ever persisted -- unique `hypothesis_id`s, unique
  positive `rank`s, `confidence` restricted to `high`/`medium`/`low`,
  non-empty title/explanation, at least one supporting-evidence reference,
  and every supporting/contradicting evidence reference checked against
  that investigation's own evidence event IDs. A response with even one
  reference to evidence that does not exist is rejected in its entirety --
  not trimmed down to the hypotheses that happened to be clean.
- Five distinguishable, always-persisted outcomes (`status` on
  `investigation_reasoning`): `completed`, `insufficient_evidence` (no
  incident was detected -- the provider is never even called),
  `unavailable` (provider not configured, unreachable, or timed out),
  `invalid_output` (the provider responded, but its structured output
  failed grounding/shape validation), and `no_valid_hypotheses` (a validly
  empty response -- the model itself judged the evidence too ambiguous). A
  reasoning failure never blocks, mutates, or destroys the underlying
  Phase 3 investigation.
- Confidence is a bounded, model-derived qualitative label
  (`high`/`medium`/`low`) throughout the API, storage, and UI -- never
  presented as a calibrated statistical probability.
- Every reasoning attempt writes an `audit_log` row (`actor="ai"` once a
  provider call was actually attempted, `actor="system"` for the two
  provider-independent short-circuits) recording the outcome shape only --
  never a raw prompt or raw provider response.
- `apps/web/investigations/[id]`: the detail page now shows Incident ->
  Dominant signal -> Impact -> Evidence -> Reasoning -> Hypotheses, with
  every factual section badged FACT, every hypothesis badged INFERENCE, and
  each hypothesis's `uncertainty` field badged UNCERTAINTY -- plus a "Run
  reasoning" / "Re-run reasoning" control and a distinct rendered state for
  each of the five outcomes above.
- A broader frontend visual pass alongside this phase: one deliberately-
  designed light theme (see `apps/web/app/globals.css` for why the previous
  `prefers-color-scheme` auto-switch was removed rather than properly
  dark-mode-themed -- it was the root cause of the navbar contrast bug,
  since every page's actual components used hardcoded colors that never
  read those theme variables), a fixed navbar with explicit active-route
  highlighting, and a small shared component set
  (`apps/web/components/ui.tsx`) applied consistently across
  merchants/events/investigations in place of ad hoc per-page styling.

Verification: all checks in `scripts/verify-phase-4.sh` were executed and
passed on the project owner's machine -- Docker Compose Postgres + Redis
startup, Alembic upgrade `0003` -> `0004`, Alembic downgrade `0004` ->
`0003` -> `0004`, backend test suite (63 passed, including the reasoning
suite covering success, ranking, evidence grounding -- valid and
hallucinated references, duplicate hypothesis IDs/ranks, invalid
confidence/rank, hypotheses with no supporting evidence -- empty-but-valid
results, provider-not-configured and provider-error failure modes, the
insufficient-evidence short-circuit, the safety invariant that reasoning
never mutates the investigation it read, rerun/persistence semantics, and
auth/404s), ruff (all checks passed), mypy (no issues), the live backend
`/reason`/`/reasoning` endpoint checks, frontend ESLint and production
build, security/git hygiene checks, and Docker Compose teardown. The
manual browser walkthrough also passed, confirming the investigation
detail page shows Incident -> Dominant signal -> Impact -> Evidence ->
Reasoning in order, and that a "reasoning unavailable" state (provider not
configured, and separately a real provider call that failed once real
credentials were tried) renders correctly without disturbing the
deterministic sections above it. One real issue was found during that
manual pass and fixed rather than worked around: `HostedReasoningProvider`
was including the hosted provider's raw JSON error body (which can contain
account/billing-specific text -- an insufficient-credits response was the
case that surfaced it) directly in the exception message that becomes
`InvestigationReasoning.failure_reason` and is returned by the API and
shown in the UI. The fix keeps the full diagnostic detail in a server-side
log line only; the message that propagates to the API/UI is now a generic
"HTTP {status}" description. This does not change the `unavailable` status
contract -- covered by new unit tests in
`apps/api/tests/test_reasoning_provider.py` that mock the HTTP layer
directly (standard-library `unittest.mock`, no new test dependency) since
this is the one class the rest of the reasoning test suite deliberately
never exercises.

Status: COMPLETE

## 13. Phase completion status

Phases 1, 2, 3, and 4 are COMPLETE (implemented, verified, documented). No
later phase has any implementation yet.

## 14. Verification results

See `docs/verification/phase-01.md` and `docs/verification/phase-02.md`
for the full checklists, exact commands, and the issues found and fixed
during Phase 1 and Phase 2 verification. Phase 3 and Phase 4's results are
summarized directly below, since no separate `docs/verification/phase-03.md`
or `docs/verification/phase-04.md` exists.

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

Phase 4 summary: 63/63 backend tests passed (44 from Phases 1-3 plus the
reasoning suite -- see section 12 for exactly what it covers), ruff clean,
mypy clean, both Alembic directions verified (`0003` <-> `0004`), the live
`/reason`/`/reasoning` endpoint checks all passed, frontend ESLint and
production build both succeeded, security/git hygiene checks passed, and
the manual browser walkthrough confirmed the full Incident -> Dominant
signal -> Impact -> Evidence -> Reasoning hierarchy and both the
provider-not-configured and real-provider-failure "unavailable" states.
One real issue was found and fixed rather than worked around: a hosted
provider error response's raw JSON body (which can carry account/billing-
specific text) was reaching `InvestigationReasoning.failure_reason`, and
from there the API and UI, verbatim -- see section 12 (Phase 4) for the
fix and its regression tests.

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
`bash scripts/verify-phase-3.sh` / `bash scripts/verify-phase-4.sh` to do
all of the above plus each phase's full verification suite in one pass.
Phase 4's reasoning endpoint works with no further setup -- it reports
itself as unavailable if `ANTHROPIC_API_KEY` is unset in `.env`; set it to
try reasoning against the real provider.

## 16. Environment variables

See `.env.example` for the complete list and comments. `API_KEY` is required
by the backend at startup; `DATABASE_URL` and `REDIS_URL` default to the
local docker-compose services. `CORS_ALLOWED_ORIGINS` is only read outside
development (in development, `localhost:3000`/`:3001` are always allowed).
Razorpay keys remain reserved for a later phase and are optional until
then. `ANTHROPIC_API_KEY` configures the Phase 4 reasoning provider (see
section 12) and is optional -- without it, reasoning reports itself as
unavailable rather than failing. `.env` is never committed.

The frontend reads two kinds of variables from `apps/web/.env.local`
(see `apps/web/.env.local.example`): `NEXT_PUBLIC_API_BASE_URL`, used
client-side only by the public `/health` page, and `API_BASE_URL`/`API_KEY`,
read only by server-side Next.js Route Handlers so the shared API key never
reaches the browser. `.env.local` is never committed.

## 17. Testing

Backend: `pytest` (unit tests for config/auth, integration tests for
`/health` against real and simulated-failure Postgres/Redis, for the
merchant/event API -- creation, listing, filtering, 404s, auth, invalid
input, and idempotent replay -- for the investigation API -- detection
threshold, window boundaries, non-concerning event types, the dominant-
signal heuristic and its tie-breaking, currency-safe impact calculation,
unknown-amount tracking, evidence ordering, `as_of` handling, persistence
even without an incident, filtering, auth, and 404s -- and for investigation
reasoning: ranked evidence-grounded hypotheses persisting correctly, valid
evidence references accepted, a hallucinated evidence reference rejecting
the entire response, a hypothesis with no supporting evidence rejected,
duplicate hypothesis IDs/ranks and invalid confidence/rank values rejected,
an empty-but-valid hypothesis list distinguished from a rejected one,
provider-not-configured and provider-error failure modes, the
insufficient-evidence short-circuit never calling the provider at all, a
direct check that reasoning never mutates the investigation it read, reruns
persisting as new rows rather than overwriting, and auth/404s). Every
reasoning test injects a fake provider via FastAPI's `dependency_overrides`
-- none of the suite calls the real hosted reasoning API, spends provider
credits, or requires network access. `apps/api/tests/test_reasoning_provider.py`
separately unit-tests `HostedReasoningProvider` itself (the one class the
tests above deliberately never exercise) by mocking `httpx.post` with the
standard library `unittest.mock` -- covering a malformed response body, a
timeout, and, specifically, that an upstream error response's raw text
never leaks into the exception message that becomes
`InvestigationReasoning.failure_reason`. Frontend: `npx tsc --noEmit`,
`npm run lint`, `npm run build`.

## 18. Known limitations

- FIND detection is a fixed, code-level rule (>=3 concerning events in a
  rolling 60-minute window) — not statistical/adaptive anomaly detection,
  and not configurable via the API. The "dominant signal" is a frequency
  heuristic, explicitly not causal root-cause reasoning. Phase 4 adds a
  reasoning layer that proposes plausible, evidence-grounded hypotheses
  over that evidence, but this is still not causal ROOT CAUSE detection --
  see sections 4 and 12 (Phase 4). Causal ROOT CAUSE, SIMULATE, DECIDE,
  POLICY, ACT, VERIFY, and LEARN are all future phases.
- Reasoning re-runs are append-only: each call to `POST .../reason`
  persists a new `investigation_reasoning` row rather than updating or
  deduplicating a previous one, even if the evidence has not changed.
- A hypothesis's `confidence` is a bounded, model-derived qualitative label
  (`high`/`medium`/`low`), not a calibrated statistical probability --
  nothing in this codebase computes it from historical accuracy.
- Evidence-grounding validation rejects an entire reasoning response if any
  single hypothesis cites evidence outside the investigation, rather than
  salvaging the hypotheses that were clean; this is a deliberate safety
  choice (see `app/domain/reasoning.py`), not a partial-validation gap.
- Retrying an "unavailable"/"invalid_output" reasoning result is manual --
  a person clicks "Re-run reasoning" in the UI; there is no automatic
  retry or background job.
- Investigations are triggered only on demand via the API; there is no
  background job or automatic re-evaluation on event ingestion.
- The API-key auth model is intentionally minimal (single shared key); it is
  not a substitute for real multi-tenant auth if that becomes necessary.
- The event-type vocabulary is a fixed set in code, duplicated as a constant
  on the frontend rather than served from an endpoint; fine at this scale.
- Phases 1-4's automated verification (installs, tests, docker compose,
  builds) were authored and written from an environment without
  package-registry or Docker access, and were executed by the project owner
  locally — see `docs/verification/phase-01.md` and
  `docs/verification/phase-02.md` for Phase 1 and Phase 2; Phase 3 and
  Phase 4's results are summarized in sections 12 and 14 above rather than
  a separate file, since neither `docs/verification/phase-03.md` nor
  `docs/verification/phase-04.md` was ever created. Unlike Phases 1-3,
  Phase 4's writing environment also had no access to the platform-specific
  Next.js/SWC binary `npm run build` needs -- but it did have a working
  Node install, so `npx tsc --noEmit` and `npm run lint` were actually run
  (and passed) rather than only written; see section 14 for exactly what
  was and was not executed.

## 19. Future architecture

See the approved Phase 0 architecture review (development conversation) for
the full target architecture, database schema, evaluation design, and
Razorpay integration plan across all 14 phases.
