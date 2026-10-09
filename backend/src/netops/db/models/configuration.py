"""Configuration management (M4/M5): config versions and detected changes.

The configuration text itself lives in the Git repository, not in the database.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import ChangeOrigin, ConfigTrigger
from netops.db.models._common import EntityMixin, host_address


class ConfigVersion(EntityMixin, Base):
    """A distinct configuration of a device, committed to Git.

    A new row is written only when the normalized configuration changed; every backup
    attempt is recorded as a ``config`` collection run.
    """

    __tablename__ = "config_versions"
    __table_args__ = (
        UniqueConstraint("device_id", "git_commit", name="uq_config_versions_device_id_git_commit"),
        # SHA-1 (40) or SHA-256 (64) object names.
        CheckConstraint("git_commit ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'", name="git_commit_format"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    collected_at: Mapped[datetime]
    git_commit: Mapped[str]
    # sha256 (hex) of the normalized config; M5 compares it before pushing a change.
    content_hash: Mapped[str]
    trigger: Mapped[ConfigTrigger]
    size_bytes: Mapped[int]


# Latest version of a device and its version history.
Index(
    "ix_config_versions_device_id_collected_at",
    ConfigVersion.device_id,
    ConfigVersion.collected_at.desc(),
)


class ConfigChange(EntityMixin, Base):
    """A configuration change, made through the platform (M5) or outside it (CLI, PuTTY)."""

    __tablename__ = "config_changes"
    __table_args__ = (
        host_address("source_ip"),
        CheckConstraint("before_version_id <> after_version_id", name="versions_differ"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    detected_at: Mapped[datetime] = mapped_column(server_default=func.now())
    origin: Mapped[ChangeOrigin]
    # From %SYS-5-CONFIG_I / archive log; NULL when unknown (e.g. found by the nightly diff).
    username: Mapped[str | None]
    source_ip: Mapped[str | None] = mapped_column(INET)
    # Commands as entered (archive log config) or as pushed by M5.
    commands: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )
    before_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("config_versions.id", ondelete="SET NULL")
    )
    after_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("config_versions.id", ondelete="SET NULL")
    )


# Change-fault correlation: "changes on device D in the hour before T".
Index(
    "ix_config_changes_device_id_detected_at",
    ConfigChange.device_id,
    ConfigChange.detected_at.desc(),
)
# Network-wide change timeline, newest first.
Index("ix_config_changes_detected_at", ConfigChange.detected_at.desc())
