"""Example data for the OpenAPI contract: one small, fictional campus network.

Every schema's example is built from these values so that the mock server (Prism) returns
data that hangs together across endpoints. Addresses are from private (10.0.0.0/8) or
documentation (192.0.2.0/24, 198.51.100.0/24) ranges; names, MACs and serials are made up.

    core-sw-1 / core-sw-2   L3 core pair, HSRP gateway 10.0.20.1 for VLAN 20 (staff)
    dist-sw-b               distribution switch of B Block, Po1 up to core-sw-1
    sw-b2-03                access switch, B Block floor 2; host 10.0.20.57 on Gi1/0/17
    ap-b2-01                access point on sw-b2-03 Gi1/0/5 (not managed)
    fw-1                    pfSense edge firewall (SNMP only)
    isp-ce-1                provider router, CDP neighbour outside the allowed subnets
"""

from typing import Any


def _id(n: int) -> str:
    return f"5e0c7a1d-0000-4000-8000-{n:012d}"


# --- Identifiers ---------------------------------------------------------------------------

LOC_CAMPUS = _id(1001)
LOC_B_BLOCK = _id(1002)
LOC_B_FLOOR_2 = _id(1003)

DEV_CORE_1 = _id(2001)
DEV_CORE_2 = _id(2002)
DEV_DIST_B = _id(2003)
DEV_ACC_B2_03 = _id(2004)
DEV_FW_1 = _id(2005)
DEV_AP_B2_01 = _id(2006)
DEV_ISP_CE_1 = _id(2007)

IF_ACC_GI1_0_17 = _id(3001)  # host port, VLAN 20
IF_ACC_GI1_0_49 = _id(3002)  # uplink to dist-sw-b Gi1/0/3
IF_ACC_GI1_0_5 = _id(3003)  # access point port
IF_DIST_GI1_0_3 = _id(3101)
IF_DIST_PO1 = _id(3102)
IF_DIST_TE1_1_1 = _id(3103)
IF_DIST_TE1_1_2 = _id(3104)
IF_CORE1_PO1 = _id(3201)
IF_CORE1_TE1_0_1 = _id(3202)
IF_CORE1_TE1_0_2 = _id(3203)
IF_CORE1_VL20 = _id(3204)
IF_CORE1_VL40 = _id(3205)

LINK_ACC_DIST = _id(3501)
LINK_DIST_CORE_A = _id(3502)
LINK_DIST_CORE_B = _id(3503)

RUN_ARP_CORE_1 = _id(4001)
RUN_MAC_ACC_B2_03 = _id(4002)
RUN_IF_ACC_B2_03 = _id(4003)
RUN_MAC_DIST_B = _id(4004)
RUN_ROUTES_CORE_1 = _id(4005)
RUN_HSRP_CORE_1 = _id(4006)

ALARM_VLAN_MISMATCH = _id(5001)
ALARM_CRC_RISING = _id(5002)
INCIDENT_FLOOR_2 = _id(5101)
FINDING_TRUNK_VLAN = _id(5201)
FINDING_CRC_RISING = _id(5202)

CONFIG_V1 = _id(6001)
CONFIG_V2 = _id(6002)
CHANGE_TRUNK_VLAN = _id(6101)

JOB_REFRESH = _id(7001)
JOB_DISCOVERY = _id(7002)
DISCOVERY_RUN = _id(7101)
CREDENTIAL_PROFILE_RO = _id(8001)
CREDENTIAL_PROFILE_OLD = _id(8002)

# --- Times (UTC) ---------------------------------------------------------------------------

T_FIRST_SEEN = "2026-09-01T09:00:00Z"
T_CHANGE = "2026-10-08T22:41:12Z"  # someone removes VLAN 20 from a trunk
T_INCIDENT = "2026-10-08T22:43:05Z"
T_RUN = "2026-10-09T07:55:00Z"
T_NOW = "2026-10-09T08:00:00Z"

# --- Reference objects ---------------------------------------------------------------------

LOCATION_REF_FLOOR_2: dict[str, Any] = {
    "id": LOC_B_FLOOR_2,
    "name": "Floor 2",
    "path": "Main campus / B Block / Floor 2",
}
DEVICE_REF_CORE_1: dict[str, Any] = {
    "id": DEV_CORE_1,
    "hostname": "core-sw-1",
    "mgmt_ip": "10.0.0.1",
}
DEVICE_REF_DIST_B: dict[str, Any] = {
    "id": DEV_DIST_B,
    "hostname": "dist-sw-b",
    "mgmt_ip": "10.0.0.11",
}
DEVICE_REF_ACC_B2_03: dict[str, Any] = {
    "id": DEV_ACC_B2_03,
    "hostname": "sw-b2-03",
    "mgmt_ip": "10.0.0.23",
}
DEVICE_REF_AP_B2_01: dict[str, Any] = {
    "id": DEV_AP_B2_01,
    "hostname": "ap-b2-01",
    "mgmt_ip": "10.0.30.21",
}
INTERFACE_REF_HOST_PORT: dict[str, Any] = {
    "id": IF_ACC_GI1_0_17,
    "device_id": DEV_ACC_B2_03,
    "name": "Gi1/0/17",
}
INTERFACE_REF_ACC_UPLINK: dict[str, Any] = {
    "id": IF_ACC_GI1_0_49,
    "device_id": DEV_ACC_B2_03,
    "name": "Gi1/0/49",
}
INTERFACE_REF_DIST_DOWNLINK: dict[str, Any] = {
    "id": IF_DIST_GI1_0_3,
    "device_id": DEV_DIST_B,
    "name": "Gi1/0/3",
}
INTERFACE_REF_DIST_PO1: dict[str, Any] = {
    "id": IF_DIST_PO1,
    "device_id": DEV_DIST_B,
    "name": "Po1",
}
INTERFACE_REF_CORE1_PO1: dict[str, Any] = {
    "id": IF_CORE1_PO1,
    "device_id": DEV_CORE_1,
    "name": "Po1",
}
INTERFACE_REF_CORE1_VL20: dict[str, Any] = {
    "id": IF_CORE1_VL20,
    "device_id": DEV_CORE_1,
    "name": "Vlan20",
}
INTERFACE_REF_CORE1_VL40: dict[str, Any] = {
    "id": IF_CORE1_VL40,
    "device_id": DEV_CORE_1,
    "name": "Vlan40",
}


def page(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    """A list envelope example."""
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "limit": 50,
        "offset": 0,
    }
