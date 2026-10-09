# NetOps Platform

Centralized network management, monitoring and fault-diagnosis platform for Cisco
IOS/IOS-XE campus networks. Graduation project.

> Status: repository scaffolding. The stack runs end to end (UI → nginx → API → TimescaleDB
> and Redis, plus Celery workers), but no network features are implemented yet.

## Quickstart

Prerequisites: Docker with Compose v2, GNU Make, OpenSSL (for `make up` to generate a
database password). For local development also [uv](https://docs.astral.sh/uv/) and
Node.js 24 (≥ 22.12 works).

```bash
make up         # creates deploy/.env on first run, builds, migrates the database, starts all services
```

Then open:

- UI: <http://localhost:8080> (shows database and Redis status)
- API docs: <http://localhost:8080/api/docs>
- Health: `curl http://localhost:8080/api/health`
  → `{"status":"ok","version":"0.1.0","db":"ok","redis":"ok"}` (HTTP 503 if a dependency is down)

`make logs` follows the logs and `make down` stops everything (the database volume is
kept). Without Make: `cp deploy/.env.example deploy/.env`, set `POSTGRES_PASSWORD`, then
`cd deploy && docker compose up --build`.

All ports are bound to `127.0.0.1`: web `8080`, api `8000`, PostgreSQL `5433`, Redis
`6379`. Change them in `deploy/.env`.

## Development

```bash
make install    # backend venv (uv sync), frontend node_modules (npm ci), git pre-commit hooks
make lint       # ruff, mypy --strict, eslint, prettier, tsc
make test       # backend unit tests (no database, Redis or network needed)
make test-integration  # schema and query tests against the compose database (after `make up`)
```

Run parts of the stack outside Docker:

```bash
# Backend on the host, against the db and redis containers
docker compose -f deploy/docker-compose.yml up -d db redis
cp backend/.env.example backend/.env    # then copy POSTGRES_PASSWORD from deploy/.env
cd backend && uv run uvicorn netops.main:app --reload

# Frontend dev server with hot reload; proxies /api and /ws to localhost:8000
cd frontend && npm run dev
```

New migration: `cd backend && uv run alembic revision --autogenerate -m "add devices table"`.

## Repository layout

```
backend/    FastAPI app, Celery workers, Alembic migrations (Python package `netops`)
frontend/   React + TypeScript (Vite) single-page app
deploy/     docker-compose.yml, nginx config, .env.example
docs/       data model overview (data-model.md) and architecture decision records (adr/)
lab/        lab topologies and captured device fixtures (placeholder)
```

Module map, conventions and hard rules for contributors: [CLAUDE.md](CLAUDE.md).
