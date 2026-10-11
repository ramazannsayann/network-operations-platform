"""Configuration management (M4): versions (text in Git), diffs and detected changes.

Every configuration text the API returns is redacted (ADR-0007): secret values are replaced
by ``<redacted>`` (certificates by one ``<certificate redacted>`` line) and the rest of each
line is kept, so a diff still shows that a secret line changed. No endpoint returns the
complete text.
"""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, Page, example
from netops.db.enums import ChangeOrigin, CollectionStatus, ConfigTrigger

_V0: dict[str, Any] = {
    "id": ex.CONFIG_V0,
    "device_id": ex.DEV_DIST_B,
    "collected_at": "2026-10-07T02:00:00Z",
    "git_commit": "4d2b6f8a0c1e3d5b7f9a1c3e5d7b9f1a3c5e7d9b",
    "content_hash": "a1c3e5b7d9f1a3c5e7b9d1f3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c3",
    "trigger": "scheduled",
    "size_bytes": 18339,
}
_V1: dict[str, Any] = {
    "id": ex.CONFIG_V1,
    "device_id": ex.DEV_DIST_B,
    "collected_at": "2026-10-08T02:00:00Z",
    "git_commit": "9f1c2e7a4b8d3f6e0a1b2c3d4e5f60718293a4b5",
    "content_hash": "4b7d1e9c2a6f8053e1d7c4b9a2f6e8d0c3b5a7f9e1d2c4b6a8f0e2d4c6b8a0f2",
    "trigger": "scheduled",
    "size_bytes": 18342,
}
_V2: dict[str, Any] = {
    "id": ex.CONFIG_V2,
    "device_id": ex.DEV_DIST_B,
    "collected_at": "2026-10-08T22:41:40Z",
    "git_commit": "c3e5a7b9d1f2e4c6a8b0d2f4e6c8a0b2d4f6e8a1",
    "content_hash": "e2a4c6b8d0f1e3a5c7b9d1f3e5a7c9b1d3f5e7a9c1b3d5f7e9a1c3b5d7f9e1a3",
    "trigger": "change_event",
    "size_bytes": 18301,
}
_DIFF = """--- dist-sw-b @ 2026-10-08T02:00:00Z
+++ dist-sw-b @ 2026-10-08T22:41:40Z
@@ -212,7 +212,7 @@
 interface GigabitEthernet1/0/3
  description access sw-b2-03 Gi1/0/49
  switchport mode trunk
- switchport trunk allowed vlan 20,30,99
+ switchport trunk allowed vlan 30,99
  switchport trunk native vlan 99
 !
@@ -386,3 +386,3 @@
 !
-username jdoe privilege 15 secret 9 <redacted>
+username jdoe privilege 15 secret 9 <redacted>
 !
"""
CHANGE_EXAMPLE: dict[str, Any] = {
    "id": ex.CHANGE_TRUNK_VLAN,
    "device": ex.DEVICE_REF_DIST_B,
    "detected_at": ex.T_CHANGE,
    "origin": "external",
    "username": "jdoe",
    "source_ip": "10.0.0.250",
    "commands": ["interface GigabitEthernet1/0/3", "switchport trunk allowed vlan remove 20"],
    "before_version_id": ex.CONFIG_V1,
    "after_version_id": ex.CONFIG_V2,
    "detected_by": "change_event",
}
_CHANGE_UNREPORTED: dict[str, Any] = CHANGE_EXAMPLE | {
    "id": ex.CHANGE_UNREPORTED,
    "detected_at": "2026-10-08T02:00:00Z",
    "username": None,
    "source_ip": None,
    "commands": [],
    "before_version_id": ex.CONFIG_V0,
    "after_version_id": ex.CONFIG_V1,
    "detected_by": "scheduled",
}


class ConfigVersion(ApiModel):
    model_config = example(_V2)

    id: UUID
    device_id: UUID
    collected_at: AwareDatetime
    git_commit: str
    content_hash: str = Field(description="sha256 of the normalized configuration.")
    trigger: ConfigTrigger
    size_bytes: int = Field(ge=0)


class ConfigVersionPage(Page[ConfigVersion]):
    model_config = example(ex.page([_V2, _V1], total=37))


class ConfigVersionContent(ConfigVersion):
    model_config = example(
        _V2
        | {
            "content": "hostname dist-sw-b\n!\ninterface GigabitEthernet1/0/3\n"
            " description access sw-b2-03 Gi1/0/49\n switchport mode trunk\n"
            " switchport trunk allowed vlan 30,99\n switchport trunk native vlan 99\n!\n"
            "snmp-server community <redacted> RO 20\n!\nend\n"
        }
    )

    content: str = Field(
        description="The normalized configuration with secrets redacted (``<redacted>``)."
    )


class ConfigDiff(ApiModel):
    model_config = example(
        {
            "from_version": _V1,
            "to_version": _V2,
            "unified_diff": _DIFF,
            "added_lines": 2,
            "removed_lines": 2,
        }
    )

    from_version: ConfigVersion
    to_version: ConfigVersion
    unified_diff: str = Field(
        description="Unified diff of the redacted texts (computed on the complete texts, so a "
        "changed secret shows as a changed line); empty when they are equal."
    )
    added_lines: int = Field(ge=0)
    removed_lines: int = Field(ge=0)


class ConfigChange(ApiModel):
    model_config = example(CHANGE_EXAMPLE)

    id: UUID
    device: DeviceRef
    detected_at: AwareDatetime = Field(
        description="When the first syslog message of the change arrived, or when the backup "
        "that found it ran."
    )
    origin: ChangeOrigin = Field(
        description="``platform``: made by the platform's write account (M5); ``external``: "
        "made outside the platform (CLI session, another tool) or by an unknown user."
    )
    username: str | None = Field(description="NULL when no syslog reported the change.")
    source_ip: IPvAnyAddress | None
    commands: list[str] = Field(description="Commands as entered (archive log), redacted.")
    before_version_id: UUID | None
    after_version_id: UUID | None
    detected_by: ConfigTrigger | None = Field(
        description="Trigger of the backup that recorded the new version: ``change_event`` "
        "(syslog reported the change) or ``scheduled`` / ``manual`` (a backup found a "
        "difference nobody reported)."
    )


class ConfigChangePage(Page[ConfigChange]):
    model_config = example(ex.page([CHANGE_EXAMPLE, _CHANGE_UNREPORTED], total=2))


_BACKUP_SUMMARY: dict[str, Any] = {
    "device": ex.DEVICE_REF_DIST_B,
    "last_backup_at": "2026-10-09T02:30:12Z",
    "last_backup_status": "success",
    "version_count": 37,
    "latest_version": _V2,
    "last_change_at": ex.T_CHANGE,
    "recent_external_changes": 2,
}


class ConfigBackupSummary(ApiModel):
    """Backup state of one managed device (the Config page)."""

    model_config = example(_BACKUP_SUMMARY)

    device: DeviceRef
    last_backup_at: AwareDatetime | None = Field(
        description="When the latest successful backup (config collection run) finished."
    )
    last_backup_status: CollectionStatus | None = Field(
        description="Status of the latest backup attempt; NULL if there was none."
    )
    version_count: int = Field(ge=0)
    latest_version: ConfigVersion | None
    last_change_at: AwareDatetime | None
    recent_external_changes: int = Field(
        ge=0, description="External changes detected in the last ``days`` days."
    )


class ConfigBackupSummaryPage(Page[ConfigBackupSummary]):
    model_config = example(ex.page([_BACKUP_SUMMARY]))
