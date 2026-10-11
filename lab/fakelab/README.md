# Fake lab

A small, made-up campus served by fake Cisco IOS/IOS-XE devices, for developing and
evaluating discovery (M1) and the collectors (M2) without real equipment. Everything here
is fictional: addresses from `10.0.0.0/8` and `198.51.100.0/24` (documentation), made-up
names and serial numbers.

`topology.yaml` is the single source. From it, `netops_fakes` (in
`backend/src/netops_fakes/`) derives each device's state and renders the CLI output of
every command our parsers support; the round-trip tests (`backend/tests/test_fakelab.py`)
prove that the output parses back into exactly what the file describes.

```
            isp-ce1 (198.51.100.1, outside the allowed subnet: out_of_scope)
               |
             rtr1 (ISR4331, OSPF, static default to the provider)
            /     \            routed /30s, OSPF
        core1 ==== core2       C9300 L3 pair: HSRP, STP root core1, Po1 (2 x Te)
         |  \    /  |
         |   \  /   |         dual-homed distribution
       dist1   dist2           dist2 = 2-member stack, also reachable via 10.255.0.70
       /   \    /   \
  access1 access2 access3 access4 (wrong credentials: auth_failed)
             |
            ap1 (CDP only: unsupported_platform)
```

| Device | Address | What it tests |
| --- | --- | --- |
| core1 | 10.255.0.2 | Seed; STP root; HSRP active for VLANs 10, 98, 99; EtherChannel to core2 |
| core2 | 10.255.0.3 | HSRP active for VLANs 20, 30; OSPF DR on the management VLAN |
| rtr1 | 10.255.0.129 (loopback) | Router command set (no switching commands); OSPF; CDP neighbour outside scope |
| isp-ce1 | 198.51.100.1 | Out of scope: recorded, never connected to |
| dist1 | 10.255.0.11 | Distribution role from the graph |
| dist2 | 10.255.0.12 and 10.255.0.70 | Stack with two serials; second management SVI → de-duplication by serial |
| access1-3 | 10.255.0.21/.22/.73 | Hosts (MAC/ARP), IOS 15.2 and IOS-XE access switches |
| access4 | 10.255.0.74 | Accepts no password: `auth_failed` after at most two logins |
| ap1 | 10.255.0.40 | Access point seen via CDP: `unsupported_platform` |

The allowed subnet for discovery is `10.255.0.0/24`.

## Running it

In tests (no Docker needed): `make test-integration` discovers the fake lab on
127.0.0.1 (one port per device, mapped by the connection-target resolver).

In containers, with the real stack (one container per device and address on a dedicated
`10.255.0.0/24` network that the worker joins):

```bash
make fakelab-up         # stack + fake devices; adds a random FAKELAB_PASSWORD to deploy/.env
make fakelab-seed       # credential profiles: fakelab-outdated (wrong) and fakelab
make fakelab-discover   # netops discover from core1, prints every address's outcome
make fakelab-accuracy   # precision/recall against topology.yaml
make fakelab-down       # stop everything (make up for the normal stack)
```

From the UI: open <http://localhost:8080/discovery>, enter seed `10.255.0.2`, subnet
`10.255.0.0/24` and both fakelab profiles, then watch the run and the map. The same flow is
automated: `cd frontend && npm run e2e:fakelab` (expects 11 devices and 13 logical links on
the map: 14 cables, two of them one EtherChannel), and `npm run screenshots` refreshes
`docs/screenshots/`.

After editing `topology.yaml`, run `make fakelab-compose` to regenerate
`deploy/docker-compose.fakelab.yml` (a test fails while it is stale), and
`make fakelab-fixtures` to regenerate the running-config fixtures in `lab/fixtures/`.

## Configurations and the change simulator

Every fake device also serves `show running-config`, rendered from the same state as its
other outputs (VLANs, trunks and their VLAN lists, access ports, port-channels, SVIs with
HSRP, OSPF, descriptions, shut ports), with obviously fake secrets
(`backend/src/netops_fakes/fake_secrets.py`) and `logging host` pointing at the events
service (`syslog_host: 10.255.0.253` in `topology.yaml`).

A change scenario changes a fake device the way an operator would, keeps every output of
every device consistent (the running-config, `show interfaces switchport`, spanning tree,
MAC and ARP tables, CDP/LLDP) and sends the syslog a device with archive logging sends:
one `%PARSER-5-CFGLOG_LOGGEDCMD` per command, link messages, then `%SYS-5-CONFIG_I`, from
the device's own address.

```bash
make fakelab-backup     # back up every managed device now (what the nightly job does)
make fakelab-change DEVICE=dist1 SCENARIO=remove-vlan-from-trunk
make fakelab-change DEVICE=access1 SCENARIO=shutdown-port CHANGE_USER=asmith
make fakelab-change DEVICE=dist1 SCENARIO=change-description TEXT="uplink to access2"
make fakelab-reset      # undo every change (no syslog: the next backup finds the revert)
```

| Scenario | Default target | Effect |
| --- | --- | --- |
| `remove-vlan-from-trunk` | VLAN 20 on the device's last trunk towards a switch with VLAN 20 hosts (on dist1: Gi1/0/2 to access2) | The VLAN's hosts behind the trunk are cut off: they leave the other switches' MAC tables and the cores' ARP tables; on access2 VLAN 20 elects its own root. |
| `shutdown-port` | The first port with a host, else that trunk | The cable goes down at both ends: interface state, CDP/LLDP, spanning tree, MAC and ARP follow. |
| `change-description` | That trunk | Only the description (and the running-config) changes. |

Options: `PORT=Gi1/0/2`, `VLAN=20`, `TEXT=...`, `CHANGE_USER=jdoe`, `SOURCE_IP=192.0.2.77`.
The change appears in the UI ("Config değişiklikleri", the device's Config tab) about 30 s
later: the events service waits `CONFIG_CHANGE_DEBOUNCE_SECONDS` after the last message,
then a worker backs the device up (about one more second in the fake lab).

The scenarios are building blocks (`netops_fakes.scenarios`: remove/add a VLAN on a trunk,
shut/enable a port, change a description), each returning the changed topology, the typed
commands and the link messages, so M6 can stage its faults with them. Changes live in the
`fakelab-state` volume, shared by all fake devices; in tests `LocalLab.change` applies
them in memory and sends the syslog from a socket mapped to the device's address.

## Scale

`netops_fakes.topology.synthetic(n)` builds a campus of `n` devices (6-240) with the same
structure: one router, two cores, dual-homed distribution switches and access switches with
two hosts each. `make test-scale` discovers 50 of them (also in CI);
`make test-scale SCALE_DEVICES=200` for a larger manual run.

## The real lab

`tools/eval/discovery_accuracy.py` compares any inventory with a topology file in this
format, so a hand-written `topology.yaml` of the real lab (devices and links only, made-up
or lab addressing) can be evaluated the same way. Never commit an institution's addressing
plan (see CONTRIBUTING.md).
