"""Configuration changes on the fake lab, as reusable building blocks.

A building block takes a topology and returns a ``Change``: the topology after the change,
the commands an operator would have typed (what ``archive / log config`` reports in
%PARSER-5-CFGLOG_LOGGEDCMD) and the other messages the device logs because of it (link
state). Every derived output follows from the new topology, so the running-config and the
show commands of every device stay consistent. Blocks chain (pass ``change.topology`` to
the next one); M6 fault diagnosis will stage its faults with them.

Named scenarios (``SCENARIOS``) pick sensible defaults for a device:

remove-vlan-from-trunk  VLAN (default 20) off a trunk; the VLAN's hosts behind it are cut
                        off (on dist1: VLAN 20 towards access2)
shutdown-port           an access port with a host, else that trunk (on dist1: to access2)
change-description      a new description on that trunk

"That trunk" is the device's last trunk to another switch, preferring trunks towards a
switch with hosts (``downlink``); ``port`` (and ``vlan``, ``text``) override the defaults.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from netops.core.ifname import normalize
from netops.db.enums import SwitchportMode
from netops_fakes.lab import DeviceState, Lab, Port, build, ordered_ports
from netops_fakes.topology import ChangeRecord, Topology

DEFAULT_VLAN = 20


class ScenarioError(ValueError):
    """The change does not apply to this device (no such port, not a trunk, ...)."""


@dataclass(frozen=True)
class Change:
    device: str
    scenario: str
    commands: tuple[str, ...]
    topology: Topology  # the lab after the change
    # Messages the device logs besides CFGLOG / CONFIG_I, e.g. "%LINK-5-CHANGED: ...".
    events: tuple[str, ...] = ()


def _state(lab: Lab, device: str) -> DeviceState:
    state = lab.devices.get(device)
    if state is None or state.device.external:
        raise ScenarioError(f"{device!r} is not a fake device of this lab")
    return state


def _port(state: DeviceState, port: str) -> Port:
    found = state.ports.get(normalize(port))
    if found is None:
        raise ScenarioError(f"{state.name} has no port {port!r}")
    return found


# --- building blocks --------------------------------------------------------------------------


def remove_vlan_from_trunk(
    topology: Topology, device: str, port: str, vlan: int, *, scenario: str = "remove-vlan"
) -> Change:
    trunk = _port(_state(build(topology), device), port)
    if trunk.mode is not SwitchportMode.TRUNK:
        raise ScenarioError(f"{device} {trunk.name} is not a trunk")
    if vlan not in (trunk.allowed_vlans or ()):
        raise ScenarioError(f"VLAN {vlan} is not allowed on {device} {trunk.name}")
    allowed = [v for v in trunk.allowed_vlans or () if v != vlan]
    return Change(
        device=device,
        scenario=scenario,
        commands=(f"interface {trunk.name}", f"switchport trunk allowed vlan remove {vlan}"),
        topology=topology.with_port(device, trunk.name, allowed_vlans=allowed),
    )


def add_vlan_to_trunk(
    topology: Topology, device: str, port: str, vlan: int, *, scenario: str = "add-vlan"
) -> Change:
    trunk = _port(_state(build(topology), device), port)
    if trunk.mode is not SwitchportMode.TRUNK:
        raise ScenarioError(f"{device} {trunk.name} is not a trunk")
    allowed = sorted({*(trunk.allowed_vlans or ()), vlan})
    return Change(
        device=device,
        scenario=scenario,
        commands=(f"interface {trunk.name}", f"switchport trunk allowed vlan add {vlan}"),
        topology=topology.with_port(device, trunk.name, allowed_vlans=allowed),
    )


def shutdown_port(
    topology: Topology, device: str, port: str, *, scenario: str = "shutdown"
) -> Change:
    target = _port(_state(build(topology), device), port)
    if not target.admin_up:
        raise ScenarioError(f"{device} {target.name} is already shut down")
    return Change(
        device=device,
        scenario=scenario,
        commands=(f"interface {target.name}", "shutdown"),
        topology=topology.with_port(device, target.name, shutdown=True),
        events=(
            f"%LINK-5-CHANGED: Interface {target.name}, changed state to administratively down",
            f"%LINEPROTO-5-UPDOWN: Line protocol on Interface {target.name}, changed state to down",
        ),
    )


def enable_port(
    topology: Topology, device: str, port: str, *, scenario: str = "no-shutdown"
) -> Change:
    target = _port(_state(build(topology), device), port)
    if target.admin_up:
        raise ScenarioError(f"{device} {target.name} is not shut down")
    return Change(
        device=device,
        scenario=scenario,
        commands=(f"interface {target.name}", "no shutdown"),
        topology=topology.with_port(device, target.name, shutdown=False),
        events=(
            f"%LINK-3-UPDOWN: Interface {target.name}, changed state to up",
            f"%LINEPROTO-5-UPDOWN: Line protocol on Interface {target.name}, changed state to up",
        ),
    )


def change_description(
    topology: Topology, device: str, port: str, text: str, *, scenario: str = "description"
) -> Change:
    target = _port(_state(build(topology), device), port)
    if not text.strip() or "\n" in text:
        raise ScenarioError("a description is one non-empty line")
    return Change(
        device=device,
        scenario=scenario,
        commands=(f"interface {target.name}", f"description {text}"),
        topology=topology.with_port(device, target.name, description=text),
    )


def record(change: Change, user: str, at: datetime) -> Topology:
    """The topology after ``change``, with the change in its history (running-config header)."""
    return change.topology.with_record(
        ChangeRecord(
            device=change.device,
            scenario=change.scenario,
            user=user,
            at=at,
            commands=list(change.commands),
        )
    )


# --- named scenarios --------------------------------------------------------------------------


def _hosts_in(lab: Lab, device: str, vlan: int | None) -> bool:
    hosts = lab.devices[device].device.hosts
    return any(vlan is None or host.vlan == vlan for host in hosts)


def downlink(lab: Lab, device: str, vlan: int | None = None) -> Port:
    """The device's last trunk (in port order) to another switch, carrying ``vlan``;
    trunks towards a switch with hosts (in ``vlan``) first."""
    state = _state(lab, device)
    trunks = [
        port
        for port in ordered_ports(state)
        if port.mode is SwitchportMode.TRUNK
        and port.channel is None
        and port.up
        and port.peer is not None
        and lab.devices[port.peer[0]].is_switch
        and (vlan is None or port.carries(vlan))
    ]
    towards_hosts = [p for p in trunks if p.peer and _hosts_in(lab, p.peer[0], vlan)]
    candidates = towards_hosts or trunks
    if not candidates:
        raise ScenarioError(f"{device} has no trunk to another switch; pass a port")
    return candidates[-1]


def _host_port(lab: Lab, device: str) -> Port | None:
    state = _state(lab, device)
    ports = [state.ports[host.port] for host in state.device.hosts]
    return next((port for port in ports if port.admin_up), None)


def _scenario_remove_vlan(
    topology: Topology, device: str, port: str | None, vlan: int | None, text: str | None
) -> Change:
    lab = build(topology)
    vlan = vlan or DEFAULT_VLAN
    name = port or downlink(lab, device, vlan).name
    return remove_vlan_from_trunk(topology, device, name, vlan, scenario="remove-vlan-from-trunk")


def _scenario_shutdown(
    topology: Topology, device: str, port: str | None, vlan: int | None, text: str | None
) -> Change:
    lab = build(topology)
    if port is None:
        host_port = _host_port(lab, device)
        port = host_port.name if host_port else downlink(lab, device).name
    return shutdown_port(topology, device, port, scenario="shutdown-port")


def _scenario_description(
    topology: Topology, device: str, port: str | None, vlan: int | None, text: str | None
) -> Change:
    lab = build(topology)
    target = _port(_state(lab, device), port) if port else downlink(lab, device)
    new = text or f"{target.description or target.name} (edited)"
    return change_description(topology, device, target.name, new, scenario="change-description")


Scenario = Callable[[Topology, str, str | None, int | None, str | None], Change]

SCENARIOS: dict[str, Scenario] = {
    "remove-vlan-from-trunk": _scenario_remove_vlan,
    "shutdown-port": _scenario_shutdown,
    "change-description": _scenario_description,
}


def run_scenario(
    topology: Topology,
    device: str,
    name: str,
    *,
    port: str | None = None,
    vlan: int | None = None,
    text: str | None = None,
) -> Change:
    if name not in SCENARIOS:
        raise ScenarioError(f"unknown scenario {name!r} (known: {', '.join(SCENARIOS)})")
    return SCENARIOS[name](topology, device, port, vlan, text)
