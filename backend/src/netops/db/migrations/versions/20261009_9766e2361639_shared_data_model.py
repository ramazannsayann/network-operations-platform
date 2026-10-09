"""Shared data model: entities, collection runs, observation hypertables (ADR-0002).

Revision ID: 9766e2361639
Revises: 0d297f19dced
Create Date: 2026-10-09 16:50:37.633189+00:00
"""

from collections.abc import Sequence
from datetime import timedelta

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from netops.db.timescale import (
    CHUNK_INTERVAL,
    EVENTS_RETENTION,
    METRICS_RETENTION,
    OBSERVATION_RETENTION,
)

# revision identifiers, used by Alembic.
revision: str = "9766e2361639"
down_revision: str | Sequence[str] | None = "0d297f19dced"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum types are created once up front (several tables share one) and dropped last.
# Values are frozen here on purpose: later changes to netops.db.enums need a new migration.
ENUMS: dict[str, tuple[str, ...]] = {
    "incident_state": ("open", "resolved"),
    "device_type": ("switch", "l3_switch", "router", "firewall", "ap", "wlc", "unknown"),
    "device_role": ("core", "distribution", "access", "edge", "unknown"),
    "os_family": ("ios", "iosxe", "pfsense", "other", "unknown"),
    "reachability": ("reachable", "unreachable", "unknown"),
    "discovery_source": ("seed", "cdp", "lldp", "arp", "manual"),
    "collection_kind": (
        "facts",
        "interfaces",
        "neighbors",
        "vlans",
        "mac_table",
        "arp_table",
        "routes",
        "stp",
        "hsrp",
        "ospf",
        "config",
    ),
    "collection_trigger": (
        "scheduled",
        "discovery",
        "event",
        "manual",
        "pre_change",
        "post_change",
    ),
    "collection_status": ("running", "success", "partial", "failed"),
    "config_trigger": ("scheduled", "change_event", "pre_change", "post_change", "manual"),
    "event_kind": ("syslog", "trap"),
    "interface_kind": (
        "physical",
        "port_channel",
        "svi",
        "loopback",
        "tunnel",
        "management",
        "other",
    ),
    "duplex": ("full", "half", "auto", "unknown"),
    "switchport_mode": ("access", "trunk", "routed", "unknown"),
    "severity": ("critical", "major", "minor", "warning", "info"),
    "alarm_state": ("open", "acknowledged", "cleared"),
    "change_origin": ("platform", "external"),
    "hsrp_state": ("active", "standby", "listen", "speak", "learn", "init"),
    "link_source": ("cdp", "lldp", "inferred", "manual"),
    "mac_entry_type": ("dynamic", "static", "other"),
    "neighbor_protocol": ("cdp", "lldp"),
    "ospf_neighbor_state": (
        "down",
        "attempt",
        "init",
        "2way",
        "exstart",
        "exchange",
        "loading",
        "full",
    ),
    "route_protocol": ("connected", "local", "static", "ospf", "other"),
    "stp_port_role": ("root", "designated", "alternate", "backup", "disabled"),
    "stp_port_state": ("forwarding", "blocking", "learning", "listening", "disabled", "broken"),
    "vlan_status": ("active", "suspended", "shutdown", "unsupported", "unknown"),
}

# (table, time column, retention). Retention periods come from netops.db.timescale, the
# single place they are defined; changing one later needs a new migration (see there).
HYPERTABLES: tuple[tuple[str, str, timedelta], ...] = (
    ("interface_snapshots", "collected_at", OBSERVATION_RETENTION),
    ("vlan_observations", "collected_at", OBSERVATION_RETENTION),
    ("neighbor_observations", "collected_at", OBSERVATION_RETENTION),
    ("mac_entries", "collected_at", OBSERVATION_RETENTION),
    ("arp_entries", "collected_at", OBSERVATION_RETENTION),
    ("route_entries", "collected_at", OBSERVATION_RETENTION),
    ("stp_instance_observations", "collected_at", OBSERVATION_RETENTION),
    ("stp_port_observations", "collected_at", OBSERVATION_RETENTION),
    ("hsrp_observations", "collected_at", OBSERVATION_RETENTION),
    ("ospf_neighbor_observations", "collected_at", OBSERVATION_RETENTION),
    ("metrics", "time", METRICS_RETENTION),
    ("events", "received_at", EVENTS_RETENTION),
)

# Dependency order; downgrade drops them in reverse.
TABLES: tuple[str, ...] = (
    "incidents",
    "locations",
    "devices",
    "collection_runs",
    "config_versions",
    "device_serials",
    "events",
    "interfaces",
    "alarms",
    "arp_entries",
    "config_changes",
    "findings",
    "hsrp_observations",
    "interface_addresses",
    "interface_snapshots",
    "links",
    "mac_entries",
    "metrics",
    "neighbor_observations",
    "ospf_neighbor_observations",
    "route_entries",
    "stp_instance_observations",
    "stp_port_observations",
    "vlan_observations",
)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _interval(value: timedelta) -> str:
    if value % timedelta(days=1) == timedelta(0):
        return f"{value.days} days"
    return f"{int(value.total_seconds())} seconds"


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind)

    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", _enum("incident_state"), server_default="open", nullable=False),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(state = 'resolved') = (resolved_at IS NOT NULL)",
            name=op.f("ck_incidents_resolved_iff_resolved_at"),
        ),
        sa.CheckConstraint(
            "resolved_at >= opened_at", name=op.f("ck_incidents_resolved_after_opened")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_table(
        "locations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("building", sa.Text(), nullable=True),
        sa.Column("floor", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("parent_id <> id", name=op.f("ck_locations_not_own_parent")),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["locations.id"],
            name=op.f("fk_locations_parent_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
        sa.UniqueConstraint(
            "parent_id",
            "name",
            name="uq_locations_parent_id_name",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("hostname", sa.Text(), nullable=True),
        sa.Column("mgmt_ip", postgresql.INET(), nullable=True),
        sa.Column("device_type", _enum("device_type"), server_default="unknown", nullable=False),
        sa.Column("role", _enum("device_role"), server_default="unknown", nullable=False),
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("os_family", _enum("os_family"), server_default="unknown", nullable=False),
        sa.Column("os_version", sa.Text(), nullable=True),
        sa.Column("sys_object_id", sa.Text(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("is_managed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reachability", _enum("reachability"), server_default="unknown", nullable=False),
        sa.Column("discovered_via", _enum("discovery_source"), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sys_object_id ~ '^[0-9]+(\\.[0-9]+)*$'", name=op.f("ck_devices_sys_object_id_format")
        ),
        sa.CheckConstraint(
            "hostname IS NOT NULL OR mgmt_ip IS NOT NULL", name=op.f("ck_devices_identifiable")
        ),
        sa.CheckConstraint(
            "masklen(mgmt_ip) = CASE family(mgmt_ip) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_devices_mgmt_ip_is_host"),
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_devices_location_id_locations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint("mgmt_ip", name=op.f("uq_devices_mgmt_ip")),
    )
    op.create_index("ix_devices_hostname", "devices", ["hostname"], unique=False)
    op.create_index("ix_devices_location_id", "devices", ["location_id"], unique=False)
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _enum("collection_kind"), nullable=False),
        sa.Column("trigger", _enum("collection_trigger"), nullable=False),
        sa.Column("status", _enum("collection_status"), server_default="running", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_collection_runs_finished_unless_running"),
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR error IS NOT NULL",
            name=op.f("ck_collection_runs_failed_has_error"),
        ),
        sa.CheckConstraint(
            "finished_at >= started_at", name=op.f("ck_collection_runs_finished_after_started")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_collection_runs_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_runs")),
        sa.UniqueConstraint(
            "id", "device_id", "started_at", name="uq_collection_runs_id_device_id_started_at"
        ),
    )
    op.create_index(
        "ix_collection_runs_device_id_kind_started_at",
        "collection_runs",
        ["device_id", "kind", sa.literal_column("started_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_collection_runs_started_at", "collection_runs", ["started_at"], unique=False
    )
    op.create_table(
        "config_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("git_commit", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("trigger", _enum("config_trigger"), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_config_versions_content_hash_format")
        ),
        sa.CheckConstraint(
            "git_commit ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'",
            name=op.f("ck_config_versions_git_commit_format"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_config_versions_size_bytes_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_config_versions_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_config_versions")),
        sa.UniqueConstraint(
            "device_id", "git_commit", name="uq_config_versions_device_id_git_commit"
        ),
    )
    op.create_index(
        "ix_config_versions_device_id_collected_at",
        "config_versions",
        ["device_id", sa.literal_column("collected_at DESC")],
        unique=False,
    )
    op.create_table(
        "device_serials",
        sa.Column("serial", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("stack_member", sa.Integer(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "serial <> '' AND serial = upper(btrim(serial))",
            name=op.f("ck_device_serials_serial_canonical"),
        ),
        sa.CheckConstraint(
            "stack_member >= 0", name=op.f("ck_device_serials_stack_member_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_device_serials_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("serial", name=op.f("pk_device_serials")),
    )
    op.create_index("ix_device_serials_device_id", "device_serials", ["device_id"], unique=False)
    op.create_table(
        "events",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_ip", postgresql.INET(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("kind", _enum("event_kind"), nullable=False),
        sa.Column("facility", sa.SmallInteger(), nullable=True),
        sa.Column("severity", sa.SmallInteger(), nullable=True),
        sa.Column("mnemonic", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("parsed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("facility BETWEEN 0 AND 23", name=op.f("ck_events_facility_valid")),
        sa.CheckConstraint(
            "masklen(source_ip) = CASE family(source_ip) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_events_source_ip_is_host"),
        ),
        sa.CheckConstraint("severity BETWEEN 0 AND 7", name=op.f("ck_events_severity_valid")),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_events_device_id_devices"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", "received_at", name=op.f("pk_events")),
    )
    op.create_index(
        "ix_events_device_id_received_at",
        "events",
        ["device_id", sa.literal_column("received_at DESC")],
        unique=False,
    )
    op.create_table(
        "interfaces",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_normalized", sa.Text(), nullable=False),
        sa.Column("kind", _enum("interface_kind"), server_default="other", nullable=False),
        sa.Column("parent_interface_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mac", postgresql.MACADDR(), nullable=True),
        sa.Column("admin_up", sa.Boolean(), nullable=True),
        sa.Column("oper_up", sa.Boolean(), nullable=True),
        sa.Column("speed_mbps", sa.Integer(), nullable=True),
        sa.Column("duplex", _enum("duplex"), nullable=True),
        sa.Column("mtu", sa.Integer(), nullable=True),
        sa.Column("switchport_mode", _enum("switchport_mode"), nullable=True),
        sa.Column("access_vlan", sa.Integer(), nullable=True),
        sa.Column("native_vlan", sa.Integer(), nullable=True),
        sa.Column("allowed_vlans", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("err_disabled_reason", sa.Text(), nullable=True),
        sa.Column("in_errors", sa.BigInteger(), nullable=True),
        sa.Column("crc_errors", sa.BigInteger(), nullable=True),
        sa.Column("late_collisions", sa.BigInteger(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "access_vlan BETWEEN 1 AND 4094 AND native_vlan BETWEEN 1 AND 4094 AND 1 <= ALL (allowed_vlans) AND 4094 >= ALL (allowed_vlans)",
            name=op.f("ck_interfaces_vlans_valid"),
        ),
        sa.CheckConstraint(
            "in_errors >= 0 AND crc_errors >= 0 AND late_collisions >= 0",
            name=op.f("ck_interfaces_counters_non_negative"),
        ),
        sa.CheckConstraint("parent_interface_id <> id", name=op.f("ck_interfaces_not_own_parent")),
        sa.CheckConstraint(
            "speed_mbps >= 0 AND mtu > 0", name=op.f("ck_interfaces_speed_mtu_valid")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_interfaces_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_interface_id"],
            ["interfaces.id"],
            name=op.f("fk_interfaces_parent_interface_id_interfaces"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interfaces")),
        sa.UniqueConstraint(
            "device_id", "name_normalized", name="uq_interfaces_device_id_name_normalized"
        ),
    )
    op.create_index("ix_interfaces_mac", "interfaces", ["mac"], unique=False)
    op.create_index(
        "ix_interfaces_parent_interface_id", "interfaces", ["parent_interface_id"], unique=False
    )
    op.create_table(
        "alarms",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("interface_id", sa.Uuid(), nullable=True),
        sa.Column("rule_key", sa.Text(), nullable=False),
        sa.Column("severity", _enum("severity"), nullable=False),
        sa.Column("state", _enum("alarm_state"), server_default="open", nullable=False),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_occurrence_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Text(), nullable=True),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "(state = 'cleared') = (cleared_at IS NOT NULL)",
            name=op.f("ck_alarms_cleared_iff_cleared_at"),
        ),
        sa.CheckConstraint(
            "state <> 'acknowledged' OR acknowledged_at IS NOT NULL",
            name=op.f("ck_alarms_acknowledged_has_time"),
        ),
        sa.CheckConstraint(
            "last_occurrence_at >= opened_at", name=op.f("ck_alarms_last_occurrence_after_opened")
        ),
        sa.CheckConstraint(
            "occurrence_count >= 1", name=op.f("ck_alarms_occurrence_count_positive")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_alarms_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_alarms_incident_id_incidents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_alarms_interface_id_interfaces"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alarms")),
    )
    op.create_index(
        "ix_alarms_device_id_opened_at",
        "alarms",
        ["device_id", sa.literal_column("opened_at DESC")],
        unique=False,
    )
    op.create_index("ix_alarms_incident_id", "alarms", ["incident_id"], unique=False)
    op.create_index(
        "ix_alarms_opened_at_not_cleared",
        "alarms",
        ["opened_at"],
        unique=False,
        postgresql_where=sa.text("state <> 'cleared'"),
    )
    op.create_index(
        "uq_alarms_dedup_key_not_cleared",
        "alarms",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("state <> 'cleared'"),
    )
    op.create_table(
        "arp_entries",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=False),
        sa.Column("mac", postgresql.MACADDR(), nullable=False),
        sa.Column("interface_id", sa.Uuid(), nullable=False),
        sa.Column("vrf", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "masklen(ip) = CASE family(ip) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_arp_entries_ip_is_host"),
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_arp_entries_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_arp_entries_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_arp_entries")),
    )
    op.create_index(
        "ix_arp_entries_ip_collected_at",
        "arp_entries",
        ["ip", sa.literal_column("collected_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_arp_entries_mac_collected_at",
        "arp_entries",
        ["mac", sa.literal_column("collected_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_arp_entries_run_id", "arp_entries", ["run_id", "collected_at"], unique=False
    )
    op.create_table(
        "config_changes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("origin", _enum("change_origin"), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("source_ip", postgresql.INET(), nullable=True),
        sa.Column(
            "commands", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("before_version_id", sa.Uuid(), nullable=True),
        sa.Column("after_version_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "before_version_id <> after_version_id", name=op.f("ck_config_changes_versions_differ")
        ),
        sa.CheckConstraint(
            "masklen(source_ip) = CASE family(source_ip) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_config_changes_source_ip_is_host"),
        ),
        sa.ForeignKeyConstraint(
            ["after_version_id"],
            ["config_versions.id"],
            name=op.f("fk_config_changes_after_version_id_config_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["before_version_id"],
            ["config_versions.id"],
            name=op.f("fk_config_changes_before_version_id_config_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_config_changes_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_config_changes")),
    )
    op.create_index(
        "ix_config_changes_detected_at",
        "config_changes",
        [sa.literal_column("detected_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_config_changes_device_id_detected_at",
        "config_changes",
        ["device_id", sa.literal_column("detected_at DESC")],
        unique=False,
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", _enum("severity"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("interface_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_findings_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_findings_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_findings_interface_id_interfaces"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index(
        "ix_findings_device_id_created_at",
        "findings",
        ["device_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_findings_incident_id_score",
        "findings",
        ["incident_id", sa.literal_column("score DESC")],
        unique=False,
    )
    op.create_table(
        "hsrp_observations",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("interface_id", sa.Uuid(), nullable=False),
        sa.Column("group_number", sa.Integer(), nullable=False),
        sa.Column("virtual_ip", postgresql.INET(), nullable=False),
        sa.Column("state", _enum("hsrp_state"), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("preempt", sa.Boolean(), nullable=False),
        sa.Column("active_router", postgresql.INET(), nullable=True),
        sa.Column("standby_router", postgresql.INET(), nullable=True),
        sa.CheckConstraint(
            "group_number BETWEEN 0 AND 4095", name=op.f("ck_hsrp_observations_group_number_valid")
        ),
        sa.CheckConstraint(
            "masklen(active_router) = CASE family(active_router) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_hsrp_observations_active_router_is_host"),
        ),
        sa.CheckConstraint(
            "masklen(standby_router) = CASE family(standby_router) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_hsrp_observations_standby_router_is_host"),
        ),
        sa.CheckConstraint(
            "masklen(virtual_ip) = CASE family(virtual_ip) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_hsrp_observations_virtual_ip_is_host"),
        ),
        sa.CheckConstraint(
            "priority BETWEEN 0 AND 255", name=op.f("ck_hsrp_observations_priority_valid")
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_hsrp_observations_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_hsrp_observations_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_hsrp_observations")),
    )
    op.create_index(
        "ix_hsrp_observations_virtual_ip_collected_at",
        "hsrp_observations",
        ["virtual_ip", sa.literal_column("collected_at DESC")],
        unique=False,
    )
    op.create_index(
        "uq_hsrp_observations_run_interface_group",
        "hsrp_observations",
        ["run_id", "interface_id", "group_number", "collected_at"],
        unique=True,
    )
    op.create_table(
        "interface_addresses",
        sa.Column("interface_id", sa.Uuid(), nullable=False),
        sa.Column("address", postgresql.INET(), nullable=False),
        sa.Column("is_secondary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_interface_addresses_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("interface_id", "address", name=op.f("pk_interface_addresses")),
    )
    op.create_index(
        "ix_interface_addresses_address",
        "interface_addresses",
        ["address"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={"address": "inet_ops"},
    )
    op.create_table(
        "interface_snapshots",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("interface_id", sa.Uuid(), nullable=False),
        sa.Column("admin_up", sa.Boolean(), nullable=True),
        sa.Column("oper_up", sa.Boolean(), nullable=True),
        sa.Column("speed_mbps", sa.Integer(), nullable=True),
        sa.Column("duplex", _enum("duplex"), nullable=True),
        sa.Column("mtu", sa.Integer(), nullable=True),
        sa.Column("switchport_mode", _enum("switchport_mode"), nullable=True),
        sa.Column("access_vlan", sa.Integer(), nullable=True),
        sa.Column("native_vlan", sa.Integer(), nullable=True),
        sa.Column("allowed_vlans", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("err_disabled_reason", sa.Text(), nullable=True),
        sa.Column("in_errors", sa.BigInteger(), nullable=True),
        sa.Column("crc_errors", sa.BigInteger(), nullable=True),
        sa.Column("late_collisions", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "access_vlan BETWEEN 1 AND 4094 AND native_vlan BETWEEN 1 AND 4094 AND 1 <= ALL (allowed_vlans) AND 4094 >= ALL (allowed_vlans)",
            name=op.f("ck_interface_snapshots_vlans_valid"),
        ),
        sa.CheckConstraint(
            "in_errors >= 0 AND crc_errors >= 0 AND late_collisions >= 0",
            name=op.f("ck_interface_snapshots_counters_non_negative"),
        ),
        sa.CheckConstraint(
            "speed_mbps >= 0 AND mtu > 0", name=op.f("ck_interface_snapshots_speed_mtu_valid")
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_interface_snapshots_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_interface_snapshots_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_interface_snapshots")),
    )
    op.create_index(
        "ix_interface_snapshots_interface_id_collected_at",
        "interface_snapshots",
        ["interface_id", sa.literal_column("collected_at DESC")],
        unique=False,
    )
    op.create_index(
        "uq_interface_snapshots_run_interface",
        "interface_snapshots",
        ["run_id", "interface_id", "collected_at"],
        unique=True,
    )
    op.create_table(
        "links",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("a_interface_id", sa.Uuid(), nullable=False),
        sa.Column("b_interface_id", sa.Uuid(), nullable=False),
        sa.Column("source", _enum("link_source"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "a_interface_id < b_interface_id", name=op.f("ck_links_endpoints_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["a_interface_id"],
            ["interfaces.id"],
            name=op.f("fk_links_a_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["b_interface_id"],
            ["interfaces.id"],
            name=op.f("fk_links_b_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_links")),
        sa.UniqueConstraint(
            "a_interface_id", "b_interface_id", name="uq_links_a_interface_id_b_interface_id"
        ),
    )
    op.create_index("ix_links_b_interface_id", "links", ["b_interface_id"], unique=False)
    op.create_table(
        "mac_entries",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("mac", postgresql.MACADDR(), nullable=False),
        sa.Column("interface_id", sa.Uuid(), nullable=True),
        sa.Column("entry_type", _enum("mac_entry_type"), nullable=False),
        sa.CheckConstraint("vlan_id BETWEEN 1 AND 4094", name=op.f("ck_mac_entries_vlan_id_valid")),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_mac_entries_interface_id_interfaces"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_mac_entries_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_mac_entries")),
    )
    op.create_index(
        "ix_mac_entries_mac_collected_at",
        "mac_entries",
        ["mac", sa.literal_column("collected_at DESC")],
        unique=False,
    )
    op.create_index(
        "uq_mac_entries_run_vlan_mac",
        "mac_entries",
        ["run_id", "vlan_id", "mac", "collected_at"],
        unique=True,
    )
    op.create_table(
        "metrics",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("interface_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_metrics_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_metrics_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_metrics_interface_id_name_time",
        "metrics",
        ["interface_id", "name", "time"],
        unique=False,
        postgresql_where=sa.text("interface_id IS NOT NULL"),
    )
    op.create_index(
        "uq_metrics_device_interface_name_time",
        "metrics",
        ["device_id", "interface_id", "name", "time"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "neighbor_observations",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("local_interface_id", sa.Uuid(), nullable=False),
        sa.Column("protocol", _enum("neighbor_protocol"), nullable=False),
        sa.Column("remote_name", sa.Text(), nullable=True),
        sa.Column("remote_mgmt_ip", postgresql.INET(), nullable=True),
        sa.Column("remote_port", sa.Text(), nullable=True),
        sa.Column("remote_platform", sa.Text(), nullable=True),
        sa.Column("remote_capabilities", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.CheckConstraint(
            "masklen(remote_mgmt_ip) = CASE family(remote_mgmt_ip) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_neighbor_observations_remote_mgmt_ip_is_host"),
        ),
        sa.ForeignKeyConstraint(
            ["local_interface_id"],
            ["interfaces.id"],
            name=op.f("fk_neighbor_observations_local_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_neighbor_observations_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_neighbor_observations")),
    )
    op.create_index(
        "ix_neighbor_observations_run_id",
        "neighbor_observations",
        ["run_id", "collected_at"],
        unique=False,
    )
    op.create_table(
        "ospf_neighbor_observations",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("neighbor_router_id", postgresql.INET(), nullable=False),
        sa.Column("neighbor_ip", postgresql.INET(), nullable=False),
        sa.Column("interface_id", sa.Uuid(), nullable=False),
        sa.Column("area", sa.BigInteger(), nullable=False),
        sa.Column("state", _enum("ospf_neighbor_state"), nullable=False),
        sa.CheckConstraint(
            "area BETWEEN 0 AND 4294967295", name=op.f("ck_ospf_neighbor_observations_area_valid")
        ),
        sa.CheckConstraint(
            "masklen(neighbor_ip) = CASE family(neighbor_ip) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_ospf_neighbor_observations_neighbor_ip_is_host"),
        ),
        sa.CheckConstraint(
            "masklen(neighbor_router_id) = CASE family(neighbor_router_id) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_ospf_neighbor_observations_neighbor_router_id_is_host"),
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_ospf_neighbor_observations_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_ospf_neighbor_observations_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_ospf_neighbor_observations")),
    )
    op.create_index(
        "uq_ospf_neighbor_observations_run_interface_neighbor",
        "ospf_neighbor_observations",
        ["run_id", "interface_id", "neighbor_router_id", "collected_at"],
        unique=True,
    )
    op.create_table(
        "route_entries",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("prefix", postgresql.CIDR(), nullable=False),
        sa.Column("protocol", _enum("route_protocol"), nullable=False),
        sa.Column("next_hop", postgresql.INET(), nullable=True),
        sa.Column("out_interface_id", sa.Uuid(), nullable=True),
        sa.Column("admin_distance", sa.Integer(), nullable=True),
        sa.Column("metric", sa.BigInteger(), nullable=True),
        sa.Column("vrf", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "admin_distance BETWEEN 0 AND 255", name=op.f("ck_route_entries_admin_distance_valid")
        ),
        sa.CheckConstraint(
            "masklen(next_hop) = CASE family(next_hop) WHEN 4 THEN 32 ELSE 128 END",
            name=op.f("ck_route_entries_next_hop_is_host"),
        ),
        sa.CheckConstraint("metric >= 0", name=op.f("ck_route_entries_metric_non_negative")),
        sa.ForeignKeyConstraint(
            ["out_interface_id"],
            ["interfaces.id"],
            name=op.f("fk_route_entries_out_interface_id_interfaces"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_route_entries_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_route_entries")),
    )
    op.create_index(
        "ix_route_entries_run_id", "route_entries", ["run_id", "collected_at"], unique=False
    )
    op.create_table(
        "stp_instance_observations",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("root_bridge_id", sa.Text(), nullable=False),
        sa.Column("root_cost", sa.Integer(), nullable=False),
        sa.Column("root_interface_id", sa.Uuid(), nullable=True),
        sa.Column("is_root", sa.Boolean(), nullable=False),
        sa.Column("topology_changes", sa.BigInteger(), nullable=True),
        sa.Column("last_topology_change_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "NOT is_root OR root_interface_id IS NULL",
            name=op.f("ck_stp_instance_observations_root_has_no_root_port"),
        ),
        sa.CheckConstraint(
            "root_cost >= 0 AND topology_changes >= 0",
            name=op.f("ck_stp_instance_observations_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "vlan_id BETWEEN 1 AND 4094", name=op.f("ck_stp_instance_observations_vlan_id_valid")
        ),
        sa.ForeignKeyConstraint(
            ["root_interface_id"],
            ["interfaces.id"],
            name=op.f("fk_stp_instance_observations_root_interface_id_interfaces"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_stp_instance_observations_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_stp_instance_observations")),
    )
    op.create_index(
        "uq_stp_instance_observations_run_vlan",
        "stp_instance_observations",
        ["run_id", "vlan_id", "collected_at"],
        unique=True,
    )
    op.create_table(
        "stp_port_observations",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("interface_id", sa.Uuid(), nullable=False),
        sa.Column("role", _enum("stp_port_role"), nullable=False),
        sa.Column("state", _enum("stp_port_state"), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.CheckConstraint("cost >= 0", name=op.f("ck_stp_port_observations_cost_non_negative")),
        sa.CheckConstraint(
            "vlan_id BETWEEN 1 AND 4094", name=op.f("ck_stp_port_observations_vlan_id_valid")
        ),
        sa.ForeignKeyConstraint(
            ["interface_id"],
            ["interfaces.id"],
            name=op.f("fk_stp_port_observations_interface_id_interfaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_stp_port_observations_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_stp_port_observations")),
    )
    op.create_index(
        "uq_stp_port_observations_run_vlan_interface",
        "stp_port_observations",
        ["run_id", "vlan_id", "interface_id", "collected_at"],
        unique=True,
    )
    op.create_table(
        "vlan_observations",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("status", _enum("vlan_status"), nullable=True),
        sa.CheckConstraint(
            "vlan_id BETWEEN 1 AND 4094", name=op.f("ck_vlan_observations_vlan_id_valid")
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "device_id", "collected_at"],
            ["collection_runs.id", "collection_runs.device_id", "collection_runs.started_at"],
            name=op.f("fk_vlan_observations_run_id_collection_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", "collected_at", name=op.f("pk_vlan_observations")),
    )
    op.create_index(
        "uq_vlan_observations_run_vlan",
        "vlan_observations",
        ["run_id", "vlan_id", "collected_at"],
        unique=True,
    )

    # Hypertables are converted while still empty. create_default_indexes => false because
    # every index the queries need is declared on the models (and so known to Alembic).
    for table, time_column, retention in HYPERTABLES:
        op.execute(
            f"SELECT create_hypertable('{table}', by_range('{time_column}',"
            f" INTERVAL '{_interval(CHUNK_INTERVAL)}'), create_default_indexes => false)"
        )
        op.execute(
            f"SELECT add_retention_policy('{table}',"
            f" drop_after => INTERVAL '{_interval(retention)}')"
        )


def downgrade() -> None:
    # Dropping a hypertable also drops its chunks and its retention job.
    for table in reversed(TABLES):
        op.drop_table(table)
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind)
