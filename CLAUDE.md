# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## Project summary

NetOps Platform is a university graduation project (4-person team, two semesters): a
centralized network management, monitoring and fault-diagnosis platform for Cisco
IOS/IOS-XE campus networks. The design reference document is the project proposal,
[docs/proposal/proposal-v2.pdf](docs/proposal/proposal-v2.pdf) (Turkish): requirements
(section 5), architecture and data model (section 6), module designs (section 7). Stack
decisions and their reasons are in
[docs/adr/0001-technology-stack.md](docs/adr/0001-technology-stack.md).

Current state: scaffolding, the shared data model, the v1 API contract, encrypted
credential profiles, the read-only SSH layer, parsers for 16 IOS/IOS-XE show commands, the
M2 collectors (`collect_device`), M1 discovery (BFS over CDP/LLDP, links, roles;
`netops.discover`), the device/discovery/job endpoints, the `netops` operator CLI and the
fake lab. Other endpoints still answer 501. No topology endpoints, SNMP polling, config
management or UI screens yet.

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
| M1 | Discovery & topology (seed/subnet scans, CDP/LLDP, topology graph) | `backend/src/netops/discovery/` (engine, links, roles; [ADR-0005](docs/adr/0005-discovery.md)) |
| M2 | Inventory (facts, interfaces, VLANs, ARP/MAC, routes, HSRP, STP; device detail) | `backend/src/netops/inventory/` (collectors, `collect_device` task) |
| M3 | Monitoring & alarms (SNMP/SSH polling, time-series metrics, thresholds) | `backend/src/netops/collectors/` |
| M4 | Config management (backup, versioning, diff, compliance) | `backend/src/netops/configmgmt/` |
| M5 | Central configuration (templated changes, dry-run, approval, rollback) | `backend/src/netops/configmgmt/` |
| M6 | Fault diagnosis (alarm/topology/change correlation, root-cause hints) | `backend/src/netops/diagnosis/` |
| M7 | Security (authentication, RBAC, credential vault, audit log) | credential profiles only: `db/models/credentials.py`, `core/crypto.py` |

Shared backend packages: `api/` (routers), `core/` (settings, logging, Redis client,
`ifname` interface-name normalizer, `secrets`/`crypto` for credentials), `db/` (models,
enums, sessions, state helper, Alembic migrations), `netaccess/` (read-only SSH: Nornir +
Netmiko behind the command guard), `parsing/` (TextFSM parsers -> dataclasses),
`workers/` (Celery app, tasks, job bookkeeping), `cli.py` (the `netops` operator CLI).

`backend/src/netops_fakes/` is a second top-level module of the same package: the fake lab
(topology model, state derivation, IOS output rendering, fake SSH devices, accuracy
evaluation). Tests, the fakelab containers and `tools/eval/` use it; `netops` must never
import it.

## Data model

All modules share one schema: [docs/data-model.md](docs/data-model.md) (tables and ER
diagrams) and [ADR-0002](docs/adr/0002-data-model.md) (principles). In short:

- Entities (`devices`, `interfaces`, `links`, ...) have UUID ids and are updated in place.
- Observations (`mac_entries`, `interface_snapshots`, ...) are append-only TimescaleDB
  hypertables written by one `collection_runs` row; they subclass
  `netops.db.models.Observation` and set `collected_at = run.started_at` (enforced by a
  composite foreign key). Nothing may reference a hypertable.
- State of device D for kind K at time T = latest successful run of K for D with
  `started_at <= T`: use `netops.db.state` (`run_at`, `runs_at`, `state_at`), never ad-hoc
  "latest row" queries.
- Match interfaces on `name_normalized` from `netops.core.ifname.normalize`.
- Retention periods and chunk size live only in `netops/db/timescale.py`.

## API

- Contract: `docs/api/openapi.json`, generated from the routers in `netops/api/v1/` and the
  Pydantic schemas in `netops/api/schemas/`. Conventions: [ADR-0003](docs/adr/0003-api-conventions.md)
  (`/api/v1`, problem+json errors, `{items,total,limit,offset}` lists, 202 + jobs, `at` for
  time travel, enums reused from `netops.db.enums`, bearer auth declared on every endpoint
  except health and login). WebSocket: `docs/api/websocket.md`.
- Unimplemented endpoints raise `not_implemented()` (501 problem). When implementing one,
  keep the contract (any contract change is reviewed as a diff of `openapi.json`), add it
  to `IMPLEMENTED_OPERATIONS` in `tests/test_api_contract.py` and test it against the
  database in `tests/integration/test_api.py`.
- Every schema needs a realistic example from `netops/api/schemas/examples.py`
  (private/documentation addresses only).
- After any change under `netops/api/`, run `make openapi` and commit `docs/api/openapi.json`
  and `frontend/src/api/schema.d.ts`; never edit them by hand.
- Frontend code calls the API only through the typed client in `frontend/src/api/client.ts`.

## Device access and credentials (ADR-0004)

- Talk to devices only through `netops.netaccess.run_show`; every command passes the
  read-only guard (`show ...`, `terminal length 0`, `terminal width N`). There is no
  config path; M5 adds a separate one. Never call Netmiko or Nornir directly elsewhere.
- Collectors live in `netops/inventory/collectors.py` (commands per kind, required ones,
  persist function); storage goes through `netops/inventory/persistence.py`, which also
  replays recorded output (`ingest_raw`) for tests.
- Parsers (`netops/parsing`) return dataclasses with canonical interface names, MACs, IPs
  and expanded VLAN lists. Every parser has fixtures in `lab/fixtures/` (provenance in
  `lab/fixtures/README.md`) and tests in `backend/tests/test_parsing.py`.
- Secrets are `netops.core.secrets.Secret` objects; unwrap them only where they are used,
  never log them, and `redact()` error text that might contain one. Stored secrets are
  Fernet-encrypted with `CREDENTIALS_KEY` (generated into `deploy/.env` by `make up`).
- Create database engines with `netops.db.session.create_engine` (inet values as strings).
- Collectors run per device type (`collectors.kinds_for` / `commands_for`): routers skip
  switching commands, L2 switches skip routing.
- SSH sessions connect where `netops.netaccess.target` resolves the management address to
  (identity in production). Never use the resolved address for scope checks or storage.

## Discovery (ADR-0005)

- `netops.discovery.engine.run_discovery` is one BFS run (Celery task `netops.discover`):
  at most two logins per device, de-duplication by serial, placeholders (unmanaged devices
  with a `management_status`) for everything not crawled, then links and roles.
- Work started through the API creates a `jobs` row (`netops.workers.jobs`) and is enqueued
  by task name through the `get_task_queue` dependency.
- The fake lab (`lab/fakelab/topology.yaml`) must keep rendering output that our parsers
  parse into exactly what it describes (`tests/test_fakelab.py`); after editing it, run
  `make fakelab-compose`.

## Repository layout

- `backend/`: Python 3.12 package `netops` (src layout), managed with uv; tests in `backend/tests/`
- `frontend/`: Vite + React + TypeScript (strict)
- `deploy/`: `docker-compose.yml`, nginx config, `.env.example`
- `docs/adr/`: architecture decision records; `docs/data-model.md`: schema overview
- `lab/`: device output fixtures (`fixtures/`) and the fake lab (`fakelab/topology.yaml`)
- `tools/eval/`: evaluation scripts (`discovery_accuracy.py`)

## Commands

Run from the repo root unless noted.

```bash
make install    # uv sync + npm ci + pre-commit install
make env        # create deploy/.env (DB password, CREDENTIALS_KEY) or add a missing key
make up         # build, run migrations (one-shot `migrate` service), start the stack (UI on :8080)
make migrate    # alembic upgrade head via the `migrate` service, without restarting anything
make logs       # follow logs
make down       # stop (keeps the db volume)
make test       # backend unit tests (no database or network)
make test-integration  # integration tests against the compose db (needs `make up`)
make test-scale        # discover a generated 50-device campus (SCALE_DEVICES=200 for more)
make fakelab-up        # stack + fake devices; then fakelab-seed, fakelab-discover,
                       # fakelab-accuracy, fakelab-down (see lab/fakelab/README.md)
make lint       # ruff, ruff format --check, mypy --strict, eslint, prettier, tsc
make format     # auto-fix formatting
make openapi    # regenerate docs/api/openapi.json and frontend/src/api/schema.d.ts
make mock       # Prism mock server for the contract on :4010 (UI: cd frontend && npm run dev:mock)
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
  Generate with autogenerate, then review: create shared enum types explicitly, add
  `create_hypertable` / `add_retention_policy` for new hypertables, keep downgrade working.
  The integration tests fail if models and migrations drift apart.
- Every index gets a short comment saying which query it serves.
- Long-running or device-facing work runs in Celery tasks, never in API request handlers.
  Tasks must be idempotent.
- Frontend: TypeScript strict, no `any`; API calls live in `frontend/src/api/`.
- Commits: imperative mood, short subject line (≤ 72 chars), e.g. `Add SNMP interface poller`;
  one logical change per commit. Record significant decisions as a new ADR in `docs/adr/`.

## Never commit

The repository is public. Never commit (not in a branch, fixture, screenshot or temporary
commit): **real device configurations**; **the university's or any institution's IP
addressing plan** (subnets, VLAN plans, management addresses, revealing hostnames), even
though it uses private addresses; **pilot data** collected from the university network;
**credentials** (passwords, enable secrets, SNMP communities/keys, tokens, private keys,
`.env` files). Lab topologies and fixtures use made-up addressing from documentation or
private ranges only, e.g. `10.0.0.0/8`, `192.0.2.0/24` (also `198.51.100.0/24`,
`203.0.113.0/24`, `2001:db8::/32`), with made-up hostnames, MACs and serials.

## Hard rules

- **Never commit credentials**: no passwords, SNMP communities, API keys, private keys or
  real device configurations with secrets. Only `*.env.example` files with placeholders are
  committed; `.env` files are git-ignored. pre-commit runs gitleaks and detect-private-key.
- **Never weaken the read-only guard** or add a way to send configuration outside M5's
  (future) audited write path.
- **Tests must never connect to, or push configuration to, real devices.** Use mocks and
  captured fixtures from `lab/fixtures/`. pytest runs with `--disable-socket`
  (pytest-socket), so unit tests cannot open any network connection. Only tests marked
  `@pytest.mark.integration` may connect, and only to 127.0.0.1 / ::1 (the compose
  database, in a separate `*_test` database that they recreate, and the fake SSH devices
  from `netops_fakes`, which listen on 127.0.0.1).
