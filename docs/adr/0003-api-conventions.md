# ADR-0003: API conventions

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** project team (4 members)

## Context

The proposal (section 8.1) asks for the API to be agreed first, as an OpenAPI document,
so frontend and backend can be built in parallel. Step 4 defines that contract for
M1–M4 and M6 (M5 change jobs and M7 user management get their own contract later). The
document is `docs/api/openapi.json`; this ADR records the rules every endpoint follows.

## Decision

### Contract workflow

- The contract is written as code: FastAPI routers (`netops/api/v1/`) and Pydantic v2
  schemas (`netops/api/schemas/`). Handlers are stubs that answer **501** with a problem
  body until a module implements them.
- `make openapi` writes `docs/api/openapi.json` and the frontend's TypeScript types
  (`frontend/src/api/schema.d.ts`, openapi-typescript). Both are committed; CI fails if
  either is stale. Reviewing the diff of `openapi.json` in a pull request is the contract
  review.
- The frontend calls the API through a typed client (`openapi-fetch`) and can run against
  a Prism mock server that serves the contract's examples (`npm run mock`).
- `operationId` is the handler's function name (`list_devices`), so generated code reads well.

### Versioning

- REST endpoints live under `/api/v1`; `/api/health` stays unversioned.
- Within v1, changes are additive only: new endpoints, new optional parameters, new response
  fields, new enum values. Clients must ignore unknown fields and tolerate unknown enum
  values. Removing or renaming anything, or changing a type, needs `/api/v2`.

### Data format

- JSON with snake_case field names.
- Ids are UUID strings (syslog/trap events, which live in a hypertable, use integer ids).
- Timestamps are ISO 8601 and always carry an offset. Responses use UTC (`...Z`); inputs
  without an offset are rejected with 422.
- Network values are strings in canonical form: host addresses `10.0.20.57` (IPv6
  compressed), interface addresses with prefix `10.0.20.1/24`, prefixes `10.0.20.0/24`,
  MACs lower-case colon-separated `3c:52:82:6e:41:9a`. VLAN ids are integers 1–4094.
- Enums that exist in the database are the same Python enums (`netops.db.enums`), so
  the API and the database cannot drift apart. Enums that exist only in the API (job
  status, user role, path warning codes, ...) live next to their schemas and must move to
  `netops.db.enums` if they are ever stored.

### Errors

- Every 4xx/5xx response is an RFC 9457 problem (`application/problem+json`) with the
  shared `Problem` schema: `type`, `title`, `status`, `detail`, `instance` (the request path).
- `type` is `about:blank` for plain HTTP errors; API-specific types are URNs:
  `urn:netops:problem:not-implemented` (contract stubs) and
  `urn:netops:problem:validation-error` (422, with an `errors` list of `{loc, msg, type}`).
- A search that finds nothing is an answer, not an error: the host locator returns 200 with
  `status: "not_found"` and a `reason`. 404 means the addressed resource does not exist.

### Collections

- `limit` (default 50, maximum 500) and `offset`; the response is the envelope
  `{items, total, limit, offset}`.
- Filters are query parameters named after the field. A parameter given several times
  means OR (`?severity=critical&severity=major`); different parameters combine with AND.
  `q` is a case-insensitive text search where an endpoint offers one.
- Time windows use `from` (inclusive) and `to` (exclusive, default now) on the endpoint's
  main timestamp, which its description names. Two endpoints keep the names of the step-4
  specification: `/topology/changes` uses `since`/`until`, and `/configs/diff` uses
  `from`/`to` for the two version ids being compared.
- `sort` takes a field name, prefixed with `-` for descending; the allowed values are
  listed per endpoint in the contract.

### Writes

- `POST` creates and returns 201 with the resource; `PATCH` is a partial update (fields
  absent from the body stay unchanged); `DELETE` returns 204.
- Long-running operations (device refresh, discovery) return **202 Accepted** with a
  `JobRef` body (`id`, `kind`, `status`, `href`, `target_href`) and a `Location` header
  pointing at `GET /api/v1/jobs/{id}`. Progress is also pushed on the WebSocket
  (`job.status`, `discovery.progress`). Where jobs are stored is left to the modules.

### Time travel

- Endpoints that read observed network state take an optional `at` timestamp (default:
  now): interfaces, topology, host locator, path trace (in the body) and impact analysis.
  `at` means exactly what `netops.db.state` implements (ADR-0002): for each device and
  kind, the latest successful collection run that started at or before `at`.
- Responses say which data they used: the effective `at`, and `observed_at` /
  `collected_at` / `run_id` on the observed parts, so the UI can show data age and M6
  evidence can be verified.
- Inventory entities (devices, locations) are current state only.

### Security

- An HTTP bearer scheme `bearerAuth` (JWT) is declared, and every operation except
  `GET /api/health` and `POST /api/v1/auth/login` requires it in the contract.
- Tokens are **not checked yet**; M7 implements validation (and roles) behind the same
  dependency, without changing the contract. The WebSocket authenticates with the same
  token in its first message (`docs/api/websocket.md`).

### Examples

- Every object schema has at least one realistic example, built from one fictional
  campus network (`netops/api/schemas/examples.py`) so examples agree with each other
  across endpoints. Only private (`10.0.0.0/8`) and documentation (`192.0.2.0/24`,
  `198.51.100.0/24`) addresses are used.
- The first example of a schema is copied to every request/response media type that uses
  it, which is where mock servers read it; error responses get an example matching their
  status code. Tests check that every example validates against its schema.

## Consequences

- The frontend can be built against the mock before any endpoint exists, and typing
  errors show up at build time when the contract changes.
- Every API change is visible in review as a diff of `openapi.json` and `schema.d.ts`.
- The contract is ahead of the schema in places (discovery runs, jobs, users and
  credential profiles have no tables yet); the modules add them when they implement the
  endpoints.
- The committed `openapi.json` is large (~400 KB) because of the examples; it is
  generated and never edited by hand.
