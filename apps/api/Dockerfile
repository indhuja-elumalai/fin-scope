# FIN-SCOPE API image (FastAPI + Uvicorn).
#
# Build from the repo root:
#   docker build -t fin-scope-api apps/api
#
# On start it applies database migrations (`alembic upgrade head`) and then
# serves the API on $PORT (Render sets this; defaults to 8000 locally).

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# app/config.py resolves an optional .env three levels above app/, so the
# code lives at the same depth it has in the repository.
WORKDIR /srv/fin-scope/apps/api

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 finscope \
    && chown -R finscope /srv/fin-scope
USER finscope

ENV PORT=8000
EXPOSE 8000

CMD ["docker-entrypoint.sh"]
