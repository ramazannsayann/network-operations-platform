"""Host locator (M6, FR-12): from an IP or MAC address to the edge port it is connected to."""

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress

from netops.api.schemas import examples as ex
from netops.api.schemas.common import (
    ApiModel,
    DeviceRef,
    InterfaceRef,
    LocationRef,
    MacAddress,
    VlanId,
    example,
)
from netops.db.enums import CollectionKind


class QueryKind(StrEnum):
    IP = "ip"
    MAC = "mac"


class Connection(StrEnum):
    WIRED = "wired"
    WIRELESS = "wireless"


class WirelessMode(StrEnum):
    """Proposal 7.6: where a wireless client's MAC appears on the wired network."""

    CENTRAL = "central"  # tunnelled to the controller: seen on the controller's port
    LOCAL = "local"  # locally switched (FlexConnect): seen on the AP's port


class NotFoundReason(StrEnum):
    NO_ARP_ENTRY = "no_arp_entry"  # IP not in any ARP table: host off or silent
    MAC_NOT_LEARNED = "mac_not_learned"  # MAC aged out of every MAC table (silent host)
    ONLY_ON_UPLINKS = "only_on_uplinks"  # MAC seen only on ports facing other devices
    OUTSIDE_MANAGED_NETWORK = "outside_managed_network"  # no managed gateway for the subnet


class HostEvidence(ApiModel):
    """One table entry the answer is based on, with the run that collected it."""

    model_config = example(
        {
            "source": "arp_table",
            "run_id": ex.RUN_ARP_CORE_1,
            "collected_at": ex.T_RUN,
            "device": ex.DEVICE_REF_CORE_1,
            "interface": ex.INTERFACE_REF_CORE1_VL20,
            "vlan_id": 20,
            "ip": "10.0.20.57",
            "mac": "3c:52:82:6e:41:9a",
            "used": True,
            "note": "Gateway ARP entry: 10.0.20.57 is 3c:52:82:6e:41:9a",
        }
    )

    source: CollectionKind = Field(description="arp_table or mac_table.")
    run_id: UUID
    collected_at: AwareDatetime
    device: DeviceRef
    interface: InterfaceRef | None
    vlan_id: VlanId | None
    ip: IPvAnyAddress | None
    mac: MacAddress
    used: bool = Field(description="False for entries that were looked at and ruled out.")
    note: str


class EdgePort(ApiModel):
    model_config = example(
        {
            "device": ex.DEVICE_REF_ACC_B2_03,
            "interface": ex.INTERFACE_REF_HOST_PORT,
            "location": ex.LOCATION_REF_FLOOR_2,
        }
    )

    device: DeviceRef
    interface: InterfaceRef
    location: LocationRef | None


class WirelessAttachment(ApiModel):
    model_config = example(
        {"mode": "local", "access_point": ex.DEVICE_REF_AP_B2_01, "controller": None}
    )

    mode: WirelessMode
    access_point: DeviceRef | None = Field(description="Known for locally switched clients.")
    controller: DeviceRef | None = Field(description="Known for centrally switched clients.")


_EVIDENCE: list[dict[str, Any]] = [
    {
        "source": "arp_table",
        "run_id": ex.RUN_ARP_CORE_1,
        "collected_at": ex.T_RUN,
        "device": ex.DEVICE_REF_CORE_1,
        "interface": ex.INTERFACE_REF_CORE1_VL20,
        "vlan_id": 20,
        "ip": "10.0.20.57",
        "mac": "3c:52:82:6e:41:9a",
        "used": True,
        "note": "Gateway ARP entry: 10.0.20.57 is 3c:52:82:6e:41:9a",
    },
    {
        "source": "mac_table",
        "run_id": ex.RUN_MAC_DIST_B,
        "collected_at": ex.T_RUN,
        "device": ex.DEVICE_REF_DIST_B,
        "interface": ex.INTERFACE_REF_DIST_DOWNLINK,
        "vlan_id": 20,
        "ip": None,
        "mac": "3c:52:82:6e:41:9a",
        "used": False,
        "note": "Gi1/0/3 is the link to sw-b2-03, not an edge port",
    },
    {
        "source": "mac_table",
        "run_id": ex.RUN_MAC_ACC_B2_03,
        "collected_at": ex.T_RUN,
        "device": ex.DEVICE_REF_ACC_B2_03,
        "interface": ex.INTERFACE_REF_HOST_PORT,
        "vlan_id": 20,
        "ip": None,
        "mac": "3c:52:82:6e:41:9a",
        "used": True,
        "note": "Edge port: no neighbouring device on Gi1/0/17",
    },
]
FOUND_EXAMPLE: dict[str, Any] = {
    "status": "found",
    "query": "10.0.20.57",
    "query_kind": "ip",
    "at": ex.T_NOW,
    "ip": "10.0.20.57",
    "mac": "3c:52:82:6e:41:9a",
    "vlan_id": 20,
    "connection": "wired",
    "edge": {
        "device": ex.DEVICE_REF_ACC_B2_03,
        "interface": ex.INTERFACE_REF_HOST_PORT,
        "location": ex.LOCATION_REF_FLOOR_2,
    },
    "wireless": None,
    "evidence": _EVIDENCE,
}
NOT_FOUND_EXAMPLE: dict[str, Any] = {
    "status": "not_found",
    "query": "10.0.20.199",
    "query_kind": "ip",
    "at": ex.T_NOW,
    "reason": "no_arp_entry",
    "detail": "No ARP entry for 10.0.20.199 on its gateway core-sw-1 (Vlan20) after a ping. "
    "The host is probably switched off or not on the network.",
    "evidence": [],
}


class HostFound(ApiModel):
    model_config = example(FOUND_EXAMPLE)

    status: Literal["found"]
    query: str
    query_kind: QueryKind
    at: AwareDatetime
    ip: IPvAnyAddress | None
    mac: MacAddress
    vlan_id: VlanId | None
    connection: Connection
    edge: EdgePort = Field(
        description="Where the host plugs in; for wireless clients, the AP's or controller's port."
    )
    wireless: WirelessAttachment | None
    evidence: list[HostEvidence]


class HostNotFound(ApiModel):
    model_config = example(NOT_FOUND_EXAMPLE)

    status: Literal["not_found"]
    query: str
    query_kind: QueryKind
    at: AwareDatetime
    reason: NotFoundReason
    detail: str = Field(description="Explanation to show the user.")
    evidence: list[HostEvidence] = Field(description="Entries that were checked and ruled out.")


HostLocateResult = Annotated[HostFound | HostNotFound, Field(discriminator="status")]
