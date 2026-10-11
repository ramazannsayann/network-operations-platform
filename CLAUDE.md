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
credential profiles, the read-only SSH layer, parsers for 17 IOS/IOS-XE show commands, the
M2 collectors (`collect_device`), M1 discovery (BFS over CDP/LLDP, links, roles;
`netops.discover`) and topology, M4 configuration backups (local Git repository,
redaction, diffs, external change detection) with a syslog receiver (the `events`
service), M7 security (users, argon2id passwords, TOTP MFA, JWT access tokens with
rotating refresh cookies, RBAC on every route, the append-only audit log), the
device/discovery/job/topology/config/event/user/credential/audit endpoints, the `netops`
operator CLI, the fake lab with its change simulator and the UI (sign-in, shell, map,
devices, discovery, config, config changes, events, profile, admin pages). Other endpoints
still answer 501. No SNMP polling, alarms, compliance, M5 push or SSO yet.

## Architecture

```
browser ──► web (nginx: static React app, proxies /api and /ws)
              └─► api (FastAPI, uvicorn) ──► db (PostgreSQL 16 + TimescaleDB)
                                         └─► redis (cache, pub/sub)
            scheduler (Celery beat) ──► redis (broker) ──► worker (Celery) ──► db / devices
devices ──syslog, UDP 514──► events (asyncio receiver) ──► db, redis (broker)
worker (read-write), api (read-only) ──► config-repo volume (local Git repository)
```

`api`, `worker`, `scheduler` and `events` run from the same backend image with different
commands.

## Module map

| Module | Scope | Code location |
| --- | --- | --- |
| M1 | Discovery & topology (seed/subnet scans, CDP/LLDP, topology graph) | `backend/src/netops/discovery/` (engine, links, roles; [ADR-0005](docs/adr/0005-discovery.md)) |
| M2 | Inventory (facts, interfaces, VLANs, ARP/MAC, routes, HSRP, STP; device detail) | `backend/src/netops/inventory/` (collectors, `collect_device` task) |
| M3 | Monitoring & alarms (SNMP/SSH polling, time-series metrics, thresholds) | `backend/src/netops/collectors/`; syslog receiver: `backend/src/netops/events/` |
| M4 | Config management (backup, versioning, diff, compliance) | `backend/src/netops/configmgmt/` (normalize, parser, redact, diff, store, backup, changes; [ADR-0007](docs/adr/0007-config-management.md)) |
| M5 | Central configuration (templated changes, dry-run, approval, rollback) | `backend/src/netops/configmgmt/` |
| M6 | Fault diagnosis (alarm/topology/change correlation, root-cause hints) | `backend/src/netops/diagnosis/` |
| M7 | Security (authentication, RBAC, credential vault, audit log) | `backend/src/netops/auth/` (passwords, tokens, totp, rbac, audit, ratelimit, service, users, credentials), `api/security.py`, `core/crypto.py` ([ADR-0008](docs/adr/0008-authentication.md)) |

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
  time travel, enums reused from `netops.db.enums`, bearer auth on every endpoint except
  health, login, MFA verification and refresh). WebSocket: `docs/api/websocket.md`.
- Every route declares exactly one permission with `**guard(Permission.X)` (see
  "Authentication and audit" below); `tests/test_rbac.py` fails for a route without one.
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

## Authentication and audit (ADR-0008)

- Permissions and the role mapping live only in `netops.auth.rbac` (`Permission`,
  `ROLE_PERMISSIONS`). A new route uses an existing permission or adds one there and to
  the role matrix in `tests/test_rbac.py`. The UI hides what a role cannot do with
  `useCan(...)` / `RequirePermission` (`frontend/src/auth/`); the API enforces it anyway.
- Actions that change something are audited with `netops.auth.audit.record` in the same
  transaction (`record_now` for failures that roll back). Details hold names, ids and
  counts, never secrets; keys naming one (password, secret, token, code, key) are refused.
  `audit_log` is append-only (database triggers); never add an UPDATE or DELETE path.
- Auth logic (login, MFA, refresh rotation, lockout) is in `netops.auth.service`; routers
  only translate it to HTTP. Every login failure returns the same 401 and message.
- There are no default accounts: the first admin comes from `netops users create-admin`.
  Never commit a usable password, TOTP secret or recovery code; tests that sign in
  generate theirs at random.
- Unit tests: the `client` fixture signs in as an admin (`principal(role)` in
  `tests/conftest.py` for other roles), `anonymous_client` sends no token. Integration tests sign in for
  real (`tests/integration/support.py`: `add_user`, `sign_in`).
- The browser keeps the access token in memory only (`frontend/src/auth/session.ts`);
  never put it in storage, a cookie or a URL.

## Configurations (ADR-0007)

- Complete configurations (secrets included) live only in the local Git repository
  (`netops.configmgmt.store`, volume `config-repo`); the database has commit, hash and
  size. Never push it anywhere; never commit a real configuration to this repository.
- Every configuration text that leaves the backend (API, UI, logs, diffs, commit
  messages, syslog commands) goes through `netops.configmgmt.redact`; there is no endpoint
  for the raw text. A new secret-bearing command gets a rule and a case in
  `tests/test_configmgmt.py`. Never log configuration text or device output; the
  netmiko/paramiko/nornir loggers stay at WARNING (`netops.core.logging`).
- Diffs come from `netops.configmgmt.diff.redacted_diff` (computed on the real text,
  printed redacted); IOS configuration structure from `netops.configmgmt.parser` (no GPL
  libraries such as ciscoconfparse).
- Configuration fixtures are generated from the fake lab only (`make fakelab-fixtures`).

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
make env        # create deploy/.env (DB password, CREDENTIALS_KEY, AUTH_SIGNING_KEY) or add a missing key
make up         # build, run migrations (one-shot `migrate` service), start the stack (UI on :8080)
make migrate    # alembic upgrade head via the `migrate` service, without restarting anything
make logs       # follow logs
make down       # stop (keeps the db volume)
make test       # backend unit tests (no database or network)
make test-integration  # integration tests against the compose db (needs `make up`)
make test-scale        # discover a generated 50-device campus (SCALE_DEVICES=200 for more)
make fakelab-up        # stack + fake devices; then fakelab-seed, fakelab-discover,
                       # fakelab-accuracy, fakelab-down (see lab/fakelab/README.md)
make fakelab-users     # UI users fakelab-admin/-operator/-viewer (FAKELAB_UI_PASSWORD in deploy/.env)
make fakelab-backup    # back up every managed device's configuration now
make fakelab-change DEVICE=dist1 SCENARIO=remove-vlan-from-trunk  # change + its syslog
make fakelab-reset     # undo the fake lab's changes
make fakelab-fixtures  # regenerate the running-config fixtures from the fake lab
make lint       # ruff, ruff format --check, mypy --strict, eslint, prettier, tsc
make format     # auto-fix formatting
make openapi    # regenerate docs/api/openapi.json and frontend/src/api/schema.d.ts
make mock       # Prism mock server for the contract on :4010 (UI: cd frontend && npm run dev:mock)
```

First admin of a stack: `docker compose -f deploy/docker-compose.yml exec api netops users
create-admin` (prompts; no default account exists).

Frontend tests (in `frontend/`): `npm test` (Vitest), `npm run e2e` (Playwright smoke against
the Prism mock), `npm run e2e:fakelab` and `npm run screenshots` (real stack + fake lab).

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
- Frontend ([ADR-0006](docs/adr/0006-frontend.md)): TypeScript strict, no `any`; server
  state only through the TanStack Query hooks in `frontend/src/api/queries.ts` (typed
  openapi-fetch client); Mantine components; every user-facing string in both
  `src/i18n/locales/tr.json` (default) and `en.json` (a test checks the keys match), network
  terms (VLAN, trunk, EtherChannel, HSRP, port names, roles) stay English; status is never
  shown by colour alone. Pure logic gets Vitest tests next to it; user flows get Playwright
  tests in `frontend/e2e/` (smoke against the Prism mock in CI).
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
