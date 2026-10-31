#!/bin/sh
# Container entrypoint: migrate, then serve.
set -e

echo "[entrypoint] applying database migrations"
alembic upgrade head

echo "[entrypoint] starting API on port ${PORT:-8000}"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips="*"
