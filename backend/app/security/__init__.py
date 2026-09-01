"""Security core for the FinBit API (CONTRACT_MOBILE_ADMIN.md section 3).

The package holds the layers that stand between a request and a router:
app keys, the device secret derivation, the canonical string and its HMAC,
tokens, password hashing, rate limiting and the transport level middleware.

This module deliberately imports none of its own submodules. Keeping the
package init empty of them means importing app.security.signing never drags in
argon2 or PyJWT, and it leaves the import graph acyclic so the submodules can
share the clock helpers below without a circular import.

Every timestamp written by this package is ISO 8601 UTC with a trailing Z, the
same shape phase 1 uses, so a human reading the tables sees one format.
"""

from __future__ import annotations

from datetime import datetime, timezone

ISO_SECONDS = "%Y-%m-%dT%H:%M:%SZ"
ISO_MICROSECONDS = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now() -> datetime:
    """The current instant, always timezone aware and always UTC."""
    return datetime.now(timezone.utc)


def iso_utc(moment: datetime | None = None) -> str:
    """Second resolution ISO 8601 UTC, matching every phase 1 timestamp."""
    return (moment or utc_now()).astimezone(timezone.utc).strftime(ISO_SECONDS)


def iso_utc_precise(moment: datetime | None = None) -> str:
    """Microsecond resolution ISO 8601 UTC.

    Used only where sub-second accuracy changes behavior: the token bucket
    refills continuously, so rounding its clock to whole seconds would hand out
    free tokens on every burst.
    """
    return (moment or utc_now()).astimezone(timezone.utc).strftime(ISO_MICROSECONDS)


def parse_iso_utc(value: str | None) -> datetime | None:
    """Parse either resolution back to an aware UTC datetime, or None.

    Never raises: an unreadable timestamp in the database is treated as absent
    so one bad row cannot take a request down.
    """
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith(("z", "Z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def unix_seconds(moment: datetime | None = None) -> int:
    """Unix seconds as an int, the unit the signature timestamp uses."""
    return int((moment or utc_now()).timestamp())


__all__ = [
    "ISO_MICROSECONDS",
    "ISO_SECONDS",
    "iso_utc",
    "iso_utc_precise",
    "parse_iso_utc",
    "unix_seconds",
    "utc_now",
]
