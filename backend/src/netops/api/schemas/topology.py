"""Topology graph (M1): L2 (physical links) and L3 (devices and subnets)."""

from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress, IPvAnyInterface, IPvAnyNetwork

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, InterfaceRef, example
from netops.db.enums import (
    DeviceRole,
    DeviceType,
    HsrpState,
    LinkSource,
    ManagementStatus,
    Reachability,
    TopologyLayer,
)

__all__ = ["TopologyLayer"]


class NodeKind(StrEnum):
    DEVICE = "device"
    SUBNET = "subnet"  # L3 only


class EdgeKind(StrEnum):
    LINK = "link"  # one physical link (L2)
    ETHERCHANNEL = "etherchannel"  # bundled links collapsed into one edge (L2)
    SUBNET_MEMBER = "subnet_member"  # device interface in a subnet (L3)


_CORE_NODE: dict[str, Any] = {
    "id": ex.DEV_CORE_1,
    "kind": "device",
    "label": "core-sw-1",
    "device_id": ex.DEV_CORE_1,
    "device_type": "l3_switch",
    "role": "core",
    "location_id": ex.LOC_CAMPUS,
    "reachability": "reachable",
    "is_managed": True,
    "management_status": "managed",
    "out_of_scope": False,
    "mgmt_ip": "10.0.0.1",
    "model": "C9500-24Y4C",
    "open_alarm_count": 0,
    "prefix": None,
    "gateway_ips": [],
}
_DIST_NODE: dict[str, Any] = _CORE_NODE | {
    "id": ex.DEV_DIST_B,
    "label": "dist-sw-b",
    "device_id": ex.DEV_DIST_B,
    "role": "distribution",
    "location_id": ex.LOC_B_BLOCK,
    "mgmt_ip": "10.0.0.11",
    "model": "C9300-24T",
}
_ACC_NODE: dict[str, Any] = _CORE_NODE | {
    "id": ex.DEV_ACC_B2_03,
    "label": "sw-b2-03",
    "device_id": ex.DEV_ACC_B2_03,
    "device_type": "switch",
    "role": "access",
    "location_id": ex.LOC_B_FLOOR_2,
    "mgmt_ip": "10.0.0.23",
    "model": "WS-C2960X-48FPD-L",
    "open_alarm_count": 1,
}
_AP_NODE: dict[str, Any] = _CORE_NODE | {
    "id": ex.DEV_AP_B2_01,
    "label": "ap-b2-01",
    "device_id": ex.DEV_AP_B2_01,
    "device_type": "ap",
    "role": "unknown",
    "location_id": ex.LOC_B_FLOOR_2,
    "reachability": "unknown",
    "is_managed": False,
    "management_status": "unsupported_platform",
    "mgmt_ip": "10.0.30.41",
    "model": "AIR-AP2802I-E-K9",
}
_ISP_NODE: dict[str, Any] = _CORE_NODE | {
    "id": ex.DEV_ISP_CE_1,
    "label": "isp-ce-1",
    "device_id": ex.DEV_ISP_CE_1,
    "device_type": "router",
    "role": "unknown",
    "location_id": None,
    "reachability": "unknown",
    "is_managed": False,
    "management_status": "out_of_scope",
    "out_of_scope": True,
    "mgmt_ip": "198.51.100.1",
    "model": "ISR4331/K9",
}
_SUBNET_NODE: dict[str, Any] = {
    "id": "10.0.20.0/24",
    "kind": "subnet",
    "label": "10.0.20.0/24",
    "device_id": None,
    "device_type": None,
    "role": None,
    "location_id": None,
    "reachability": None,
    "is_managed": False,
    "management_status": None,
    "out_of_scope": False,
    "mgmt_ip": None,
    "model": None,
    "open_alarm_count": 0,
    "prefix": "10.0.20.0/24",
    "gateway_ips": ["10.0.20.1"],
}
_ETHERCHANNEL_EDGE: dict[str, Any] = {
    "id": f"etherchannel:{ex.IF_CORE1_PO1}:{ex.IF_DIST_PO1}",
    "kind": "etherchannel",
    "source": ex.DEV_CORE_1,
    "target": ex.DEV_DIST_B,
    "source_interface": ex.INTERFACE_REF_CORE1_PO1,
    "target_interface": ex.INTERFACE_REF_DIST_PO1,
    "link_source": "cdp",
    "is_active": True,
    "members": [
        {
            "link_id": ex.LINK_DIST_CORE_A,
            "source_interface": {
                "id": ex.IF_CORE1_TE1_0_1,
                "device_id": ex.DEV_CORE_1,
                "name": "Te1/0/1",
            },
            "target_interface": {
                "id": ex.IF_DIST_TE1_1_1,
                "device_id": ex.DEV_DIST_B,
                "name": "Te1/1/1",
            },
            "is_active": True,
        },
        {
            "link_id": ex.LINK_DIST_CORE_B,
            "source_interface": {
                "id": ex.IF_CORE1_TE1_0_2,
                "device_id": ex.DEV_CORE_1,
                "name": "Te1/0/2",
            },
            "target_interface": {
                "id": ex.IF_DIST_TE1_1_2,
                "device_id": ex.DEV_DIST_B,
                "name": "Te1/1/2",
            },
            "is_active": False,
        },
    ],
    "link_id": None,
    "address": None,
    "hsrp_state": None,
}
_ACCESS_EDGE: dict[str, Any] = {
    "id": ex.LINK_ACC_DIST,
    "kind": "link",
    "source": ex.DEV_DIST_B,
    "target": ex.DEV_ACC_B2_03,
    "source_interface": ex.INTERFACE_REF_DIST_DOWNLINK,
    "target_interface": ex.INTERFACE_REF_ACC_UPLINK,
    "link_source": "cdp",
    "is_active": True,
    "members": [],
    "link_id": ex.LINK_ACC_DIST,
    "address": None,
    "hsrp_state": None,
}
_AP_EDGE: dict[str, Any] = _ACCESS_EDGE | {
    "id": "link:ap-b2-01",
    "source": ex.DEV_ACC_B2_03,
    "target": ex.DEV_AP_B2_01,
    "source_interface": {"id": ex.IF_ACC_GI1_0_5, "device_id": ex.DEV_ACC_B2_03, "name": "Gi1/0/5"},
    "target_interface": None,
    "link_source": "lldp",
    "link_id": None,
}


_SUBNET_EDGE: dict[str, Any] = {
    "id": f"member:{ex.IF_CORE1_VL20}:10.0.20.0/24",
    "kind": "subnet_member",
    "source": ex.DEV_CORE_1,
    "target": "10.0.20.0/24",
    "source_interface": {"id": ex.IF_CORE1_VL20, "device_id": ex.DEV_CORE_1, "name": "Vlan20"},
    "target_interface": None,
    "link_source": None,
    "is_active": True,
    "members": [],
    "link_id": None,
    "address": "10.0.20.2/24",
    "hsrp_state": "active",
}


class TopologyNode(ApiModel):
    model_config = example(_ACC_NODE, _ISP_NODE, _SUBNET_NODE)

    id: str = Field(description="The device id, or the prefix of a subnet node (L3).")
    kind: NodeKind
    label: str
    device_id: UUID | None
    device_type: DeviceType | None
    role: DeviceRole | None
    location_id: UUID | None
    reachability: Reachability | None
    is_managed: bool
    management_status: ManagementStatus | None = Field(
        description="Why the device is (not) managed; NULL for subnet nodes."
    )
    out_of_scope: bool = Field(description="Seen as a neighbour outside the allowed subnets.")
    mgmt_ip: IPvAnyAddress | None
    model: str | None
    open_alarm_count: int = Field(ge=0, description="Open alarms (always 0 until M3).")
    prefix: IPvAnyNetwork | None = Field(description="For subnet nodes (L3).")
    gateway_ips: list[IPvAnyAddress] = Field(
        description="HSRP virtual gateway addresses in the subnet (L3 subnet nodes)."
    )


class EdgeMember(ApiModel):
    model_config = example(_ETHERCHANNEL_EDGE["members"][0])

    link_id: UUID
    source_interface: InterfaceRef
    target_interface: InterfaceRef
    is_active: bool


class TopologyEdge(ApiModel):
    model_config = example(_ETHERCHANNEL_EDGE, _ACCESS_EDGE, _SUBNET_EDGE)

    id: str
    kind: EdgeKind
    source: str = Field(description="Node id.")
    target: str = Field(description="Node id.")
    source_interface: InterfaceRef | None
    target_interface: InterfaceRef | None
    link_source: LinkSource | None
    is_active: bool
    members: list[EdgeMember] = Field(description="Member links of an EtherChannel edge.")
    link_id: UUID | None = Field(description="The links row, for single-link edges.")
    address: IPvAnyInterface | None = Field(
        description="L3: the device's address (with prefix length) in the subnet."
    )
    hsrp_state: HsrpState | None = Field(
        description="L3: the device's HSRP state in the subnet; 'active' marks the router "
        "that currently answers for the gateway address."
    )


class Topology(ApiModel):
    model_config = example(
        {
            "layer": "l2",
            "at": ex.T_NOW,
            "nodes": [_CORE_NODE, _DIST_NODE, _ACC_NODE, _AP_NODE, _ISP_NODE],
            "edges": [_ETHERCHANNEL_EDGE, _ACCESS_EDGE, _AP_EDGE],
        },
        {
            "layer": "l3",
            "at": ex.T_NOW,
            "nodes": [_CORE_NODE, _SUBNET_NODE],
            "edges": [_SUBNET_EDGE],
        },
    )

    layer: TopologyLayer
    at: AwareDatetime = Field(description="The point in time the graph describes.")
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


class DeviceChange(ApiModel):
    model_config = example({"device": ex.DEVICE_REF_AP_B2_01, "at": "2026-10-08T23:10:00Z"})

    device: DeviceRef
    at: AwareDatetime = Field(description="First seen (added) or last seen (removed).")


class LinkChange(ApiModel):
    model_config = example(
        {
            "link_id": ex.LINK_ACC_DIST,
            "a": {"device": ex.DEVICE_REF_DIST_B, "interface": ex.INTERFACE_REF_DIST_DOWNLINK},
            "b": {"device": ex.DEVICE_REF_ACC_B2_03, "interface": ex.INTERFACE_REF_ACC_UPLINK},
            "link_source": "cdp",
            "at": ex.T_INCIDENT,
        }
    )

    link_id: UUID
    a: "LinkEnd"
    b: "LinkEnd"
    link_source: LinkSource
    at: AwareDatetime


class LinkEnd(ApiModel):
    model_config = example(
        {"device": ex.DEVICE_REF_DIST_B, "interface": ex.INTERFACE_REF_DIST_DOWNLINK}
    )

    device: DeviceRef
    interface: InterfaceRef


LinkChange.model_rebuild()


# --- Saved map layout ---------------------------------------------------------------------

Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1e6, le=1e6)]


class NodePosition(ApiModel):
    model_config = example({"node_id": ex.DEV_CORE_1, "x": 420.0, "y": 80.0})

    node_id: str = Field(
        min_length=1, max_length=64, description="A device id, or a subnet prefix (L3)."
    )
    x: Coordinate
    y: Coordinate


class TopologyLayoutUpdate(ApiModel):
    model_config = example(
        {
            "positions": [
                {"node_id": ex.DEV_CORE_1, "x": 420.0, "y": 80.0},
                {"node_id": ex.DEV_ACC_B2_03, "x": 300.0, "y": 320.0},
            ]
        }
    )

    positions: list[NodePosition] = Field(
        max_length=5000,
        description="Replaces the saved positions of the layer; an empty list resets it "
        "to the automatic layout.",
    )


class TopologyLayout(ApiModel):
    model_config = example(
        {
            "layer": "l2",
            "positions": [
                {"node_id": ex.DEV_CORE_1, "x": 420.0, "y": 80.0},
                {"node_id": ex.DEV_ACC_B2_03, "x": 300.0, "y": 320.0},
            ],
            "updated_at": ex.T_RUN,
        }
    )

    layer: TopologyLayer
    positions: list[NodePosition]
    updated_at: AwareDatetime | None = Field(description="NULL if never saved.")


class TopologyChanges(ApiModel):
    """Topology drift between ``since`` and ``until`` (proposal 7.1, step 8)."""

    model_config = example(
        {
            "since": "2026-10-08T00:00:00Z",
            "until": ex.T_NOW,
            "added_devices": [{"device": ex.DEVICE_REF_AP_B2_01, "at": "2026-10-08T23:10:00Z"}],
            "removed_devices": [],
            "added_links": [],
            "removed_links": [
                {
                    "link_id": ex.LINK_ACC_DIST,
                    "a": {
                        "device": ex.DEVICE_REF_DIST_B,
                        "interface": ex.INTERFACE_REF_DIST_DOWNLINK,
                    },
                    "b": {
                        "device": ex.DEVICE_REF_ACC_B2_03,
                        "interface": ex.INTERFACE_REF_ACC_UPLINK,
                    },
                    "link_source": "cdp",
                    "at": ex.T_INCIDENT,
                }
            ],
        }
    )

    since: AwareDatetime
    until: AwareDatetime
    added_devices: list[DeviceChange]
    removed_devices: list[DeviceChange]
    added_links: list[LinkChange]
    removed_links: list[LinkChange]
