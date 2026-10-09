# ADR-0002: Shared data model

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** project team (4 members)

## Context

The proposal's central design decision (section 6.4) is that every module reads and writes
one shared, normalized, time-stamped data model: discovery (M1), inventory (M2) and
monitoring (M3) write it; fault diagnosis (M6) must be able to ask not only "what is the
state now?" but "what was the state at time T?" ("time travel", section 7.8), e.g. to
compare MAC tables, STP roles and OSPF adjacencies before and after a fault. The proposal
describes this as every state record carrying a `snapshot_id` and a `collected_at`.

Volumes are moderate but not small: at 200 devices, polling every 5 minutes produces tens
of millions of metric rows per day, and every inventory pass rewrites interface, MAC and
ARP state for every device. PostgreSQL with TimescaleDB was chosen in ADR-0001.

The full table list with one line per table is in [docs/data-model.md](../data-model.md).

## Decision

### 1. Two kinds of tables: entities and observations

- **Entities** have a stable UUID identity and are updated in place: locations, devices,
  device_serials, interfaces, interface_addresses, links, collection_runs, alarms,
  incidents, config_versions, config_changes, findings. Entities that are discovered on the
  network carry `first_seen_at` / `last_seen_at`.
- **Observations** are append-only rows produced by one collection run, each with
  `collected_at`: interface_snapshots, vlan_observations, neighbor_observations,
  mac_entries, arp_entries, route_entries, stp_instance_observations,
  stp_port_observations, hsrp_observations, ospf_neighbor_observations. Every observation
  table is a TimescaleDB hypertable on `collected_at` with a retention policy.
- `metrics` (on `time`) and `events` (on `received_at`) are hypertables too, but are not
  tied to a collection run.
- TimescaleDB requires the partitioning column in every unique index, so observation
  tables have the composite primary key `(id, collected_at)` (`id` is a bigint identity).
  Foreign keys from hypertables to regular tables are fine; **nothing may reference a
  hypertable**.

### 2. Collection runs define point-in-time state

Every collector execution creates a `collection_runs` row (device, kind, trigger, status,
started_at, finished_at, error). This row is the proposal's `snapshot_id`.

> The state of device D at time T for kind K is the latest **successful** run of kind K
> for D with `started_at <= T`, together with its observation rows.

`netops.db.state` implements this as reusable async helpers: `run_at` (one device),
`runs_at` (many devices, one LATERAL index probe each), `state_at` (the observation rows)
and `observations_of` (a SELECT for one run's rows).

All rows of a run carry the run's `started_at` as `collected_at` and the run's device as
`device_id`. A composite foreign key `(run_id, device_id, collected_at)` →
`collection_runs (id, device_id, started_at)` makes the database enforce this. As a
result, the rows of one run sit in one chunk and are found by an exact match on
`collected_at`, and per-run uniqueness can be enforced (e.g. one row per VLAN and MAC in a
MAC-table run).

### 3. Native PostgreSQL types

`inet` for addresses (with prefix where relevant, e.g. interface addresses `10.0.20.1/24`),
`cidr` for route prefixes, `macaddr` for MACs, `timestamptz` (UTC) for every timestamp,
PostgreSQL enum types for closed value sets (26 of them, defined in `netops.db.enums`),
`jsonb` only for genuinely free-form data (alarm details, finding evidence, parsed event
fields), and arrays where a value is a set (`allowed_vlans int[]`, `commands text[]`).

PostgreSQL compares `inet` values including the netmask (`'10.0.0.1/24' <> '10.0.0.1'`),
so every column that holds a single host address has a CHECK that it is a /32 or /128.

### 4. Interface names are normalized

`interfaces.name` keeps the name exactly as reported; `name_normalized` holds the canonical
long form produced by `netops.core.ifname.normalize` ("Gi1/0/1", "Gig 1/0/1" and
"GigabitEthernet1/0/1" all become "GigabitEthernet1/0/1"). Interfaces are unique on
`(device_id, name_normalized)`. Collectors must match interfaces on the normalized name.

### 5. Devices are de-duplicated by serial number

`device_serials` has the serial as its primary key and points to a device, so a stack or
VSS pair with several serials is one device, and a device seen via several IP addresses
is recognised by its serial. Serials are stored trimmed and upper-case (CHECK).

### 6. Retention

| Data | Retention |
| --- | --- |
| Observations (all run-based hypertables) | 30 days |
| `metrics` | 90 days |
| `events` | 90 days |

The values live in one place, `netops/db/timescale.py`, together with the chunk interval
(1 day). TimescaleDB drops whole chunks, so data disappears up to one chunk interval
after its retention period. Changing a value later requires a migration that replaces the
policy (`remove_retention_policy` + `add_retention_policy`).

### Further decisions made while implementing

- Hypertables are created with `create_default_indexes => false`; every index is declared
  on the models (each with a comment saying which query it serves), so
  `alembic revision --autogenerate` stays clean. An integration test runs the equivalent
  of `alembic check` against the migrated database.
- `metrics` has no surrogate id or primary key: it is the narrowest, highest-volume table.
  A unique index on (device_id, interface_id, name, time) with `NULLS NOT DISTINCT`
  identifies a sample; the ORM uses those columns as its identity.
- Enum types are created explicitly in the migration with their values frozen there, so
  a later change to `netops.db.enums` always needs its own migration.
- ON DELETE behaviour: deleting a device cascades to everything collected from it;
  references to optional things (an interface on an alarm, an incident on an alarm) are
  set to NULL.

## Why entities versus observations

Keeping only the latest state (update in place everywhere) makes the "before and after"
comparisons M6 depends on impossible, and keeping full history of everything in regular
tables grows without bound and makes "current state" queries expensive. Separating the
two gives:

- fast current-state reads from small entity tables (interfaces also keep a copy of the
  latest snapshot's state columns for the device page);
- complete, immutable history for a bounded period in hypertables, where retention is
  cheap (dropping chunks rather than DELETE) and time-range queries skip whole chunks;
- a single, explicit definition of "state at T" via collection runs, which also records
  failed and partial runs, so a failed poll never makes data disappear.

## Deliberately deferred

- **Users, roles, encrypted device credentials and the append-only audit log** belong to
  M7 and will get their own ADR and migration. Until then, `alarms.acknowledged_by` and
  `config_changes.username` are plain text.
- **Change jobs** (templated change requests, per-device previews, approvals, apply and
  rollback state) belong to M5.
- Compliance rules and results (M4, FR-09), notification channels and maintenance windows
  (M3), saved topology layouts (M1), discovery settings (seed, allowed subnets) and
  wireless controller data (bonus scope).
- TimescaleDB compression and continuous aggregates for `metrics` (needed before the
  200-device scale test; to be added with M3).
- A periodic job that deletes `collection_runs` older than the observation retention
  (their observation rows are already gone by then).
- ORM relationships. They will be added where modules need them, with `lazy="raise"` so
  async code cannot trigger hidden lazy loads.

## Consequences

- Collectors follow one pattern: create a run, insert observations with
  `collected_at = run.started_at`, update the entities (latest state and `last_seen_at`),
  then mark the run `success`, `partial` or `failed`.
- The database enforces much of the model's integrity (composite run foreign key, host
  address checks, VLAN ranges, alarm deduplication, ordered link endpoints), so collector
  bugs fail loudly instead of corrupting history.
- Observation rows cannot be referenced by foreign keys. Findings refer to evidence by
  run id and timestamp inside `evidence` (jsonb), and that evidence expires with the
  observation retention.
- Every new observation table must follow the same pattern (subclass `Observation`, use
  `observation_table_args`, add a hypertable and retention policy in its migration).
