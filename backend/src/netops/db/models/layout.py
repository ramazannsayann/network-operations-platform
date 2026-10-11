"""Saved positions of topology map nodes (one global layout per layer until M7 adds users)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import TopologyLayer


class TopologyPosition(Base):
    """Where an operator placed a node. ``node_id`` is the device id, or a subnet prefix on
    the L3 map; device positions disappear with their device."""

    __tablename__ = "topology_positions"
    __table_args__ = (
        CheckConstraint(
            "device_id IS NULL OR node_id = device_id::text", name="node_is_the_device"
        ),
        # Positions of a device (cleanup when the device is deleted, ON DELETE CASCADE).
        Index("ix_topology_positions_device_id", "device_id"),
    )

    layer: Mapped[TopologyLayer] = mapped_column(primary_key=True)
    node_id: Mapped[str] = mapped_column(primary_key=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    x: Mapped[float]
    y: Mapped[float]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
