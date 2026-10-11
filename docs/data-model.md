# Data model

The shared database schema used by all modules. The principles behind it, and what was left
out on purpose, are in [ADR-0002](adr/0002-data-model.md). The SQLAlchemy models in
`backend/src/netops/db/models/` are the source of truth; the diagrams show the main columns
only.

- **Entities** (regular tables) have a UUID `id` and are updated in place.
- **Observations** (TimescaleDB hypertables, kept 30 days) are append-only rows written by one
  collection run; `metrics` and `events` are hypertables kept 90 days.
- The state of device D for kind K at time T is the latest successful collection run of kind
  K for D with `started_at <= T`; use `netops.db.state` to query it.

## Inventory and topology

```mermaid
erDiagram
    locations |o--o{ locations : "parent of"
    locations |o--o{ devices : "contains"
    devices ||--o{ device_serials : "identified by"
    credential_profiles |o--o{ devices : "logs in to"
    devices ||--o{ interfaces : "has"
    interfaces |o--o{ interfaces : "port-channel of"
    interfaces ||--o{ interface_addresses : "configured with"
    interfaces ||--o{ links : "a side"
    interfaces ||--o{ links : "b side"

    locations {
        uuid id PK
        text name
        text building
        text floor
        uuid parent_id FK
    }
    devices {
        uuid id PK
        text hostname
        inet mgmt_ip UK
        device_type device_type
        device_role role
        bool role_is_manual "heuristic leaves it alone"
        os_family os_family
        uuid location_id FK
        bool is_managed
        management_status management_status "why (not) managed"
        reachability reachability
        discovery_source discovered_via
        uuid credential_profile_id FK "the profile that worked"
        int ssh_port "NULL: SSH_PORT"
        timestamptz last_seen_at
    }
    credential_profiles {
        uuid id PK
        text name UK
        credential_kind kind "ssh or snmpv3"
        text username
        bytea password_encrypted "Fernet"
    }
    device_serials {
        text serial PK
        uuid device_id FK
        int stack_member
    }
    interfaces {
        uuid id PK
        uuid device_id FK
        text name
        text name_normalized "unique per device"
        interface_kind kind
        uuid parent_interface_id FK
        macaddr mac
        bool oper_up "latest snapshot copy"
    }
    interface_addresses {
        uuid interface_id PK, FK
        inet address PK "with prefix"
        bool is_secondary
    }
    links {
        uuid id PK
        uuid a_interface_id FK "a < b"
        uuid b_interface_id FK
        link_source source
        bool is_active
    }
```

## Discovery runs and jobs

```mermaid
erDiagram
    jobs ||--o| discovery_runs : "tracks"
    discovery_runs ||--o{ discovery_run_items : "dealt with"
    devices |o--o{ discovery_run_items : "found / placeholder"
    devices |o--o{ discovery_run_items : "seen from (via)"

    jobs {
        uuid id PK
        job_kind kind "device_refresh or discovery"
        job_status status
        uuid target_id "device or discovery run"
        int progress_completed
        int progress_total
        text error
    }
    discovery_runs {
        uuid id PK
        uuid job_id FK, UK
        job_status status
        inet_array seeds
        cidr_array allowed_subnets
        uuid_array credential_profile_ids "in order"
        int found "and queued, scanned, new_devices, skipped, errors"
    }
    discovery_run_items {
        bigint id PK
        uuid run_id FK
        inet address "unique per run"
        int hop
        uuid via_device_id FK
        text via_interface
        discovery_item_status status
        uuid device_id FK
        int attempts "at most 2"
        text error
    }
```

`topology_positions` (layer, node_id, device_id, x, y, updated_at) holds the map layout
operators saved; `node_id` is a device id or, on the L3 map, a subnet prefix.

Discovery (M1, [ADR-0005](adr/0005-discovery.md)) records one item per address it dealt
with. Devices it does not log in to (out of scope, wrong credentials, access points) are
still created as unmanaged placeholders so the map shows them; `devices.management_status`
says why.

## Collection runs and observations

Every observation row references its run with the composite foreign key
`(run_id, device_id, collected_at)` → `collection_runs (id, device_id, started_at)`, so all
rows of a run share its device and timestamp.

```mermaid
erDiagram
    devices ||--o{ collection_runs : "collected by"
    collection_runs ||--o{ interface_snapshots : "interfaces"
    collection_runs ||--o{ vlan_observations : "vlans"
    collection_runs ||--o{ neighbor_observations : "neighbors"
    collection_runs ||--o{ mac_entries : "mac_table"
    collection_runs ||--o{ arp_entries : "arp_table"
    collection_runs ||--o{ route_entries : "routes"
    collection_runs ||--o{ stp_instance_observations : "stp"
    collection_runs ||--o{ stp_port_observations : "stp"
    collection_runs ||--o{ hsrp_observations : "hsrp"
    collection_runs ||--o{ ospf_neighbor_observations : "ospf"
    interfaces ||--o{ interface_snapshots : "state of"

    collection_runs {
        uuid id PK
        uuid device_id FK
        collection_kind kind
        collection_trigger trigger
        collection_status status
        timestamptz started_at
        timestamptz finished_at
        text error
    }
    interface_snapshots {
        bigint id PK
        timestamptz collected_at PK "= run.started_at"
        uuid run_id FK
        uuid device_id FK
        uuid interface_id FK
        bool admin_up
        bool oper_up
        switchport_mode switchport_mode
        int_array allowed_vlans
        bigint crc_errors
    }
    mac_entries {
        bigint id PK
        timestamptz collected_at PK
        uuid run_id FK
        int vlan_id
        macaddr mac
        uuid interface_id FK
    }
    arp_entries {
        bigint id PK
        timestamptz collected_at PK
        uuid run_id FK
        inet ip
        macaddr mac
        uuid interface_id FK
    }
```

The other observation tables (`vlan_observations`, `neighbor_observations`,
`route_entries`, `stp_instance_observations`, `stp_port_observations`, `hsrp_observations`,
`ospf_neighbor_observations`) have the same four leading columns
(`id`, `collected_at`, `run_id`, `device_id`).

## Monitoring, configuration and diagnosis

```mermaid
erDiagram
    devices ||--o{ metrics : "measured"
    interfaces |o--o{ metrics : "measured"
    devices |o--o{ events : "sent"
    devices ||--o{ alarms : "raised on"
    interfaces |o--o{ alarms : "raised on"
    incidents |o--o{ alarms : "groups"
    devices ||--o{ config_versions : "configured as"
    devices ||--o{ config_changes : "changed by"
    config_versions |o--o{ config_changes : "before / after"
    incidents |o--o{ findings : "explained by"
    devices |o--o{ findings : "about"

    metrics {
        timestamptz time
        uuid device_id FK
        uuid interface_id FK
        text name
        double value
    }
    events {
        bigint id PK
        timestamptz received_at PK
        inet source_ip
        uuid device_id FK
        event_kind kind
        text mnemonic
        text message
    }
    alarms {
        uuid id PK
        uuid device_id FK
        text rule_key
        severity severity
        alarm_state state
        text dedup_key "unique while not cleared"
        int occurrence_count
        uuid incident_id FK
    }
    incidents {
        uuid id PK
        text title
        incident_state state
    }
    config_versions {
        uuid id PK
        uuid device_id FK
        timestamptz collected_at
        text git_commit
        text content_hash "sha256"
    }
    config_changes {
        uuid id PK
        uuid device_id FK
        change_origin origin
        text username
        inet source_ip
        text_array commands
        uuid before_version_id FK
        uuid after_version_id FK
    }
    findings {
        uuid id PK
        uuid incident_id FK
        text kind
        severity severity
        jsonb evidence "reasoning chain"
        int score
    }
```

## Tables

### Entities

| Table | Purpose |
| --- | --- |
| `locations` | Places devices live in (campus > building > floor), maintained by users. |
| `devices` | One logical device (a stack or VSS pair is one), with type, role, OS, location and reachability. |
| `device_serials` | Chassis serial numbers → device; the de-duplication key for discovery. |
| `credential_profiles` | Named SSH / SNMPv3 credentials; secrets Fernet-encrypted ([ADR-0004](adr/0004-credentials-and-device-access.md)). |
| `interfaces` | Device interfaces by normalized name, with port-channel membership and the latest known state. |
| `interface_addresses` | IP addresses (with prefix) configured on interfaces; used for subnet → gateway lookups. |
| `links` | Physical links between two interfaces, stored once (a < b), from CDP/LLDP, inference or manual entry; inactive once no longer reported. |
| `jobs` | Long-running operations started through the API (device refresh, discovery): status, progress, error. |
| `discovery_runs` | One discovery run: seeds, allowed subnets, credential profiles, progress counters. |
| `topology_positions` | Saved node positions of the topology map per layer (one global layout until M7). |
| `discovery_run_items` | What a run did with each address: discovered, duplicate, auth_failed, unreachable, out_of_scope, unsupported_platform, no_mgmt_ip. |
| `collection_runs` | One row per collector execution: device, kind, trigger, status and timing; defines point-in-time state. |
| `alarms` | Problems with a lifecycle (open → acknowledged → cleared), deduplicated per `dedup_key`. |
| `incidents` | Groups of alarms attributed to one root cause by M6. |
| `config_versions` | Distinct device configurations: Git commit, normalized-content hash, size (text is in Git). |
| `config_changes` | Configuration changes made through the platform or outside it, with user, source IP and commands. |
| `findings` | Diagnosis results: root-cause candidates with explanation, evidence chain and score. |

### Observations (hypertables)

| Table | Written by run kind | Purpose |
| --- | --- | --- |
| `interface_snapshots` | `interfaces` | Per-interface status, speed/duplex, switchport mode and VLANs, error counters. |
| `vlan_observations` | `vlans` | VLANs defined on the device and their status. |
| `neighbor_observations` | `neighbors` | CDP/LLDP neighbours per local interface; links are derived from them. |
| `mac_entries` | `mac_table` | MAC address table: MAC → port per VLAN (host finder). |
| `arp_entries` | `arp_table` | ARP table: IP → MAC per interface (host finder). |
| `route_entries` | `routes` | Routing table, one row per next hop (L3 path tracing). |
| `stp_instance_observations` | `stp` | Per-VLAN spanning-tree root, root port, cost and topology-change count. |
| `stp_port_observations` | `stp` | Per-VLAN spanning-tree role and state of each port. |
| `hsrp_observations` | `hsrp` | HSRP groups: virtual IP, state, priority, active and standby routers. |
| `ospf_neighbor_observations` | `ospf` | OSPF adjacencies: neighbour router ID, address, interface, area, state. |
| `metrics` | (SNMP poller) | Narrow time series: one numeric sample per device/interface, metric name and time. |
| `events` | (syslog/trap receiver) | Raw syslog messages and SNMP traps with parsed fields. |

Run kinds `facts` and `config` write no observation table: `facts` updates `devices` and
`device_serials`; `config` writes `config_versions` when the configuration changed.

Which commands each kind runs, and which of them are required, is defined in
`backend/src/netops/inventory/collectors.py`.

### Names used in the proposal

| Proposal (section 6.4) | Here |
| --- | --- |
| `snapshot_id` | `collection_runs.id` (`run_id` on observations) |
| `vlans`, `stp_ports` | `vlan_observations`, `stp_instance_observations`, `stp_port_observations` |
| `routes`, `hsrp_groups` | `route_entries`, `hsrp_observations` |
| `svis` | `interfaces` with `kind = 'svi'` plus `interface_addresses` |
| `changes` | `config_changes` |
| `users`, `credentials`, `audit_log` | deferred to M7 |
