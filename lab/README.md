# Lab

Placeholder for everything we need to develop and test against Cisco IOS/IOS-XE
networks **without touching production equipment**. Nothing here is used yet.

Planned contents:

- `topologies/`: lab topology definitions (e.g. Cisco Modeling Labs, GNS3 or EVE-NG
  exports) for the campus network we develop against, with a diagram and addressing plan.
- `fixtures/`: captured device output used by unit tests: `show` command output, SNMP
  walks, running configurations. Tests parse these files; they never connect to a device.
- Notes on how to bring the lab up and point a local stack at it.

Rules for this directory (see "Never commit" in CONTRIBUTING.md):

- Fixtures are captured only from our own lab (CML or the physical lab), never from the
  university network, the pilot or any other real network.
- Lab addressing is made up, from documentation or private ranges only (e.g. `10.0.0.0/8`,
  `192.0.2.0/24`), with made-up hostnames; never copy an institution's IP plan.
- Remove lab credentials from captured output before committing (`enable secret`,
  `username ... secret`, SNMP communities and SNMPv3 keys).
- Lab device credentials belong in a git-ignored `.env` file, never in topology files.
