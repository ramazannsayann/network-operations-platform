# Device output fixtures

Raw CLI output that the parser tests (`backend/tests/test_parsing.py`), the collector tests
and the fake SSH device (`backend/src/netops_fakes/device.py`) use; the fake lab generator
(`netops_fakes.render`) follows these formats. Nothing here comes from
the university network, the pilot or any other real network (see "Never commit" in
[CONTRIBUTING.md](../../CONTRIBUTING.md)).

## Layout

```
cisco_ios/<command>/*.raw     one directory per command, spaces replaced by "_"
                              (show_mac_address-table holds "show mac address-table")
devices/dist-sw1/<command>.raw  one coherent lab device, every supported command
```

## Sources

### `cisco_ios/*/cisco_ios_*.raw`, `four_neighbors.raw`, `show_etherchannel_summary*.raw`

Copied from the test suite of **ntc-templates**:

- Repository: <https://github.com/networktocode/ntc-templates>
- Tag `v9.3.0`, commit `bb4c7f5142d50aadb5cf3e4e74cebb994bb2f223`, directory `tests/cisco_ios/`
- License: Apache License 2.0, Copyright 2015 Jason Edelman / Network to Code, LLC; a copy is
  in [cisco_ios/LICENSE-ntc-templates](cisco_ios/LICENSE-ntc-templates). These files remain
  under that license.

The upstream test directory `show_mac-address-table` was copied to `show_mac_address-table`
and `show_spanning-tree/cisco_ios_show_spanning_tree.raw` kept its name. ntc-templates has no
separate `cisco_xe` test outputs; IOS-XE output is among the `cisco_ios` files (for example
`show_version/cisco_ios_show_version1.raw`, `4`, `5`, `_special_build`).

**Changes made** (Apache-2.0 section 4b): before committing, every file was scanned for public
IP addresses, organisation names in host or domain names and secrets. The following were
replaced; nothing else was edited.

| File | Replaced |
| --- | --- |
| `show_cdp_neighbors_detail/cisco_ios_show_cdp_neighbors_detail2.raw` | `1.1.1.1` → `192.0.2.1` |
| `show_lldp_neighbors_detail/cisco_ios_show_lldp_neighbors_detail2.raw` | `11.11.11.11` → `192.0.2.11`, `33.33.33.3` → `192.0.2.33`, `55.55.55.55` → `192.0.2.55`, `USSC-CAMPUS-CORE-GW` → `CAMPUS-CORE-GW`, `acme123.com` → `example.net` |
| `show_lldp_neighbors_detail/cisco_ios_show_lldp_neighbors_detail_02.raw` | `SW-MGMT.cisco.com` → `SW-MGMT.example.net` |
| `show_interfaces/cisco_ios_show_interfaces_01.raw` | `111.222.0.37` → `198.51.100.37` |
| `show_ip_interface_brief/cisco_ios_show_ip_interface_brief.raw` | `1.1.1.1` → `192.0.2.1` |
| `show_ip_route/cisco_ios_show_ip_route_vrf.raw` | `50.0.0.0` → `198.51.100.0`, `50.1.1.1` → `198.51.100.1` |
| `show_ip_route/cisco_ios_show_ip_route_wildcard.raw` | `1.0.0.0/8` → `192.0.2.0/24`, `1.1.1.0/30` → `192.0.2.0/30`, `1.1.1.1` → `192.0.2.1` |

Left as they are, on purpose:

- Firmware version strings that look like IPv4 addresses (`Version 6.4.2.6-4.1.1.6`,
  `S/W revision: 47.80.132.1`, `Version: 8.10.162.0`, `H/W revision: 9.1.3.3`,
  `F/W revision: 5.0.9.0`).
- `cisco.com` / `www.cisco.com` support URLs and the `gnu.org` licence URL in banners.
- "token" in `show_vlan`, which is the Token Ring VLAN type, not a secret.
- Upstream outputs whose addresses could not be replaced without breaking the routing
  logic (`show_ip_route/cisco_ios_show_ip_route.raw`, `show_interfaces3`) were not copied.

### `cisco_ios/*/netops_*.raw` and `devices/dist-sw1/`

Written for this project, with made-up names, serial numbers, MACs and addresses from
`10.0.0.0/8` only:

- `netops_empty.raw`: commands that return an empty table.
- `netops_not_enabled.raw`: `% CDP is not enabled` / `% LLDP is not enabled`.
- `devices/dist-sw1/`: one IOS-XE 17.9 Catalyst 9300 stack (two members) with access ports,
  an err-disabled port, a half-duplex port with late collisions, a two-member LACP
  port-channel to the core, SVIs with HSRP (active in VLAN 20, standby in VLAN 30), OSPF over
  VLAN 99 with ECMP routes, Rapid-PVST and CDP/LLDP neighbours. Its outputs agree with each
  other, so collector tests can check the stored rows end to end. The fake SSH device serves
  this directory.

## Known gaps

- `show lldp neighbors detail` on older IOS releases does not print `Local Intf`; such
  neighbours cannot be attached to a local port and are skipped
  (`cisco_ios_show_lldp_neighbors_detail2.raw`, `5`).
- `show spanning-tree` gives no topology-change counters; those need
  `show spanning-tree detail` and stay empty for now.
- `show interfaces` shows only the primary address of an interface; secondary addresses
  need `show ip interface`.
