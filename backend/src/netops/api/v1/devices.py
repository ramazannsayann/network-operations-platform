"""Devices and interfaces (M1/M2)."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from netops.api.problems import not_implemented, problems
from netops.api.schemas.common import JobRef
from netops.api.schemas.devices import (
    Device,
    DevicePage,
    DeviceRefreshRequest,
    InterfaceDetail,
    InterfacePage,
)
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import ACCEPTED, DEFAULT_LIMIT, At, Limit, Offset, SearchText
from netops.db.enums import DeviceRole, DeviceType, InterfaceKind, Reachability

router = APIRouter(tags=["devices"], dependencies=AUTHENTICATED, responses=problems(401, 422, 501))

DeviceSort = Literal[
    "hostname", "-hostname", "mgmt_ip", "-mgmt_ip", "last_seen_at", "-last_seen_at"
]
InterfaceSort = Literal["name_normalized", "-name_normalized"]


@router.get("/devices")
async def list_devices(
    device_type: Annotated[list[DeviceType] | None, Query()] = None,
    role: Annotated[list[DeviceRole] | None, Query()] = None,
    location_id: UUID | None = None,
    reachability: Annotated[list[Reachability] | None, Query()] = None,
    q: SearchText = None,
    sort: DeviceSort = "hostname",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> DevicePage:
    """Inventory. ``q`` matches hostname, management IP or serial number (substring)."""
    raise not_implemented()


@router.get("/devices/{device_id}", responses=problems(404))
async def get_device(device_id: UUID) -> Device:
    raise not_implemented()


@router.post(
    "/devices/{device_id}/refresh",
    status_code=status.HTTP_202_ACCEPTED,
    responses=ACCEPTED | problems(404, 409),
)
async def refresh_device(device_id: UUID, body: DeviceRefreshRequest | None = None) -> JobRef:
    """Collect the device's state now ("refresh now"). 409 if it is not managed."""
    raise not_implemented()


@router.get("/devices/{device_id}/interfaces", responses=problems(404))
async def list_device_interfaces(
    device_id: UUID,
    at: At = None,
    kind: Annotated[list[InterfaceKind] | None, Query()] = None,
    oper_up: bool | None = None,
    sort: InterfaceSort = "name_normalized",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> InterfacePage:
    """Interfaces of a device with their state at ``at`` (default: latest)."""
    raise not_implemented()


@router.get("/interfaces/{interface_id}", responses=problems(404))
async def get_interface(interface_id: UUID, at: At = None) -> InterfaceDetail:
    """One interface: addresses, link peer, port-channel members and its state at ``at``."""
    raise not_implemented()
