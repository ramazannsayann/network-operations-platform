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

After editing `topology.yaml`, run `make fakelab-compose` to regenerate
`deploy/docker-compose.fakelab.yml` (a test fails while it is stale).

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
