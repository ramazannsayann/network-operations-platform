"""Syslog parsing (Cisco IOS / IOS-XE formats), change windows and receiver protections."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from netops.configmgmt.changes import ChangeReport, origin_of
from netops.db.enums import ChangeOrigin
from netops.events.debounce import ChangeDebouncer
from netops.events.receiver import EventsService, TokenBucket
from netops.events.syslog import CFGLOG, CONFIG_I, parse_syslog

# --- syslog formats ------------------------------------------------------------------------------

FORMATS: list[tuple[bytes, dict[str, Any]]] = [
    # Plain IOS: counter, timestamp with msec, clock not synchronized ("*").
    (
        b"<189>34: *Mar  1 00:12:03.123: %SYS-5-CONFIG_I: Configured from console by jdoe "
        b"on vty0 (192.0.2.77)",
        {
            "facility": 23,
            "severity": 5,
            "mnemonic": CONFIG_I,
            "parsed": {
                "counter": 34,
                "device_time": "*Mar  1 00:12:03.123",
                "via": "console",
                "user": "jdoe",
                "line": "vty0",
                "source_ip": "192.0.2.77",
            },
        },
    ),
    # service sequence-numbers, no username (no AAA): the "by" names the line.
    (
        b"<189>35: 000035: *Mar  1 00:12:09.555: %SYS-5-CONFIG_I: Configured from console by "
        b"vty0 (192.0.2.78)",
        {
            "mnemonic": CONFIG_I,
            "parsed": {
                "counter": 35,
                "sequence": 35,
                "device_time": "*Mar  1 00:12:09.555",
                "via": "console",
                "line": "vty0",
                "source_ip": "192.0.2.78",
            },
        },
    ),
    # Console session.
    (
        b"<189>2: .Oct 10 12:00:01: %SYS-5-CONFIG_I: Configured from console by console",
        {
            "parsed": {
                "counter": 2,
                "device_time": ".Oct 10 12:00:01",
                "via": "console",
                "line": "console",
            }
        },
    ),
    # logging origin-id hostname, show-timezone, year.
    (
        b"<189>1201: dist-b: Oct 10 2026 12:00:01.123 CEST: %PARSER-5-CFGLOG_LOGGEDCMD: "
        b"User:jdoe  logged command:interface GigabitEthernet1/0/3",
        {
            "mnemonic": CFGLOG,
            "message": "User:jdoe  logged command:interface GigabitEthernet1/0/3",
            "parsed": {
                "counter": 1201,
                "hostname": "dist-b",
                "device_time": "Oct 10 2026 12:00:01.123 CEST",
                "user": "jdoe",
                "command": "interface GigabitEthernet1/0/3",
            },
        },
    ),
    # Hostname, sequence number and timestamp all present (IOS 15 with origin-id).
    (
        b"<189>17: access1: 000017: Oct 10 12:00:01.123 UTC: %SYS-5-CONFIG_I: Configured from "
        b"console by jdoe on vty0 (192.0.2.77)",
        {"parsed": {"counter": 17, "hostname": "access1", "sequence": 17, "user": "jdoe"}},
    ),
    # No service timestamps at all, IP as origin-id.
    (
        b"<187>88: 10.0.0.21: %LINK-3-UPDOWN: Interface GigabitEthernet1/0/5, changed state "
        b"to down",
        {
            "severity": 3,
            "mnemonic": "LINK-3-UPDOWN",
            "parsed": {
                "counter": 88,
                "hostname": "10.0.0.21",
                "interface": "GigabitEthernet1/0/5",
                "state": "down",
            },
        },
    ),
    # Uptime timestamps.
    (
        b"<189>12: 1w2d: %LINEPROTO-5-UPDOWN: Line protocol on Interface Gi1/0/1, changed state "
        b"to up",
        {
            "mnemonic": "LINEPROTO-5-UPDOWN",
            "parsed": {
                "counter": 12,
                "device_time": "1w2d",
                "interface": "GigabitEthernet1/0/1",
                "state": "up",
            },
        },
    ),
    (
        b"<189>13: 00:12:03: %LINK-5-CHANGED: Interface Te1/1/1, changed state to "
        b"administratively down",
        {"parsed": {"device_time": "00:12:03", "state": "administratively down"}},
    ),
    # No counter, no hostname (some IOS-XE releases).
    (
        b"<190>Oct 10 12:00:01.123: %SEC_LOGIN-5-LOGIN_SUCCESS: Login Success [user: jdoe] "
        b"[Source: 192.0.2.77] [localport: 22] at 12:00:01 UTC Sat Oct 10 2026",
        {
            "severity": 6,
            "mnemonic": "SEC_LOGIN-5-LOGIN_SUCCESS",
            "parsed": {"device_time": "Oct 10 12:00:01.123"},
        },
    ),
    # Facility with a dash (PLATFORM-ENV style) and NETCONF-made change.
    (
        b"<189>5: core-a: Oct 10 12:00:01 UTC: %SYS-5-CONFIG_I: Configured from "
        b"NETCONF/RESTCONF by admin, transaction-id 42",
        {"parsed": {"via": "NETCONF/RESTCONF", "user": "admin", "hostname": "core-a"}},
    ),
    (
        b"<186>9: Oct 10 12:00:01: %ILPOWER-3-CONTROLLER_PORT_ERR: Controller port error, "
        b"Interface Gi1/0/7: Power Controller reports power Imax error detected",
        {"severity": 2, "mnemonic": "ILPOWER-3-CONTROLLER_PORT_ERR"},
    ),
    # RFC 5424 (IOS-XE "logging host ... rfc5424"-style).
    (
        b"<189>1 2026-10-10T12:00:01.123Z dist1 - - - - %SYS-5-CONFIG_I: Configured from "
        b"console by jdoe on vty0 (192.0.2.77)",
        {
            "parsed": {
                "hostname": "dist1",
                "device_time": "2026-10-10T12:00:01.123Z",
                "user": "jdoe",
            }
        },
    ),
    # Without a mnemonic, and not syslog at all.
    (b"<190>hello", {"facility": 23, "severity": 6, "mnemonic": None, "message": "hello"}),
    (b"garbage \xff", {"facility": None, "severity": None, "mnemonic": None}),
]


@pytest.mark.parametrize(("datagram", "expected"), FORMATS)
def test_cisco_syslog_formats(datagram: bytes, expected: dict[str, Any]) -> None:
    message = parse_syslog(datagram)
    for key, value in expected.items():
        if key == "parsed":
            for field, field_value in value.items():
                assert message.parsed.get(field) == field_value, (field, message.parsed)
        else:
            assert getattr(message, key) == value, key


def test_exec_commands_and_mnemonic_text() -> None:
    message = parse_syslog(
        b"<189>3: Oct 10 12:00:01: %PARSER-5-CFGLOG_LOGGEDCMD: User:jdoe  logged command:"
        b"!exec: enable"
    )
    assert message.parsed["exec"] is True
    config_i = parse_syslog(FORMATS[0][0])
    assert config_i.message == "Configured from console by jdoe on vty0 (192.0.2.77)"
    assert config_i.is_config_change


@pytest.mark.parametrize(
    ("command", "hidden"),
    [
        ("snmp-server community FakeCommunity9 RO", "FakeCommunity9"),
        ("username bob privilege 15 secret 0 FakePass1", "FakePass1"),
        ("enable secret FakeEnable2", "FakeEnable2"),
        (" key 7 FakeKey3", "FakeKey3"),  # tacacs server block, logged without its parent
        ("crypto isakmp key FakePsk4 address 192.0.2.1", "FakePsk4"),
    ],
)
def test_cfglog_commands_are_redacted_before_anything_stores_them(
    command: str, hidden: str
) -> None:
    datagram = (
        f"<189>4: Oct 10 12:00:01: %PARSER-5-CFGLOG_LOGGEDCMD: User:jdoe  logged command:{command}"
    )
    message = parse_syslog(datagram.encode())
    assert hidden not in message.message
    assert hidden not in str(message.parsed)
    assert "<redacted>" in message.parsed["command"]


# --- change windows ------------------------------------------------------------------------------

T0 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
DEVICE = uuid.uuid4()
OTHER = uuid.uuid4()


def test_a_window_closes_after_the_quiet_period_with_everything_it_collected() -> None:
    windows = ChangeDebouncer(quiet=30, maximum=300)
    windows.command(DEVICE, T0, 0, command="interface Gi1/0/2", username="jdoe")
    windows.command(
        DEVICE,
        T0 + timedelta(seconds=5),
        5,
        command="switchport trunk allowed vlan remove 20",
        username="jdoe",
    )
    windows.configured(
        DEVICE, T0 + timedelta(seconds=9), 9, username="jdoe", line="vty0", source_ip="192.0.2.77"
    )
    assert windows.next_deadline() == 39
    assert windows.due(38) == []
    ((device, report),) = windows.due(39)
    assert device == DEVICE
    assert report == ChangeReport(
        username="jdoe",
        source_ip="192.0.2.77",
        line="vty0",
        commands=("interface Gi1/0/2", "switchport trunk allowed vlan remove 20"),
        first_event_at=T0,
        last_event_at=T0 + timedelta(seconds=9),
    )
    assert len(windows) == 0
    assert windows.next_deadline() is None


def test_messages_keep_extending_the_window_up_to_the_maximum() -> None:
    windows = ChangeDebouncer(quiet=30, maximum=100)
    for second in range(0, 200, 20):
        windows.command(DEVICE, T0 + timedelta(seconds=second), second, command=f"cmd {second}")
        if second < 100:
            assert windows.next_deadline() == min(second + 30, 100)
    assert len(windows.due(100)) == 1  # closed at the maximum although messages kept coming


def test_devices_have_windows_of_their_own() -> None:
    windows = ChangeDebouncer(quiet=30, maximum=300)
    windows.configured(DEVICE, T0, 0, username="jdoe")
    windows.configured(OTHER, T0, 20, username="asmith")
    assert [d for d, _ in windows.due(30)] == [DEVICE]
    assert [(d, r.username) for d, r in windows.flush()] == [(OTHER, "asmith")]


def test_the_config_i_user_wins_over_cfglog_users() -> None:
    windows = ChangeDebouncer(quiet=30, maximum=300)
    windows.command(DEVICE, T0, 0, command="hostname x", username="first")
    windows.configured(DEVICE, T0, 1, username="leaver")
    windows.command(DEVICE, T0, 2, command="hostname y", username="third")
    ((_, report),) = windows.flush()
    assert report.username == "leaver"
    only_cfglog = ChangeDebouncer(quiet=30, maximum=300)
    only_cfglog.command(DEVICE, T0, 0, command="hostname x", username="first")
    only_cfglog.configured(DEVICE, T0, 1, line="console")  # no AAA user
    ((_, report),) = only_cfglog.flush()
    assert (report.username, report.line) == ("first", "console")


def test_invalid_window_settings() -> None:
    with pytest.raises(ValueError, match="quiet"):
        ChangeDebouncer(quiet=30, maximum=10)


def test_change_report_round_trips_through_json_and_is_redacted() -> None:
    report = ChangeReport(
        username="jdoe",
        source_ip="192.0.2.77",
        line="vty0",
        commands=("interface Gi1/0/2", "snmp-server community FakeCommunity9 RO"),
        first_event_at=T0,
        last_event_at=T0,
    )
    back = ChangeReport.from_json(report.to_json())
    assert back.commands == ("interface Gi1/0/2", "snmp-server community <redacted> RO")
    assert back.first_event_at == T0
    assert back.username == "jdoe"


def test_origin_is_platform_only_for_the_platform_write_account() -> None:
    assert origin_of(None, "netops-rw") is ChangeOrigin.EXTERNAL
    assert origin_of(ChangeReport(username="jdoe"), "netops-rw") is ChangeOrigin.EXTERNAL
    assert origin_of(ChangeReport(username="netops-rw"), "netops-rw") is ChangeOrigin.PLATFORM
    assert origin_of(ChangeReport(username="netops-rw"), None) is ChangeOrigin.EXTERNAL


# --- receiver protections ------------------------------------------------------------------------


def test_token_bucket() -> None:
    bucket = TokenBucket(rate=2, burst=3, now=0)
    assert [bucket.allow(0) for _ in range(4)] == [True, True, True, False]
    assert bucket.allow(0.5)  # one token back after half a second
    assert not bucket.allow(0.5)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _service(**overrides: Any) -> tuple[EventsService, _Clock]:
    from netops.core.settings import Settings

    settings = Settings(
        postgres_password="x",  # noqa: S106 - never used: no database in this test
        credentials_key="aGVsbG8taGVsbG8taGVsbG8taGVsbG8taGVsbG8tMTI=",
        syslog_max_datagram_bytes=600,
        syslog_rate_per_source=1,
        syslog_burst_per_source=3,
        **overrides,
    )

    async def on_change(device_id: uuid.UUID, report: ChangeReport) -> None:
        raise AssertionError("no change expected")

    clock = _Clock()
    service = EventsService(settings, None, on_change, clock=clock)  # type: ignore[arg-type]
    return service, clock


def test_oversized_datagrams_and_floods_are_dropped_before_queueing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> EventsService:
        service, clock = _service()
        service.received(b"<189>1: x" * 100, ("192.0.2.10", 514))  # 900 bytes
        for _ in range(5):
            service.received(b"<189>2: %SYS-5-CONFIG_I: x", ("192.0.2.11", 514))
        clock.now = 2.0  # two tokens back
        for _ in range(3):
            service.received(b"<189>3: %SYS-5-CONFIG_I: x", ("192.0.2.11", 514))
        service.received(b"<189>4: other source", ("192.0.2.12", 514))
        return service

    service = asyncio.run(scenario())
    assert service.stats.received == 10
    assert service.stats.too_large == 1
    assert service.stats.rate_limited == 3  # 2 of the first 5 and 1 of the next 3
    assert service._queue.qsize() == 6
    # One log line per source and reason, without the message text.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 2
    assert all("CONFIG_I" not in r.getMessage() for r in warnings)


def test_the_source_resolver_decides_whose_datagram_it_is() -> None:
    async def scenario() -> EventsService:
        service, _ = _service()
        service.source_of = lambda address: f"10.255.0.{address[1] - 40000}"
        service.received(b"<189>1: x", ("127.0.0.1", 40011))
        return service

    service = asyncio.run(scenario())
    assert service._queue.get_nowait()[0] == "10.255.0.11"
