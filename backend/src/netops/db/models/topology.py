"""Topology entities (M1): physical links between interfaces."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from netops.db.base import Base
from netops.db.enums import LinkSource
from netops.db.models._common import EntityMixin, SeenMixin


class Link(EntityMixin, SeenMixin, Base):
    """A physical link. Endpoints are ordered (a < b) so each cable is stored exactly once.

    EtherChannels are not links of their own: members are linked individually and grouped
    through interfaces.parent_interface_id.
    """

    __tablename__ = "links"
    __table_args__ = (
        UniqueConstraint(
            "a_interface_id", "b_interface_id", name="uq_links_a_interface_id_b_interface_id"
        ),
        CheckConstraint("a_interface_id < b_interface_id", name="endpoints_ordered"),
        # Links of an interface on the b side (the unique constraint covers the a side).
        Index("ix_links_b_interface_id", "b_interface_id"),
    )

    a_interface_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interfaces.id", ondelete="CASCADE")
    )
    b_interface_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interfaces.id", ondelete="CASCADE")
    )
    source: Mapped[LinkSource]
    # False once the link stops being seen; kept for topology drift reports.
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
