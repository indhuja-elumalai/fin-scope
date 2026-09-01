# Phase 2 Verification — Event Engine (Financial Event Ingestion)

## Phase

2 — Event Engine / Core Domain

## Objective

Establish the deterministic domain layer that later phases (FIND,
Investigation, Simulation, ...) read from: merchants, financial event
ingestion with a controlled vocabulary, idempotent replay handling,
merchant-existence enforcement, retrieval/filtering, and an append-only
audit trail for every ingested event. Per the project's vertical-slice
development principle, this phase also includes the minimum functional
frontend surface needed to exercise it end to end (not the final Product
UI, which remains Phase 11) -- still no anomaly detection, AI, simulation,
or Razorpay integration.

## Delivered functionality

- `apps/api/app/models/financial_event.py`: `financial_events` table, FK
  to `merchants`, unique `(source, external_reference)` for idempotency
- `apps/api/alembic/versions/0002_financial_events.py`: migration
- `apps/api/app/domain/{merchants,events}.py`: business logic separate from
  routers -- event-type vocabulary validation, merchant-existence check,
  idempotent dedup on `(source, external_reference)`, audit-log write
- `apps/api/app/schemas/{merchant,event}.py`: Pydantic request/response
  contracts, separate from the ORM models
- `apps/api/app/routers/merchants.py`: `POST/GET /v1/merchants`,
  `GET /v1/merchants/{id}` (API-key protected)
- `apps/api/app/routers/events.py`: `POST/GET /v1/events`,
  `GET /v1/events/{id}` (API-key protected)
- `apps/api/tests/{test_merchants,test_events}.py`: 19 new tests
- `apps/web/app/merchants`, `apps/web/app/events`, `apps/web/app/events/[id]`:
  minimal functional UI -- merchant creation/listing; event ingestion,
  filterable listing, and detail inspection; loading/empty/error states
- `apps/web/app/api/{merchants,events}/**/route.ts`: Next.js Route Handlers
  that proxy to FastAPI server-side, so the shared `API_KEY` is read only
  from a server-side environment variable and never reaches the browser
- CORS is now environment-driven (`apps/api/app/config.py`,
  `apps/api/app/main.py`): both local dev ports (3000, 3001) are allowed in
  development; outside development the allowlist is empty unless
  `CORS_ALLOWED_ORIGINS` is explicitly set
- `scripts/verify-phase-2.sh`: the full verification suite as a single
  runnable script, including live CORS preflight checks

## Environment note

As in Phase 1, this implementation was written from a session whose
tool-execution shells (a cloud workspace and a bridge VM that mounts this
repository) have no Docker, no package-registry/network access, and cannot
execute this repository's own `.venv` or `node_modules` (both built for the
project owner's Mac). Every file was written and reviewed there -- syntax
was checked, ruff/mypy conventions were verified by hand, and known lint
rules (see Issue 2 below) were reasoned through from evidence -- but every
command below was executed by the project owner locally (macOS,
Python 3.13.7, Docker) and the results are transcribed from that real
execution.

## Automated verification (final results)

| # | Check | Command | Status |
|---|-------|---------|--------|
| 1 | Docker Compose Postgres + Redis startup | `docker compose -f infra/docker-compose.yml up -d` | ✅ PASS -- both healthy |
| 2 | Alembic upgrade (0001 -> 0002) | `alembic upgrade head` | ✅ PASS |
| 3 | Alembic downgrade to 0001, then back to head | `alembic downgrade 0001 && alembic upgrade head` | ✅ PASS |
| 4 | Backend test suite | `pytest -v` | ✅ PASS -- **28 passed**, 1 pre-existing third-party deprecation warning (unrelated to Phase 2 code, see Known limitations) |
| 5 | Lint | `ruff check .` | ✅ PASS -- **All checks passed!** |
| 6 | Type check | `mypy app` | ✅ PASS -- **Success: no issues found in 21 source files** |
| 7 | `POST /v1/merchants` | `curl -X POST .../v1/merchants` | ✅ PASS -- `201`, merchant created |
| 8 | `POST /v1/merchants`, no key | same, no header | ✅ PASS -- `401 Missing API key` |
| 9 | `GET /v1/merchants` | `curl .../v1/merchants` | ✅ PASS -- `200`, includes the created merchant |
| 10 | `GET /v1/merchants/{id}` | `curl .../v1/merchants/{id}` | ✅ PASS -- `200` |
| 11 | `GET /v1/merchants/{random-uuid}` | same, unknown id | ✅ PASS -- `404 Merchant not found` |
| 12 | `POST /v1/events`, unknown merchant | `curl -X POST .../v1/events` | ✅ PASS -- `404 Merchant ... not found` |
| 13 | `POST /v1/events`, invalid `event_type` | same, bad value | ✅ PASS -- `422`, vocabulary listed in error detail |
| 14 | `POST /v1/events`, valid | same, valid payload | ✅ PASS -- `201 Created` |
| 15 | `POST /v1/events`, same `(source, external_reference)` again | same body replayed | ✅ PASS -- `200 OK`, identical event id (idempotent, not a duplicate) |
| 16 | `GET /v1/events?merchant_id=...` | `curl .../v1/events?merchant_id=...` | ✅ PASS -- `200`, includes the event, correct `total` |
| 17 | `GET /v1/events/{id}` | `curl .../v1/events/{id}` | ✅ PASS -- `200` |
| 18 | `GET /v1/events/{random-uuid}` | same, unknown id | ✅ PASS -- `404 Event not found` |
| 19 | `GET /v1/events`, no key | no header | ✅ PASS -- `401 Missing API key` |
| 20 | CORS preflight, origin `http://localhost:3000` | `curl -X OPTIONS ...` | ✅ PASS -- `200`, origin echoed back |
| 21 | CORS preflight, origin `http://localhost:3001` | same | ✅ PASS -- `200`, origin echoed back |
| 22 | CORS preflight, unrelated origin | same, disallowed origin | ✅ PASS -- `400 Disallowed CORS origin`, not echoed |
| 23 | Frontend lint | `npm run lint` | ✅ PASS -- clean |
| 24 | Frontend production build | `npm run build` | ✅ PASS -- Next.js 16.3.4, compiled successfully, all 9 routes built |
| 25 | Frontend <-> backend end-to-end (manual) | see Manual verification | ✅ PASS |
| 26 | `.env` not tracked by git | `git ls-files \| grep '^\.env$'` | ✅ PASS |
| 27 | `apps/web/.env.local` not tracked by git | `git ls-files \| grep '^apps/web/\.env\.local$'` | ✅ PASS |
| 28 | `.venv/` not tracked by git | `git ls-files \| grep '^\.venv/'` | ✅ PASS |
| 29 | `node_modules/` not tracked by git | `git ls-files \| grep 'node_modules/'` | ✅ PASS |

## Issues found during verification, and their fixes

Four real issues surfaced during Phase 2 development and verification. Each
is recorded here rather than quietly patched, per the project's
verification policy.

### 1. `apps/web/.env.local.example` was never actually tracked by git

**Symptom:** found during a pre-implementation diff review, not a test
failure. `git ls-files` did not include `apps/web/.env.local.example`,
despite the README instructing `cp .env.local.example .env.local` as part
of local setup since Phase 1.

**Root cause:** `apps/web/.gitignore` (a create-next-app default) contains
a broad `.env*` pattern, which matched the example file too -- a fresh
clone was silently missing the file the README told you to copy.

**Fix:** added `!.env.local.example` to `apps/web/.gitignore` to explicitly
un-ignore that one tracked file, alongside the equivalent root-level
`!.env.example` pattern that already existed.

### 2. `react-hooks/set-state-in-effect` ESLint errors (3) in the frontend

**Symptom:** `npm run lint` reported 3 errors, all `react-hooks/set-state-in-effect`,
at the `loadMerchants()`/`loadEvents()` call sites inside `useEffect` in
both `apps/web/app/merchants/page.tsx` and `apps/web/app/events/page.tsx`.

**Root cause:** both pages defined their data-loading logic as
`useCallback`-memoized functions that set state, then called those
functions both from a `useEffect` and imperatively from event handlers
(to refresh the list after a create). An Effect invoking a function that
sets state for reasons the Effect itself can't see is exactly the pattern
this rule targets.

**Fix:** restructured both pages so each Effect inlines its own fetch (no
external function reference) and does nothing but fetch -> report
success/error/done, with a proper `ignore`-flag cancellation guard (a real,
separate gap fixed at the same time -- neither page previously guarded
against a stale response after unmount/re-filter, unlike the Phase 1 health
page). A `refreshIndex` counter state is each Effect's dependency for
"reload me," bumped by the event handler that causes it (a successful
create); filter changes set `loading` from their own `onChange` handler
before changing the filter state, since event handlers -- unlike Effects --
are allowed to set state synchronously.

Verified fixed by a full `npm run lint` re-run: 0 errors.

### 3. `GET /api/merchants` returning 401 from the frontend despite matching keys

**Symptom:** the Next.js proxy route returned 401 even though the API key
in `apps/web/.env.local` and the backend's `.env` were confirmed identical
(compared by hash, without exposing either value).

**Root cause:** `apps/api/app/config.py` had `env_file=".env"`, a bare
relative path. pydantic-settings resolves a relative `env_file` against the
process's working directory at startup, not the file's own location. The
documented local-setup steps (`cd apps/api` before running `uvicorn`) put
the working directory at `apps/api/`, where a `.env` file has never
existed -- only the repo-root one does. A missing `env_file` is not an
error in pydantic-settings; it's silently skipped, and `Settings()` falls
through to whatever happens to already be exported in that shell. A stale
`API_KEY` from an earlier session was what the running server was actually
using.

**Fix:** `env_file` is now resolved to an absolute path anchored to
`config.py`'s own location (`Path(__file__).resolve().parents[3] / ".env"`),
independent of the process's working directory. Added a regression test,
`test_env_file_path_is_absolute_and_cwd_independent`.

Verified fixed by check #7-19 above, run against a fresh `uvicorn` process
started per the documented `cd apps/api` steps.

### 4. False failure in `scripts/verify-phase-2.sh`'s live-check section, caused by a stale process on port 8000 -- not a Phase 2 code defect

**Symptom:** a first run of `scripts/verify-phase-2.sh` showed nearly every
live check in section 7 returning `401 Invalid API key`, including checks
that should have been 201/200/404/422.

**Investigation:** the log line immediately preceding the checks read
`ERROR: [Errno 48] ... address already in use` -- the script's own
`uvicorn` never started; a different backend process (left running from
the manual end-to-end testing performed just before, per step 9's own
instructions) was still bound to port 8000, using a different `API_KEY`
value. The script's `curl` calls landed on that other process, not its
own. The two `307` redirects seen in that run were a downstream artifact
of `MERCHANT_ID`/`EVENT_ID` coming back empty after the first request
failed, not a separate bug. This was confirmed as environmental rather
than a code defect three ways: the CORS preflight checks in the same
section (which don't depend on any prior request) passed correctly; the
project owner's independent manual verification (below) had already
exercised the identical functionality successfully through the real
frontend; and "Invalid API key" is the correct, designed response for a
key mismatch -- the auth code was behaving exactly as intended, just for
the wrong server instance.

**Resolution:** no code was changed for this. The project owner stopped
the stray process and re-ran the script; every check in section 7 then
passed for real (see the table above), confirming the first run's failures
were not evidence of an actual defect.

## Failure / edge-case tests

Covered by `test_events.py` (`test_ingest_event_unknown_merchant`,
`test_ingest_event_invalid_event_type`, `test_ingest_event_requires_api_key`,
`test_get_event_not_found`, `test_list_events_requires_api_key`) and
`test_merchants.py` (`test_create_merchant_requires_api_key`,
`test_create_merchant_rejects_empty_name`, `test_get_merchant_not_found`,
`test_list_merchants_requires_api_key`). All executed as part of the
28-test pytest run above, and independently re-exercised live via curl in
checks 8, 11, 12, 13, 19, 22.

## Engineering review

- Architecture: matches the approved layered design -- domain logic
  (`app/domain/`) is separate from routers and schemas; no FIND/AI/
  simulation/execution logic was introduced ahead of its phase.
- AI boundaries: no AI code exists in Phase 2; nothing to review.
- Determinism: event-type validation, idempotency, and merchant-existence
  checks are all pure deterministic logic; no randomness or external-model
  dependency.
- Security: `/v1/merchants` and `/v1/events` require the API key; the
  frontend never holds that key client-side -- Next.js Route Handlers proxy
  server-side, reading `API_KEY` from a server-only environment variable
  (see Issue 3's fix for why that value must resolve correctly). CORS is
  environment-driven and fails closed outside development.
  `.env`/`.env.local`/`.venv`/`node_modules` confirmed excluded from git
  (checks 26-29).
- Idempotency: `(source, external_reference)` uniqueness enforced at the
  database level via a unique constraint, not just in application logic;
  verified live (check 15) and in `test_ingest_event_is_idempotent`.
- Observability: every successful ingestion writes an `audit_log` row
  (`actor="system"`, `event_type="financial_event_ingested"`) with the
  merchant, event type, source, and external reference -- confirmed present
  in Postgres during manual verification.
- Scope: no FIND/anomaly detection, AI, simulation, or Razorpay integration
  was introduced. The frontend is the minimum functional surface to
  exercise this phase (per the project's vertical-slice UI principle), not
  the final Product UI reserved for Phase 11.

## Manual verification

Performed and confirmed by the project owner:

- [x] `GET /health` -- database ok, redis ok
- [x] `GET /v1/merchants` without an API key -- `401`
- [x] `GET /v1/merchants` with `X-API-Key` -- `200`
- [x] Created a merchant successfully through the frontend (`/merchants`)
- [x] `POST /v1/events` -- `201 Created`
- [x] `GET /v1/events?merchant_id=...` -- event retrieved
- [x] Replayed an identical event -- `200 OK`, same event id
- [x] Postgres `audit_log` confirmed a `financial_event_ingested` row

## Known limitations

- No business logic beyond ingestion/retrieval exists yet -- FIND through
  LEARN are all future phases.
- The event-type vocabulary is a fixed set in code
  (`app.domain.events.KNOWN_EVENT_TYPES`), duplicated as a constant in the
  frontend rather than served from an endpoint; acceptable at this scale,
  worth revisiting if the catalog grows.
- `pytest` reports one pre-existing third-party deprecation warning
  (`StarletteDeprecationWarning: Using httpx with starlette.testclient is
  deprecated`) from the FastAPI/Starlette/httpx version combination already
  in use since Phase 1. Not introduced by, or specific to, Phase 2 changes;
  left unaddressed since fixing it would mean changing pinned dependency
  versions, which was not required by any test failure.
- As in Phase 1, this phase's automated verification was authored and
  code-reviewed from an environment without Docker or package-registry
  access, and executed by the project owner locally -- see the Environment
  note above and Issue 4 for a case where that split briefly produced a
  misleading (environmental, not code) failure.

## Final result

**PASS.** All 29 automated checks above executed and passed for real
against a correctly running server. Four issues were found during
development and verification (documented above) -- one a missed-file
gitignore bug, one a real ESLint violation with a proper architectural fix,
one a genuine backend defect (env-file path resolution) that was the actual
401 root cause, and one a false failure correctly traced to a stale process
rather than misdiagnosed as a code defect. None were hidden or worked
around by weakening a test, assertion, or lint rule.

## Commit hash

Recorded after commit (see Phase 2 Completion Summary).
