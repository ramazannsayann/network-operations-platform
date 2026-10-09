"""Keeping secrets (passwords, keys) out of logs, exceptions, repr() and serialised data.

Wrap every secret in ``Secret`` as soon as it is read and unwrap it with
``get_secret_value()`` only at the point of use (e.g. when opening an SSH session).
"""

import hmac
from collections.abc import Iterable
from typing import NoReturn, Self

MASK = "**********"


class Secret:
    """A string that prints as ``**********`` and refuses to be pickled."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("Secret wraps a str")
        self._value = value

    def get_secret_value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Secret('{MASK}')"

    def __str__(self) -> str:
        return MASK

    def __format__(self, format_spec: str) -> str:
        return MASK

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        return hmac.compare_digest(self._value.encode(), other._value.encode())

    __hash__ = None  # type: ignore[assignment]  # unhashable: no dict keys or sets of secrets

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: object) -> Self:
        return self

    def __reduce__(self) -> NoReturn:
        # Keeps secrets out of pickled task arguments, caches and the like.
        raise TypeError("Secret values cannot be pickled")


def redact(text: str, secrets: Iterable[Secret | str | None]) -> str:
    """Replace every occurrence of the given secrets in ``text`` with the mask."""
    for secret in secrets:
        value = secret.get_secret_value() if isinstance(secret, Secret) else secret
        if value:
            text = text.replace(value, MASK)
    return text
