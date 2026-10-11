"""Authentication building blocks without a database: password policy and hashing, tokens,
TOTP and recovery codes, audit details, rate limiting."""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
import pytest
from pydantic import SecretStr

from netops.auth import audit, passwords, tokens, totp
from netops.auth.ratelimit import MemoryRateLimiter
from netops.core.settings import Settings, get_settings
from netops.db.enums import AuditOutcome

USER = uuid.uuid4()
SESSION = uuid.uuid4()
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)

# --- password policy --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("short", "too_short"),
        ("elevenchars", "too_short"),
        ("x" * 257, "too_long"),
        ("password1234", "common"),
        ("Password2026!", "common"),
        ("P@ssw0rd2026!", "common"),
        ("qwertyuiopasdfghjkl", "common"),
        ("Galatasaray1905!", "common"),
        ("NetOps-2026-NetOps", "common"),
        ("aaaaaaaaaaaaaaa", "repetitive"),
        ("abababababababab", "repetitive"),
        ("abcdefghijklmnop", "sequence"),
        ("987654321098", "sequence"),
        ("1qaz2wsx3edc4rfv", "sequence"),
        ("mehmet.yilmaz-2026-x", "contains_name"),
    ],
)
def test_rejected_passwords(password: str, code: str) -> None:
    violations = passwords.check_policy(
        password,
        username="mehmet.yilmaz",
        names=("Mehmet Y\u0131lmaz", None),  # Turkish dotless i
    )
    assert code in {v.code for v in violations}, violations


@pytest.mark.parametrize(
    "password",
    [
        "correct horse battery staple",
        "kahve-limon-bisiklet-73",
        "Tr0ub4dor&3-but-longer",
        "zwölf Zeichen mindestens",  # any characters, no composition rules
        "çok uzun bir parola cümlesi",
    ],
)
def test_accepted_passwords(password: str) -> None:
    assert passwords.check_policy(password, username="operator1") == []


def test_the_common_password_list_is_bundled_and_lower_case() -> None:
    common = passwords.common_passwords()
    assert len(common) > 200
    assert {"123456", "password", "qwerty", "sifre", "netops"} <= common
    assert all(entry == entry.lower() for entry in common)


def test_argon2id_hash_and_verify() -> None:
    hashed = passwords.hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert passwords.verify_password(hashed, "correct horse battery staple")
    assert not passwords.verify_password(hashed, "correct horse battery stapl")
    assert not passwords.verify_password("not-a-hash", "x")
    assert not passwords.needs_rehash(hashed)
    # Same salt never: two hashes of one password differ.
    assert passwords.hash_password("correct horse battery staple") != hashed


def test_unknown_users_cost_one_hash_too() -> None:
    hashed = passwords.hash_password("correct horse battery staple")
    started = time.perf_counter()
    assert not passwords.verify_password(hashed, "wrong guess for a user")
    known = time.perf_counter() - started
    passwords.verify_password(None, "warm the dummy hash up")
    started = time.perf_counter()
    assert not passwords.verify_password(None, "wrong guess for a user")
    unknown = time.perf_counter() - started
    assert unknown > known / 3  # the same order of magnitude: an argon2 run in both cases


def test_weaker_hashes_are_upgraded() -> None:
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash("x" * 12)
    assert passwords.needs_rehash(weak)
    assert passwords.verify_password(weak, "x" * 12)


# --- tokens -----------------------------------------------------------------------------------


def settings_with(key: str) -> Settings:
    return get_settings().model_copy(update={"auth_signing_key": SecretStr(key)})


def test_access_token_round_trip() -> None:
    settings = get_settings()
    token, lifetime = tokens.issue_access_token(USER, SESSION, settings, datetime.now(UTC))
    assert lifetime == 15 * 60
    claims = tokens.decode(token, tokens.ACCESS, settings)
    assert (claims.user_id, claims.session_id) == (USER, SESSION)
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "HS256"
    payload = jwt.decode(token, options={"verify_signature": False})
    assert {"iss", "aud", "sub", "iat", "exp", "jti", "typ", "sid"} == set(payload)
    assert "role" not in payload  # the role is read from the database on every request


def test_tokens_with_a_wrong_key_expired_or_tampered_are_rejected() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token, _ = tokens.issue_access_token(USER, SESSION, settings, now)

    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode(token, tokens.ACCESS, settings_with("another-key-" + "x" * 32))
    expired, _ = tokens.issue_access_token(USER, SESSION, settings, now - timedelta(hours=1))
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode(expired, tokens.ACCESS, settings)
    header, payload, signature = token.split(".")
    forged_payload = jwt.utils.base64url_encode(
        jwt.utils.base64url_decode(payload).replace(str(USER).encode(), str(uuid.uuid4()).encode())
    ).decode()
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode(f"{header}.{forged_payload}.{signature}", tokens.ACCESS, settings)
    unsigned = jwt.encode(
        jwt.decode(token, options={"verify_signature": False}), key=None, algorithm="none"
    )
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode(unsigned, tokens.ACCESS, settings)
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode("not.a.jwt", tokens.ACCESS, settings)


def test_a_challenge_is_not_an_access_token_and_vice_versa() -> None:
    settings = get_settings()
    challenge = tokens.issue_mfa_challenge(USER, settings, datetime.now(UTC))
    with pytest.raises(tokens.InvalidTokenError, match="type"):
        tokens.decode(challenge, tokens.ACCESS, settings)
    access, _ = tokens.issue_access_token(USER, SESSION, settings, datetime.now(UTC))
    with pytest.raises(tokens.InvalidTokenError, match="type"):
        tokens.decode(access, tokens.MFA_CHALLENGE, settings)
    assert tokens.decode(challenge, tokens.MFA_CHALLENGE, settings).user_id == USER


def test_signing_keys_rotate() -> None:
    old, new = "old-key-" + "a" * 32, "new-key-" + "b" * 32
    token, _ = tokens.issue_access_token(USER, SESSION, settings_with(old), datetime.now(UTC))
    # The new key signs; the old one still verifies its tokens until they expire.
    assert tokens.decode(token, tokens.ACCESS, settings_with(f"{new},{old}")).user_id == USER
    with pytest.raises(tokens.InvalidTokenError):
        tokens.decode(token, tokens.ACCESS, settings_with(new))


def test_signing_keys_must_be_long() -> None:
    with pytest.raises(ValueError, match="AUTH_SIGNING_KEY"):
        Settings(
            postgres_password=SecretStr("x"),
            credentials_key=get_settings().credentials_key,
            auth_signing_key=SecretStr("short"),
        )


def test_refresh_tokens_are_random_and_stored_hashed() -> None:
    first, first_hash = tokens.new_refresh_token()
    second, _ = tokens.new_refresh_token()
    assert first != second
    assert len(first) >= 43
    assert first_hash == tokens.hash_refresh_token(first)
    assert first not in first_hash


# --- TOTP and recovery codes -----------------------------------------------------------------


def test_totp_accepts_the_current_and_adjacent_steps_once() -> None:
    secret = totp.new_secret()
    generator = pyotp.TOTP(secret)
    step = int(NOW.timestamp()) // 30
    code = generator.at(NOW)
    assert totp.verify(secret, code, NOW, None) == step
    assert totp.verify(secret, code, NOW, step) is None  # replay
    previous = generator.at(NOW - timedelta(seconds=30))
    assert totp.verify(secret, previous, NOW, None) == step - 1
    assert totp.verify(secret, generator.at(NOW + timedelta(seconds=30)), NOW, None) == step + 1
    assert totp.verify(secret, generator.at(NOW - timedelta(seconds=90)), NOW, None) is None
    assert totp.verify(secret, "12345", NOW, None) is None
    assert totp.verify(secret, "abcdef", NOW, None) is None
    assert totp.verify(secret, f"{code[:3]} {code[3:]}", NOW, None) == step  # spaces are fine


def test_enrollment_material() -> None:
    secret = totp.new_secret()
    assert len(secret) == 32
    uri = totp.provisioning_uri(secret, "operator1", "NetOps")
    assert uri.startswith("otpauth://totp/NetOps:operator1?secret=")
    assert "issuer=NetOps" in uri
    qr = totp.qr_svg_data_uri(uri)
    assert qr.startswith("data:image/svg+xml")


def test_recovery_codes() -> None:
    codes = totp.new_recovery_codes()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(len(code) == 11 and code[5] == "-" for code in codes)
    # Typed with other case and without the dash: the same code.
    assert totp.hash_recovery_code(codes[0]) == totp.hash_recovery_code(
        codes[0].upper().replace("-", " ")
    )


# --- audit details and rate limits ------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["password", "new_password", "mfa_secret", "token", "code", "api_key"]
)
def test_audit_details_refuse_secrets(key: str) -> None:
    with pytest.raises(audit.AuditDetailsError):
        audit.entry("auth.login", AuditOutcome.FAILED, details={key: "x"})
    with pytest.raises(audit.AuditDetailsError):
        audit.entry("auth.login", AuditOutcome.FAILED, details={"nested": [{key: "x"}]})


def test_audit_details_allow_names_and_counts() -> None:
    entry = audit.entry(
        "credentials.update",
        AuditOutcome.SUCCESS,
        actor_ip="10.0.0.250",
        target_id=USER,
        details={
            "profile_name": "campus-ro",
            "fields": ["password"],
            "recovery_codes_left": 9,
            "temporary_password_set": True,
        },
    )
    assert entry.actor_ip == "10.0.0.250"
    assert entry.target_id == str(USER)
    assert audit.entry("x.y", AuditOutcome.SUCCESS, actor_ip="not-an-ip").actor_ip is None


def test_memory_rate_limiter() -> None:
    limiter = MemoryRateLimiter()

    async def hits() -> list[int | None]:
        return [await limiter.hit("login:10.0.0.1", 3, 60) for _ in range(5)]

    results = asyncio.run(hits())
    assert results[:3] == [None, None, None]
    assert all(r is not None and 0 < r <= 60 for r in results[3:])
    assert asyncio.run(limiter.hit("login:10.0.0.2", 3, 60)) is None  # per address
