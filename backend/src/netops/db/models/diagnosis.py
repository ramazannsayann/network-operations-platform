"""Fault diagnosis (M6): findings, i.e. root-cause candidates with their reasoning."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import Severity
from netops.db.models._common import EntityMixin


class Finding(EntityMixin, Base):
    """One diagnosis result: what is wrong, why we think so, and how strongly."""

    __tablename__ = "findings"

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # NULL for findings of an on-demand check that is not tied to an incident.
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE")
    )
    # Rule that produced it, e.g. "port.crc_rising", "link.native_vlan_mismatch".
    kind: Mapped[str]
    severity: Mapped[Severity]
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    interface_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interfaces.id", ondelete="SET NULL")
    )
    title: Mapped[str]
    explanation: Mapped[str]
    # Reasoning chain: ordered steps, each naming the data it used (collection_run ids,
    # event ids, timestamps) and the rule applied, so a finding can be verified.
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # Ranks root-cause candidates within an incident; higher is more likely.
    score: Mapped[int] = mapped_column(default=0, server_default="0")


# Root-cause candidates of an incident, best first.
Index("ix_findings_incident_id_score", Finding.incident_id, Finding.score.desc())
# A device's diagnosis history.
Index("ix_findings_device_id_created_at", Finding.device_id, Finding.created_at.desc())
