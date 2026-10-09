"""Device access over SSH (Nornir + Netmiko), read-only.

The read path exposes only ``run_show``: every command must pass the read-only guard
(``guard.check_read_only``) before any connection is opened. Configuration changes are not
possible through this package; M5 will add a separate, audited write path (ADR-0004).
"""

from netops.netaccess.guard import ReadOnlyCommandError, check_read_only
from netops.netaccess.inventory import DeviceAccess, DeviceAccessError, load_device_access
from netops.netaccess.runner import ShowResult, run_show

__all__ = [
    "DeviceAccess",
    "DeviceAccessError",
    "ReadOnlyCommandError",
    "ShowResult",
    "check_read_only",
    "load_device_access",
    "run_show",
]
