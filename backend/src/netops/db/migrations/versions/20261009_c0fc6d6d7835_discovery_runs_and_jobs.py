"""Discovery runs and items, jobs, and devices.management_status / role_is_manual / ssh_port.

Revision ID: c0fc6d6d7835
Revises: 5c3f79f02fc2
Create Date: 2026-10-09 20:01:59.664496+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c0fc6d6d7835"
down_revision: str | Sequence[str] | None = "5c3f79f02fc2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here on purpose (see the shared data model migration).
ENUMS: dict[str, tuple[str, ...]] = {
    "management_status": (
        "managed",
        "out_of_scope",
        "auth_failed",
        "unreachable",
        "unsupported_platform",
        "manual",
    ),
    "discovery_item_status": (
        "discovered",
        "duplicate",
        "auth_failed",
        "unreachable",
        "out_of_scope",
        "unsupported_platform",
        "no_mgmt_ip",
    ),
    "job_kind": ("device_refresh", "discovery"),
    "job_status": ("queued", "running", "succeeded", "failed"),
}


def _enum(name: str) -> postgresql.ENUM:
    if name == "discovery_source":  # created by the shared data model migration
        return postgresql.ENUM(name=name, create_type=False)
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind)

    op.add_column(
        "devices",
        sa.Column("role_is_manual", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "devices",
        sa.Column(
            "management_status",
            _enum("management_status"),
            server_default="manual",
            nullable=False,
        ),
    )
    op.add_column("devices", sa.Column("ssh_port", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_devices_ssh_port_valid"), "devices", "ssh_port BETWEEN 1 AND 65535"
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", _enum("job_kind"), nullable=False),
        sa.Column("status", _enum("job_status"), server_default="queued", nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("progress_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status <> 'failed' OR error IS NOT NULL", name=op.f("ck_jobs_failed_has_error")
        ),
        sa.CheckConstraint(
            "progress_completed >= 0 AND progress_total >= 0",
            name=op.f("ck_jobs_progress_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_target_id_created_at", "jobs", ["target_id", "created_at"])

    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum("job_status"), server_default="queued", nullable=False),
        sa.Column("seeds", postgresql.ARRAY(postgresql.INET()), nullable=False),
        sa.Column("allowed_subnets", postgresql.ARRAY(postgresql.CIDR()), nullable=False),
        sa.Column("credential_profile_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new_devices", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status <> 'failed' OR error IS NOT NULL",
            name=op.f("ck_discovery_runs_failed_has_error"),
        ),
        sa.CheckConstraint(
            "cardinality(allowed_subnets) > 0", name=op.f("ck_discovery_runs_has_allowed_subnets")
        ),
        sa.CheckConstraint(
            "cardinality(credential_profile_ids) > 0", name=op.f("ck_discovery_runs_has_profiles")
        ),
        sa.CheckConstraint("cardinality(seeds) > 0", name=op.f("ck_discovery_runs_has_seeds")),
        sa.CheckConstraint(
            "queued >= 0 AND scanned >= 0 AND found >= 0 AND new_devices >= 0 AND skipped >= 0 AND errors >= 0",
            name=op.f("ck_discovery_runs_counters_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_discovery_runs_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_runs")),
        sa.UniqueConstraint("job_id", name=op.f("uq_discovery_runs_job_id")),
    )
    op.create_index("ix_discovery_runs_requested_at", "discovery_runs", ["requested_at"])

    op.create_table(
        "discovery_run_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("address", postgresql.INET(), nullable=True),
        sa.Column("hop", sa.Integer(), nullable=False),
        sa.Column("via_device_id", sa.Uuid(), nullable=True),
        sa.Column("via_interface", sa.Text(), nullable=True),
        sa.Column("source", _enum("discovery_source"), nullable=False),
        sa.Column("neighbor_name", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("status", _enum("discovery_item_status"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("is_new", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "address IS NOT NULL OR status = 'no_mgmt_ip'",
            name=op.f("ck_discovery_run_items_address_unless_no_mgmt_ip"),
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 2", name=op.f("ck_discovery_run_items_at_most_two_attempts")
        ),
        sa.CheckConstraint("hop >= 0", name=op.f("ck_discovery_run_items_hop_non_negative")),
        sa.CheckConstraint(
            "masklen(address) = CASE family(address) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_discovery_run_items_address_is_host"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_discovery_run_items_device_id_devices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["discovery_runs.id"],
            name=op.f("fk_discovery_run_items_run_id_discovery_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["via_device_id"],
            ["devices.id"],
            name=op.f("fk_discovery_run_items_via_device_id_devices"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_run_items")),
    )
    op.create_index("ix_discovery_run_items_device_id", "discovery_run_items", ["device_id"])
    op.create_index("ix_discovery_run_items_run_id_hop", "discovery_run_items", ["run_id", "hop"])
    op.create_index(
        "ix_discovery_run_items_via_device_id", "discovery_run_items", ["via_device_id"]
    )
    op.create_index(
        "uq_discovery_run_items_run_id_address",
        "discovery_run_items",
        ["run_id", "address"],
        unique=True,
        postgresql_where="address IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_table("discovery_run_items")
    op.drop_table("discovery_runs")
    op.drop_table("jobs")
    op.drop_constraint(op.f("ck_devices_ssh_port_valid"), "devices", type_="check")
    op.drop_column("devices", "ssh_port")
    op.drop_column("devices", "management_status")
    op.drop_column("devices", "role_is_manual")
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind)
