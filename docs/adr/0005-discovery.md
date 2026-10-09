# ADR-0005: Discovery (M1) and the fake lab

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** project team (4 members)

## Context

Proposal section 7.1 describes M1: starting from seed addresses, walk CDP/LLDP neighbours
breadth-first within allowed subnets, log in with at most two credential profiles per
device (so a wrong password cannot lock an account on the AAA server), de-duplicate devices
reached through several addresses by serial number, and build the topology from the
neighbour tables. Step 6 implements this on top of the M2 collectors (ADR-0004) and needs a
lab to develop and evaluate it against without real devices.

## Decision

### One run, breadth-first, as one Celery task

- A run is requested through `POST /api/v1/discovery/runs` or `netops discover`
  (`netops.discovery.service.request_discovery`): seeds, allowed subnets, credential
  profiles in order. One run at a time (409 otherwise); requests are serialised with an
  advisory lock, and a run still queued or running after two hours counts as abandoned.
- `netops.discover` (Celery) executes the whole run (`netops.discovery.engine`). It takes
  every free SSH slot (at most `SSH_MAX_CONCURRENCY`, ADR-0004) and processes each BFS level
  in parallel within them. Progress is written to `discovery_runs` and its `jobs` row after
  every level; `GET /api/v1/jobs/{id}` and `GET /api/v1/discovery/runs/{id}` read it. A
  redelivered task starts the run over; discovery converges on the same devices.
- `discovery_run_items` records what happened to every address: `discovered`, `duplicate`,
  `auth_failed`, `unreachable`, `out_of_scope`, `unsupported_platform`, `no_mgmt_ip`, with
  the hop, the neighbour that pointed there, the number of logins and the error.

### Per address

1. **Scope.** Only addresses inside the allowed subnets are ever connected to. Scope checks,
   de-duplication and everything stored use management addresses; the
   connection-target resolver (`netops.netaccess.target`, identity in production) only
   decides which socket a session opens. Integration tests map each fake device's address to
   `127.0.0.1:<port>` with it.
2. **Credentials.** The profile that worked on this device last time first (looked up by
   management address or any interface address), then the run's profiles in order, at most
   two logins. Authentication failures are never retried with the same profile. The
   profile that works is stored on the device (`devices.credential_profile_id`).
3. **Phase A** (one session): `show version`, `show inventory`, CDP and LLDP neighbours and
   `show ip route`. The device type comes from the model (router families) and from whether
   the device routes (L2 switches answer `show ip route` with "Default gateway is ...").
4. **Identification** (sequential within a level): serial numbers first (any serial reached
   earlier in this run makes the address a `duplicate`: a second management SVI of a
   device we already have; no second device is created), then the management address, then
   an address-less placeholder with the same hostname; otherwise a new device. This also
   ends step 5's "serial belongs to another device" partial runs, which came from two device
   rows for one chassis.
5. **Neighbours.** In-scope neighbours of supported platforms (Cisco devices advertising
   switch or router capabilities) are queued for the next level. Out-of-scope neighbours,
   access points, phones and other platforms are recorded and created as **unmanaged
   placeholder devices** so the topology map shows them; they are never connected to.
   Failed logins (`auth_failed`, `unreachable`) also get a placeholder.
   `devices.management_status` (`managed`, `out_of_scope`, `auth_failed`, `unreachable`,
   `unsupported_platform`, `manual`) lets the map flag them without joining run history.
6. **Phase B** (second session): the remaining collectors for the device type
   (`netops.inventory.collectors.KINDS_BY_TYPE`): routers skip the switching commands and
   L2 switches skip routing, so neither ends up with partial runs. The same command sets
   apply to M2's `collect_device`. Runs are stored through the M2 collectors, one database
   session per device, up to eight devices at once; the per-device collection lock
   (ADR-0004) is held while a device's data is stored.

### Links and drift (`netops.discovery.links`)

After the last level, links are rebuilt from the latest successful (or partial) neighbours
run of every device. The remote device is matched by management address or any interface
address, then by a serial in the Device ID, then by a hostname no other device has; the
remote port is normalised. Links both ends report win conflicts over one-sided reports on
the same interface. A link is stored once (a < b) from CDP if CDP reported it, else LLDP.
EtherChannel members are separate links; the port-channel comes from
`interfaces.parent_interface_id`. A link the latest neighbours runs of both endpoints no
longer report becomes `is_active = false` (kept for drift reports).

### Roles (`netops.discovery.roles`)

A deliberately simple heuristic on device types and active links: routers are `edge`; L3
switches linked to a router are `core` (without routers: the L3 switches with the most
switch neighbours); other switches get their distance from the core, and a switch with a
switch neighbour farther from the core is `distribution`, otherwise `access`; devices
discovery does not crawl stay `unknown`. `devices.role_is_manual` keeps a role an operator
set (the API to set it comes with the topology/inventory editing work).

### Topology API (step 7)

- `GET /topology?layer=l2`: every device (placeholders included, flagged by
  `management_status` and `out_of_scope`) and the active links; links between members of
  the same two port-channels are collapsed into one `etherchannel` edge with a `members`
  list (members not seen while another one is are listed with `is_active: false`).
- `layer=l3`: L3 devices (routers, L3 switches), one node per subnet of their addresses
  (no /32 or /128), and an edge per device address in a subnet, with the device's HSRP state
  there; subnet nodes list their HSRP virtual gateways. An L3 device without collected
  addresses (a provider router out of scope) joins the subnet its management address is in.
- `at`: devices first seen by then; links reported by the neighbours runs in force at `at`
  (the same matching as `rebuild_links`, `links_reported_at`); addresses seen by the
  interfaces runs in force; HSRP from the HSRP runs in force (all via `netops.db.state`).
  Device identities and management statuses are today's.
- `GET /topology/changes`: added devices and links by `first_seen_at`; a removal is dated at
  the first successful discovery run after the thing was last seen (drift is detected by
  discovery). **Limitation:** devices and links keep one row each, so something that
  disappears and comes back shows only its latest state; its earlier absence is not in the
  history.
- `GET/PUT /topology/layout`: saved node positions per layer in `topology_positions`, one
  global layout until M7 adds users. Node ids are device ids or (L3) subnet prefixes, so
  the table has a `node_id` besides the nullable `device_id`.

### API and CLI

The endpoints listed in step 6 are implemented; the contract changed additively:
`DeviceSummary.management_status` and a `management_status` filter on `GET /devices`.
Work is enqueued by task name through an injectable queue (`get_task_queue`), so the API
does not import worker code and tests need no broker. The CLI (`netops`, Typer) reads
passwords only from a hidden prompt or stdin, never from arguments.

### The fake lab

- `lab/fakelab/topology.yaml` describes a small campus (format:
  `backend/src/netops_fakes/topology.py`). `netops_fakes.lab` derives every device's state
  (ports, PVST+, MAC learning, ARP, HSRP, OSPF with ECMP, CDP/LLDP both ways) and
  `netops_fakes.render` renders IOS/IOS-XE output for all 16 parsed commands, following the
  real fixtures. Round-trip tests parse every output with our parsers and compare against
  the derived models and the YAML. `synthetic(n)` generates same-shaped campuses of 6-240
  devices for scale tests.
- **Where it lives:** `backend/src/netops_fakes/`, a second top-level module of the
  backend package (`uv_build` `module-name = ["netops", "netops_fakes"]`). Tests, the
  scale test, the accuracy tool and the fakelab containers share one implementation, one
  lock file and one toolchain (ruff, mypy). `netops` never imports it; asyncssh is only in
  the optional `fakelab` extra and the dev group.
- Containers: `deploy/docker-compose.fakelab.yml` (generated from the topology) runs one
  fake device per container and management address with the device's address on a
  dedicated network; the worker joins it. `make fakelab-up/seed/discover/accuracy/down`.

## Consequences

- Discovery of the fake lab, including the wrong-password switch, the provider router
  outside scope and the stack reachable via two addresses, is tested end to end on any
  machine (`make test-integration`), with 100% device and link precision/recall; a
  50-device generated campus runs in CI and reports its duration.
- Holding every free SSH slot makes scheduled collections wait while a discovery runs;
  acceptable for a campus-sized network, revisit if runs get long.
- Placeholders mean the inventory contains devices the platform does not manage; API
  clients filter on `management_status`.

## Deferred

- Subnet sweeps and ARP-based discovery (seed/CDP/LLDP only for now), SNMP-based
  identification (M3), IPv6 management addresses beyond what the parsers already accept.
- An API to override roles (`devices.role_is_manual` is ready for it); per-user layouts (M7).
- Merging two existing device rows that turn out to be one chassis (discovery now prevents
  them; older data would need a one-off merge).
- Trust-on-first-use host keys (ADR-0004).
