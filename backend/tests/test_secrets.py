"""Secrets never leak through repr(), str(), logging, exceptions, pickling or settings errors."""

import io
import json
import logging
import pickle
import secrets

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from netops.core import crypto
from netops.core.logging import JsonFormatter
from netops.core.secrets import MASK, Secret, redact
from netops.core.settings import Settings
from netops.db.enums import CredentialKind
from netops.db.models import CredentialProfile

# Random per run, so no password-like literal sits in the repository.
PASSWORD = "pw-" + secrets.token_urlsafe(12)


def test_secret_never_shows_its_value() -> None:
    secret = Secret(PASSWORD)
    rendered = [repr(secret), str(secret), f"{secret}", f"{secret!r}", "%s" % secret, f"{secret}"]  # noqa: UP031
    assert all(PASSWORD not in text for text in rendered)
    assert repr(secret) == f"Secret('{MASK}')"
    assert secret.get_secret_value() == PASSWORD


def test_secret_inside_containers_and_exceptions_is_masked() -> None:
    secret = Secret(PASSWORD)
    assert PASSWORD not in repr({"password": secret})
    assert PASSWORD not in str(ValueError("login failed", secret))


def test_logging_does_not_leak_secrets() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("netops.tests.secrets")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        secret = Secret(PASSWORD)
        logger.warning("connecting with %s", secret, extra={"credentials": {"password": secret}})
        logger.error("failed", exc_info=ValueError(secret))
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert PASSWORD not in output
    assert json.loads(output.splitlines()[0])["credentials"] == {"password": MASK}


def test_secrets_cannot_be_pickled() -> None:
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(Secret(PASSWORD))


def test_redact_replaces_every_occurrence() -> None:
    text = f"auth failed for admin/{PASSWORD} (retry with {PASSWORD})"
    assert (
        redact(text, [Secret(PASSWORD), None, ""])
        == f"auth failed for admin/{MASK} (retry with {MASK})"
    )


def test_credential_profile_repr_does_not_leak() -> None:
    profile = CredentialProfile(
        name="lab-ro", kind=CredentialKind.SSH, username="netops-ro", password=Secret(PASSWORD)
    )
    assert PASSWORD not in repr(profile)
    assert PASSWORD not in repr(vars(profile))


def test_encryption_round_trip_and_key_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()

    def use_keys(value: str) -> None:
        monkeypatch.setattr(
            crypto, "get_cipher", lambda: crypto.MultiFernet(crypto.parse_keys(value))
        )

    use_keys(old_key)
    token = crypto.encrypt_secret(Secret(PASSWORD))
    assert PASSWORD.encode() not in token

    use_keys(f"{new_key},{old_key}")  # rotation: new key first, old key still decrypts
    assert crypto.decrypt_secret(token).get_secret_value() == PASSWORD

    use_keys(new_key)  # old key removed: the token can no longer be read
    with pytest.raises(crypto.CredentialDecryptionError) as excinfo:
        crypto.decrypt_secret(token)
    assert PASSWORD not in str(excinfo.value)


def test_settings_refuse_a_missing_or_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CREDENTIALS_KEY")
    with pytest.raises(ValidationError, match="credentials_key"):
        Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setenv("CREDENTIALS_KEY", "change-me")
    with pytest.raises(ValidationError, match="Fernet") as excinfo:
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert "change-me" not in str(excinfo.value)
