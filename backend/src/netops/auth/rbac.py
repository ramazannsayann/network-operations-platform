"""Permissions and the roles that have them: the only place this mapping lives.

Every API route declares exactly one permission (``netops.api.security.guard``); a test
fails for a route without one and checks every role against every route. Proposal 7.7:
viewer reads, operator also runs discovery, refreshes, backups and saves the map layout,
admin does everything, including users, credential profiles and the audit log.
"""

from enum import StrEnum

from netops.db.enums import UserRole


class Permission(StrEnum):
    DEVICES_READ = "devices:read"
    DEVICES_REFRESH = "devices:refresh"
    TOPOLOGY_READ = "topology:read"
    TOPOLOGY_LAYOUT_WRITE = "topology:layout:write"
    DISCOVERY_READ = "discovery:read"
    DISCOVERY_RUN = "discovery:run"
    CONFIGS_READ = "configs:read"
    CONFIGS_BACKUP = "configs:backup"
    EVENTS_READ = "events:read"
    METRICS_READ = "metrics:read"
    ALARMS_READ = "alarms:read"
    ALARMS_ACK = "alarms:ack"
    DIAGNOSIS_READ = "diagnosis:read"
    LOCATIONS_READ = "locations:read"
    LOCATIONS_MANAGE = "locations:manage"
    JOBS_READ = "jobs:read"
    CREDENTIALS_READ = "credentials:read"
    CREDENTIALS_MANAGE = "credentials:manage"
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"
    # The signed-in user's own account: profile, password, MFA, sessions, logout.
    PROFILE = "profile:self"


_VIEWER = frozenset(
    {
        Permission.DEVICES_READ,
        Permission.TOPOLOGY_READ,
        Permission.DISCOVERY_READ,
        Permission.CONFIGS_READ,
        Permission.EVENTS_READ,
        Permission.METRICS_READ,
        Permission.ALARMS_READ,
        Permission.DIAGNOSIS_READ,
        Permission.LOCATIONS_READ,
        Permission.JOBS_READ,
        Permission.PROFILE,
    }
)
_OPERATOR = _VIEWER | {
    Permission.DISCOVERY_RUN,
    Permission.DEVICES_REFRESH,
    Permission.CONFIGS_BACKUP,
    Permission.TOPOLOGY_LAYOUT_WRITE,
    Permission.ALARMS_ACK,
    # Names of the profiles a discovery run may try (never their secrets).
    Permission.CREDENTIALS_READ,
}

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.VIEWER: _VIEWER,
    UserRole.OPERATOR: frozenset(_OPERATOR),
    UserRole.ADMIN: frozenset(Permission),
}


def permissions_of(role: UserRole) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]
