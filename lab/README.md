# Lab

Everything we need to develop and test against Cisco IOS/IOS-XE networks **without
touching production equipment**.

- `fixtures/`: device output used by the parser and collector tests (provenance in
  [fixtures/README.md](fixtures/README.md)). Tests parse these files; they never connect to
  a device.
- `fakelab/`: a made-up campus (`topology.yaml`) served by fake SSH devices, in tests and in
  containers; see [fakelab/README.md](fakelab/README.md).
- Planned: the real lab's topology (CML / physical lab) in the same format, for
  `tools/eval/discovery_accuracy.py`, and notes on pointing a local stack at it.

Rules for this directory (see "Never commit" in CONTRIBUTING.md):

- Fixtures are captured only from our own lab (CML or the physical lab), never from the
  university network, the pilot or any other real network.
- Lab addressing is made up, from documentation or private ranges only (e.g. `10.0.0.0/8`,
  `192.0.2.0/24`), with made-up hostnames; never copy an institution's IP plan.
- Remove lab credentials from captured output before committing (`enable secret`,
  `username ... secret`, SNMP communities and SNMPv3 keys).
- Lab device credentials belong in a git-ignored `.env` file, never in topology files.
