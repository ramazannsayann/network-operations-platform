# ADR-0004: Device credentials and safe device access

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** project team (4 members)

## Context

To collect data the platform must log in to every network device, so it stores the
credentials of the whole network. The proposal calls this out as the platform's main risk
(section 7.7): stored device passwords and SNMPv3 keys must be encrypted (NFR-05), never be
shown, and the platform must not be able to change device configuration outside the
controlled M5 workflow. Step 5 adds the first code that touches devices: credential
profiles (a minimal part of M7), the read-only SSH layer and the M2 collectors.

## Decision

### Credential profiles, encrypted at rest

- `credential_profiles` holds named SSH profiles (username, password, optional enable
  secret) and SNMPv3 profiles (username, authentication and privacy protocol and keys).
  Devices reference one profile (`devices.credential_profile_id`, a profile in use cannot be
  deleted).
- SNMPv3 is authPriv only. MD5, DES and 3DES are deliberately not offered.
- Secret columns (`*_encrypted`, `bytea`) hold **Fernet** tokens (AES-128-CBC with an
  HMAC-SHA256 tag, from `cryptography`). They are decrypted only when a row is loaded, into
  a `Secret` object (`netops.core.secrets`), and unwrapped only at the point of use (opening
  the SSH session).

### The key: CREDENTIALS_KEY

- One or more comma-separated Fernet keys in the environment variable `CREDENTIALS_KEY`.
  The first key encrypts; every key decrypts (`MultiFernet`).
- `make up` (and `make env` for older files) generates a key into `deploy/.env` with
  `openssl rand -base64 32 | tr '+/' '-_'`. Like every `.env` file it is never committed.
- Every backend service (api, worker, scheduler, migrate) refuses to start without a valid
  key. Settings validation errors never echo the value they rejected.
- **Backups:** keep a copy of the key somewhere other than the database backups. A database
  backup together with the key reveals every device password; a database backup without
  the key means all stored credentials must be entered again.
- **Rotation:** (1) generate a new key; (2) set `CREDENTIALS_KEY=<new>,<old>` and restart,
  which makes new writes use the new key while old rows stay readable; (3) re-encrypt
  every row with the new key (`MultiFernet.rotate`, see "Deferred"); (4) remove the old key.

### Secrets never leak

- `Secret` prints as `**********` in `repr`, `str`, f-strings and logging, refuses to be
  pickled (so it cannot end up in Celery messages or caches) and is unhashable.
- Error texts from the device layer pass through `redact()` before they reach logs or
  `collection_runs.error`. Tests prove that repr, logging, exceptions, settings errors and
  session logs do not contain a secret.
- The API (when M7 adds credential endpoints) returns no secret fields at all.

### Read-only device access

- `netops.netaccess` builds a Nornir inventory from devices and their SSH profile and
  exposes one function for the read path: `run_show(devices, commands)`.
- Every command must pass the **read-only guard** before any connection is opened, and again
  right before it is sent. Allowed: `show <...>`, `terminal length 0`,
  `terminal width <n>`. Rejected: everything else, abbreviations (`sh ver`), and any
  command with a line break or other control character, `;`, `|` (output modifiers such as
  `| redirect` and `| tee` write files on the device), non-ASCII characters or surrounding
  whitespace.
- The layer has no method that sends configuration. M5 will add a separate write path with
  its own approval and audit flow, using the write-enabled device account that only M5 may
  use (proposal 7.7: two device accounts).
- SSH sessions use only the profile's password (no SSH agent, no keys from the worker's home
  directory). Timeouts, retries and the maximum number of parallel sessions come from
  settings. Authentication failures are not retried, so a wrong password cannot lock the
  account on the AAA server.
- Concurrency is limited with PostgreSQL advisory locks: one collection per device at a
  time and at most `SSH_MAX_CONCURRENCY` sessions across all workers. The locks disappear
  with the database connection, so a crashed worker cannot leave one behind.
- Netmiko session logs are **off** by default. When `SSH_SESSION_LOG_DIR` is set for
  debugging, Netmiko replaces the password and enable secret in them.

### SSH host keys

Strict host key checking is configurable (`SSH_STRICT_HOST_KEY_CHECKING`, optionally with
`SSH_KNOWN_HOSTS_FILE`). It is **off by default** for the lab, and the worker logs a
warning while it is off. Turning it on without a maintained known-hosts file would make
every new device fail.

## Deferred

- **Trust-on-first-use host key storage:** record each device's host key in the database at
  first contact, verify it on every later session, alert on changes. Until then, production
  use needs a known-hosts file or accepts the risk of a man-in-the-middle on the management
  network.
- A command that re-encrypts all credential rows with the first key (step 3 of rotation).
- Docker secrets or a KMS instead of an environment variable for `CREDENTIALS_KEY`.
- A second reference for the SNMPv3 profile on devices (M3), credential CRUD in the API and
  UI, and an audit trail of credential use (M7).
- A per-device SSH port (all devices use `SSH_PORT`, default 22).

## Consequences

- Stolen database backups do not reveal device passwords without the key; the key becomes
  the thing to protect and back up.
- Code that touches devices has exactly one read entry point, and configuration changes
  cannot be made through it even by mistake.
- Tests and fixtures never need real credentials: test passwords and keys are generated at
  run time, and the fake SSH device listens on 127.0.0.1 only.
