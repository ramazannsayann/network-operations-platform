"""Operator CLI: ``netops ...`` (in the containers: ``docker compose exec api netops ...``).

Secrets are only ever read from a hidden prompt or from stdin (``--password-stdin``), never
from command-line arguments (they would end up in shell history and ``ps`` output), and
never printed.
"""

import asyncio
import ipaddress
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

import typer
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.secrets import Secret
from netops.core.settings import get_settings
from netops.db.enums import CredentialKind, DiscoveryItemStatus, JobStatus
from netops.db.models import CredentialProfile, Device, DeviceSerial, DiscoveryRun, DiscoveryRunItem
from netops.db.session import create_engine
from netops.discovery.service import (
    CredentialProfileError,
    DiscoveryInProgressError,
    request_discovery,
)

app = typer.Typer(
    help="NetOps platform operator commands.", no_args_is_help=True, add_completion=False
)
credentials = typer.Typer(help="Device credential profiles (SSH).", no_args_is_help=True)
devices = typer.Typer(help="Inventory.", no_args_is_help=True)
app.add_typer(credentials, name="credentials")
app.add_typer(devices, name="devices")


def _db[T](work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def main() -> T:
        engine = create_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def _table(rows: list[list[str]], header: list[str]) -> None:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for row in [header, *rows]:
        typer.echo(
            "  ".join(str(cell).ljust(width) for cell, width in zip(row, widths, strict=True))
        )


# --- credentials ------------------------------------------------------------------------------


def _read_secret(label: str, from_stdin: bool) -> str:
    if from_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
    else:
        value = typer.prompt(label, hide_input=True, confirmation_prompt=True)
    if not value:
        raise typer.BadParameter(f"{label} must not be empty")
    return value


@credentials.command("add")
def credentials_add(
    name: Annotated[str, typer.Argument(help="Unique profile name, e.g. campus-ro.")],
    username: Annotated[str, typer.Option(help="SSH username (read-only account).")],
    enable: Annotated[bool, typer.Option(help="Also prompt for an enable secret.")] = False,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the password from stdin.")
    ] = False,
    update: Annotated[bool, typer.Option(help="Replace the secrets of an existing profile.")] = (
        False
    ),
) -> None:
    """Add an SSH credential profile. The password is prompted for (hidden) or read from
    stdin; it is stored encrypted and never shown again."""
    password = Secret(_read_secret("Password", password_stdin))
    enable_secret = Secret(_read_secret("Enable secret", False)) if enable else None

    async def store(session: AsyncSession) -> str:
        profile = await session.scalar(
            select(CredentialProfile).where(CredentialProfile.name == name)
        )
        if profile is not None and not update:
            raise typer.BadParameter(f"profile {name!r} exists (use --update to replace it)")
        if profile is None:
            profile = CredentialProfile(id=uuid.uuid4(), name=name, kind=CredentialKind.SSH)
            session.add(profile)
        profile.username = username
        profile.password = password
        profile.enable_secret = enable_secret
        await session.commit()
        return str(profile.id)

    profile_id = _db(store)
    typer.echo(f"Stored SSH profile {name!r} ({profile_id}).")


@credentials.command("list")
def credentials_list() -> None:
    """List credential profiles (never their secrets)."""

    async def load(session: AsyncSession) -> list[list[str]]:
        used = (
            select(Device.credential_profile_id, func.count().label("n"))
            .group_by(Device.credential_profile_id)
            .subquery()
        )
        rows = await session.execute(
            select(CredentialProfile, used.c.n)
            .outerjoin(used, used.c.credential_profile_id == CredentialProfile.id)
            .order_by(CredentialProfile.name)
        )
        return [[p.name, p.kind.value, p.username, str(n or 0), str(p.id)] for p, n in rows.all()]

    _table(_db(load), ["NAME", "KIND", "USERNAME", "DEVICES", "ID"])


# --- discovery --------------------------------------------------------------------------------


async def _profile_ids(session: AsyncSession, profiles: list[str]) -> list[uuid.UUID]:
    ids = []
    for ref in profiles:
        try:
            condition = CredentialProfile.id == uuid.UUID(ref)
        except ValueError:
            condition = CredentialProfile.name == ref
        profile_id = await session.scalar(select(CredentialProfile.id).where(condition))
        if profile_id is None:
            raise typer.BadParameter(f"no credential profile {ref!r}")
        ids.append(profile_id)
    return ids


@app.command()
def discover(
    seed: Annotated[list[str], typer.Option(help="Seed address (repeatable).")],
    subnet: Annotated[list[str], typer.Option(help="Allowed subnet, CIDR (repeatable).")],
    profile: Annotated[
        list[str], typer.Option(help="Credential profile name or id, in order (repeatable).")
    ],
    wait: Annotated[bool, typer.Option(help="Follow the run until it finishes.")] = True,
    inline: Annotated[
        bool, typer.Option(help="Run here instead of on a worker (local tests only).")
    ] = False,
) -> None:
    """Start a CDP/LLDP discovery from the seeds, within the allowed subnets."""
    try:
        seeds = [ipaddress.ip_address(s) for s in seed]
        subnets = [ipaddress.ip_network(s, strict=False) for s in subnet]
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None

    async def request(session: AsyncSession) -> uuid.UUID:
        ids = await _profile_ids(session, profile)
        try:
            run, _ = await request_discovery(session, seeds, subnets, ids)
        except (DiscoveryInProgressError, CredentialProfileError) as exc:
            raise typer.BadParameter(str(exc)) from None
        return run.id

    run_id = _db(request)
    typer.echo(f"Discovery run {run_id} requested.")
    started = time.monotonic()
    # Imported here: the engine pulls in Nornir/Netmiko, the task the Celery app.
    if inline:
        from netops.discovery.engine import run_discovery

        asyncio.run(run_discovery(run_id, get_settings()))
    else:
        from netops.discovery.tasks import discover as discover_task

        discover_task.delay(str(run_id))
        if not wait:
            return
    status = _follow(run_id)
    typer.echo(f"Finished in {time.monotonic() - started:.1f} s.")
    _print_run(run_id)
    if status is not JobStatus.SUCCEEDED:
        raise typer.Exit(1)


def _follow(run_id: uuid.UUID) -> JobStatus:
    last = None
    while True:
        run = _db(lambda session: session.get(DiscoveryRun, run_id))
        if run is None:
            raise typer.BadParameter(f"discovery run {run_id} disappeared")
        progress = (run.status, run.scanned, run.found, run.skipped, run.errors, run.queued)
        if progress != last:
            typer.echo(
                f"  {run.status.value}: {run.found} found ({run.new_devices} new), "
                f"{run.skipped} skipped, {run.errors} errors, {run.queued} queued"
            )
            last = progress
        if run.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
            if run.error:
                typer.echo(f"  error: {run.error}", err=True)
            return run.status
        time.sleep(2)


def _print_run(run_id: uuid.UUID) -> None:
    async def load(session: AsyncSession) -> list[list[str]]:
        rows = await session.execute(
            select(DiscoveryRunItem, Device.hostname)
            .outerjoin(Device, Device.id == DiscoveryRunItem.device_id)
            .where(DiscoveryRunItem.run_id == run_id)
            .order_by(DiscoveryRunItem.hop, DiscoveryRunItem.id)
        )
        return [
            [
                str(item.hop),
                str(item.address or "-"),
                hostname or item.neighbor_name or "-",
                item.status.value,
                str(item.attempts),
                (item.error or "")[:60],
            ]
            for item, hostname in rows.all()
        ]

    rows = _db(load)
    _table(rows, ["HOP", "ADDRESS", "DEVICE", "STATUS", "LOGINS", "NOTE"])
    statuses = [row[3] for row in rows]
    summary = ", ".join(
        f"{statuses.count(s.value)} {s.value}" for s in DiscoveryItemStatus if s.value in statuses
    )
    typer.echo(summary)


# --- devices ----------------------------------------------------------------------------------


@devices.command("list")
def devices_list(
    q: Annotated[str | None, typer.Option(help="Filter: hostname, address or serial.")] = None,
) -> None:
    """List devices with their type, role and management status."""

    async def load(session: AsyncSession) -> list[list[str]]:
        serials = (
            select(DeviceSerial.device_id, func.string_agg(DeviceSerial.serial, ",").label("s"))
            .group_by(DeviceSerial.device_id)
            .subquery()
        )
        stmt = (
            select(Device, serials.c.s)
            .outerjoin(serials, serials.c.device_id == Device.id)
            .order_by(Device.hostname, Device.mgmt_ip)
        )
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Device.hostname.ilike(pattern),
                    func.host(Device.mgmt_ip).ilike(pattern),
                    serials.c.s.ilike(pattern),
                )
            )
        return [
            [
                d.hostname or "-",
                str(d.mgmt_ip or "-"),
                d.device_type.value,
                d.role.value,
                d.management_status.value,
                d.model or "-",
                s or "-",
            ]
            for d, s in (await session.execute(stmt)).all()
        ]

    rows = _db(load)
    _table(rows, ["HOSTNAME", "MGMT IP", "TYPE", "ROLE", "STATUS", "MODEL", "SERIALS"])
    typer.echo(f"{len(rows)} devices")
