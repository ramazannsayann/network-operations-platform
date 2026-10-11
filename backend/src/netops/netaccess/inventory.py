"""Who to connect to and how: devices + credential profiles -> Nornir inventory."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from nornir.core import Nornir
from nornir.core.configuration import Config, LoggingConfig
from nornir.core.inventory import (
    ConnectionOptions,
    Defaults,
    Groups,
    Host,
    Hosts,
    Inventory,
)
from nornir.core.plugins.connections import ConnectionPluginRegister
from nornir.plugins.runners import ThreadedRunner
from nornir_netmiko.connections import Netmiko
from sqlalchemy.ext.asyncio import AsyncSession

from netops.core.secrets import Secret
from netops.core.settings import Settings
from netops.db.enums import CredentialKind, OsFamily
from netops.db.models import CredentialProfile, Device
from netops.netaccess.target import TargetResolver, resolve_target

logger = logging.getLogger(__name__)

CONNECTION = "netmiko"
ConnectionPluginRegister.register(CONNECTION, Netmiko)

# Netmiko device types. Until the facts collector has identified the OS, IOS is assumed:
# the commands and prompts this read path uses are the same on IOS-XE.
NETMIKO_PLATFORMS = {
    OsFamily.IOS: "cisco_ios",
    OsFamily.IOSXE: "cisco_xe",
    OsFamily.UNKNOWN: "cisco_ios",
}


class DeviceAccessError(Exception):
    """The device cannot be reached over SSH as configured (no address, no profile, ...)."""


@dataclass(frozen=True, slots=True)
class DeviceAccess:
    """Everything needed to open an SSH session to one device. Secrets stay wrapped."""

    device_id: UUID
    name: str
    host: str
    port: int
    platform: str
    username: str
    password: Secret = field(repr=False)
    enable_secret: Secret | None = field(default=None, repr=False)

    def secrets(self) -> tuple[Secret, ...]:
        return tuple(s for s in (self.password, self.enable_secret) if s is not None)


def device_access(device: Device, profile: CredentialProfile | None, port: int) -> DeviceAccess:
    """``port`` is the global SSH_PORT, used unless the device has a port of its own."""
    label = device.hostname or str(device.mgmt_ip or device.id)
    if device.mgmt_ip is None:
        raise DeviceAccessError(f"{label}: no management address")
    if profile is None:
        raise DeviceAccessError(f"{label}: no credential profile assigned")
    if profile.kind is not CredentialKind.SSH or profile.password is None:
        raise DeviceAccessError(
            f"{label}: credential profile {profile.name!r} is not an SSH profile"
        )
    platform = NETMIKO_PLATFORMS.get(device.os_family)
    if platform is None:
        raise DeviceAccessError(f"{label}: {device.os_family} is not supported over SSH")
    return DeviceAccess(
        device_id=device.id,
        name=label,
        host=str(device.mgmt_ip),
        port=device.ssh_port or port,
        platform=platform,
        username=profile.username,
        password=profile.password,
        enable_secret=profile.enable_secret,
    )


async def load_device_access(session: AsyncSession, device: Device, port: int) -> DeviceAccess:
    profile = (
        await session.get(CredentialProfile, device.credential_profile_id)
        if device.credential_profile_id
        else None
    )
    return device_access(device, profile, port)


_warned_about_host_keys = False


def netmiko_options(access: DeviceAccess, settings: Settings) -> dict[str, Any]:
    """ConnectHandler arguments other than host/port/username/password."""
    global _warned_about_host_keys
    strict = settings.ssh_strict_host_key_checking
    if not strict and not _warned_about_host_keys:
        logger.warning(
            "SSH host keys are not verified (SSH_STRICT_HOST_KEY_CHECKING is off); "
            "acceptable in the lab only, see ADR-0004"
        )
        _warned_about_host_keys = True
    options: dict[str, Any] = {
        "conn_timeout": settings.ssh_connect_timeout_seconds,
        "auth_timeout": settings.ssh_connect_timeout_seconds,
        "banner_timeout": settings.ssh_connect_timeout_seconds,
        "read_timeout_override": settings.ssh_command_timeout_seconds,
        # Only the profile's password: no SSH agent or keys from the worker's home directory.
        "use_keys": False,
        "allow_agent": False,
        "ssh_strict": strict,
        "system_host_keys": strict and settings.ssh_known_hosts_file is None,
        "alt_host_keys": settings.ssh_known_hosts_file is not None,
        "alt_key_file": str(settings.ssh_known_hosts_file or ""),
        "session_log": None,
    }
    if access.enable_secret is not None:
        options["secret"] = access.enable_secret.get_secret_value()
    if settings.ssh_session_log_dir is not None:
        # Debugging only. Netmiko replaces the password and enable secret in this log.
        settings.ssh_session_log_dir.mkdir(parents=True, exist_ok=True)
        options["session_log"] = str(settings.ssh_session_log_dir / f"{access.device_id}.log")
    return options


def build_nornir(
    accesses: Sequence[DeviceAccess],
    settings: Settings,
    resolve: TargetResolver = resolve_target,
) -> Nornir:
    """A Nornir object for these devices; secrets are unwrapped only into its hosts.

    ``resolve`` maps each device's address to the socket address actually connected to
    (identity in production, see netops.netaccess.target).
    """
    targets = {access.device_id: resolve(access.host, access.port) for access in accesses}
    hosts = Hosts(
        {
            str(access.device_id): Host(
                name=str(access.device_id),
                hostname=targets[access.device_id][0],
                port=targets[access.device_id][1],
                username=access.username,
                password=access.password.get_secret_value(),
                platform=access.platform,
                connection_options={
                    CONNECTION: ConnectionOptions(extras=netmiko_options(access, settings))
                },
                data={"name": access.name},
            )
            for access in accesses
        }
    )
    return Nornir(
        inventory=Inventory(hosts=hosts, groups=Groups(), defaults=Defaults()),
        runner=ThreadedRunner(num_workers=max(1, min(settings.ssh_max_concurrency, len(hosts)))),
        # Nornir's own log file is not wanted; netops logging covers it.
        config=Config(logging=LoggingConfig(enabled=False)),
    )
