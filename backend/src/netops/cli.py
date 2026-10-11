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
from typing import TYPE_CHECKING, Annotated, Any

import typer
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from netops.core.secrets import Secret
from netops.core.settings import get_settings
from netops.db.enums import CredentialKind, DiscoveryItemStatus, JobStatus
from netops.db.models import CredentialProfile, Device, DeviceSerial, DiscoveryRun, DiscoveryRunItem
from netops.db.session import create_engine

if TYPE_CHECKING:
    from netops.db.enums import UserRole
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
configs = typer.Typer(help="Configuration backups (M4).", no_args_is_help=True)
users = typer.Typer(help="Platform users (M7).", no_args_is_help=True)
app.add_typer(users, name="users")
app.add_typer(credentials, name="credentials")
app.add_typer(devices, name="devices")
app.add_typer(configs, name="configs")


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
        from netops.auth.credentials import ProfileFields, create_profile, update_profile
        from netops.auth.users import CLI

        profile = await session.scalar(
            select(CredentialProfile).where(CredentialProfile.name == name)
        )
        if profile is not None and not update:
            raise typer.BadParameter(f"profile {name!r} exists (use --update to replace it)")
        fields = ProfileFields(
            name=name,
            username=username,
            password=password,
            enable_secret=enable_secret,
            clear_enable_secret=enable_secret is None,
        )
        if profile is None:
            profile = await create_profile(session, CLI, CredentialKind.SSH, fields)
        else:
            profile = await update_profile(session, CLI, profile, fields)
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


@configs.command("backup")
def configs_backup(
    device: Annotated[
        str | None, typer.Option(help="Only this device (hostname or management address).")
    ] = None,
    inline: Annotated[
        bool, typer.Option(help="Run here instead of on a worker (local tests only).")
    ] = False,
) -> None:
    """Back up configurations now, as the scheduled backup does (trigger "scheduled")."""
    from netops.configmgmt.tasks import managed_devices
    from netops.db.enums import CollectionKind, CollectionTrigger

    if device is None:
        ids = asyncio.run(managed_devices())
    else:

        async def find(session: AsyncSession) -> list[uuid.UUID]:
            found = await session.scalars(
                select(Device.id).where(
                    or_(Device.hostname == device, func.host(Device.mgmt_ip) == device)
                )
            )
            return list(found)

        ids = _db(find)
        if not ids:
            raise typer.BadParameter(f"no device {device!r}")
    if inline:
        from netops.inventory.service import collect_device

        for device_id in ids:
            outcome = asyncio.run(
                collect_device(
                    device_id, [CollectionKind.CONFIG], CollectionTrigger.SCHEDULED, get_settings()
                )
            )
            typer.echo(f"{device_id}: {outcome}")
        return
    from netops.workers.celery_app import celery_app

    for device_id in ids:
        celery_app.send_task(
            "netops.collect_device",
            kwargs={
                "device_id": str(device_id),
                "kinds": [CollectionKind.CONFIG.value],
                "trigger": CollectionTrigger.SCHEDULED.value,
            },
        )
    typer.echo(f"Configuration backup queued for {len(ids)} devices.")


# --- users (M7) -------------------------------------------------------------------------------


def _new_password(password_stdin: bool, label: str = "Password") -> str:
    """Read a new password (hidden prompt with confirmation, or stdin) and check the
    policy here, so a rejected one can be retyped."""
    from netops.auth.passwords import check_policy

    while True:
        value = _read_secret(label, password_stdin)
        violations = check_policy(value)
        if not violations:
            return value
        message = " ".join(v.message for v in violations)
        if password_stdin:
            raise typer.BadParameter(message)
        typer.echo(f"Rejected: {message}", err=True)


def _role(value: str) -> "UserRole":
    from netops.db.enums import UserRole

    try:
        return UserRole(value)
    except ValueError:
        choices = ", ".join(r.value for r in UserRole)
        raise typer.BadParameter(f"role must be one of {choices}") from None


def _create_user(
    username: str,
    display_name: str | None,
    email: str | None,
    role: "UserRole",
    password: str,
    must_change_password: bool,
) -> str:
    from netops.auth.service import ConflictError, PasswordRejectedError
    from netops.auth.users import CLI, InvalidUsernameError, create_user

    async def create(session: AsyncSession) -> str:
        user = await create_user(
            session,
            CLI,
            username=username,
            display_name=display_name or username,
            email=email,
            role=role,
            password=password,
            must_change_password=must_change_password,
        )
        return str(user.id)

    try:
        return _db(create)
    except (ConflictError, PasswordRejectedError, InvalidUsernameError) as exc:
        raise typer.BadParameter(str(exc)) from None


@users.command("create-admin")
def users_create_admin(
    username: Annotated[str, typer.Option(prompt=True, help="Login name (lower-cased).")],
    display_name: Annotated[str | None, typer.Option(help="Full name.")] = None,
    email: Annotated[str | None, typer.Option(help="Email address.")] = None,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the password from stdin.")
    ] = False,
    force: Annotated[
        bool, typer.Option(help="Create one even though an active admin exists (asks first).")
    ] = False,
) -> None:
    """Create the first admin (the platform has no default account). Refuses while an
    active admin exists, unless --force is given and confirmed. The password is typed
    hidden (twice) and never echoed; MFA enrollment follows at the first sign-in."""
    from netops.auth.users import active_admins
    from netops.db.enums import UserRole

    admins = _db(active_admins)
    if admins and not force:
        raise typer.BadParameter(
            f"{admins} active admin(s) exist; sign in as one of them, or use --force"
        )
    if admins and not typer.confirm(
        f"{admins} active admin(s) already exist. Create another admin anyway?", default=False
    ):
        raise typer.Abort()
    password = _new_password(password_stdin)
    user_id = _create_user(username, display_name, email, UserRole.ADMIN, password, False)
    typer.echo(f"Created admin {username.strip().lower()!r} ({user_id}).")


@users.command("create")
def users_create(
    username: Annotated[str, typer.Argument(help="Login name (lower-cased).")],
    role: Annotated[str, typer.Option(help="admin, operator or viewer.")] = "viewer",
    display_name: Annotated[str | None, typer.Option(help="Full name.")] = None,
    email: Annotated[str | None, typer.Option(help="Email address.")] = None,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the password from stdin.")
    ] = False,
    temporary: Annotated[
        bool, typer.Option(help="The user must change the password at the first sign-in.")
    ] = True,
) -> None:
    """Create a user (admins normally do this in the UI)."""
    password = _new_password(password_stdin)
    user_id = _create_user(username, display_name, email, _role(role), password, temporary)
    typer.echo(f"Created user {username.strip().lower()!r} ({user_id}).")


def _user_action(username: str, action: Callable[[AsyncSession, Any], Awaitable[None]]) -> None:
    from netops.db.models import User

    async def run(session: AsyncSession) -> bool:
        user = await session.scalar(select(User).where(User.username == username.strip().lower()))
        if user is None:
            return False
        await action(session, user)
        return True

    if not _db(run):
        raise typer.BadParameter(f"no user {username!r}")


@users.command("list")
def users_list() -> None:
    """List users with role, state and MFA (never their secrets)."""
    from netops.db.models import User

    async def load(session: AsyncSession) -> list[list[str]]:
        rows = await session.scalars(select(User).order_by(User.username))
        return [
            [
                u.username,
                u.role.value,
                "active" if u.is_active else "inactive",
                "on" if u.mfa_enabled else "off",
                u.last_login_at.isoformat(timespec="seconds") if u.last_login_at else "-",
            ]
            for u in rows
        ]

    _table(_db(load), ["USERNAME", "ROLE", "STATE", "MFA", "LAST LOGIN"])


@users.command("set-password")
def users_set_password(
    username: Annotated[str, typer.Argument()],
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the password from stdin.")
    ] = False,
    temporary: Annotated[
        bool, typer.Option(help="The user must change it at the next sign-in.")
    ] = True,
) -> None:
    """Set a user's password on the server (e.g. the only admin forgot theirs); ends the
    user's sessions and lifts a lockout."""
    from netops.auth.users import CLI, reset_password

    password = _new_password(password_stdin)

    async def act(session: AsyncSession, user: Any) -> None:
        await reset_password(session, CLI, user, password)
        if not temporary:
            user.must_change_password = False
            await session.commit()

    _user_action(username, act)
    typer.echo(f"Password of {username!r} set.")


@users.command("reset-mfa")
def users_reset_mfa(username: Annotated[str, typer.Argument()]) -> None:
    """Remove a user's authenticator and recovery codes (lost phone)."""
    from netops.auth.users import CLI, reset_mfa

    async def act(session: AsyncSession, user: Any) -> None:
        await reset_mfa(session, CLI, user)

    _user_action(username, act)
    typer.echo(f"MFA of {username!r} reset; they enroll again at the next sign-in.")


@users.command("unlock")
def users_unlock(username: Annotated[str, typer.Argument()]) -> None:
    """Lift a lockout after failed sign-ins."""
    from netops.auth.users import CLI, unlock

    async def act(session: AsyncSession, user: Any) -> None:
        await unlock(session, CLI, user)

    _user_action(username, act)
    typer.echo(f"{username!r} unlocked.")
