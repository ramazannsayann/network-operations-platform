# ADR-0007: Configuration management (M4): storage, redaction and change detection

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** project team (4 members)

## Context

Proposal section 7.4 describes M4: back up every device's running-configuration, keep its
versions, show diffs and detect changes made outside the platform; section 7.3 adds a syslog
receiver to M3, which is how such changes are noticed as they happen. Step 8 implements
backups, versioning, diffs, the syslog receiver and external change detection; compliance
rules, configuration push and rollback (M5), alarms (M3) and access control (M7) come later.

Running-configurations contain secrets: enable and user secrets (hashes and reversible type
7 strings), line passwords, SNMP communities and v3 keys, TACACS+/RADIUS keys, IKE
pre-shared keys, NTP and routing-protocol keys, key chains, wireless PSKs, certificates.
M5 will roll back with `configure replace`, which needs the complete text, secrets
included. The project repository is public.

## Decision

### Complete configurations at rest, only in a local Git repository

- The normalized running-configuration of each device is one file, `<device id>.cfg`, in a
  **bare Git repository** on the platform server: the Docker volume `config-repo`, mounted at
  `/var/lib/netops/configs` (read-write in `worker`, read-only in `api`; `CONFIG_REPO_PATH`).
  Every new version is one commit on `main`.
- The repository is **never pushed** and has no remote. It is unrelated to the project's
  GitHub repository; `*.cfg` and `backend/var/` (a host-side development path) are
  git-ignored there. Configurations of real devices are never committed to the project.
- The text is **not redacted at rest**: M5 needs it as it is. Only the commit id, the
  sha256 of the normalized text (`content_hash`), the size and the trigger go to the
  database (`config_versions`).
- **Permissions:** the directory belongs to the `netops` user (uid 10001) with mode `0700`;
  the image creates it that way and the store re-applies it on every write.
- **Consistency:** a backup commits to Git first and then to the database. If the database
  transaction fails, Git keeps an unreferenced commit and the next backup commits the same
  text again; the database never points at a commit Git does not have. If texts are lost,
  the API answers 503 for them while the metadata stays.
- **Concurrent workers** take turns through a lock file and move `main` with a
  compare-and-swap, so no commit is lost (tested with eight concurrent writers).

**Backing up the volume.** It holds secrets: store the archive encrypted and with the same
access restrictions as database backups.

```bash
docker run --rm -v netops_config-repo:/repo:ro -v "$PWD":/backup alpine \
  tar czf /backup/config-repo-$(date +%F).tgz -C /repo .
gpg --symmetric --cipher-algo AES256 config-repo-$(date +%F).tgz && rm config-repo-$(date +%F).tgz
```

Restore: stop `worker` and `api`, extract the archive into an empty `netops_config-repo`
volume (owner uid 10001, mode 0700), start them again. The archive is an ordinary bare Git
repository: `git log`, `git show main:<device id>.cfg` work on it.

### Git library: dulwich

| Option | For | Against |
| --- | --- | --- |
| **dulwich** | Pure Python wheel, nothing to install in the slim image; writes objects and refs directly (no working tree, no index), which a bare repository with compare-and-swap needs; typed API. License Apache-2.0 OR GPL-2.0-or-later: we use it under Apache-2.0. | Slower than libgit2 on huge repositories (irrelevant at one small file per device). |
| pygit2 | Fast (libgit2). | Binary dependency; GPLv2 with linking exception. |
| git CLI | The reference implementation. | `git` and its dependencies in the runtime image, a subprocess per operation, output parsing; working-tree based. |

Plain `git` still reads the repository (a test checks `git show main:<id>.cfg`).

### Our own IOS configuration parser

`netops.configmgmt.parser` builds the parent/child hierarchy from indentation (~150 lines),
handles `!` separators, banners (their text is data, not commands) and certificate blocks.
The redactor uses it now, compliance checks will later. We do not use ciscoconfparse or
ciscoconfparse2: both are GPLv3, and while the project's license is undecided, depending
on them would decide it.

### Normalization

`show running-config` is accepted only when complete (a `hostname` line and the final
`end`; a user below privilege 15 sees a partial configuration, which must not become a
version). Removed before hashing: `Building configuration...`, `Current configuration : N
bytes`, `! Last configuration change at ...`, `! NVRAM config last updated at ...`, `! No
configuration change since last restart`, `! No NVRAM config update since last restart`,
`! Time: ...`, `ntp clock-period N`, the bare `!` lines the header leaves at the top,
trailing spaces and CR/LF. Changing these rules changes the hash of unchanged
configurations: the next backup records one version per device whose diff shows only the
normalization.

### Redaction: every text that leaves the backend

- A secret value becomes the fixed marker `<redacted>`; the rest of the line (keywords,
  encryption type, key numbers, addresses) stays. Certificate payloads collapse into one
  `<certificate redacted>` line.
- **Diffs are computed on the complete texts and printed redacted**, so a changed secret
  still shows as a removed and an added line (`-enable secret 9 <redacted>` /
  `+enable secret 9 <redacted>`).
- Where redaction is applied: version texts and diffs in the API; the commands of
  `config_changes` (stored redacted and redacted again on output); syslog messages (CFGLOG
  commands are redacted when received, before anything stores or forwards them, because a
  device without `hidekeys` logs keys as typed); Git commit messages (commands redacted);
  logs (no configuration text is logged, the `RunningConfig` model leaves the text out of
  `repr()`, and the Netmiko, Paramiko and Nornir loggers, which log raw device I/O at DEBUG,
  never go below WARNING whatever `LOG_LEVEL` says).
- Rules, specific first (some only inside their block, e.g. `key` under `tacacs server`):
  `enable secret|password` (with level and algorithm-type), `username ... secret|password`
  (types 0, 5, 7, 8, 9), line and trustpoint `password`, `snmp-server community`,
  `snmp-server host` community/user, `snmp-server user` auth and priv keys, legacy
  `tacacs-server`/`radius-server ... key`, `key` under `tacacs server`/`radius server`,
  `server-private ... key`, `crypto isakmp key`, keyring `pre-shared-key address|hostname ...
  key`, IKEv2 `pre-shared-key [local|remote]`, `ntp authentication-key`, `key-string` (key
  chains, HSRP MD5), `ip ospf message-digest-key`, `authentication-key`, `authentication
  text`, HSRP plain `standby ... authentication`, `wpa-psk`, WLAN `set-key`, BGP `neighbor
  ... password`. A line no specific rule matched still goes through a generic
  `password|secret <value>` rule, so unknown commands err towards hiding.
- No endpoint returns the complete text in this step. M5 reads it internally; M7 may add an
  Admin-only reveal with an audit entry.
- All configuration fixtures are synthetic: the fake lab renders running-configurations
  with obviously fake secrets (`netops_fakes/fake_secrets.py`); an integration test scans
  every API response and log record of a change scenario for them.

### Backups and versions

- New collection kind `config` (`show running-config` through the read-only layer). It is
  collected on request only, not with the default kinds: by the scheduled backup
  (`netops.backup_configs`, `CONFIG_BACKUP_SCHEDULE`, default `30 2 * * *` UTC), after a
  change event, and by a device refresh that names it (`kinds: ["config"]`, also `netops
  configs backup`). Triggers map to `config_versions.trigger`: `scheduled`, `change_event`,
  `manual`; `pre_change`/`post_change` are reserved for M5.
- Unchanged hash: a successful `config` run and nothing else. New hash: a commit, a
  `config_versions` row and, unless it is the device's first backup (the baseline), a
  `config_changes` row. Commit messages name the device, the trigger and, when syslog
  reported it, the user, source address, line and the (redacted) commands.

### Syslog receiver: the `events` service

- `python -m netops.events`: an asyncio UDP server on port 514 inside its container
  (`SYSLOG_HOST_PORT` on the host, 127.0.0.1 by default). It parses Cisco IOS/IOS-XE syslog
  with or without the message counter, `logging origin-id`, `service sequence-numbers` and
  `service timestamps` (msec, year, time zone, `*`/`.` sync markers, uptime), and RFC 5424,
  into `events` (facility, severity, `FACILITY-SEVERITY-MNEMONIC`, message, parsed fields
  for CONFIG_I, CFGLOG and LINK/LINEPROTO).
- The source address is resolved to a device through `devices.mgmt_ip`, then interface
  addresses (cached 5 minutes, unknown sources 1 minute). Datagrams from unknown sources
  are dropped and logged once per source and 10 minutes; no device is ever created from
  syslog.
- Protections: a maximum datagram size (`SYSLOG_MAX_DATAGRAM_BYTES`, 2048), a token bucket
  per source (`SYSLOG_RATE_PER_SOURCE` 50/s, burst 200), a bounded queue; logs carry
  addresses and counts, never message text.
- **The source address must be the device's.** In the fake lab the devices and the service
  share a Docker network, so it is. On a Linux production host, run the service with host
  networking (`network_mode: host`, then `POSTGRES_HOST`/`REDIS_URL`/`CELERY_BROKER_URL`
  pointing at the published ports on 127.0.0.1); Docker's port publishing would otherwise
  rewrite sources. Docker Desktop (macOS, Windows) always NATs UDP from outside to its
  gateway: a datagram sent to the published port from the host arrives from `172.x.0.1` and
  is dropped as unknown (observed during step 8).

### External change detection

- `%SYS-5-CONFIG_I` (user, line, source address) and `%PARSER-5-CFGLOG_LOGGEDCMD` (user and
  each command, from `archive / log config`) open or extend a per-device window. It closes
  `CONFIG_CHANGE_DEBOUNCE_SECONDS` (30) after the last message, at the latest
  `CONFIG_CHANGE_MAX_WINDOW_SECONDS` (300) after the first. Then the Celery task
  `netops.config_change_event` backs the device up (trigger `change_event`, retried while
  the device is being collected) with the window's report.
- The change row: origin `platform` only when the user is `PLATFORM_WRITE_USERNAME` (the
  account M5 will push with), otherwise `external`; user, source address, the commands,
  before/after versions; `detected_at` is the arrival of the window's first message.
- **Lost syslog**: the next scheduled (or manual) backup finds the difference and records it
  as `external` with an unknown user; the API's `detected_by` (the trigger of the version
  that revealed it) says "found by the scheduled backup".
- Windows live in the events service's memory. Stopping the service hands open windows over
  at once; a crash loses them, and the next backup records those changes with an unknown
  user.

## Consequences

- Secrets are at rest in one volume on the platform server. Its permissions, the host's
  disk encryption and encrypted backups protect them; M7 adds access control on top.
- Redaction is pattern-based. A secret in a command no rule knows is caught by the generic
  rule only if it follows `password` or `secret`; new patterns are added with a test case.
- The syslog receiver is a single process; scaling it out would need the windows in Redis.
- If a manual backup records a change before its window closes, that change keeps an
  unknown user (the syslog-triggered backup then finds no difference).
- Device prerequisites (logging host, archive logging, privilege 15 for the read account,
  `ip scp server enable` for M5): [docs/device-prerequisites.md](../device-prerequisites.md).
