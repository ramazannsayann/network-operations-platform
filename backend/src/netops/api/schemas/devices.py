"""Devices and interfaces (M1/M2)."""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress, IPvAnyInterface

from netops.api.schemas import examples as ex
from netops.api.schemas.common import (
    ApiModel,
    DeviceRef,
    InterfaceRef,
    LocationRef,
    MacAddress,
    Page,
    VlanId,
    example,
)
from netops.db.enums import (
    CollectionKind,
    CollectionStatus,
    DeviceRole,
    DeviceType,
    DiscoverySource,
    Duplex,
    InterfaceKind,
    ManagementStatus,
    OsFamily,
    Reachability,
    SwitchportMode,
)

_ACC_SUMMARY: dict[str, Any] = {
    "id": ex.DEV_ACC_B2_03,
    "hostname": "sw-b2-03",
    "mgmt_ip": "10.0.0.23",
    "device_type": "switch",
    "role": "access",
    "vendor": "Cisco",
    "model": "WS-C2960X-48FPD-L",
    "os_family": "ios",
    "os_version": "15.2(7)E10",
    "location": ex.LOCATION_REF_FLOOR_2,
    "is_managed": True,
    "management_status": "managed",
    "reachability": "reachable",
    "discovered_via": "cdp",
    "serials": ["FOC2051X0AB"],
    "open_alarm_count": 1,
    "first_seen_at": ex.T_FIRST_SEEN,
    "last_seen_at": ex.T_RUN,
    "last_polled_at": ex.T_RUN,
}
_CORE_SUMMARY: dict[str, Any] = {
    "id": ex.DEV_CORE_1,
    "hostname": "core-sw-1",
    "mgmt_ip": "10.0.0.1",
    "device_type": "l3_switch",
    "role": "core",
    "vendor": "Cisco",
    "model": "C9500-24Y4C",
    "os_family": "iosxe",
    "os_version": "17.12.4",
    "location": {"id": ex.LOC_CAMPUS, "name": "Main campus", "path": "Main campus"},
    "is_managed": True,
    "management_status": "managed",
    "reachability": "reachable",
    "discovered_via": "seed",
    "serials": ["FDO2312A1BC"],
    "open_alarm_count": 0,
    "first_seen_at": ex.T_FIRST_SEEN,
    "last_seen_at": ex.T_RUN,
    "last_polled_at": ex.T_RUN,
}


class DeviceSummary(ApiModel):
    model_config = example(_ACC_SUMMARY)

    id: UUID
    hostname: str | None
    mgmt_ip: IPvAnyAddress | None
    device_type: DeviceType
    role: DeviceRole
    vendor: str | None
    model: str | None
    os_family: OsFamily
    os_version: str | None
    location: LocationRef | None
    is_managed: bool
    management_status: ManagementStatus = Field(
        description="Why the platform does (not) manage the device. Discovery also lists "
        "devices it does not log in to (out of scope, wrong credentials, access points...)."
    )
    reachability: Reachability
    discovered_via: DiscoverySource
    serials: list[str]
    open_alarm_count: int = Field(ge=0, description="Open or acknowledged alarms.")
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    last_polled_at: AwareDatetime | None


class DeviceSerial(ApiModel):
    model_config = example({"serial": "FOC2051X0AB", "stack_member": 1})

    serial: str
    stack_member: int | None = Field(description="Switch number in a stack/VSS; NULL if alone.")


class CollectionFreshness(ApiModel):
    """How current one kind of collected data is for a device."""

    model_config = example(
        {
            "kind": "mac_table",
            "last_status": "success",
            "last_started_at": ex.T_RUN,
            "last_success_at": ex.T_RUN,
        }
    )

    kind: CollectionKind
    last_status: CollectionStatus
    last_started_at: AwareDatetime
    last_success_at: AwareDatetime | None


class Device(DeviceSummary):
    model_config = example(
        _ACC_SUMMARY
        | {
            "serials": ["FOC2051X0AB"],
            "serial_details": [{"serial": "FOC2051X0AB", "stack_member": None}],
            "sys_object_id": "1.3.6.1.4.1.9.1.1208",
            "interface_count": 52,
            "collections": [
                {
                    "kind": "interfaces",
                    "last_status": "success",
                    "last_started_at": ex.T_RUN,
                    "last_success_at": ex.T_RUN,
                },
                {
                    "kind": "mac_table",
                    "last_status": "failed",
                    "last_started_at": ex.T_RUN,
                    "last_success_at": "2026-10-09T07:40:00Z",
                },
            ],
        }
    )

    serial_details: list[DeviceSerial]
    sys_object_id: str | None
    interface_count: int = Field(ge=0)
    collections: list[CollectionFreshness] = Field(
        description="Latest run per collection kind, so the UI can show how fresh the data is."
    )


class DevicePage(Page[DeviceSummary]):
    model_config = example(ex.page([_CORE_SUMMARY, _ACC_SUMMARY], total=6))


class DeviceRefreshRequest(ApiModel):
    model_config = example({"kinds": ["interfaces", "mac_table", "arp_table"]})

    kinds: list[CollectionKind] | None = Field(
        default=None, description="What to collect now; all supported kinds when omitted."
    )


# --- Interfaces -----------------------------------------------------------------------------

_HOST_PORT_STATE: dict[str, Any] = {
    "observed_at": ex.T_RUN,
    "run_id": ex.RUN_IF_ACC_B2_03,
    "admin_up": True,
    "oper_up": True,
    "speed_mbps": 1000,
    "duplex": "full",
    "mtu": 1500,
    "switchport_mode": "access",
    "access_vlan": 20,
    "native_vlan": None,
    "allowed_vlans": None,
    "err_disabled_reason": None,
    "in_errors": 0,
    "crc_errors": 0,
    "late_collisions": 0,
}
_HOST_PORT: dict[str, Any] = {
    "id": ex.IF_ACC_GI1_0_17,
    "device_id": ex.DEV_ACC_B2_03,
    "name": "Gi1/0/17",
    "name_normalized": "GigabitEthernet1/0/17",
    "kind": "physical",
    "description": "B214 desk 2",
    "mac": "70:1f:53:4a:10:11",
    "parent_interface_id": None,
    "state": _HOST_PORT_STATE,
}
_UPLINK: dict[str, Any] = {
    "id": ex.IF_ACC_GI1_0_49,
    "device_id": ex.DEV_ACC_B2_03,
    "name": "Gi1/0/49",
    "name_normalized": "GigabitEthernet1/0/49",
    "kind": "physical",
    "description": "uplink dist-sw-b Gi1/0/3",
    "mac": "70:1f:53:4a:10:31",
    "parent_interface_id": None,
    "state": _HOST_PORT_STATE
    | {
        "switchport_mode": "trunk",
        "access_vlan": None,
        "native_vlan": 99,
        "allowed_vlans": [20, 30, 99],
        "in_errors": 12,
        "crc_errors": 12,
    },
}


class InterfaceState(ApiModel):
    """Interface state from one ``interfaces`` collection run."""

    model_config = example(_HOST_PORT_STATE)

    observed_at: AwareDatetime = Field(description="collected_at of the snapshot used.")
    run_id: UUID
    admin_up: bool | None
    oper_up: bool | None
    speed_mbps: int | None
    duplex: Duplex | None
    mtu: int | None
    switchport_mode: SwitchportMode | None
    access_vlan: VlanId | None
    native_vlan: VlanId | None
    allowed_vlans: list[VlanId] | None = Field(description="Fully expanded list.")
    err_disabled_reason: str | None
    in_errors: int | None
    crc_errors: int | None
    late_collisions: int | None


class InterfaceSummary(ApiModel):
    model_config = example(_HOST_PORT)

    id: UUID
    device_id: UUID
    name: str = Field(description='As reported by the device, e.g. "Gi1/0/17".')
    name_normalized: str = Field(description='Canonical long form, e.g. "GigabitEthernet1/0/17".')
    kind: InterfaceKind
    description: str | None
    mac: MacAddress | None
    parent_interface_id: UUID | None = Field(description="Port-channel this port is a member of.")
    state: InterfaceState | None = Field(description="NULL if never collected before `at`.")


class InterfacePage(Page[InterfaceSummary]):
    model_config = example(ex.page([_HOST_PORT, _UPLINK], total=52))


class InterfaceAddress(ApiModel):
    model_config = example({"address": "10.0.20.2/24", "is_secondary": False})

    address: IPvAnyInterface = Field(description="Address with prefix length.")
    is_secondary: bool


class InterfaceDetail(InterfaceSummary):
    model_config = example(
        _UPLINK
        | {
            "device": ex.DEVICE_REF_ACC_B2_03,
            "addresses": [],
            "neighbor": {
                "device": ex.DEVICE_REF_DIST_B,
                "interface": ex.INTERFACE_REF_DIST_DOWNLINK,
                "link_id": ex.LINK_ACC_DIST,
            },
            "members": [],
        }
    )

    device: DeviceRef
    addresses: list[InterfaceAddress]
    neighbor: "LinkPeer | None" = Field(description="Far end of the physical link, if known.")
    members: list[InterfaceRef] = Field(description="Member ports, for a port-channel.")


class LinkPeer(ApiModel):
    model_config = example(
        {
            "device": ex.DEVICE_REF_DIST_B,
            "interface": ex.INTERFACE_REF_DIST_DOWNLINK,
            "link_id": ex.LINK_ACC_DIST,
        }
    )

    device: DeviceRef
    interface: InterfaceRef
    link_id: UUID


InterfaceDetail.model_rebuild()
