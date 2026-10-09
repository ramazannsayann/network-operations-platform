"""Device credential profiles (the minimal part of M7 needed to reach devices).

Secrets are stored Fernet-encrypted (ADR-0004) and loaded as ``Secret`` objects, so they
never show up in repr(), logs or API responses.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from netops.core.secrets import Secret
from netops.db.base import Base
from netops.db.enums import CredentialKind, SnmpAuthProtocol, SnmpPrivProtocol
from netops.db.models._common import EntityMixin
from netops.db.types import EncryptedSecret


class CredentialProfile(EntityMixin, Base):
    """A named set of credentials, SSH (CLI) or SNMPv3, shared by many devices."""

    __tablename__ = "credential_profiles"
    __table_args__ = (
        CheckConstraint(
            "kind <> 'ssh' OR (password_encrypted IS NOT NULL AND auth_protocol IS NULL"
            " AND auth_key_encrypted IS NULL AND priv_protocol IS NULL"
            " AND priv_key_encrypted IS NULL)",
            name="ssh_fields",
        ),
        # Only authPriv is supported for SNMPv3 (proposal 4.1, NFR-05).
        CheckConstraint(
            "kind <> 'snmpv3' OR (auth_protocol IS NOT NULL AND auth_key_encrypted IS NOT NULL"
            " AND priv_protocol IS NOT NULL AND priv_key_encrypted IS NOT NULL"
            " AND password_encrypted IS NULL AND enable_secret_encrypted IS NULL)",
            name="snmpv3_fields",
        ),
    )

    name: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[CredentialKind]
    username: Mapped[str]
    # SSH
    password: Mapped[Secret | None] = mapped_column("password_encrypted", EncryptedSecret)
    enable_secret: Mapped[Secret | None] = mapped_column("enable_secret_encrypted", EncryptedSecret)
    # SNMPv3 (authPriv)
    auth_protocol: Mapped[SnmpAuthProtocol | None]
    auth_key: Mapped[Secret | None] = mapped_column("auth_key_encrypted", EncryptedSecret)
    priv_protocol: Mapped[SnmpPrivProtocol | None]
    priv_key: Mapped[Secret | None] = mapped_column("priv_key_encrypted", EncryptedSecret)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
