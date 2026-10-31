# Convenience targets. Run from the repository root.
# The API targets expect apps/api dependencies installed (see README) and
# DATABASE_URL / REDIS_URL / API_KEY set in the environment or in .env.

.PHONY: help infra-up infra-down migrate seed-demo seed-demo-ai api web test lint

help:
	@echo "infra-up      start local Postgres + Redis (docker compose)"
	@echo "infra-down    stop them"
	@echo "migrate       alembic upgrade head"
	@echo "seed-demo     load idempotent demo data (no AI call)"
	@echo "seed-demo-ai  same, plus one real reasoning call per incident"
	@echo "api           run the API on :8000"
	@echo "web           run the web app on :3000"
	@echo "test          backend tests"
	@echo "lint          ruff + eslint"

infra-up:
	docker compose -f infra/docker-compose.yml up -d

infra-down:
	docker compose -f infra/docker-compose.yml down

migrate:
	cd apps/api && alembic upgrade head

seed-demo:
	cd apps/api && python scripts/seed_demo.py

seed-demo-ai:
	cd apps/api && python scripts/seed_demo.py --reasoning

api:
	cd apps/api && uvicorn app.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

test:
	cd apps/api && pytest -q

lint:
	cd apps/api && ruff check .
	cd apps/web && npm run lint
