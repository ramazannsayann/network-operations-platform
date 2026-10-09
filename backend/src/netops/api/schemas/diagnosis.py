"""Path trace (FR-13) and impact analysis (FR-16) of the diagnosis module (M6)."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress, IPvAnyNetwork

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, InterfaceRef, VlanId, example
from netops.db.enums import HsrpState, RouteProtocol


class HopLayer(StrEnum):
    L2 = "l2"
    L3 = "l3"


class PathStatus(StrEnum):
    COMPLETE = "complete"  # reached the destination
    INCOMPLETE = "incomplete"  # stopped early; see warnings


class PathWarningCode(StrEnum):
    POLICY_NOT_EVALUATED = "policy_not_evaluated"  # ACLs/firewall rules are never evaluated
    STALE_DATA = "stale_data"  # a hop is based on old collection runs
    UNMANAGED_HOP = "unmanaged_hop"  # the path crosses a device we cannot read
    ECMP = "ecmp"  # equal-cost routes: one of several paths is shown
    NO_ROUTE = "no_route"
    DESTINATION_NOT_FOUND = "destination_not_found"


class PathTraceRequest(ApiModel):
    model_config = example({"source": "10.0.20.57", "destination": "10.0.40.12", "at": None})

    source: IPvAnyAddress
    destination: IPvAnyAddress
    at: AwareDatetime | None = Field(default=None, description="Trace at this time; now if NULL.")


class GatewayInfo(ApiModel):
    model_config = example(
        {
            "virtual_ip": "10.0.20.1",
            "hsrp_group": 20,
            "hsrp_state": "active",
            "active_router": "10.0.20.2",
            "standby_router": "10.0.20.3",
        }
    )

    virtual_ip: IPvAnyAddress
    hsrp_group: int | None
    hsrp_state: HsrpState | None = Field(description="State of this hop's device in the group.")
    active_router: IPvAnyAddress | None
    standby_router: IPvAnyAddress | None


class RoutingDecision(ApiModel):
    model_config = example(
        {
            "prefix": "10.0.40.0/24",
            "protocol": "connected",
            "next_hop": None,
            "admin_distance": 0,
            "metric": 0,
            "vrf": None,
        }
    )

    prefix: IPvAnyNetwork = Field(description="The matching (longest-prefix) route.")
    protocol: RouteProtocol
    next_hop: IPvAnyAddress | None
    admin_distance: int | None
    metric: int | None
    vrf: str | None


_GATEWAY_HOP: dict[str, Any] = {
    "index": 2,
    "layer": "l3",
    "device": ex.DEVICE_REF_CORE_1,
    "in_interface": ex.INTERFACE_REF_CORE1_VL20,
    "out_interface": ex.INTERFACE_REF_CORE1_VL40,
    "vlan_id": 40,
    "gateway": {
        "virtual_ip": "10.0.20.1",
        "hsrp_group": 20,
        "hsrp_state": "active",
        "active_router": "10.0.20.2",
        "standby_router": "10.0.20.3",
    },
    "routing": {
        "prefix": "10.0.40.0/24",
        "protocol": "connected",
        "next_hop": None,
        "admin_distance": 0,
        "metric": 0,
        "vrf": None,
    },
    "observed_at": ex.T_RUN,
}


class PathHop(ApiModel):
    model_config = example(_GATEWAY_HOP)

    index: int = Field(ge=0, description="Position on the path, from 0 at the source.")
    layer: HopLayer
    device: DeviceRef
    in_interface: InterfaceRef | None
    out_interface: InterfaceRef | None
    vlan_id: VlanId | None
    gateway: GatewayInfo | None = Field(description="Set where the packet is routed by a gateway.")
    routing: RoutingDecision | None = Field(description="Set on L3 hops.")
    observed_at: AwareDatetime = Field(description="Oldest collection run this hop relies on.")


class PathWarning(ApiModel):
    model_config = example(
        {
            "code": "policy_not_evaluated",
            "message": "ACLs and firewall rules are not evaluated; a policy may still drop "
            "this traffic.",
        }
    )

    code: PathWarningCode
    message: str


_HOPS: list[dict[str, Any]] = [
    {
        "index": 0,
        "layer": "l2",
        "device": ex.DEVICE_REF_ACC_B2_03,
        "in_interface": ex.INTERFACE_REF_HOST_PORT,
        "out_interface": ex.INTERFACE_REF_ACC_UPLINK,
        "vlan_id": 20,
        "gateway": None,
        "routing": None,
        "observed_at": ex.T_RUN,
    },
    {
        "index": 1,
        "layer": "l2",
        "device": ex.DEVICE_REF_DIST_B,
        "in_interface": ex.INTERFACE_REF_DIST_DOWNLINK,
        "out_interface": ex.INTERFACE_REF_DIST_PO1,
        "vlan_id": 20,
        "gateway": None,
        "routing": None,
        "observed_at": ex.T_RUN,
    },
    _GATEWAY_HOP,
]


class PathTrace(ApiModel):
    model_config = example(
        {
            "source": "10.0.20.57",
            "destination": "10.0.40.12",
            "at": ex.T_NOW,
            "status": "complete",
            "hops": _HOPS,
            "warnings": [
                {
                    "code": "policy_not_evaluated",
                    "message": "ACLs and firewall rules are not evaluated; a policy may "
                    "still drop this traffic.",
                }
            ],
        }
    )

    source: IPvAnyAddress
    destination: IPvAnyAddress
    at: AwareDatetime
    status: PathStatus
    hops: list[PathHop]
    warnings: list[PathWarning]


class ImpactTarget(ApiModel):
    model_config = example({"device_id": ex.DEV_DIST_B, "link_id": None})

    device_id: UUID | None
    link_id: UUID | None


class ImpactAnalysis(ApiModel):
    """Devices that lose reachability from the platform if the target fails (FR-16)."""

    model_config = example(
        {
            "target": {"device_id": ex.DEV_DIST_B, "link_id": None},
            "at": ex.T_NOW,
            "reference_point": ex.DEVICE_REF_CORE_1,
            "unreachable_devices": [ex.DEVICE_REF_ACC_B2_03, ex.DEVICE_REF_AP_B2_01],
        }
    )

    target: ImpactTarget
    at: AwareDatetime
    reference_point: DeviceRef = Field(
        description="Where the platform attaches to the network; reachability is measured from it."
    )
    unreachable_devices: list[DeviceRef]
