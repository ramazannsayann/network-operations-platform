"""Custom column types."""

from typing import Any

from sqlalchemy import Dialect, LargeBinary
from sqlalchemy.types import TypeDecorator

from netops.core.crypto import decrypt_secret, encrypt_secret
from netops.core.secrets import Secret


class EncryptedSecret(TypeDecorator[Secret]):
    """A ``Secret`` stored Fernet-encrypted (bytea); decrypted only when loaded."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> bytes | None:
        if value is None:
            return None
        if not isinstance(value, Secret):
            raise TypeError("encrypted columns take netops.core.secrets.Secret values")
        return encrypt_secret(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Secret | None:
        return None if value is None else decrypt_secret(bytes(value))
