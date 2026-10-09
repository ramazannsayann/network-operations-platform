"""Storing parsed collector output: collection runs, observations and entities (ADR-0002).

Independent of SSH: ``ingest_raw`` stores raw command output from any source (a device,
fixture files), so tests and M6 can replay recorded output.

A run is opened (status ``running``) and committed first. Its observations are written
with ``collected_at = run.started_at``, the entities it touched are upserted, and the run
is finished as ``success``, ``partial`` (some optional commands failed, or data was
skipped) or ``failed``, all in one transaction. Anything that goes wrong while storing is
recorded on the run; it never propagates to the caller.
"""

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from netops.core.ifname import interface_kind
from netops.db.enums import CollectionKind, CollectionStatus, CollectionTrigger, Reachability
from netops.db.models import CollectionRun, Device, Interface, Observation
from netops.inventory.collectors import COLLECTORS, commands_for
from netops.parsing import CommandError, ParseError, parse

logger = logging.getLogger(__name__)

# Long error texts (many failed commands) are cut so a run row stays readable.
_MAX_ERROR_LENGTH = 4000


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Context:
    """What a collector's persist function works with."""

    session: AsyncSession
    device: Device
    run: CollectionRun
    warnings: list[str] = field(default_factory=list)
    _interfaces: dict[str, Interface] | None = None

    @property
    def seen_at(self) -> datetime:
        """Timestamp for observations (collected_at) and entities (last_seen_at)."""
        return self.run.started_at

    async def interfaces(self) -> dict[str, Interface]:
        """The device's interfaces by canonical name (loaded once per run)."""
        if self._interfaces is None:
            rows = await self.session.scalars(
                select(Interface).where(Interface.device_id == self.device.id)
            )
            self._interfaces = {row.name_normalized: row for row in rows}
        return self._interfaces

    async def interface(self, name: str) -> Interface:
        """The interface with this canonical name, created if the device has none yet."""
        interfaces = await self.interfaces()
        existing = interfaces.get(name)
        if existing is not None:
            return existing
        created = Interface(
            id=uuid.uuid4(),
            device_id=self.device.id,
            name=name,
            name_normalized=name,
            kind=interface_kind(name),
            first_seen_at=self.seen_at,
            last_seen_at=self.seen_at,
        )
        self.session.add(created)
        interfaces[name] = created
        return created

    def observation(self, **values: Any) -> dict[str, Any]:
        """Row values for an observation table: the run's keys plus ``values``."""
        return {
            "collected_at": self.run.started_at,
            "run_id": self.run.id,
            "device_id": self.device.id,
            **values,
        }

    async def insert(self, model: type[Observation], rows: Sequence[dict[str, Any]]) -> None:
        if rows:
            await self.session.flush()  # interfaces created above must exist first
            await self.session.execute(insert(model), list(rows))


async def start_run(
    session: AsyncSession,
    device_id: uuid.UUID,
    kind: CollectionKind,
    trigger: CollectionTrigger,
    started_at: datetime | None = None,
) -> uuid.UUID:
    """Open (and commit) a ``running`` run; returns its id."""
    run = CollectionRun(
        id=uuid.uuid4(),
        device_id=device_id,
        kind=kind,
        trigger=trigger,
        status=CollectionStatus.RUNNING,
        started_at=started_at or utcnow(),
    )
    session.add(run)
    await session.commit()
    return run.id


async def fail_run(session: AsyncSession, run_id: uuid.UUID, error: str) -> CollectionStatus:
    await session.execute(
        update(CollectionRun)
        .where(CollectionRun.id == run_id)
        .values(
            status=CollectionStatus.FAILED,
            finished_at=utcnow(),
            error=error[:_MAX_ERROR_LENGTH] or "failed",
        )
    )
    await session.commit()
    return CollectionStatus.FAILED


def _parse_outputs(
    commands: Sequence[str], outputs: Mapping[str, str], command_errors: Mapping[str, str]
) -> tuple[dict[str, Any], list[str]]:
    parsed: dict[str, Any] = {}
    errors: list[str] = []
    for command in commands:
        if command in command_errors:
            errors.append(f"{command}: {command_errors[command]}")
            continue
        raw = outputs.get(command)
        if raw is None:
            errors.append(f"{command}: no output")
            continue
        try:
            parsed[command] = parse(command, raw)
        except (CommandError, ParseError) as exc:
            errors.append(str(exc))
    return parsed, errors


async def complete_run(
    session: AsyncSession,
    device_id: uuid.UUID,
    run_id: uuid.UUID,
    outputs: Mapping[str, str],
    command_errors: Mapping[str, str] | None = None,
) -> CollectionStatus:
    """Parse the outputs of a started run, store them and finish the run."""
    # Fresh copies: an earlier kind's rollback may have expired the loaded objects.
    run = await session.get(CollectionRun, run_id, populate_existing=True)
    device = await session.get(Device, device_id, populate_existing=True)
    if run is None or device is None:
        raise LookupError(f"run {run_id} or device {device_id} does not exist")
    collector = COLLECTORS[run.kind]
    commands = commands_for(run.kind, device.device_type)

    parsed, errors = _parse_outputs(commands, outputs, command_errors or {})
    missing_required = collector.required - parsed.keys()
    if not parsed or missing_required:
        return await fail_run(session, run_id, "\n".join(errors))

    context = Context(session=session, device=device, run=run)
    try:
        await collector.persist(context, parsed)
        problems = errors + context.warnings
        finished_at = utcnow()
        run.status = CollectionStatus.PARTIAL if problems else CollectionStatus.SUCCESS
        run.finished_at = finished_at
        run.error = "\n".join(problems)[:_MAX_ERROR_LENGTH] or None
        device.last_polled_at = finished_at
        device.last_seen_at = finished_at
        device.reachability = Reachability.REACHABLE
        status = run.status
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("storing collected data failed", extra={"run_id": str(run_id)})
        return await fail_run(session, run_id, f"storing failed: {type(exc).__name__}: {exc}")
    return status


async def ingest_raw(
    session: AsyncSession,
    device: Device,
    kind: CollectionKind,
    raw_outputs: Mapping[str, str],
    *,
    trigger: CollectionTrigger = CollectionTrigger.MANUAL,
    started_at: datetime | None = None,
) -> CollectionRun:
    """Store recorded output (command -> raw text) for one collection kind as a new run."""
    run_id = await start_run(session, device.id, kind, trigger, started_at)
    await complete_run(session, device.id, run_id, raw_outputs)
    run = await session.get(CollectionRun, run_id, populate_existing=True)
    if run is None:
        raise LookupError(f"run {run_id} disappeared")
    return run
