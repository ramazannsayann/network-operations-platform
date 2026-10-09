"""Physical links from CDP/LLDP neighbour observations (M1).

Every device's latest successful neighbours run (partial runs count: one protocol is
enough) reports (local interface, remote device, remote port). The remote device is matched
by management address (including any address on its interfaces), then by a serial number in
the Device ID, then by hostname; the remote port is normalised. A link is stored once per
cable (a < b by interface id), from CDP if CDP reported it, otherwise LLDP.

Conflicts: an interface can be on more than one candidate link only if no report from both
ends says otherwise. Links both ends agree on win; one-sided reports are kept when they do
not touch an interface of such a link.

EtherChannel members are separate links; their port-channel comes from
interfaces.parent_interface_id. Links that the latest neighbours runs of both endpoints no
longer report become ``is_active = false`` (topology drift); they are kept for drift reports.
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from netops.core.ifname import interface_kind, normalize
from netops.db.enums import CollectionKind, LinkSource, NeighborProtocol
from netops.db.models import (
    Device,
    DeviceSerial,
    Interface,
    InterfaceAddress,
    Link,
    NeighborObservation,
)
from netops.db.state import runs_at
from netops.discovery.classify import serial_in_name, short_name

logger = logging.getLogger(__name__)

InterfaceKey = tuple[uuid.UUID, str]  # (device id, canonical interface name)


@dataclass
class Candidate:
    reported_by: set[uuid.UUID] = field(default_factory=set)
    protocols: set[NeighborProtocol] = field(default_factory=set)


@dataclass
class LinkChanges:
    created: int = 0
    refreshed: int = 0
    deactivated: int = 0


class _Directory:
    """Who is who: management addresses, serials and hostnames -> device id."""

    def __init__(self) -> None:
        self.by_address: dict[str, uuid.UUID] = {}
        self.by_serial: dict[str, uuid.UUID] = {}
        self.by_name: dict[str, uuid.UUID] = {}

    async def load(self, session: AsyncSession) -> None:
        names: dict[str, set[uuid.UUID]] = {}
        for device_id, mgmt_ip, hostname in await session.execute(
            select(Device.id, Device.mgmt_ip, Device.hostname)
        ):
            if mgmt_ip:
                self.by_address[str(mgmt_ip)] = device_id
            if hostname:
                names.setdefault(hostname.lower(), set()).add(device_id)
        # Names shared by several devices (e.g. unconfigured "Switch") identify nobody.
        self.by_name = {name: ids.pop() for name, ids in names.items() if len(ids) == 1}
        for device_id, host in await session.execute(
            select(Interface.device_id, func.host(InterfaceAddress.address)).join(
                Interface, Interface.id == InterfaceAddress.interface_id
            )
        ):
            self.by_address.setdefault(host, device_id)
        for serial, device_id in await session.execute(
            select(DeviceSerial.serial, DeviceSerial.device_id)
        ):
            self.by_serial[serial] = device_id

    def find(self, observation: NeighborObservation) -> uuid.UUID | None:
        if observation.remote_mgmt_ip:
            found = self.by_address.get(str(observation.remote_mgmt_ip))
            if found:
                return found
        serial = serial_in_name(observation.remote_name)
        if serial and serial in self.by_serial:
            return self.by_serial[serial]
        name = short_name(observation.remote_name)
        return self.by_name.get(name.lower()) if name else None


_MAC_LIKE = re.compile(
    r"^(?:[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}|[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5})$", re.I
)


def _port(remote_port: str | None) -> str | None:
    """A canonical interface name, or None for LLDP port IDs that are not names (MACs)."""
    text = (remote_port or "").strip()
    if not any(ch.isdigit() for ch in text) or _MAC_LIKE.match(text):
        return None
    return normalize(text)


async def rebuild_links(session: AsyncSession) -> LinkChanges:
    """Create, refresh and deactivate links from the latest neighbour observations."""
    now = datetime.now(UTC)
    runs = await runs_at(session, CollectionKind.NEIGHBORS, include_partial=True)
    changes = LinkChanges()
    if not runs:
        return changes

    directory = _Directory()
    await directory.load(session)
    interfaces: dict[InterfaceKey, Interface] = {
        (i.device_id, i.name_normalized): i for i in await session.scalars(select(Interface))
    }
    by_id = {i.id: i for i in interfaces.values()}

    observations = await session.scalars(
        select(NeighborObservation).where(
            NeighborObservation.run_id.in_([r.id for r in runs.values()]),
            NeighborObservation.collected_at.in_({r.started_at for r in runs.values()}),
        )
    )
    candidates: dict[frozenset[uuid.UUID], Candidate] = {}
    for observation in observations:
        remote = directory.find(observation)
        port = _port(observation.remote_port)
        if remote is None or port is None or remote == observation.device_id:
            continue
        remote_interface = interfaces.get((remote, port))
        if remote_interface is None:
            # A port of a device not collected (yet): placeholders get interfaces this way.
            remote_interface = Interface(
                id=uuid.uuid4(),
                device_id=remote,
                name=port,
                name_normalized=port,
                kind=interface_kind(port),
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(remote_interface)
            interfaces[(remote, port)] = remote_interface
            by_id[remote_interface.id] = remote_interface
        key = frozenset({observation.local_interface_id, remote_interface.id})
        candidate = candidates.setdefault(key, Candidate())
        candidate.reported_by.add(observation.device_id)
        candidate.protocols.add(observation.protocol)
    await session.flush()

    agreed = {key for key, c in candidates.items() if len(c.reported_by) == 2}
    taken = {interface for key in agreed for interface in key}
    accepted = agreed | {key for key in candidates if key not in agreed and not key & taken}

    existing = {
        frozenset({link.a_interface_id, link.b_interface_id}): link
        for link in await session.scalars(select(Link))
    }
    for key in accepted:
        a, b = sorted(key)
        source = (
            LinkSource.CDP if NeighborProtocol.CDP in candidates[key].protocols else LinkSource.LLDP
        )
        link = existing.get(key)
        if link is None:
            session.add(
                Link(
                    id=uuid.uuid4(),
                    a_interface_id=a,
                    b_interface_id=b,
                    source=source,
                    is_active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            changes.created += 1
        else:
            link.is_active, link.last_seen_at, link.source = True, now, source
            changes.refreshed += 1

    # Drift: a link neither endpoint's latest neighbours run reports any more.
    for key, link in existing.items():
        if key in accepted or not link.is_active:
            continue
        endpoints = {by_id[i].device_id for i in key if i in by_id}
        if endpoints & runs.keys():
            link.is_active = False
            changes.deactivated += 1
    await session.commit()
    logger.info("links rebuilt", extra=vars(changes))
    return changes
