"""Credential profiles (encrypted device credentials, ADR-0004) and devices.credential_profile_id.

Revision ID: 5c3f79f02fc2
Revises: 9766e2361639
Create Date: 2026-10-09 17:59:07.577404+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5c3f79f02fc2"
down_revision: str | Sequence[str] | None = "9766e2361639"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here on purpose (see the shared data model migration).
ENUMS: dict[str, tuple[str, ...]] = {
    "credential_kind": ("ssh", "snmpv3"),
    "snmp_auth_protocol": ("sha", "sha224", "sha256", "sha384", "sha512"),
    "snmp_priv_protocol": ("aes128", "aes192", "aes256"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind)

    # *_encrypted columns hold Fernet tokens (netops.db.types.EncryptedSecret).
    op.create_table(
        "credential_profiles",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", _enum("credential_kind"), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("enable_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("auth_protocol", _enum("snmp_auth_protocol"), nullable=True),
        sa.Column("auth_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("priv_protocol", _enum("snmp_priv_protocol"), nullable=True),
        sa.Column("priv_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind <> 'snmpv3' OR (auth_protocol IS NOT NULL AND auth_key_encrypted IS NOT NULL AND priv_protocol IS NOT NULL AND priv_key_encrypted IS NOT NULL AND password_encrypted IS NULL AND enable_secret_encrypted IS NULL)",
            name=op.f("ck_credential_profiles_snmpv3_fields"),
        ),
        sa.CheckConstraint(
            "kind <> 'ssh' OR (password_encrypted IS NOT NULL AND auth_protocol IS NULL AND auth_key_encrypted IS NULL AND priv_protocol IS NULL AND priv_key_encrypted IS NULL)",
            name=op.f("ck_credential_profiles_ssh_fields"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credential_profiles")),
        sa.UniqueConstraint("name", name=op.f("uq_credential_profiles_name")),
    )
    op.add_column("devices", sa.Column("credential_profile_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_devices_credential_profile_id", "devices", ["credential_profile_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_devices_credential_profile_id_credential_profiles"),
        "devices",
        "credential_profiles",
        ["credential_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_devices_credential_profile_id_credential_profiles"), "devices", type_="foreignkey"
    )
    op.drop_index("ix_devices_credential_profile_id", table_name="devices")
    op.drop_column("devices", "credential_profile_id")
    op.drop_table("credential_profiles")
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind)
