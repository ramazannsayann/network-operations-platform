"""Topology graph (M1): L2 (physical links) and L3 (devices and subnets)."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyNetwork

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, InterfaceRef, example
from netops.db.enums import DeviceRole, DeviceType, LinkSource, Reachability


class TopologyLayer(StrEnum):
    L2 = "l2"
    L3 = "l3"


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
    "out_of_scope": False,
    "prefix": None,
}
_DIST_NODE: dict[str, Any] = _CORE_NODE | {
    "id": ex.DEV_DIST_B,
    "label": "dist-sw-b",
    "device_id": ex.DEV_DIST_B,
    "role": "distribution",
    "location_id": ex.LOC_B_BLOCK,
}
_ACC_NODE: dict[str, Any] = _CORE_NODE | {
    "id": ex.DEV_ACC_B2_03,
    "label": "sw-b2-03",
    "device_id": ex.DEV_ACC_B2_03,
    "device_type": "switch",
    "role": "access",
    "location_id": ex.LOC_B_FLOOR_2,
}
_AP_NODE: dict[str, Any] = _CORE_NODE | {
    "id": ex.DEV_AP_B2_01,
    "label": "ap-b2-01",
    "device_id": ex.DEV_AP_B2_01,
    "device_type": "ap",
    "role": "access",
    "location_id": ex.LOC_B_FLOOR_2,
    "reachability": "unknown",
    "is_managed": False,
}
_ISP_NODE: dict[str, Any] = _CORE_NODE | {
    "id": "neighbor:198.51.100.1",
    "label": "isp-ce-1",
    "device_id": None,
    "device_type": "router",
    "role": "edge",
    "location_id": None,
    "reachability": "unknown",
    "is_managed": False,
    "out_of_scope": True,
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


class TopologyNode(ApiModel):
    model_config = example(_ACC_NODE, _ISP_NODE)

    id: str = Field(description="Device id, subnet prefix, or a synthetic id for neighbours.")
    kind: NodeKind
    label: str
    device_id: UUID | None
    device_type: DeviceType | None
    role: DeviceRole | None
    location_id: UUID | None
    reachability: Reachability | None
    is_managed: bool
    out_of_scope: bool = Field(description="Seen as a neighbour outside the allowed subnets.")
    prefix: IPvAnyNetwork | None = Field(description="For subnet nodes (L3).")


class EdgeMember(ApiModel):
    model_config = example(_ETHERCHANNEL_EDGE["members"][0])

    link_id: UUID
    source_interface: InterfaceRef
    target_interface: InterfaceRef
    is_active: bool


class TopologyEdge(ApiModel):
    model_config = example(_ETHERCHANNEL_EDGE, _ACCESS_EDGE)

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


class Topology(ApiModel):
    model_config = example(
        {
            "layer": "l2",
            "at": ex.T_NOW,
            "nodes": [_CORE_NODE, _DIST_NODE, _ACC_NODE, _AP_NODE, _ISP_NODE],
            "edges": [_ETHERCHANNEL_EDGE, _ACCESS_EDGE, _AP_EDGE],
        }
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
