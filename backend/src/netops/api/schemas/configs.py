"""Configuration management (M4): versions (text in Git), diffs and detected changes."""

from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, Field, IPvAnyAddress

from netops.api.schemas import examples as ex
from netops.api.schemas.common import ApiModel, DeviceRef, Page, example
from netops.db.enums import ChangeOrigin, ConfigTrigger

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
        }
    )

    content: str = Field(description="Normalized configuration text, as committed to Git.")


class ConfigDiff(ApiModel):
    model_config = example(
        {
            "from_version": _V1,
            "to_version": _V2,
            "unified_diff": _DIFF,
            "added_lines": 1,
            "removed_lines": 1,
        }
    )

    from_version: ConfigVersion
    to_version: ConfigVersion
    unified_diff: str
    added_lines: int = Field(ge=0)
    removed_lines: int = Field(ge=0)


class ConfigChange(ApiModel):
    model_config = example(CHANGE_EXAMPLE)

    id: UUID
    device: DeviceRef
    detected_at: AwareDatetime
    origin: ChangeOrigin
    username: str | None
    source_ip: IPvAnyAddress | None
    commands: list[str]
    before_version_id: UUID | None
    after_version_id: UUID | None


class ConfigChangePage(Page[ConfigChange]):
    model_config = example(ex.page([CHANGE_EXAMPLE]))
