"""Device roles from the topology (M1): a simple heuristic, overridable per device.

1. Routers are ``edge`` devices.
2. L3 switches with a link to a router are ``core``. Without routers, the L3 switches with
   the most switch neighbours are.
3. Every other switch gets its distance from the core (in active links between switches).
   A switch with a switch neighbour farther from the core than itself is
   ``distribution``; one without (a leaf, with hosts and APs only) is ``access``. Switches
   not connected to the core stay ``unknown``.
4. Devices discovery does not crawl (out of scope, unsupported platforms such as APs) stay
   ``unknown``.

Only the device types and the active links count, so the result is stable across runs.
Devices with ``role_is_manual`` keep the role an operator gave them.
"""

import uuid
from collections import deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from netops.db.enums import DeviceRole, DeviceType, ManagementStatus
from netops.db.models import Device, Interface, Link

_SWITCHES = (DeviceType.SWITCH, DeviceType.L3_SWITCH)
_NOT_CRAWLED = (ManagementStatus.OUT_OF_SCOPE, ManagementStatus.UNSUPPORTED_PLATFORM)


def derive_roles(
    types: dict[uuid.UUID, DeviceType], adjacency: dict[uuid.UUID, set[uuid.UUID]]
) -> dict[uuid.UUID, DeviceRole]:
    """The heuristic itself, on plain data: device types and who is linked to whom."""
    roles = {d: DeviceRole.EDGE for d, t in types.items() if t is DeviceType.ROUTER}
    switches = {d for d, t in types.items() if t in _SWITCHES}
    l3 = {d for d in switches if types[d] is DeviceType.L3_SWITCH}
    core = {d for d in l3 if adjacency.get(d, set()) & roles.keys()}
    if not core and l3:
        degree = {d: len(adjacency.get(d, set()) & switches) for d in l3}
        best = max(degree.values())
        core = {d for d, n in degree.items() if n == best}

    distance = dict.fromkeys(core, 0)
    queue = deque(core)
    while queue:
        node = queue.popleft()
        for peer in adjacency.get(node, set()) & switches:
            if peer not in distance:
                distance[peer] = distance[node] + 1
                queue.append(peer)

    for switch in switches:
        if switch in core:
            roles[switch] = DeviceRole.CORE
        elif switch not in distance:
            roles[switch] = DeviceRole.UNKNOWN
        else:
            below = any(
                distance.get(peer, -1) > distance[switch]
                for peer in adjacency.get(switch, set()) & switches
            )
            roles[switch] = DeviceRole.DISTRIBUTION if below else DeviceRole.ACCESS
    return roles


async def assign_roles(session: AsyncSession) -> dict[uuid.UUID, DeviceRole]:
    """Derive every device's role and store it (except manually set roles)."""
    devices = list(await session.scalars(select(Device)))
    types = {d.id: d.device_type for d in devices if d.management_status not in _NOT_CRAWLED}
    a, b = aliased(Interface), aliased(Interface)
    adjacency: dict[uuid.UUID, set[uuid.UUID]] = {}
    for a_device, b_device in await session.execute(
        select(a.device_id, b.device_id)
        .select_from(Link)
        .join(a, a.id == Link.a_interface_id)
        .join(b, b.id == Link.b_interface_id)
        .where(Link.is_active)
    ):
        adjacency.setdefault(a_device, set()).add(b_device)
        adjacency.setdefault(b_device, set()).add(a_device)

    roles = derive_roles(types, adjacency)
    for device in devices:
        if not device.role_is_manual:
            device.role = roles.get(device.id, DeviceRole.UNKNOWN)
    await session.commit()
    return roles
