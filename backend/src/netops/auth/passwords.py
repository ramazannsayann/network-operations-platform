"""Password hashing (argon2id) and the password policy.

Policy (NIST SP 800-63B style, no composition rules): at least 12 characters (at most 256,
so hashing stays cheap), not one of the common passwords in ``common_passwords.txt``, not
a common password dressed up with digits, symbols or look-alike characters
("P@ssw0rd2026!"), not a run of one or two characters or a keyboard/alphabet sequence, and
not containing the user's name.

Verification always runs one argon2 computation, also for unknown users (against a dummy
hash), so response times do not tell whether a username exists.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 256

# argon2-cffi's defaults: RFC 9106 "low memory" (argon2id, t=3, m=64 MiB, p=4).
_hasher = PasswordHasher()

_LEET = str.maketrans({"@": "a", "4": "a", "0": "o", "1": "i", "!": "i", "3": "e", "$": "s",
                       "5": "s", "7": "t", "+": "t", "9": "g", "8": "b"})  # fmt: skip
_SEQUENCES = (
    "abcdefghijklmnopqrstuvwxyz",
    "0123456789",
    "qwertyuiopasdfghjklzxcvbnm",
    "1qaz2wsx3edc4rfv5tgb6yhn7ujm8ik9ol0p",
    "zaq1xsw2cde3vfr4bgt5nhy6mju7",
    "qazwsxedcrfvtgbyhnujmikolp",
)


@dataclass(frozen=True)
class PolicyViolation:
    code: str  # too_short, too_long, common, repetitive, sequence, contains_name
    message: str


@cache
def common_passwords() -> frozenset[str]:
    lines = (Path(__file__).parent / "common_passwords.txt").read_text().splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip() and line[0] != "#")


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text)


def _is_sequence(text: str) -> bool:
    for sequence in _SEQUENCES:
        cycle = sequence * 3
        if text in cycle or text in cycle[::-1]:
            return True
    return False


def check_policy(
    password: str, *, username: str | None = None, names: tuple[str | None, ...] = ()
) -> list[PolicyViolation]:
    """Everything wrong with ``password``; empty when it may be used."""
    if len(password) < MIN_LENGTH:
        return [PolicyViolation("too_short", f"At least {MIN_LENGTH} characters are needed.")]
    if len(password) > MAX_LENGTH:
        return [PolicyViolation("too_long", f"At most {MAX_LENGTH} characters are allowed.")]
    violations = []
    lower = password.lower()
    common = common_passwords()
    stripped = lower.strip("0123456789!@#$%^&*()_+-=.,;:?'\"[]{}<>/\\|~` ")
    repeated = {
        letters[: len(letters) // k]
        for letters in (_letters(lower), _letters(lower.translate(_LEET)))
        for k in (2, 3, 4)
        if letters and len(letters) % k == 0 and letters[: len(letters) // k] * k == letters
    }
    if (
        bool(repeated & common)
        or lower in common
        or stripped in common
        or lower.translate(_LEET) in common
        or stripped.translate(_LEET) in common
        or (_letters(lower) in common and len(_letters(lower)) >= 4)
        or (_letters(lower.translate(_LEET)) in common and len(_letters(lower)) >= 4)
    ):
        violations.append(PolicyViolation("common", "This password is too common."))
    if len(set(lower)) <= 2:
        violations.append(PolicyViolation("repetitive", "This password repeats itself."))
    elif _is_sequence(lower):
        violations.append(PolicyViolation("sequence", "This password is a simple sequence."))
    words = [username, *names]
    for word in words:
        for part in re.split(r"[\s@._-]+", (word or "").lower()):
            if len(part) >= 3 and part in lower:
                violations.append(
                    PolicyViolation("contains_name", "The password must not contain your name.")
                )
                return violations
    return violations


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@cache
def _dummy_hash() -> str:
    return _hasher.hash("not-a-password-of-anyone-0f2c9a")


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant work: an unknown user (``None``) is checked against a dummy hash."""
    try:
        return _hasher.verify(password_hash or _dummy_hash(), password) and bool(password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)
