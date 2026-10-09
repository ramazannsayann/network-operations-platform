"""The read-only guard, device access objects and Netmiko options (no network needed)."""

import logging
import secrets
import uuid
from pathlib import Path

import pytest

from netops.core.secrets import Secret
from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import CredentialKind, OsFamily
from netops.netaccess import (
    DeviceAccess,
    ReadOnlyCommandError,
    check_read_only,
    run_show,
    runner,
    target,
)
from netops.netaccess import inventory as access_inventory
from netops.netaccess.guard import check_all

ALLOWED = [
    "show version",
    "show interfaces switchport",
    "show ip route vrf MGMT",
    "show mac address-table",
    "show spanning-tree",
    "SHOW VERSION",
    "terminal length 0",
    "Terminal Length 0",
    "terminal width 511",
]

REJECTED = [
    # configuration and state-changing commands
    "configure terminal",
    "conf t",
    "reload",
    "write memory",
    "copy running-config startup-config",
    "clear counters",
    "debug all",
    "enable",
    "terminal monitor",
    "terminal length 24",
    "terminal width 5111",
    # a second command smuggled in
    "show version\nconfigure terminal",
    "show version\rreload",
    "show version\r\n",
    "show version\n",
    "show version; reload",
    "show version ;reload",
    # output modifiers can write files (| redirect, | tee, | append)
    "show running-config | redirect flash:leak.txt",
    "show running-config | include hostname",
    # abbreviations, whitespace and look-alikes
    "sh ver",
    "show",
    "show ",
    " show version",
    "show version ",
    "show\tversion",
    "show version\x00",
    "show" + chr(0xA0) + "version",  # non-breaking space
    chr(0x0455) + "how version",  # Cyrillic "s"
    "",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_read_only_commands_are_allowed(command: str) -> None:
    assert check_read_only(command) == command


@pytest.mark.parametrize("command", REJECTED, ids=repr)
def test_other_commands_are_rejected(command: str) -> None:
    with pytest.raises(ReadOnlyCommandError):
        check_read_only(command)


@pytest.mark.parametrize("command", [None, 42, b"show version", ["show version"]])
def test_non_strings_are_rejected(command: object) -> None:
    with pytest.raises(ReadOnlyCommandError):
        check_read_only(command)


def test_check_all_rejects_the_whole_batch() -> None:
    with pytest.raises(ReadOnlyCommandError, match="configure"):
        check_all(["show version", "configure terminal", "show ip route"])
    with pytest.raises(ReadOnlyCommandError):
        check_all([])
    assert check_all(["show version", "show version", "show ip arp"]) == (
        "show version",
        "show ip arp",
    )


PASSWORD = "pw-" + secrets.token_hex(8)
ENABLE_SECRET = "en-" + secrets.token_hex(8)


def _access(password: str = PASSWORD) -> DeviceAccess:
    return DeviceAccess(
        device_id=uuid.uuid4(),
        name="dist-sw1",
        host="192.0.2.10",
        port=22,
        platform="cisco_xe",
        username="netops-ro",
        password=Secret(password),
        enable_secret=Secret(ENABLE_SECRET),
    )


def test_run_show_refuses_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("a connection was prepared for a forbidden command")

    monkeypatch.setattr(runner, "build_nornir", must_not_connect)
    with pytest.raises(ReadOnlyCommandError):
        run_show([_access()], ["show version", "configure terminal"])


def test_device_access_repr_hides_secrets() -> None:
    text = repr(_access())
    assert PASSWORD not in text
    assert ENABLE_SECRET not in text


def test_netmiko_options(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    monkeypatch.setattr(access_inventory, "_warned_about_host_keys", False)
    settings = get_settings().model_copy(update={"ssh_session_log_dir": tmp_path})
    access = _access()

    with caplog.at_level(logging.WARNING, logger="netops.netaccess.inventory"):
        options = access_inventory.netmiko_options(access, settings)

    assert options["use_keys"] is False
    assert options["allow_agent"] is False
    assert options["ssh_strict"] is False
    assert options["secret"] == ENABLE_SECRET
    assert options["session_log"] == str(tmp_path / f"{access.device_id}.log")
    assert "host keys are not verified" in caplog.text


def test_nornir_inventory_is_built_without_a_log_file(tmp_path: Path) -> None:
    nornir = access_inventory.build_nornir([_access()], get_settings())
    host = next(iter(nornir.inventory.hosts.values()))
    assert (host.hostname, host.port, host.platform) == ("192.0.2.10", 22, "cisco_xe")
    assert nornir.config.logging.enabled is False
    assert not Path("nornir.log").exists()


def test_the_resolver_changes_only_where_a_session_connects() -> None:
    access = _access()
    seen = []

    def to_loopback(host: str, port: int) -> tuple[str, int]:
        seen.append((host, port))
        return "127.0.0.1", 10022

    target.set_target_resolver(to_loopback)
    try:
        nornir = access_inventory.build_nornir([access], get_settings())
    finally:
        target.set_target_resolver(None)
    host = next(iter(nornir.inventory.hosts.values()))
    assert (host.hostname, host.port) == ("127.0.0.1", 10022)
    assert seen == [("192.0.2.10", 22)]
    assert access.host == "192.0.2.10"  # everything else keeps the management address
    assert target.resolve_target("192.0.2.10", 22) == ("192.0.2.10", 22)  # identity again


def test_device_ssh_port_overrides_the_global_port() -> None:
    profile = m.CredentialProfile(
        name="lab", kind=CredentialKind.SSH, username="netops-ro", password=Secret(PASSWORD)
    )
    device = m.Device(
        id=uuid.uuid4(), mgmt_ip="192.0.2.10", os_family=OsFamily.IOSXE, ssh_port=None
    )
    assert access_inventory.device_access(device, profile, 22).port == 22
    device.ssh_port = 2222
    assert access_inventory.device_access(device, profile, 22).port == 2222
