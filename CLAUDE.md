# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## Project summary

NetOps Platform is a university graduation project (4-person team, two semesters): a
centralized network management, monitoring and fault-diagnosis platform for Cisco
IOS/IOS-XE campus networks. Stack decisions and their reasons are in
[docs/adr/0001-technology-stack.md](docs/adr/0001-technology-stack.md).

Current state: repository scaffolding only (health endpoint, Celery ping task, initial
migration that enables TimescaleDB, a health status page). Feature modules are empty.

## Architecture

```
browser ──► web (nginx: static React app, proxies /api and /ws)
              └─► api (FastAPI, uvicorn) ──► db (PostgreSQL 16 + TimescaleDB)
                                         └─► redis (cache, pub/sub)
            scheduler (Celery beat) ──► redis (broker) ──► worker (Celery) ──► db / devices
```

`api`, `worker` and `scheduler` run from the same backend image with different commands.

## Module map

| Module | Scope | Code location |
| --- | --- | --- |
| M1 | Discovery & topology (seed/subnet scans, CDP/LLDP, topology graph) | `backend/src/netops/discovery/` |
| M2 | Inventory (facts, interfaces, VLANs, ARP/MAC, routes, HSRP, STP; device detail) | `backend/src/netops/inventory/` |
| M3 | Monitoring & alarms (SNMP/SSH polling, time-series metrics, thresholds) | `backend/src/netops/collectors/` |
| M4 | Config management (backup, versioning, diff, compliance) | `backend/src/netops/configmgmt/` |
| M5 | Central configuration (templated changes, dry-run, approval, rollback) | `backend/src/netops/configmgmt/` |
| M6 | Fault diagnosis (alarm/topology/change correlation, root-cause hints) | `backend/src/netops/diagnosis/` |
| M7 | Security (authentication, RBAC, credential vault, audit log) | not created yet |

Shared backend packages: `api/` (routers), `core/` (settings, logging, Redis client),
`db/` (SQLAlchemy base, sessions, Alembic migrations), `workers/` (Celery app and tasks).

## Repository layout

- `backend/`: Python 3.12 package `netops` (src layout), managed with uv; tests in `backend/tests/`
- `frontend/`: Vite + React + TypeScript (strict)
- `deploy/`: `docker-compose.yml`, nginx config, `.env.example`
- `docs/adr/`: architecture decision records
- `lab/`: lab topologies and captured device fixtures (placeholder)

## Commands

Run from the repo root unless noted.

```bash
make install    # uv sync + npm ci + pre-commit install
make up         # build, run migrations (one-shot `migrate` service), start the stack (UI on :8080)
make migrate    # alembic upgrade head via the `migrate` service, without restarting anything
make logs       # follow logs
make down       # stop (keeps the db volume)
make test       # backend pytest
make lint       # ruff, ruff format --check, mypy --strict, eslint, prettier, tsc
make format     # auto-fix formatting
```

Backend only (in `backend/`): `uv run pytest`, `uv run ruff check .`, `uv run mypy`,
`uv run alembic revision --autogenerate -m "..."` (needs a reachable database; see
`backend/.env.example`). Frontend only (in `frontend/`): `npm run dev`, `npm run lint`,
`npm run build`.

## Conventions

- Code, comments, docstrings, commit messages, issues and docs are written in English.
- Python: type hints everywhere (mypy strict must pass), ruff for lint and format, async
  for I/O in the API, `logging.getLogger(__name__)` with structured fields via `extra={...}`
  and never `print`.
- All configuration comes from environment variables via `netops.core.settings.Settings`;
  add new settings there with safe defaults (no default for secrets) and document them in
  the relevant `.env.example`.
- Schema changes only through Alembic migrations; never edit a migration that has been merged.
- Long-running or device-facing work runs in Celery tasks, never in API request handlers.
  Tasks must be idempotent.
- Frontend: TypeScript strict, no `any`; API calls live in `frontend/src/api/`.
- Commits: imperative mood, short subject line (≤ 72 chars), e.g. `Add SNMP interface poller`;
  one logical change per commit. Record significant decisions as a new ADR in `docs/adr/`.

## Hard rules

- **Never commit credentials**: no passwords, SNMP communities, API keys, private keys or
  real device configurations with secrets. Only `*.env.example` files with placeholders are
  committed; `.env` files are git-ignored. pre-commit runs gitleaks and detect-private-key.
- **Tests must never connect to, or push configuration to, real devices** (or to any real
  database or Redis). Use mocks and captured fixtures from `lab/fixtures/`. pytest runs
  with `--disable-socket` (pytest-socket), so any network access in a test fails.
