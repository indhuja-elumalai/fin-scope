# Phase 1 Verification — Foundation

## Phase

1 — Foundation

## Objective

Establish a working, professionally structured project skeleton: repo
layout, local infra, backend/frontend skeletons wired together,
config-driven secrets, API-key auth, and no business logic.

## Delivered functionality

- `apps/api`: FastAPI app (`app/main.py`), pydantic-settings config
  (`app/config.py`, fails fast on missing `DATABASE_URL`/`REDIS_URL`/`API_KEY`),
  SQLAlchemy session management (`app/db.py`), Redis client
  (`app/redis_client.py`), API-key auth dependency (`app/auth.py`),
  `GET /health` (unauthenticated, checks DB + Redis), `GET /v1/ping`
  (API-key protected)
- `merchants` and `audit_log` SQLAlchemy models + Alembic migration `0001`
- `apps/web`: Next.js app (TypeScript, Tailwind, ESLint) with a page that
  fetches and displays live `/health` status
- `infra/docker-compose.yml`: Postgres 16 + Redis 7
- `apps/api/tests`: `test_config.py`, `test_auth.py`, `test_health.py` (9 tests)
- Ruff + mypy configuration (`apps/api/pyproject.toml`)
- `scripts/verify-phase-1.sh`: the full verification suite as a single
  runnable script

## Environment note

This implementation was written from a session whose tool-execution shells
(a cloud workspace and a bridge VM that mounts this repository) have no
access to PyPI, the npm registry, or Docker over the network. Every file was
written and code-reviewed there, but all automated verification below was
executed by the project owner locally (macOS, Python 3.13.7, Node v25.6.1,
Docker 28.4.0) and the results below are transcribed from that real
execution — nothing here is marked passed without having actually run.

## Automated verification (final results)

| # | Check | Command | Status |
|---|-------|---------|--------|
| 1 | Backend dependency install | `pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt` (in `.venv`) | ✅ PASS |
| 2 | Docker Compose Postgres + Redis startup | `docker compose -f infra/docker-compose.yml up -d` | ✅ PASS |
| 3 | Alembic upgrade | `alembic upgrade head` | ✅ PASS |
| 4 | Alembic downgrade | `alembic downgrade base` (then re-upgraded) | ✅ PASS |
| 5 | Backend test suite | `pytest -v` | ✅ PASS -- **9 passed** |
| 6 | Lint | `ruff check .` | ✅ PASS -- **All checks passed!** |
| 7 | Type check | `mypy app` | ✅ PASS -- **Success: no issues found in 12 source files** |
| 8 | `GET /health`, DB + Redis up | `curl -i localhost:8000/health` | ✅ PASS -- `200`, `{"status":"ok","checks":{"database":{"status":"ok"},"redis":{"status":"ok"}}}` |
| 9 | `GET /health`, DB + Redis stopped | `curl -i localhost:8000/health` | ✅ PASS -- `503`, per-service error detail for both |
| 10 | `GET /v1/ping`, no key | `curl -i localhost:8000/v1/ping` | ✅ PASS -- `401` |
| 11 | `GET /v1/ping`, wrong key | `curl -i -H "X-API-Key: wrong-key" ...` | ✅ PASS -- `401` |
| 12 | `GET /v1/ping`, correct key | `curl -i -H "X-API-Key: ..." ...` | ✅ PASS -- `200`, `{"status":"ok"}` |
| 13 | Frontend type check | `npx tsc --noEmit` | ✅ PASS |
| 14 | Frontend lint | `npm run lint` | ✅ PASS |
| 15 | Frontend production build | `npm run build` | ✅ PASS -- Next.js 16.3.4, compiled successfully |
| 16 | `.env` not tracked by git | `git ls-files \| grep '^\.env$'` | ✅ PASS |
| 17 | `.venv/` not tracked by git | `git ls-files \| grep '^\.venv/'` | ✅ PASS |
| 18 | `node_modules/` not tracked by git | `git ls-files \| grep 'node_modules/'` | ✅ PASS |

## Issues found during verification, and their fixes

Two real issues surfaced during verification. Both are recorded here rather
than quietly fixed, per the project's verification policy.

### 1. Test-isolation bug: `test_ping_accepts_valid_api_key` failed with 401

**Symptom:** the test sent `X-API-Key: test-api-key` and asserted `200`, but
received `401`.

**Root cause:** `tests/conftest.py` set `API_KEY` via
`os.environ.setdefault("API_KEY", "test-api-key")`. `setdefault` only
applies when the variable isn't already set. When `API_KEY` was exported in
the shell for an unrelated reason (running the live server manually with a
different key value), that shell value silently won, so the running app's
real `API_KEY` no longer matched the literal `"test-api-key"` the test sent.
The 401 was the *correct* response for that mismatch -- the bug was that the
test suite's expected key wasn't pinned independently of the ambient shell.

**Fix:** `tests/conftest.py` now force-sets `API_KEY` (`os.environ["API_KEY"] = TEST_API_KEY`,
not `setdefault`) from a single named constant, and exposes it via an
`api_key` fixture that `test_auth.py` uses instead of a duplicated literal.
`DATABASE_URL`/`REDIS_URL` correctly remain `setdefault` -- those are
legitimately allowed to vary by environment; `API_KEY` is a fixture value
the tests assert against literally and must not silently drift.

Verified fixed by re-running `pytest tests/test_auth.py tests/test_config.py -v`
with `API_KEY` deliberately exported to a different value in the shell first
(reproducing the exact original failure condition) -- all passed.

### 2. Transient Docker readiness race: `/health` returned 503 under pytest despite containers being "up"

**Symptom:** `test_health_ok_when_db_and_redis_available` returned `503`
even though `docker compose ps` showed both containers running.

**Investigation:** direct `psycopg`/`redis` connectivity checks (bypassing
the app), inspection of the app's cached engine URL, and the exact `/health`
error body were all reviewed. `conftest.py` was confirmed not to construct
or override settings independently. The containers were running, but
"running" (`Up`) is not the same as "healthy" -- `docker-compose.yml`
defines `pg_isready`/`redis-cli ping` healthchecks specifically because a
container can accept the TCP connection before Postgres/Redis inside it is
actually ready to serve queries. The verification script's fixed `sleep 5`
after `docker compose up -d` was not reliably long enough to cover that
window.

**Fix:** `scripts/verify-phase-1.sh` no longer sleeps a fixed duration; it
polls `docker compose ps` for both services to report `healthy` (up to 30
seconds) before proceeding. This is a process fix, not an application code
change -- nothing in `app/`, `alembic/`, or the Docker Compose service
definitions themselves was altered for this issue.

## Failure / edge-case tests

Covered by `test_health.py` (`test_health_reports_database_failure`,
`test_health_reports_redis_failure` -- both point the health check at a
deliberately unreachable host rather than depending on the real services
being stopped mid-run) and `test_auth.py` (missing key, wrong key). All
executed as part of the 9-test pytest run above.

## Engineering review

- Architecture: matches the approved Phase 0 layered design -- no business
  logic introduced ahead of its phase.
- AI boundaries: no AI code exists in Phase 1; nothing to review.
- Determinism: `/health` and `/v1/ping` are pure deterministic checks; no
  randomness or external-model dependency.
- Security: API key required on `/v1/ping`; `/health` intentionally public;
  secrets only ever read from environment variables; `.env`/`.venv`/
  `node_modules` confirmed excluded from git (checks 16-18 above).
- Idempotency: not yet applicable -- no actions exist in Phase 1.
- Observability: `/health` reports per-dependency status, not a bare
  boolean, so a real failure is diagnosable from the response body alone --
  this is exactly what made diagnosing issue #2 above possible.
- Scope: no functionality beyond the 15 items in the approved Phase 1 scope
  was introduced. The one-off `diagnose-health.sh` script used during
  investigation was excluded from git rather than committed, since it was
  never part of that scope.

## Manual verification

- [x] Backend starts and `GET /health` returns healthy with Postgres+Redis up
- [x] `GET /v1/ping` without a key is rejected
- [x] `alembic upgrade head` then `alembic downgrade base` both run cleanly
- [x] Frontend build succeeds and integrates with the live backend health check
- [x] README accurately describes only what exists now

Confirmed by the project owner.

## Known limitations

See README section 18.

## Final result

**PASS.** All 18 automated checks above executed and passed for real. Two
issues were found and fixed during verification (documented above), not
hidden or worked around by weakening a test or assertion.

## Commit hash

Recorded after commit (see Phase 1 Completion Summary).
