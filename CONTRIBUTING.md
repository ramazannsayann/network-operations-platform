# Contributing

How the team works on this repository. Project context and code conventions are in
[CLAUDE.md](CLAUDE.md); the design reference is
[docs/proposal/proposal-v2.pdf](docs/proposal/proposal-v2.pdf).

## Setup

```bash
make install    # backend venv (uv), frontend packages (npm), git pre-commit hooks
make up         # run the stack locally: http://localhost:8080
```

## Workflow

1. **Branch from `main`**, named `<type>/<short-description>`, with the module when there is
   one:
   - `feat/m1-cdp-discovery`, `feat/m3-snmp-poller`: new functionality
   - `fix/m2-arp-parser-vrf`: bug fixes
   - `docs/adr-0003-authentication`: documentation only
   - `chore/ci-cache-uv`: tooling, CI, dependencies
2. **One pull request per logical change.** Small PRs get reviewed faster; split unrelated
   work into separate PRs.
3. **CI must pass** (backend lint/types/tests, backend integration, frontend, Docker build)
   and **one teammate must approve** before merging. `main` is protected: nobody pushes to it
   directly.
4. **Squash merge.** The PR title becomes the commit message on `main`, so write it in
   English, in the imperative mood, ≤ 72 characters: "Add CDP neighbour parser".
5. Significant design decisions get a new ADR in `docs/adr/` in the same PR. Schema changes
   come with an Alembic migration (see CLAUDE.md) and an update to `docs/data-model.md`.

## Checks to run before pushing

```bash
make lint               # ruff, ruff format --check, mypy --strict, eslint, prettier, tsc
make test               # backend unit tests (no database or network)
make test-integration   # schema and query tests against the local database (needs `make up`)
uv run --project backend pre-commit run --all-files   # what the git hook runs on commit
```

## Hard rules

- **Never commit credentials** (see below). Only `*.env.example` files with placeholders are
  committed; `.env` files are git-ignored. The pre-commit hook runs gitleaks and GitHub push
  protection is enabled, but both are safety nets, not a substitute for care.
- **Tests must never connect to, or push configuration to, real devices.** Use mocks and
  captured fixtures from `lab/fixtures/`. Unit tests cannot open network connections at all
  (pytest-socket); only `@pytest.mark.integration` tests may, and only to the local database.

## Never commit

This repository is public. Never commit, not even in a branch, a fixture, a screenshot or a
"temporary" commit:

- **Real device configurations**: running/startup configs or `show` output captured from any
  real network, sanitised or not.
- **The university's or any institution's IP addressing plan**: subnets, VLAN plans,
  management addresses, or hostnames that reveal it, even though they are private addresses.
- **Pilot data**: anything collected from the university network during the pilot
  (inventories, MAC/ARP tables, syslog, metrics, topology exports, screenshots).
- **Credentials**: passwords, enable secrets, SNMP communities and SNMPv3 keys, API tokens,
  private keys, `.env` files.

Lab topologies and fixtures use **made-up** addressing from documentation or private ranges
only, e.g. `10.0.0.0/8` and `192.0.2.0/24` (also `198.51.100.0/24`, `203.0.113.0/24`,
`2001:db8::/32`), with made-up hostnames, MAC addresses and serial numbers. Never copy
addresses from a real network, even into a private range.

If something sensitive is pushed by mistake, tell the team immediately and rotate any
exposed secret. Rewriting history does not undo a push to a public repository.
