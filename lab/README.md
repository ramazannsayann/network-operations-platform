# Lab

Placeholder for everything we need to develop and test against Cisco IOS/IOS-XE
networks **without touching production equipment**. Nothing here is used yet.

Planned contents:

- `topologies/`: lab topology definitions (e.g. Cisco Modeling Labs, GNS3 or EVE-NG
  exports) for the campus network we develop against, with a diagram and addressing plan.
- `fixtures/`: captured device output used by unit tests: `show` command output, SNMP
  walks, running configurations. Tests parse these files; they never connect to a device.
- Notes on how to bring the lab up and point a local stack at it.

Rules for this directory:

- Never commit real credentials, SNMP communities, keys or production configurations.
  Scrub captured output before committing (replace secrets, `enable secret`, `username ...
  password`, SNMP communities, public IP addresses, hostnames that identify the institution).
- Lab device credentials belong in a git-ignored `.env` file, never in topology files.
