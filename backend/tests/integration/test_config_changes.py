"""M4 end to end on 127.0.0.1: the fake lab (discovered into the test database), the syslog
receiver and the ``config`` collection.

A change scenario mutates a fake device and sends its syslog; after the debounce window
the device's configuration is backed up, a new version and a change row (user, source
address, commands) are recorded, and the API shows the redacted diff. Without syslog the
scheduled backup finds the change, with an unknown user. No fake secret may leave the
backend: API responses and every log record are scanned for them.
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from dulwich.repo import Repo
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from netops.configmgmt.changes import ChangeReport
from netops.configmgmt.store import ConfigStore
from netops.core.logging import JsonFormatter, quiet_device_io
from netops.core.settings import get_settings
from netops.db import models as m
from netops.db.enums import (
    ChangeOrigin,
    CollectionKind,
    CollectionStatus,
    CollectionTrigger,
    ConfigTrigger,
)
from netops.db.session import create_engine
from netops.events.receiver import EventsService
from netops.inventory.service import collect_device
from netops.netaccess import set_target_resolver
from netops_fakes.fake_secrets import FAKE_SECRETS
from netops_fakes.local import LocalLab
from netops_fakes.scenarios import run_scenario
from netops_fakes.topology import load
from tests.integration.support import FAKELAB_TOPOLOGY, PASSWORD, USERNAME, Recorder, run
from tests.integration.test_discovery import discover

pytestmark = pytest.mark.integration

DEBOUNCE_SECONDS = 2.0
OPERATOR = ("jdoe", "192.0.2.77")


@pytest.fixture
def lab(
    api: tuple[TestClient, Recorder],
    profiles: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, LocalLab]]:
    """The fake lab on 127.0.0.1, discovered; sessions to its addresses reach the fakes."""
    monkeypatch.setenv("CONFIG_CHANGE_DEBOUNCE_SECONDS", str(DEBOUNCE_SECONDS))
    get_settings.cache_clear()
    client, _ = api
    with LocalLab(load(FAKELAB_TOPOLOGY), USERNAME, PASSWORD) as fake_lab:
        discover(fake_lab, profiles)
        set_target_resolver(fake_lab.resolve)
        try:
            yield client, fake_lab
        finally:
            set_target_resolver(None)


def device_id(name: str) -> uuid.UUID:
    async def find(session: AsyncSession) -> uuid.UUID:
        found = await session.scalar(select(m.Device.id).where(m.Device.hostname == name))
        assert found is not None, name
        return found

    return run(find)


def backup(
    device: uuid.UUID,
    trigger: CollectionTrigger = CollectionTrigger.SCHEDULED,
    report: ChangeReport | None = None,
) -> CollectionStatus:
    outcome = asyncio.run(
        collect_device(device, [CollectionKind.CONFIG], trigger, get_settings(), report)
    )
    assert isinstance(outcome, dict), outcome
    return outcome[CollectionKind.CONFIG]


def versions(device: uuid.UUID) -> list[m.ConfigVersion]:
    async def load_versions(session: AsyncSession) -> list[m.ConfigVersion]:
        rows = await session.scalars(
            select(m.ConfigVersion)
            .where(m.ConfigVersion.device_id == device)
            .order_by(m.ConfigVersion.collected_at)
        )
        return list(rows)

    return run(load_versions)


def changes(device: uuid.UUID) -> list[m.ConfigChange]:
    async def load_changes(session: AsyncSession) -> list[m.ConfigChange]:
        rows = await session.scalars(
            select(m.ConfigChange)
            .where(m.ConfigChange.device_id == device)
            .order_by(m.ConfigChange.detected_at)
        )
        return list(rows)

    return run(load_changes)


class Receiver:
    """The events service in a thread of its own, handing change windows straight to a
    ``config`` collection (in production: the Celery task netops.config_change_event)."""

    def __init__(self, lab: LocalLab) -> None:
        self.lab = lab
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.handled: list[tuple[uuid.UUID, ChangeReport, Any]] = []
        self.address: tuple[str, int] = ("127.0.0.1", 0)

    async def _start(self) -> None:
        settings = get_settings()
        self.engine = create_engine(settings.database_url, pool_size=2)

        async def on_change(device: uuid.UUID, report: ChangeReport) -> None:
            outcome = await collect_device(
                device, [CollectionKind.CONFIG], CollectionTrigger.EVENT, settings, report
            )
            self.handled.append((device, report, outcome))

        self.service = EventsService(
            settings,
            async_sessionmaker(self.engine, expire_on_commit=False),
            on_change,
            source_of=self.lab.syslog_source,
        )
        self.address = await self.service.start("127.0.0.1", 0)

    async def _stop(self) -> None:
        await self.service.stop()
        await self.engine.dispose()

    def __enter__(self) -> "Receiver":
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self._start(), self.loop).result(10)
        return self

    def __exit__(self, *exc: object) -> None:
        asyncio.run_coroutine_threadsafe(self._stop(), self.loop).result(30)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


def wait_for(condition: Any, timeout: float = 30.0) -> float:
    started = time.monotonic()
    while not condition():
        if time.monotonic() - started > timeout:
            raise AssertionError("timed out")
        time.sleep(0.05)
    return time.monotonic() - started


def test_a_syslog_reported_change_is_recorded_with_user_source_and_commands(
    lab: tuple[TestClient, LocalLab], capsys: pytest.CaptureFixture[str]
) -> None:
    client, fake_lab = lab
    dist1 = device_id("dist1")
    assert backup(dist1) is CollectionStatus.SUCCESS
    (baseline,) = versions(dist1)
    assert baseline.trigger is ConfigTrigger.SCHEDULED
    assert changes(dist1) == []  # the first backup is a baseline, not a change

    # Unchanged: a successful run, no new version.
    assert backup(dist1) is CollectionStatus.SUCCESS
    assert len(versions(dist1)) == 1

    change = run_scenario(fake_lab.live.topology, "dist1", "remove-vlan-from-trunk")
    with Receiver(fake_lab) as receiver:
        sent = time.monotonic()
        fake_lab.change(change, receiver.address, *OPERATOR)
        wait_for(lambda: len(changes(dist1)) == 1)
        latency = time.monotonic() - sent
    with capsys.disabled():
        print(  # noqa: T201
            f"\n\nsyslog -> recorded change: {latency:.2f} s "
            f"(debounce {DEBOUNCE_SECONDS:.0f} s + backup {latency - DEBOUNCE_SECONDS:.2f} s)\n"
        )

    ((handled_device, report, outcome),) = receiver.handled
    assert handled_device == dist1
    assert outcome == {CollectionKind.CONFIG: CollectionStatus.SUCCESS}
    assert report.username == "jdoe"
    before, after = versions(dist1)
    assert after.trigger is ConfigTrigger.CHANGE_EVENT
    (recorded,) = changes(dist1)
    assert recorded.origin is ChangeOrigin.EXTERNAL
    assert recorded.username == "jdoe"
    assert recorded.source_ip == "192.0.2.77"
    assert recorded.commands == [
        "interface GigabitEthernet1/0/2",
        "switchport trunk allowed vlan remove 20",
    ]
    assert (recorded.before_version_id, recorded.after_version_id) == (before.id, after.id)

    # The commit message names the device, the trigger and the user.
    repository = Repo(str(get_settings().config_repo_path))
    try:
        message = repository[after.git_commit.encode()].message.decode()  # type: ignore[attr-defined]
    finally:
        repository.close()
    assert message.startswith("dist1: new configuration (change_event)")
    assert "Changed by: jdoe from 192.0.2.77 on vty0" in message
    events = client.get("/api/v1/events", params={"device_id": str(dist1)}).json()
    assert [e["mnemonic"] for e in reversed(events["items"])] == [
        "PARSER-5-CFGLOG_LOGGEDCMD",
        "PARSER-5-CFGLOG_LOGGEDCMD",
        "SYS-5-CONFIG_I",
    ]
    config_i = events["items"][0]
    assert config_i["source_ip"] == "10.255.0.11"
    assert config_i["device"]["hostname"] == "dist1"
    assert config_i["parsed"]["user"] == "jdoe"
    filtered = client.get(
        "/api/v1/events", params={"mnemonic": "SYS-5-CONFIG_I", "severity": [5]}
    ).json()
    assert filtered["total"] == 1

    listed = client.get("/api/v1/config-changes", params={"device_id": str(dist1)}).json()
    (item,) = listed["items"]
    assert item["detected_by"] == "change_event"
    assert item["username"] == "jdoe"
    assert item["device"]["hostname"] == "dist1"
    by_user = client.get("/api/v1/config-changes", params={"username": "jdoe"}).json()
    assert by_user["total"] == 1
    assert client.get("/api/v1/config-changes", params={"origin": "platform"}).json()["total"] == 0

    diff = client.get(
        "/api/v1/configs/diff", params={"from": str(before.id), "to": str(after.id)}
    ).json()
    assert "- switchport trunk allowed vlan 10,20,30,98-99" in diff["unified_diff"]
    assert "+ switchport trunk allowed vlan 10,30,98-99" in diff["unified_diff"]
    assert diff["unified_diff"].startswith("--- dist1 @ ")
    assert (diff["added_lines"], diff["removed_lines"]) == (1, 1)


def test_a_change_without_syslog_is_found_by_the_scheduled_backup(
    lab: tuple[TestClient, LocalLab],
) -> None:
    client, fake_lab = lab
    access1 = device_id("access1")
    assert backup(access1) is CollectionStatus.SUCCESS
    fake_lab.apply(run_scenario(fake_lab.live.topology, "access1", "shutdown-port"), "jdoe")
    assert backup(access1) is CollectionStatus.SUCCESS

    (recorded,) = changes(access1)
    assert recorded.origin is ChangeOrigin.EXTERNAL
    assert recorded.username is None
    assert recorded.source_ip is None
    assert recorded.commands == []
    item = client.get("/api/v1/config-changes", params={"device_id": str(access1)}).json()
    assert item["items"][0]["detected_by"] == "scheduled"
    diff = client.get(
        "/api/v1/configs/diff",
        params={"from": str(recorded.before_version_id), "to": str(recorded.after_version_id)},
    ).json()
    assert "+ shutdown" in diff["unified_diff"]

    summary = client.get("/api/v1/config-backups", params={"q": "access1"}).json()
    (row,) = summary["items"]
    assert row["version_count"] == 2
    assert row["recent_external_changes"] == 1
    assert row["last_backup_status"] == "success"
    assert row["latest_version"]["id"] == str(recorded.after_version_id)


def test_no_fake_secret_leaves_the_backend(
    lab: tuple[TestClient, LocalLab], caplog: pytest.LogCaptureFixture
) -> None:
    quiet_device_io()  # what configure_logging does in every service
    caplog.set_level(logging.DEBUG)
    client, fake_lab = lab
    core1 = device_id("core1")
    assert backup(core1) is CollectionStatus.SUCCESS
    change = run_scenario(fake_lab.live.topology, "core1", "change-description", text="edited")
    with Receiver(fake_lab) as receiver:
        fake_lab.change(change, receiver.address, *OPERATOR)
        # A secret typed in a session without "hidekeys" reaches the receiver as is.
        fake_lab.send_syslog(
            "core1",
            [
                "%PARSER-5-CFGLOG_LOGGEDCMD: User:jdoe  logged command:snmp-server community "
                f"{FAKE_SECRETS['snmp_community']} RO"
            ],
            receiver.address,
        )
        wait_for(lambda: len(changes(core1)) == 1)
    assert backup(core1, CollectionTrigger.MANUAL) is CollectionStatus.SUCCESS
    before, after = versions(core1)

    responses = [
        client.get("/api/v1/config-backups"),
        client.get(f"/api/v1/devices/{core1}/configs"),
        client.get(f"/api/v1/configs/{before.id}"),
        client.get(f"/api/v1/configs/{after.id}"),
        client.get("/api/v1/configs/diff", params={"from": str(before.id), "to": str(after.id)}),
        client.get("/api/v1/configs/diff", params={"from": str(before.id), "to": str(before.id)}),
        client.get("/api/v1/config-changes"),
        client.get("/api/v1/events", params={"limit": 500}),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
    content = responses[2].json()["content"]
    assert "enable secret 9 <redacted>" in content
    assert "snmp-server community <redacted> RO" in content
    formatter = JsonFormatter()
    texts = {
        "api": [response.text for response in responses],
        "logs": [formatter.format(record) for record in caplog.records],
    }
    assert texts["logs"], "nothing was logged"
    for where, items in texts.items():
        for text in items:
            for name, secret in FAKE_SECRETS.items():
                assert secret not in text, f"{name} leaked into {where}: {text[:200]}"
    # The repository does hold them: M5 needs the complete text (ADR-0007).
    stored = ConfigStore(get_settings().config_repo_path).read(after.git_commit, core1)
    assert FAKE_SECRETS["enable"] in stored
    events = json.loads(responses[-1].text)["items"]
    assert any("snmp-server community <redacted> RO" in e["message"] for e in events)


def test_config_api_errors(lab: tuple[TestClient, LocalLab]) -> None:
    client, _ = lab
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/configs/{missing}").status_code == 404
    assert client.get(f"/api/v1/devices/{missing}/configs").status_code == 404
    response = client.get("/api/v1/configs/diff", params={"from": str(missing), "to": str(missing)})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"

    dist2 = device_id("dist2")
    assert backup(dist2, CollectionTrigger.MANUAL) is CollectionStatus.SUCCESS
    (version,) = versions(dist2)
    assert version.trigger is ConfigTrigger.MANUAL
    page = client.get(f"/api/v1/devices/{dist2}/configs").json()
    assert page["total"] == 1
    assert page["items"][0]["size_bytes"] == version.size_bytes

    async def count_runs(session: AsyncSession) -> int:
        return (
            await session.scalar(
                select(func.count())
                .select_from(m.CollectionRun)
                .where(
                    m.CollectionRun.device_id == dist2,
                    m.CollectionRun.kind == CollectionKind.CONFIG,
                )
            )
            or 0
        )

    assert run(count_runs) == 1
