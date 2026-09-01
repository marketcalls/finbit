"""The one-time admin bootstrap token (CONTRACT_ADMIN_REGISTRATION.md section 2).

This token is the only thing standing between a reachable port and someone else
claiming the instance, so it is deliberately the least persistent secret in the
codebase. It is minted at startup and only while admin_users is empty, it lives
on app.state and nowhere else, and it is dropped the instant an account exists.

Nothing in this module touches the database, the filesystem or a logger. Keeping
it pure is what makes the expiry, the normalization and the comparison testable
on their own, and it means there is no code path here that could write the token
somewhere it would outlive the process. main.py prints it once; no response body
ever carries it.

The comparison runs on the normalized string, dashes and whitespace removed,
through hmac.compare_digest. The dashes exist so a person can read the token off
a console and type it back, so they carry no meaning: a caller that keeps them,
drops them, or pastes the value with a trailing newline is the same input.

Normalizing before grouping also settles a detail of the generator. The base64url
alphabet secrets.token_urlsafe draws from includes the dash itself, so a raw
token can contain one; stripping those first means the printed form round trips
to exactly the value that is compared, rather than to a slightly different one.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.security import utc_now

# Section 2, verbatim: secrets.token_urlsafe(18), valid for thirty minutes,
# grouped into four dash separated chunks purely so it can be read aloud.
TOKEN_ENTROPY_BYTES = 18
TOKEN_TTL_SECONDS = 30 * 60
TOKEN_GROUPS = 4

# The attribute the token is held under on app.state. Named once here so the
# router, main.py and the tests cannot drift apart on it.
STATE_ATTRIBUTE = "bootstrap_token"

BANNER_RULE = "=" * 60

# Compared against when no token is live, so the absent case costs the same
# comparison as a wrong one and cannot be told apart by how fast it answers.
# Nothing can present it: it is generated here and never leaves this module.
_ABSENT_REFERENCE = secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def normalize(value: str | None) -> str:
    """The comparison form of a token: no dashes and no whitespace."""
    return "".join(
        character
        for character in (value or "")
        if character != "-" and not character.isspace()
    )


def group(value: str, groups: int = TOKEN_GROUPS) -> str:
    """Break a token into dash separated chunks, for reading it off a console."""
    if groups < 2 or len(value) < groups:
        return value
    size = -(-len(value) // groups)
    return "-".join(value[start : start + size] for start in range(0, len(value), size))


def new_value() -> str:
    """One fresh token, already in its comparison form."""
    return normalize(secrets.token_urlsafe(TOKEN_ENTROPY_BYTES))


def _constant_time_equal(left: str, right: str) -> bool:
    """compare_digest over the utf-8 bytes, so any input is safe to pass.

    The str form of compare_digest rejects non-ascii, and the presented value
    comes straight off the wire, so it is encoded first rather than trusted.
    """
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass(frozen=True)
class BootstrapToken:
    """One live token: the secret, when it was minted and when it lapses."""

    value: str
    issued_at: datetime
    expires_at: datetime

    @property
    def display(self) -> str:
        """The grouped form that goes in the startup banner."""
        return group(self.value)

    @property
    def ttl_seconds(self) -> int:
        """How long this token was minted for, in whole seconds."""
        return int((self.expires_at - self.issued_at).total_seconds())

    def is_expired(self, now: datetime | None = None) -> bool:
        """True once the validity window has closed."""
        return (now or utc_now()) >= self.expires_at


def issue(
    now: datetime | None = None, ttl_seconds: int = TOKEN_TTL_SECONDS
) -> BootstrapToken:
    """Mint a token valid from this moment for ttl_seconds."""
    issued_at = now or utc_now()
    return BootstrapToken(
        value=new_value(),
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=int(ttl_seconds)),
    )


def verify(
    token: BootstrapToken | None,
    presented: str | None,
    now: datetime | None = None,
) -> bool:
    """True only when the caller presented the live token and it still holds.

    A wrong token, an expired token and no token at all take the same path and
    all come back False, so the answer cannot say which of the three it was.
    The comparison always runs, expired or not, so the expiry is not readable
    from the time the call takes either.
    """
    reference = token.value if token is not None else _ABSENT_REFERENCE
    matched = _constant_time_equal(reference, normalize(presented))
    live = token is not None and not token.is_expired(now)
    return matched and live


def banner(token: BootstrapToken) -> str:
    """The startup block of section 2, ready to hand to a logger."""
    minutes = max(1, token.ttl_seconds // 60)
    return "\n".join(
        [
            BANNER_RULE,
            "  FinBit: no admin account exists.",
            "  Open the web app at /#/admin and create it.",
            f"  Bootstrap token: {token.display}",
            f"  Valid for {minutes} minutes. Printed once per start.",
            BANNER_RULE,
        ]
    )


def store(state: object, token: BootstrapToken | None) -> None:
    """Hold a token on app.state, replacing whatever was there."""
    setattr(state, STATE_ATTRIBUTE, token)


def current(state: object) -> BootstrapToken | None:
    """The token held on app.state, or None when there is not one."""
    return getattr(state, STATE_ATTRIBUTE, None)


def clear(state: object) -> None:
    """Drop the token. Called the moment an admin account exists."""
    store(state, None)


__all__ = [
    "BANNER_RULE",
    "BootstrapToken",
    "STATE_ATTRIBUTE",
    "TOKEN_ENTROPY_BYTES",
    "TOKEN_GROUPS",
    "TOKEN_TTL_SECONDS",
    "banner",
    "clear",
    "current",
    "group",
    "issue",
    "new_value",
    "normalize",
    "store",
    "verify",
]
