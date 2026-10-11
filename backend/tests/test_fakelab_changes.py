"""The fake lab's running-configs and change scenarios: every output of every device stays
consistent with the (changed) topology, and the running-config agrees with the show
commands."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from netops.configmgmt.normalize import content_hash, normalize
from netops.configmgmt.parser import parse as parse_config
from netops.configmgmt.redact import MARKER, redact
from netops.db.enums import SwitchportMode
from netops.events.syslog import CFGLOG, CONFIG_I, parse_syslog
from netops.parsing import models as pm
from netops.parsing.cisco_ios import parse
from netops.parsing.normalize import vlan_list
from netops_fakes import lab as fakelab
from netops_fakes.fake_secrets import FAKE_SECRETS
from netops_fakes.live import LiveLab, LiveOutputs
from netops_fakes.render import render
from netops_fakes.scenarios import (
    SCENARIOS,
    ScenarioError,
    add_vlan_to_trunk,
    downlink,
    enable_port,
    record,
    run_scenario,
    shutdown_port,
)
from netops_fakes.syslog import change_messages, format_message
from netops_fakes.topology import ChangeRecord, Topology, load

TOPOLOGY = Path(__file__).resolve().parents[2] / "lab" / "fakelab" / "topology.yaml"
WHEN = datetime(2026, 10, 10, 12, 0, 1, 123000, tzinfo=UTC)


def base() -> Topology:
    return load(TOPOLOGY)


def round_trip(lab: fakelab.Lab) -> None:
    """Every rendered output parses into exactly the derived state."""
    for state in lab.served():
        outputs = render(lab, state)
        for command, expected in state.expected.items():
            got = parse(command, outputs[command])
            assert got == (list(expected) if isinstance(expected, list) else expected), (
                state.name,
                command,
            )
        check_running_config(lab, state, outputs["show running-config"])


def check_running_config(lab: fakelab.Lab, state: fakelab.DeviceState, text: str) -> None:
    """The configuration says what the show commands report."""
    tree = parse_config(normalize(text))
    statuses = {s.name: s for s in fakelab.interface_statuses(state)}
    switchports = {s.interface: s for s in fakelab.switchports(state)} if state.is_switch else {}
    configured = {line.text.removeprefix("interface "): line for line in tree.find(r"^interface ")}
    assert set(configured) == set(statuses), state.name
    for name, block in configured.items():
        children = [child.text.strip() for child in block.children]
        descriptions = [c.removeprefix("description ") for c in children if c.startswith("desc")]
        assert (descriptions[0] if descriptions else None) == statuses[name].description
        assert ("shutdown" in children) == (not statuses[name].admin_up), (state.name, name)
        port = switchports.get(name)
        if port is not None and port.mode is SwitchportMode.TRUNK:
            (allowed,) = [c for c in children if c.startswith("switchport trunk allowed vlan ")]
            assert vlan_list(allowed.rsplit(" ", 1)[1]) == port.allowed_vlans, (state.name, name)
        if port is not None and port.mode is SwitchportMode.ACCESS:
            assert f"switchport access vlan {port.access_vlan}" in children
    if state.is_switch:
        defined = {int(line.text.split()[1]) for line in tree.find(r"^vlan \d+$")}
        assert defined == {v.id for v in lab.topology.vlans}
    assert tree.find(rf"^hostname {state.name}$")


def test_running_configs_agree_with_the_other_outputs() -> None:
    round_trip(fakelab.build(base()))


def test_redaction_removes_every_fake_secret_and_nothing_else() -> None:
    lab = fakelab.build(base())
    for state in lab.served():
        text = normalize(render(lab, state)["show running-config"])
        redacted = redact(text)
        for name, secret in FAKE_SECRETS.items():
            assert secret not in redacted, (state.name, name)
        changed = [
            (before, after)
            for before, after in zip(text.splitlines(), redacted.splitlines(), strict=True)
            if before != after
        ]
        assert changed, state.name
        assert all(MARKER in after for _, after in changed)
        assert all(any(s in before for s in FAKE_SECRETS.values()) for before, _ in changed)


def test_the_normalized_config_ignores_the_header_timestamps() -> None:
    topology = base()
    later = topology.with_record(
        ChangeRecord(device="dist1", scenario="none", user="jdoe", at=WHEN, commands=[])
    )
    # Same configuration, another "Last configuration change" line: same hash.
    before = render(fakelab.build(topology), fakelab.build(topology).devices["dist1"])
    after_lab = fakelab.build(later)
    after = render(after_lab, after_lab.devices["dist1"])
    assert "by jdoe" in after["show running-config"]
    assert before["show running-config"] != after["show running-config"]
    assert content_hash(normalize(before["show running-config"])) == content_hash(
        normalize(after["show running-config"])
    )


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
@pytest.mark.parametrize("device", ["dist1", "dist2", "core1", "access1", "access2"])
def test_every_scenario_keeps_the_lab_consistent(scenario: str, device: str) -> None:
    change = run_scenario(base(), device, scenario)
    assert change.device == device
    assert change.commands[0].startswith("interface ")
    round_trip(fakelab.build(record(change, "jdoe", WHEN)))


def test_removing_vlan_20_from_the_trunk_to_access2_cuts_off_its_vlan_20_hosts() -> None:
    change = run_scenario(base(), "dist1", "remove-vlan-from-trunk")
    assert change.commands == (
        "interface GigabitEthernet1/0/2",
        "switchport trunk allowed vlan remove 20",
    )
    before, after = fakelab.build(base()), fakelab.build(change.topology)
    host = "10.10.20.103"  # access2 Gi1/0/2, VLAN 20
    host_mac = next(a.mac for a in before.devices["core2"].arps if a.ip == host)

    def macs(lab: fakelab.Lab, device: str) -> set[tuple[int, str]]:
        return {(e.vlan_id, e.mac) for e in lab.devices[device].macs}

    for device in ("dist1", "core1", "core2", "access1"):
        assert (20, host_mac) in macs(before, device)
        assert (20, host_mac) not in macs(after, device), device
    assert (20, host_mac) in macs(after, "access2")  # still learned on its own port
    assert host not in {a.ip for a in after.devices["core2"].arps}
    # VLAN 20 on access2 is a part of its own, with access2 as root; VLAN 10 is not.
    instances = {i.vlan_id: i for i in after.devices["access2"].stp.instances}  # type: ignore[union-attr]
    assert instances[20].is_root
    assert not instances[10].is_root
    trunk = after.devices["dist1"].ports["GigabitEthernet1/0/2"]
    assert trunk.allowed_vlans == (10, 30, 98, 99)
    config = render(after, after.devices["dist1"])["show running-config"]
    assert "switchport trunk allowed vlan 10,30,98-99" in config

    restored = add_vlan_to_trunk(change.topology, "dist1", "Gi1/0/2", 20)
    assert fakelab.build(restored.topology).devices["dist1"].macs == before.devices["dist1"].macs


def test_shutting_a_downlink_takes_the_cable_down_at_both_ends() -> None:
    change = shutdown_port(base(), "dist1", "Gi1/0/1")
    lab = fakelab.build(change.topology)
    statuses = {s.name: s for s in fakelab.interface_statuses(lab.devices["dist1"])}
    assert not statuses["GigabitEthernet1/0/1"].admin_up
    peer = {s.name: s for s in fakelab.interface_statuses(lab.devices["access1"])}
    assert peer["GigabitEthernet1/0/49"].admin_up
    assert not peer["GigabitEthernet1/0/49"].oper_up
    assert all(n.local_interface != "GigabitEthernet1/0/1" for n in lab.devices["dist1"].cdp)
    assert all(n.local_interface != "GigabitEthernet1/0/49" for n in lab.devices["access1"].cdp)
    assert change.events[0].startswith("%LINK-5-CHANGED: Interface GigabitEthernet1/0/1")
    output = render(lab, lab.devices["dist1"])["show interfaces"]
    assert "GigabitEthernet1/0/1 is administratively down, line protocol is down" in output
    back = enable_port(change.topology, "dist1", "Gi1/0/1")
    assert (
        fakelab.build(back.topology).devices["dist1"].cdp
        == fakelab.build(base()).devices["dist1"].cdp
    )


def test_scenario_defaults_and_errors() -> None:
    lab = fakelab.build(base())
    assert downlink(lab, "dist1", 20).name == "GigabitEthernet1/0/2"
    assert run_scenario(base(), "access1", "shutdown-port").commands[0] == (
        "interface GigabitEthernet1/0/1"  # a host port
    )
    with pytest.raises(ScenarioError, match="unknown scenario"):
        run_scenario(base(), "dist1", "reboot")
    with pytest.raises(ScenarioError, match="not a fake device"):
        run_scenario(base(), "ap1", "shutdown-port")
    with pytest.raises(ScenarioError, match="no port"):
        run_scenario(base(), "dist1", "shutdown-port", port="Gi9/9/9")
    with pytest.raises(ScenarioError, match="not allowed"):
        run_scenario(base(), "dist1", "remove-vlan-from-trunk", port="Gi1/0/2", vlan=77)


def test_syslog_messages_of_a_change() -> None:
    change = run_scenario(base(), "dist1", "remove-vlan-from-trunk")
    messages = change_messages(change, "jdoe", "192.0.2.77")
    assert messages == [
        "%PARSER-5-CFGLOG_LOGGEDCMD: User:jdoe  logged command:interface GigabitEthernet1/0/2",
        "%PARSER-5-CFGLOG_LOGGEDCMD: User:jdoe  logged command:"
        "switchport trunk allowed vlan remove 20",
        "%SYS-5-CONFIG_I: Configured from console by jdoe on vty0 (192.0.2.77)",
    ]
    topology = base()
    assert format_message(topology.device("dist1"), 17, WHEN, messages[-1]) == (
        b"<189>17: dist1: Oct 10 12:00:01.123 UTC: %SYS-5-CONFIG_I: Configured from console "
        b"by jdoe on vty0 (192.0.2.77)"
    )
    # IOS 15 switches number their messages (service sequence-numbers).
    assert format_message(topology.device("access1"), 17, WHEN, messages[-1]).startswith(
        b"<189>17: access1: 000017: Oct 10 12:00:01.123 UTC: %SYS-5-CONFIG_I"
    )


def test_live_lab_follows_the_state_file(tmp_path: Path) -> None:
    state_file = tmp_path / "topology.json"
    device_view = LiveLab(base(), state_file)  # a fake device's process
    changer = LiveLab(base(), state_file)  # python -m netops_fakes.change
    outputs = LiveOutputs(device_view, "dist1")
    assert "allowed vlan 10,20,30,98-99" in outputs["show running-config"]

    change = run_scenario(changer.topology, "dist1", "remove-vlan-from-trunk")
    changer.update(record(change, "jdoe", WHEN))
    assert json.loads(state_file.read_text())["history"][0]["user"] == "jdoe"
    config = outputs["show running-config"]
    assert re.search(r"Gi\w*1/0/2\n.*\n switchport trunk allowed vlan 10,30,98-99", config)
    assert "by jdoe" in config

    changer.reset()
    assert not state_file.exists()
    assert (
        "allowed vlan 10,20,30,98-99\n switchport mode trunk\n!" in outputs["show running-config"]
    )
    assert isinstance(
        parse("show running-config", outputs["show running-config"]), pm.RunningConfig
    )


def test_committed_config_fixtures_are_up_to_date() -> None:
    from netops_fakes.fixtures import fixtures

    directory = TOPOLOGY.parents[1] / "fixtures" / "cisco_ios" / "show_running-config"
    for name, content in fixtures(base()).items():
        assert (directory / name).read_text() == content, (
            f"{name} is stale: run `make fakelab-fixtures`"
        )


def test_messages_of_the_fake_lab_change_simulator_parse() -> None:
    topology = load(TOPOLOGY)
    change = run_scenario(topology, "access1", "shutdown-port")
    at = datetime(2026, 10, 10, 12, 0, 1, tzinfo=UTC)
    parsed = [
        parse_syslog(format_message(topology.device("access1"), 100 + i, at, text))
        for i, text in enumerate(change_messages(change, "jdoe", "192.0.2.77"))
    ]
    assert [m.mnemonic for m in parsed] == [
        CFGLOG,
        CFGLOG,
        "LINK-5-CHANGED",
        "LINEPROTO-5-UPDOWN",
        CONFIG_I,
    ]
    assert [m.parsed["command"] for m in parsed[:2]] == [
        "interface GigabitEthernet1/0/1",
        "shutdown",
    ]
    assert all(m.parsed["hostname"] == "access1" and m.parsed["sequence"] for m in parsed)
