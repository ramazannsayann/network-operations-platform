"""Topology (M1): the L2 and L3 graphs, drift, and the saved map layout."""

import bisect
import ipaddress
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime
from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from netops.api.problems import VALIDATION_ERROR, ProblemError, problems
from netops.api.schemas.common import DeviceRef, InterfaceRef
from netops.api.schemas.topology import (
    DeviceChange,
    EdgeKind,
    EdgeMember,
    LinkChange,
    LinkEnd,
    NodeKind,
    NodePosition,
    Topology,
    TopologyChanges,
    TopologyEdge,
    TopologyLayer,
    TopologyLayout,
    TopologyLayoutUpdate,
    TopologyNode,
)
from netops.api.security import AUTHENTICATED
from netops.api.v1.common import At, Session
from netops.db import models as m
from netops.db.enums import (
    CollectionKind,
    DeviceRole,
    DeviceType,
    HsrpState,
    JobStatus,
    LinkSource,
    ManagementStatus,
)
from netops.db.state import runs_at
from netops.discovery.links import links_reported_at

router = APIRouter(
    prefix="/topology",
    tags=["topology"],
    dependencies=AUTHENTICATED,
    responses=problems(401, 422, 501),
)

_L3_TYPES = (DeviceType.ROUTER, DeviceType.L3_SWITCH)
IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- devices and nodes ----------------------------------------------------------------------


async def _descendants(session: AsyncSession, location_id: UUID) -> set[UUID]:
    children: dict[UUID | None, list[UUID]] = {}
    for loc_id, parent_id in await session.execute(select(m.Location.id, m.Location.parent_id)):
        children.setdefault(parent_id, []).append(loc_id)
    found, stack = set(), [location_id]
    while stack:
        current = stack.pop()
        if current not in found:
            found.add(current)
            stack.extend(children.get(current, []))
    return found


async def _devices(
    session: AsyncSession,
    at: datetime | None,
    location_id: UUID | None,
    roles: Sequence[DeviceRole] | None,
) -> list[m.Device]:
    conditions: list[ColumnElement[bool]] = []
    if at is not None:
        conditions.append(m.Device.first_seen_at <= at)
    if location_id is not None:
        conditions.append(m.Device.location_id.in_(await _descendants(session, location_id)))
    if roles:
        conditions.append(m.Device.role.in_(roles))
    stmt = select(m.Device).where(*conditions).order_by(m.Device.hostname, m.Device.id)
    return list(await session.scalars(stmt))


def _device_node(device: m.Device) -> TopologyNode:
    return TopologyNode(
        id=str(device.id),
        kind=NodeKind.DEVICE,
        label=device.hostname or str(device.mgmt_ip or device.id),
        device_id=device.id,
        device_type=device.device_type,
        role=device.role,
        location_id=device.location_id,
        reachability=device.reachability,
        is_managed=device.is_managed,
        management_status=device.management_status,
        out_of_scope=device.management_status is ManagementStatus.OUT_OF_SCOPE,
        mgmt_ip=ipaddress.ip_address(device.mgmt_ip) if device.mgmt_ip else None,
        model=device.model,
        open_alarm_count=0,  # alarms arrive with M3
        prefix=None,
        gateway_ips=[],
    )


def _ref(interface: m.Interface) -> InterfaceRef:
    return InterfaceRef(id=interface.id, device_id=interface.device_id, name=interface.name)


# --- L2 ---------------------------------------------------------------------------------------


@dataclass
class _Channel:
    """Links between the same two port-channels, collapsed into one edge."""

    source: m.Interface  # port-channel on the source side
    target: m.Interface
    members: list[tuple[m.Link, m.Interface, m.Interface, bool]] = field(default_factory=list)


async def _l2(
    session: AsyncSession, devices: Sequence[m.Device], at: datetime | None
) -> list[TopologyEdge]:
    """Edges between the given devices: physical links, EtherChannel members collapsed.

    Without ``at``: active links. With ``at``: the links the neighbours runs in force at
    that time reported (netops.discovery.links.links_reported_at). An EtherChannel edge
    also lists members that were not seen (is_active false) while another member was.
    """
    device_ids = {d.id for d in devices}
    stmt = select(m.Link)
    reported: set[frozenset[UUID]] = set()
    if at is not None:
        stmt = stmt.where(m.Link.first_seen_at <= at)
        reported = await links_reported_at(session, at)
    links = list(await session.scalars(stmt))

    def present(link: m.Link) -> bool:
        if at is None:
            return link.is_active
        return frozenset({link.a_interface_id, link.b_interface_id}) in reported

    endpoint_ids = {i for link in links for i in (link.a_interface_id, link.b_interface_id)}
    interfaces = {
        i.id: i
        for i in await session.scalars(select(m.Interface).where(m.Interface.id.in_(endpoint_ids)))
    }
    parent_ids = {i.parent_interface_id for i in interfaces.values() if i.parent_interface_id}
    parents = {
        i.id: i
        for i in await session.scalars(select(m.Interface).where(m.Interface.id.in_(parent_ids)))
    }

    edges: list[TopologyEdge] = []
    channels: dict[frozenset[UUID], _Channel] = {}
    for link in links:
        a, b = interfaces.get(link.a_interface_id), interfaces.get(link.b_interface_id)
        if a is None or b is None or not {a.device_id, b.device_id} <= device_ids:
            continue
        pa = parents.get(a.parent_interface_id) if a.parent_interface_id else None
        pb = parents.get(b.parent_interface_id) if b.parent_interface_id else None
        if pa is not None and pb is not None:
            (source, src_member), (target, dst_member) = sorted(
                ((pa, a), (pb, b)), key=lambda pair: pair[0].id
            )
            channel = channels.setdefault(
                frozenset({pa.id, pb.id}), _Channel(source=source, target=target)
            )
            channel.members.append((link, src_member, dst_member, present(link)))
        elif present(link):
            edges.append(
                TopologyEdge(
                    id=str(link.id),
                    kind=EdgeKind.LINK,
                    source=str(a.device_id),
                    target=str(b.device_id),
                    source_interface=_ref(a),
                    target_interface=_ref(b),
                    link_source=link.source,
                    is_active=True,
                    members=[],
                    link_id=link.id,
                    address=None,
                    hsrp_state=None,
                )
            )

    for channel in channels.values():
        if not any(seen for *_, seen in channel.members):
            continue
        members = sorted(channel.members, key=lambda member: member[1].name_normalized)
        sources = {link.source for link, *_ in members}
        edges.append(
            TopologyEdge(
                id=f"etherchannel:{channel.source.id}:{channel.target.id}",
                kind=EdgeKind.ETHERCHANNEL,
                source=str(channel.source.device_id),
                target=str(channel.target.device_id),
                source_interface=_ref(channel.source),
                target_interface=_ref(channel.target),
                link_source=LinkSource.CDP if LinkSource.CDP in sources else LinkSource.LLDP,
                is_active=True,
                members=[
                    EdgeMember(
                        link_id=link.id,
                        source_interface=_ref(src),
                        target_interface=_ref(dst),
                        is_active=seen,
                    )
                    for link, src, dst, seen in members
                ],
                link_id=None,
                address=None,
                hsrp_state=None,
            )
        )
    return sorted(edges, key=lambda edge: edge.id)


# --- L3 ---------------------------------------------------------------------------------------


async def _l3(
    session: AsyncSession, devices: Sequence[m.Device], at: datetime | None
) -> tuple[list[TopologyNode], list[TopologyEdge]]:
    """L3 devices, the subnets of their addresses (no /32 or /128) and the memberships.

    An address counts if the interfaces run in force at ``at`` (default: now) saw it. HSRP
    from the HSRP runs in force at ``at`` marks each subnet's virtual gateways and which
    device is active for them. L3 devices without collected addresses (e.g. a provider
    router outside the scope) join the subnet their management address is in.
    """
    l3 = [d for d in devices if d.device_type in _L3_TYPES]
    ids = [d.id for d in l3]
    nodes = [_device_node(d) for d in l3]
    if not ids:
        return nodes, []

    interface_runs = await runs_at(
        session, CollectionKind.INTERFACES, at, device_ids=ids, include_partial=True
    )
    rows = await session.execute(
        select(m.Interface, m.InterfaceAddress)
        .join(m.InterfaceAddress, m.InterfaceAddress.interface_id == m.Interface.id)
        .where(m.Interface.device_id.in_(ids))
        .order_by(m.Interface.name_normalized)
    )
    memberships: list[tuple[m.Interface, ipaddress.IPv4Interface | ipaddress.IPv6Interface]] = []
    for interface, address in rows.all():
        run = interface_runs.get(interface.device_id)
        if run is None or address.last_seen_at < run.started_at:
            continue  # not seen by the interfaces run in force (removed since)
        if at is not None and address.first_seen_at > at:
            continue
        host = ipaddress.ip_interface(address.address)
        if host.network.prefixlen < host.max_prefixlen:
            memberships.append((interface, host))

    hsrp_runs = await runs_at(session, CollectionKind.HSRP, at, device_ids=ids)
    hsrp: dict[UUID, list[tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, HsrpState]]] = {}
    if hsrp_runs:
        for observation in await session.scalars(
            select(m.HsrpObservation).where(
                m.HsrpObservation.run_id.in_([r.id for r in hsrp_runs.values()]),
                m.HsrpObservation.collected_at.in_({r.started_at for r in hsrp_runs.values()}),
            )
        ):
            vip = ipaddress.ip_address(observation.virtual_ip)
            hsrp.setdefault(observation.interface_id, []).append((vip, observation.state))

    subnets: dict[IpNetwork, set[ipaddress.IPv4Address | ipaddress.IPv6Address]] = {}
    edges: list[TopologyEdge] = []
    for interface, host in memberships:
        groups = [(vip, state) for vip, state in hsrp.get(interface.id, []) if vip in host.network]
        gateways = subnets.setdefault(host.network, set())
        gateways.update(vip for vip, _ in groups)
        edges.append(
            _member_edge(
                str(interface.device_id), host, interface, groups[0][1] if groups else None
            )
        )

    with_addresses = {interface.device_id for interface, _ in memberships}
    for device in l3:
        if device.id in with_addresses or not device.mgmt_ip:
            continue
        mgmt = ipaddress.ip_address(device.mgmt_ip)
        for network in subnets:
            if mgmt.version == network.version and mgmt in network:
                host = ipaddress.ip_interface(f"{mgmt}/{network.prefixlen}")
                edges.append(_member_edge(str(device.id), host, None, None))

    for network, gateways in sorted(subnets.items(), key=lambda item: _network_key(item[0])):
        nodes.append(
            TopologyNode(
                id=str(network),
                kind=NodeKind.SUBNET,
                label=str(network),
                device_id=None,
                device_type=None,
                role=None,
                location_id=None,
                reachability=None,
                is_managed=False,
                management_status=None,
                out_of_scope=False,
                mgmt_ip=None,
                model=None,
                open_alarm_count=0,
                prefix=network,
                gateway_ips=sorted(gateways, key=lambda ip: (ip.version, int(ip))),
            )
        )
    return nodes, sorted(edges, key=lambda edge: edge.id)


def _network_key(network: IpNetwork) -> tuple[int, int, int]:
    return (network.version, int(network.network_address), network.prefixlen)


def _member_edge(
    device_node: str,
    host: ipaddress.IPv4Interface | ipaddress.IPv6Interface,
    interface: m.Interface | None,
    hsrp_state: HsrpState | None,
) -> TopologyEdge:
    via = interface.id if interface is not None else device_node
    return TopologyEdge(
        id=f"member:{via}:{host.network}",
        kind=EdgeKind.SUBNET_MEMBER,
        source=device_node,
        target=str(host.network),
        source_interface=_ref(interface) if interface is not None else None,
        target_interface=None,
        link_source=None,
        is_active=True,
        members=[],
        link_id=None,
        address=host,
        hsrp_state=hsrp_state,
    )


# --- endpoints -----------------------------------------------------------------------------


@router.get("")
async def get_topology(
    session: Session,
    layer: TopologyLayer = TopologyLayer.L2,
    at: At = None,
    location_id: Annotated[
        UUID | None, Query(description="Only devices in this location and below.")
    ] = None,
    role: Annotated[
        list[DeviceRole] | None, Query(description="Only devices with these roles.")
    ] = (None),
) -> Topology:
    """The topology graph at ``at``.

    L2: devices and physical links; EtherChannel members are collapsed into one edge with a
    ``members`` list. L3: devices and the subnets their interfaces are in, with HSRP
    gateways. Unmanaged and out-of-scope neighbours are included and flagged.
    """
    devices = await _devices(session, at, location_id, role)
    if layer is TopologyLayer.L2:
        nodes, edges = [_device_node(d) for d in devices], await _l2(session, devices, at)
    else:
        nodes, edges = await _l3(session, devices, at)
    return Topology(layer=layer, at=at or _utcnow(), nodes=nodes, edges=edges)


def _device_ref(device: m.Device) -> DeviceRef:
    mgmt_ip = ipaddress.ip_address(device.mgmt_ip) if device.mgmt_ip else None
    return DeviceRef(id=device.id, hostname=device.hostname, mgmt_ip=mgmt_ip)


@router.get("/changes")
async def get_topology_changes(
    session: Session,
    since: Annotated[AwareDatetime, Query(description="Start of the comparison window.")],
    until: Annotated[
        AwareDatetime | None, Query(description="End of the window; defaults to now.")
    ] = None,
) -> TopologyChanges:
    """Devices and links that appeared or disappeared between ``since`` and ``until``.

    Added: first seen in the window. Removed: no longer seen by discovery, dated at the
    first successful discovery run after they were last seen (drift is detected by
    discovery runs). A link or device that disappears and comes back keeps one row, so only
    its latest state shows (see ADR-0005).
    """
    end = until or _utcnow()
    if since > end:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="`since` must not be after `until`.",
            type_=VALIDATION_ERROR,
        )
    runs: list[datetime] = sorted(
        started
        for started in await session.scalars(
            select(m.DiscoveryRun.started_at).where(
                m.DiscoveryRun.status == JobStatus.SUCCEEDED, m.DiscoveryRun.started_at <= end
            )
        )
        if started is not None
    )

    def detected(last_seen: datetime) -> datetime | None:
        """When discovery first missed something last seen at ``last_seen``."""
        index = bisect.bisect_right(runs, last_seen)
        return runs[index] if index < len(runs) else None

    added = await session.scalars(
        select(m.Device)
        .where(m.Device.first_seen_at >= since, m.Device.first_seen_at <= end)
        .order_by(m.Device.first_seen_at)
    )
    removed: list[tuple[m.Device, datetime]] = []
    for device in await session.scalars(select(m.Device).where(m.Device.last_seen_at <= end)):
        missed = detected(device.last_seen_at)
        if missed is not None and since <= missed:
            removed.append((device, missed))
    new_links = list(
        await session.scalars(
            select(m.Link)
            .where(m.Link.first_seen_at >= since, m.Link.first_seen_at <= end)
            .order_by(m.Link.first_seen_at)
        )
    )
    gone_links: list[tuple[m.Link, datetime]] = []
    for link in await session.scalars(
        select(m.Link).where(~m.Link.is_active, m.Link.last_seen_at <= end)
    ):
        missed = detected(link.last_seen_at)
        if missed is not None and since <= missed:
            gone_links.append((link, missed))
    ends = await _link_ends(session, [*new_links, *(link for link, _ in gone_links)])
    return TopologyChanges(
        since=since,
        until=end,
        added_devices=[DeviceChange(device=_device_ref(d), at=d.first_seen_at) for d in added],
        removed_devices=[
            DeviceChange(device=_device_ref(d), at=at)
            for d, at in sorted(removed, key=lambda item: item[1])
        ],
        added_links=[_link_change(link, ends, link.first_seen_at) for link in new_links],
        removed_links=[
            _link_change(link, ends, at)
            for link, at in sorted(gone_links, key=lambda item: item[1])
        ],
    )


async def _link_ends(session: AsyncSession, links: Iterable[m.Link]) -> dict[UUID, LinkEnd]:
    interface_ids = {i for link in links for i in (link.a_interface_id, link.b_interface_id)}
    if not interface_ids:
        return {}
    rows = await session.execute(
        select(m.Interface, m.Device)
        .join(m.Device, m.Device.id == m.Interface.device_id)
        .where(m.Interface.id.in_(interface_ids))
    )
    return {
        interface.id: LinkEnd(device=_device_ref(device), interface=_ref(interface))
        for interface, device in rows.all()
    }


def _link_change(link: m.Link, ends: dict[UUID, LinkEnd], at: datetime) -> LinkChange:
    return LinkChange(
        link_id=link.id,
        a=ends[link.a_interface_id],
        b=ends[link.b_interface_id],
        link_source=link.source,
        at=at,
    )


# --- saved layout --------------------------------------------------------------------------

LayerQuery = Annotated[TopologyLayer, Query(description="The map the positions belong to.")]


async def _layout(session: AsyncSession, layer: TopologyLayer) -> TopologyLayout:
    positions = list(
        await session.scalars(
            select(m.TopologyPosition)
            .where(m.TopologyPosition.layer == layer)
            .order_by(m.TopologyPosition.node_id)
        )
    )
    return TopologyLayout(
        layer=layer,
        positions=[NodePosition(node_id=p.node_id, x=p.x, y=p.y) for p in positions],
        updated_at=max((p.updated_at for p in positions), default=None),
    )


@router.get("/layout")
async def get_topology_layout(
    session: Session, layer: LayerQuery = TopologyLayer.L2
) -> TopologyLayout:
    """Saved node positions of a map (one layout for everyone until M7 adds users)."""
    return await _layout(session, layer)


@router.put("/layout")
async def put_topology_layout(
    session: Session, body: TopologyLayoutUpdate, layer: LayerQuery = TopologyLayer.L2
) -> TopologyLayout:
    """Replace the saved positions of a map; an empty list returns it to the automatic
    layout. Node ids are device ids, or subnet prefixes on the L3 map."""
    device_ids: dict[str, UUID] = {}
    problems_found = []
    for position in body.positions:
        try:
            device_ids[position.node_id] = uuid.UUID(position.node_id)
            continue
        except ValueError:
            pass
        try:
            ipaddress.ip_network(position.node_id)
        except ValueError:
            problems_found.append(position.node_id)
            continue
        if layer is not TopologyLayer.L3:
            problems_found.append(position.node_id)
    known = set(
        await session.scalars(select(m.Device.id).where(m.Device.id.in_(device_ids.values())))
    )
    problems_found += [node for node, device_id in device_ids.items() if device_id not in known]
    if problems_found:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=f"Not a node of the {layer.value} map: {', '.join(sorted(problems_found))}.",
            type_=VALIDATION_ERROR,
        )

    now = _utcnow()
    await session.execute(delete(m.TopologyPosition).where(m.TopologyPosition.layer == layer))
    session.add_all(
        m.TopologyPosition(
            layer=layer,
            node_id=str(device_ids[p.node_id]) if p.node_id in device_ids else p.node_id,
            device_id=device_ids.get(p.node_id),
            x=p.x,
            y=p.y,
            updated_at=now,
        )
        for p in {p.node_id: p for p in body.positions}.values()
    )
    await session.commit()
    return await _layout(session, layer)
