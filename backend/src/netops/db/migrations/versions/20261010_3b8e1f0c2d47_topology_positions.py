"""Saved topology map positions (topology_positions).

Revision ID: 3b8e1f0c2d47
Revises: c0fc6d6d7835
Create Date: 2026-10-10 08:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3b8e1f0c2d47"
down_revision: str | Sequence[str] | None = "c0fc6d6d7835"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here on purpose (see the shared data model migration).
ENUMS: dict[str, tuple[str, ...]] = {"topology_layer": ("l2", "l3")}


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind)

    op.create_table(
        "topology_positions",
        sa.Column(
            "layer",
            postgresql.ENUM(*ENUMS["topology_layer"], name="topology_layer", create_type=False),
            nullable=False,
        ),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "device_id IS NULL OR node_id = device_id::text",
            name=op.f("ck_topology_positions_node_is_the_device"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_topology_positions_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("layer", "node_id", name=op.f("pk_topology_positions")),
    )
    op.create_index("ix_topology_positions_device_id", "topology_positions", ["device_id"])


def downgrade() -> None:
    op.drop_table("topology_positions")
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind)
