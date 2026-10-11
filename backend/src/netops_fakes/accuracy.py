"""Discovery accuracy: what the inventory holds versus a topology file (proposal section 9).

Devices are compared by hostname (case-insensitive, domain removed), links as unordered
pairs of (device, canonical interface name), counting active links only. Works against the
fake lab's topology.yaml and, later, a hand-written topology file of the real lab (only
``devices`` and ``links`` matter here; see netops_fakes.topology).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from netops.core.ifname import abbreviate
from netops.db.enums import DeviceRole
from netops.db.models import Device, Interface, Link
from netops_fakes.topology import Topology

LinkKey = frozenset[tuple[str, str]]


@dataclass
class Score:
    expected: int
    found: int
    matched: int
    missed: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.matched / self.found if self.found else 1.0

    @property
    def recall(self) -> float:
        return self.matched / self.expected if self.expected else 1.0


@dataclass
class Accuracy:
    devices: Score
    links: Score
    # Devices whose expected role (topology file) differs from the derived one.
    roles: Score

    @property
    def perfect(self) -> bool:
        return all(s.precision == s.recall == 1.0 for s in (self.devices, self.links))

    def report(self) -> str:
        lines = []
        for title, score in (("Devices", self.devices), ("Links", self.links)):
            lines.append(
                f"{title:<8} precision {score.precision:7.2%}  recall {score.recall:7.2%}  "
                f"(expected {score.expected}, found {score.found}, matched {score.matched})"
            )
            lines += [f"  missed:         {item}" for item in score.missed]
            lines += [f"  false positive: {item}" for item in score.false_positives]
        lines.append(
            f"Roles    {self.roles.matched}/{self.roles.expected} as expected"
            + "".join(f"\n  wrong role:     {item}" for item in self.roles.missed)
        )
        return "\n".join(lines)


def _name(hostname: str) -> str:
    return hostname.split(".")[0].lower()


def _link_text(key: LinkKey) -> str:
    (a_device, a_port), (b_device, b_port) = sorted(key)
    return f"{a_device} {abbreviate(a_port)} <-> {b_device} {abbreviate(b_port)}"


def _score[T](expected: set[T], found: set[T], render: Callable[[T], str] = str) -> Score:
    return Score(
        expected=len(expected),
        found=len(found),
        matched=len(expected & found),
        missed=sorted(render(item) for item in expected - found),
        false_positives=sorted(render(item) for item in found - expected),
    )


async def evaluate(session: AsyncSession, topology: Topology) -> Accuracy:
    devices = list(await session.scalars(select(Device)))
    names = {d.id: _name(d.hostname or str(d.mgmt_ip)) for d in devices}
    expected_devices = {_name(d.name) for d in topology.devices}

    a, b = aliased(Interface), aliased(Interface)
    rows = await session.execute(
        select(a.device_id, a.name_normalized, b.device_id, b.name_normalized)
        .select_from(Link)
        .join(a, a.id == Link.a_interface_id)
        .join(b, b.id == Link.b_interface_id)
        .where(Link.is_active)
    )
    found_links: set[LinkKey] = {
        frozenset({(names[a_dev], a_port), (names[b_dev], b_port)})
        for a_dev, a_port, b_dev, b_port in rows
    }
    expected_links: set[LinkKey] = {
        frozenset({(_name(link.a.device), link.a.port), (_name(link.b.device), link.b.port)})
        for link in topology.links
    }

    roles = {names[d.id]: d.role for d in devices}
    role_expected = {
        _name(d.name): DeviceRole(d.role) for d in topology.devices if d.role != "unknown"
    }
    wrong = sorted(
        f"{name}: expected {role}, got {roles.get(name, 'no device')}"
        for name, role in role_expected.items()
        if roles.get(name) is not role
    )
    return Accuracy(
        devices=_score(expected_devices, set(names.values())),
        links=_score(expected_links, found_links, _link_text),
        roles=Score(
            expected=len(role_expected),
            found=len(role_expected),
            matched=len(role_expected) - len(wrong),
            missed=wrong,
        ),
    )
