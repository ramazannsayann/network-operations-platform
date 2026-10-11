"""The events service: a UDP syslog receiver (``python -m netops.events``).

Per datagram, in the protocol callback (cheap, synchronous): drop it if it is larger than
SYSLOG_MAX_DATAGRAM_BYTES or its source is over the per-source rate limit (token bucket),
otherwise queue it with the time it arrived. A writer task drains the queue in batches:
it resolves each source address to a device (devices.mgmt_ip, then interface addresses;
cached), drops datagrams from unknown sources (logged at most once per source and interval;
nothing is stored and no device is created), stores the rest in ``events`` and feeds
CONFIG_I / CFGLOG messages to the change debouncer. A third task closes due change
windows and hands each report to ``on_change`` (in production: the Celery task
``netops.config_change_event``).

The source address must be the device's: on a Linux production host run the service with
host networking; Docker Desktop (macOS, Windows) rewrites the source of UDP arriving from
outside to its own gateway. Tests on 127.0.0.1 pass ``source_of`` to map their sockets to
fake devices' management addresses.

Logs carry addresses, mnemonics and counts, never message text: a CFGLOG line logged by a
device without ``hidekeys`` would carry a key.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from netops.configmgmt.changes import ChangeReport
from netops.core.settings import Settings
from netops.db.enums import EventKind
from netops.db.models import Device, Event, Interface, InterfaceAddress
from netops.events.debounce import ChangeDebouncer
from netops.events.syslog import CFGLOG, CONFIG_I, SyslogMessage, parse_syslog

logger = logging.getLogger(__name__)

OnChange = Callable[[uuid.UUID, ChangeReport], Awaitable[None]]
SourceOf = Callable[[tuple[str, int]], str]

_QUEUE_SIZE = 10_000
_BATCH = 500
_KNOWN_TTL = 300.0  # seconds a resolved source stays cached
_UNKNOWN_TTL = 60.0
_LOG_INTERVAL = 600.0  # at most one log line per source and reason in this interval


class TokenBucket:
    def __init__(self, rate: float, burst: int, now: float) -> None:
        self.rate, self.burst = rate, float(burst)
        self.tokens, self.updated = float(burst), now

    def allow(self, now: float) -> bool:
        self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


async def find_device(session: AsyncSession, address: str) -> uuid.UUID | None:
    """The device that owns ``address``: its management address or an interface address."""
    by_mgmt = await session.scalar(select(Device.id).where(Device.mgmt_ip == address))
    if by_mgmt is not None:
        return by_mgmt
    found: uuid.UUID | None = await session.scalar(
        select(Interface.device_id)
        .join(InterfaceAddress, InterfaceAddress.interface_id == Interface.id)
        .where(func.host(InterfaceAddress.address) == address)
        .order_by(InterfaceAddress.last_seen_at.desc())
        .limit(1)
    )
    return found


@dataclass
class Stats:
    received: int = 0
    stored: int = 0
    too_large: int = 0
    rate_limited: int = 0
    unknown_source: int = 0
    queue_full: int = 0
    changes: int = 0
    per_source: dict[tuple[str, str], int] = field(default_factory=dict)


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, service: "EventsService") -> None:
        self.service = service

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        self.service.received(data, (str(addr[0]), int(addr[1])))

    def error_received(self, exc: Exception) -> None:
        logger.warning("syslog socket error", extra={"error": type(exc).__name__})


class EventsService:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        on_change: OnChange,
        *,
        source_of: SourceOf | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.on_change = on_change
        self.source_of: SourceOf = source_of or (lambda address: address[0])
        self.clock = clock
        self.debouncer = ChangeDebouncer(
            settings.config_change_debounce_seconds, settings.config_change_max_window_seconds
        )
        self.stats = Stats()
        self._queue: asyncio.Queue[tuple[str, datetime, bytes]] = asyncio.Queue(_QUEUE_SIZE)
        self._buckets: dict[str, TokenBucket] = {}
        self._devices: dict[str, tuple[uuid.UUID | None, float]] = {}
        self._logged: dict[tuple[str, str], float] = {}
        self._wake = asyncio.Event()
        self._transport: asyncio.DatagramTransport | None = None
        self._tasks: list[asyncio.Task[None]] = []

    # --- receiving ------------------------------------------------------------------------------

    def received(self, data: bytes, address: tuple[str, int]) -> None:
        self.stats.received += 1
        now = self.clock()
        if len(data) > self.settings.syslog_max_datagram_bytes:
            self.stats.too_large += 1
            self._log_once(address[0], "too_large", "syslog datagram over the size limit dropped")
            return
        source = self.source_of(address)
        bucket = self._buckets.get(source)
        if bucket is None:
            bucket = self._buckets[source] = TokenBucket(
                self.settings.syslog_rate_per_source, self.settings.syslog_burst_per_source, now
            )
        if not bucket.allow(now):
            self.stats.rate_limited += 1
            self._log_once(source, "rate_limited", "syslog source over its rate limit")
            return
        try:
            self._queue.put_nowait((source, datetime.now(UTC), data))
        except asyncio.QueueFull:
            self.stats.queue_full += 1
            self._log_once(source, "queue_full", "syslog queue full, datagram dropped")

    def _log_once(self, source: str, reason: str, text: str) -> None:
        key = (source, reason)
        self.stats.per_source[key] = self.stats.per_source.get(key, 0) + 1
        now = self.clock()
        if now - self._logged.get(key, -_LOG_INTERVAL) >= _LOG_INTERVAL:
            self._logged[key] = now
            logger.warning(text, extra={"source_ip": source, "dropped": self.stats.per_source[key]})

    # --- storing --------------------------------------------------------------------------------

    async def _device_of(self, session: AsyncSession, source: str) -> uuid.UUID | None:
        cached = self._devices.get(source)
        now = self.clock()
        if cached is not None and cached[1] > now:
            return cached[0]
        try:
            ip_address(source)
        except ValueError:
            device_id = None
        else:
            device_id = await find_device(session, source)
        self._devices[source] = (device_id, now + (_KNOWN_TTL if device_id else _UNKNOWN_TTL))
        return device_id

    async def _writer(self) -> None:
        while True:
            batch = [await self._queue.get()]
            while len(batch) < _BATCH and not self._queue.empty():
                batch.append(self._queue.get_nowait())
            try:
                await self._store(batch)
            except Exception:
                logger.exception("storing syslog events failed", extra={"events": len(batch)})

    async def _store(self, batch: list[tuple[str, datetime, bytes]]) -> None:
        rows: list[dict[str, Any]] = []
        changes: list[tuple[uuid.UUID, datetime, SyslogMessage]] = []
        async with self.sessions() as session:
            for source, received_at, data in batch:
                device_id = await self._device_of(session, source)
                if device_id is None:
                    self.stats.unknown_source += 1
                    self._log_once(source, "unknown", "syslog from an unknown source ignored")
                    continue
                message = parse_syslog(data)
                rows.append(
                    {
                        "received_at": received_at,
                        "source_ip": source,
                        "device_id": device_id,
                        "kind": EventKind.SYSLOG,
                        "facility": message.facility,
                        "severity": message.severity,
                        "mnemonic": message.mnemonic,
                        "message": message.message,
                        "parsed": message.parsed or None,
                    }
                )
                if message.is_config_change and not message.parsed.get("exec"):
                    changes.append((device_id, received_at, message))
            if rows:
                await session.execute(insert(Event), rows)
                await session.commit()
                self.stats.stored += len(rows)
        if changes:
            now = self.clock()
            for device_id, at, message in changes:
                fields = message.parsed
                if message.mnemonic == CONFIG_I:
                    self.debouncer.configured(
                        device_id,
                        at,
                        now,
                        username=fields.get("user"),
                        line=fields.get("line"),
                        source_ip=fields.get("source_ip"),
                    )
                elif message.mnemonic == CFGLOG and "command" in fields:
                    self.debouncer.command(
                        device_id, at, now, command=fields["command"], username=fields.get("user")
                    )
            self._wake.set()

    # --- change windows -------------------------------------------------------------------------

    async def _closer(self) -> None:
        while True:
            deadline = self.debouncer.next_deadline()
            timeout = None if deadline is None else max(0.0, deadline - self.clock())
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout)
            self._wake.clear()
            for device_id, report in self.debouncer.due(self.clock()):
                await self._hand_over(device_id, report)

    async def _hand_over(self, device_id: uuid.UUID, report: ChangeReport) -> None:
        self.stats.changes += 1
        logger.info(
            "configuration change window closed",
            extra={
                "device_id": str(device_id),
                "user": report.username,
                "commands": len(report.commands),
            },
        )
        try:
            await self.on_change(device_id, report)
        except Exception:
            logger.exception("handing over a configuration change failed")

    # --- lifecycle ------------------------------------------------------------------------------

    async def start(self, host: str | None = None, port: int | None = None) -> tuple[str, int]:
        """Bind the UDP socket and start the tasks; returns the bound address."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(self),
            local_addr=(
                host if host is not None else self.settings.syslog_bind,
                port if port is not None else self.settings.syslog_port,
            ),
        )
        self._transport = transport
        self._tasks = [
            asyncio.create_task(self._writer(), name="syslog-writer"),
            asyncio.create_task(self._closer(), name="syslog-change-windows"),
        ]
        bound = transport.get_extra_info("sockname")
        logger.info("syslog receiver listening", extra={"address": f"{bound[0]}:{bound[1]}"})
        return str(bound[0]), int(bound[1])

    async def stop(self) -> None:
        """Stop receiving, store what is queued and hand over open change windows."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        while not self._queue.empty():
            batch = [self._queue.get_nowait() for _ in range(min(_BATCH, self._queue.qsize()))]
            await self._store(batch)
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        for device_id, report in self.debouncer.flush():
            await self._hand_over(device_id, report)
