# NetOps Platform

Centralized network management, monitoring and fault-diagnosis platform for Cisco
IOS/IOS-XE campus networks. Graduation project.

Design reference: the project proposal,
[docs/proposal/proposal-v2.pdf](docs/proposal/proposal-v2.pdf) (in Turkish).

> Status: discovery (M1) and inventory collection (M2) work against a fake lab; the
> device, discovery and job endpoints are implemented, the UI screens and the other modules
> are not yet. The stack runs end to end (UI → nginx → API → TimescaleDB and Redis, plus
> Celery workers).

## Quickstart

Prerequisites: Docker with Compose v2, GNU Make, OpenSSL (for `make up` to generate a
database password). For local development also [uv](https://docs.astral.sh/uv/) and
Node.js 24 (≥ 22.12 works).

```bash
make up         # creates deploy/.env on first run, builds, migrates the database, starts all services
```

`deploy/.env` gets a random database password and a random `CREDENTIALS_KEY`, which encrypts
the device credentials stored in the database. Keep a copy of that key outside the database
backups ([ADR-0004](docs/adr/0004-credentials-and-device-access.md)).

Then open:

- UI: <http://localhost:8080> (shows database and Redis status)
- API docs: <http://localhost:8080/api/docs>
- Health: `curl http://localhost:8080/api/health`
  → `{"status":"ok","version":"0.1.0","db":"ok","redis":"ok"}` (HTTP 503 if a dependency is down)

`make logs` follows the logs and `make down` stops everything (the database volume is
kept). Without Make: `cp deploy/.env.example deploy/.env`, set `POSTGRES_PASSWORD`, then
`cd deploy && docker compose up --build`.

TimescaleDB telemetry is turned off (`TIMESCALEDB_TELEMETRY=off`): the platform runs inside
an institution's network and must not send data out.

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

## API contract and mock server

The REST API is defined contract-first: [docs/api/openapi.json](docs/api/openapi.json)
(browsable at <http://localhost:8080/api/docs> when the stack runs), conventions in
[ADR-0003](docs/adr/0003-api-conventions.md), live updates in
[docs/api/websocket.md](docs/api/websocket.md). Devices, discovery runs and jobs are
implemented; the other endpoints still answer `501 Not Implemented`.

After changing schemas or routers in `backend/src/netops/api/`, regenerate and commit the
document and the frontend types (CI fails if they are stale):

```bash
make openapi    # docs/api/openapi.json + frontend/src/api/schema.d.ts
```

To build UI screens before the backend implements them, run the frontend against a mock
server that answers every endpoint with the contract's example data (two terminals):

```bash
cd frontend && npm run mock       # Prism on http://127.0.0.1:4010
cd frontend && npm run dev:mock   # UI on http://localhost:5173, /api proxied to the mock
```

The mock enforces the declared security: send any `Authorization: Bearer <token>` header
(tokens are not checked yet). Other responses can be requested with a `Prefer` header,
e.g. `Prefer: code=404` or `Prefer: example=not_found` on `/api/v1/hosts/locate`.

## Fake lab and discovery

A made-up campus of fake Cisco devices ([lab/fakelab/](lab/fakelab/README.md)) runs in
containers next to the stack, so discovery can be tried without real equipment:

```bash
make fakelab-up         # the stack plus one container per fake device (10.255.0.0/24)
make fakelab-seed       # two SSH credential profiles, created with the netops CLI
make fakelab-discover   # discover from core1; prints what happened to every address
make fakelab-accuracy   # device/link precision and recall against topology.yaml
make fakelab-down       # stop everything; `make up` for the normal stack again
```

Results are in the API (`GET /api/v1/devices`, `/api/v1/discovery/runs`) and in
`docker compose -f deploy/docker-compose.yml exec api netops devices list`. The operator CLI
(`netops --help` in the api container) also adds credential profiles for a real network
(`netops credentials add NAME --username USER` prompts for the password) and starts
discovery with your own seeds and subnets. Design: [ADR-0005](docs/adr/0005-discovery.md).

## Repository layout

```
backend/    FastAPI app, Celery workers, Alembic migrations (package `netops`), fake lab (`netops_fakes`)
frontend/   React + TypeScript (Vite) single-page app
deploy/     docker-compose.yml, nginx config, .env.example
docs/       data model overview (data-model.md) and architecture decision records (adr/)
lab/        device output fixtures and the fake lab topology
tools/      evaluation scripts (discovery accuracy)
```

How we work (branches, pull requests, checks, what must never be committed):
[CONTRIBUTING.md](CONTRIBUTING.md). Module map and code conventions: [CLAUDE.md](CLAUDE.md).

## License

To be decided with the project advisor; no license file has been added yet.
