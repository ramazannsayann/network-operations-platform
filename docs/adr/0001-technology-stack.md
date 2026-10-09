# ADR-0001: Technology stack and repository layout

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** project team (4 members)

## Context

We are building a centralized platform to manage, monitor and diagnose faults in Cisco
IOS/IOS-XE campus networks, as a two-semester graduation project. The platform needs to:

- talk to network devices over SSH (CLI) and SNMPv3, and receive their syslog messages
  and SNMP traps (discovery, inventory, monitoring, configuration backup and push).
  Model-driven management (NETCONF/RESTCONF) and streaming telemetry are out of scope;
  the proposal lists them as future work (section 15);
- run a lot of work on a schedule and in the background (polling hundreds of interfaces
  every few minutes, long configuration jobs), without blocking the web API;
- store two very different kinds of data: relational data (devices, interfaces, topology
  links, configuration versions, users) and high-volume time-series data (interface
  counters, CPU/memory, alarm history);
- show live state in a web UI (dashboards, alarms, topology);
- be developed by four people with mixed experience, demonstrated on a single machine or
  a lab VM, and be maintainable after handover.

Constraints: free/open tooling only, one shared repository, a reproducible environment
that runs the same on macOS, Windows (WSL 2) and Linux, and no cloud dependencies.

## Decision

| Concern | Choice |
| --- | --- |
| Backend language | Python 3.12 |
| Web framework | FastAPI (OpenAPI docs at `/api/docs`), served by uvicorn |
| Configuration | pydantic-settings, environment variables only |
| Database | PostgreSQL 16 with the TimescaleDB extension (pinned image tag) |
| Data access | SQLAlchemy 2.x async ORM/Core with the asyncpg driver; Alembic migrations |
| Background jobs | Celery workers + Celery beat scheduler, Redis 7 as broker and result backend |
| Frontend | React + TypeScript (strict) built with Vite; ESLint + Prettier |
| Edge | nginx serves the built frontend and reverse-proxies `/api` and `/ws` |
| Runtime | Docker Compose (db, redis, api, worker, scheduler, web) |
| Dependency management | uv (`uv.lock`) for Python, npm (`package-lock.json`) for the frontend |
| Quality gates | ruff (lint + format), mypy `--strict`, pytest, pre-commit, GitHub Actions |
| Repository | One monorepo: `backend/`, `frontend/`, `deploy/`, `docs/`, `lab/` |
| Logging | Structured JSON lines on stdout |

## Rationale

**Python.** The network-automation ecosystem lives in Python, including the libraries the
proposal selects (section 6.3): Nornir, NAPALM, Netmiko, TextFSM with ntc-templates for
parsing Cisco CLI output, pysnmp and ciscoconfparse. Writing the
backend in the same language as these libraries avoids a service boundary between "the
app" and "the device code", and most network-automation learning material is in Python.
3.12 is supported by all of the libraries above.

**FastAPI.** Async request handling suits an I/O-bound API that mostly waits on the
database, Redis and devices. Pydantic models give request validation and generate the
OpenAPI schema for free, which doubles as API documentation for the report and for the
frontend developers. WebSocket support covers live dashboards. Django was considered;
its admin and ORM are attractive, but its sync-first model and heavier conventions fit
less well with an async collector-heavy design.

**PostgreSQL + TimescaleDB.** One database for both relational and time-series data.
TimescaleDB hypertables, compression, retention policies and continuous aggregates give
us efficient metric storage while we keep plain SQL, joins between metrics and inventory
(e.g. "utilisation of all uplinks on access switches in building B"), transactions and a
single backup. Alternatives: InfluxDB or Prometheus next to PostgreSQL would mean two
query languages, two stores to operate and no joins; Prometheus' pull model also maps
poorly onto SNMP/SSH polling of devices we do not control. The image tag is pinned
exactly because a TimescaleDB version change needs an explicit `ALTER EXTENSION` upgrade.

**SQLAlchemy 2.x async + asyncpg + Alembic.** The de-facto standard Python ORM, with a
typed 2.0-style API that works with mypy, an async engine that matches FastAPI, and
Alembic for reviewed, versioned schema migrations. asyncpg is the fastest PostgreSQL
driver for asyncio. (The 2.1 release line keeps the 2.0 API; we use the current release.)

**Celery + beat + Redis.** Polling, discovery sweeps and configuration pushes must run
outside the request/response cycle, be retryable, be scalable by adding workers, and run
on schedules. Celery is mature and well documented, and beat covers periodic polling.
Redis is the simplest broker to run and will also serve as cache and pub/sub channel for
pushing live updates to WebSocket clients. Lighter options (RQ, Dramatiq, arq,
APScheduler inside the API) were considered; they either lack a built-in scheduler,
have smaller communities, or would couple scheduled work to the API process.

**React + TypeScript (strict) + Vite.** React has the largest ecosystem for what the UI
needs (tables, charts, topology graph rendering) and the most learning material.
TypeScript in strict mode catches API-contract mistakes at build time. Vite gives fast
dev builds with a proxy to the API. We build a single-page app; there is no need for
server-side rendering, so Next.js would add complexity without benefit.

**nginx.** One origin for UI, API and WebSockets, so no CORS configuration, cookie-based
auth (M7) stays simple, and TLS termination can be added in one place later.

**Docker Compose.** Every member gets the same PostgreSQL/TimescaleDB, Redis and Python
versions with one command, and the demo machine runs the exact same stack. Kubernetes
would be overkill for a single-host deployment.

**uv.** Fast, reproducible installs from a lockfile, and it manages the virtualenv and
Python version, which removes most "works on my machine" setup problems.

**Quality gates.** ruff replaces flake8/isort/black with one fast tool; mypy strict
on the `netops` package keeps the codebase typed from day one (much harder to add
later); pre-commit catches problems before they reach a pull request; GitHub Actions
runs the same checks plus a Docker build on every push and pull request.

**Monorepo.** With four people and one product, atomic commits across API and UI,
one CI pipeline, one issue tracker and one place for documentation outweigh the
benefits of separate repositories.

## Consequences

- Positive: one language for API, workers and device interaction; one database to back
  up and query; typed contracts end to end (pydantic → OpenAPI → TypeScript); the whole
  system starts with `make up`.
- Positive: the API and workers are separate processes from the same image, so slow
  device work can never stall the web API, and workers scale independently.
- Negative: Celery adds operational parts (broker, worker, beat) and its own learning
  curve; tasks must be idempotent and must not share in-process state with the API.
- Negative: async SQLAlchemy has sharper edges than the sync API (no lazy loading in
  async code; relationships must be loaded explicitly).
- Negative: the TimescaleDB features we plan to use (compression, continuous aggregates)
  are under the Timescale License, not an OSI licence. This is fine for an academic,
  self-hosted project but should be noted in the final report.
- Follow-ups: record the device-access design (Nornir with NAPALM/Netmiko, as chosen in
  the proposal) in M1 and the authentication approach in M7, each in its own ADR.
