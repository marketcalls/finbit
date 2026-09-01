"""Token bucket rate limiting over SQLite (contract 2, section 3.7).

A bucket holds up to `capacity` tokens and refills continuously at
capacity / window seconds. Continuous refill is what makes a burst behave: a
caller that has been quiet for half the window gets half the bucket back,
instead of everyone resetting together on a window boundary.

State lives in rate_buckets so it survives a restart and stays correct across
the FastAPI threadpool and the scheduler threads. Reads and writes go through
app.db.get_conn(write=True), which serialises writes behind the process lock
and commits, so the read-modify-write of one bucket cannot interleave.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from app.db import get_conn
from app.security import iso_utc_precise, parse_iso_utc, utc_now


@dataclass(frozen=True)
class Limit:
    """One named bucket shape: capacity tokens, refilled over window seconds."""

    name: str
    capacity: float
    window_seconds: float

    @property
    def refill_per_second(self) -> float:
        return self.capacity / self.window_seconds


@dataclass(frozen=True)
class Decision:
    """The outcome of one consume call."""

    allowed: bool
    scope: str
    identity: str
    remaining: float
    retry_after: int

    @property
    def retry_after_header(self) -> str:
        """Retry-After in whole seconds, never below one."""
        return str(max(1, self.retry_after))


SCOPE_DEVICE_REGISTER = "device_register"
SCOPE_DEVICE = "device"
SCOPE_IP = "ip"
SCOPE_ADMIN_LOGIN = "admin_login"
SCOPE_ADMIN_INGEST = "admin_ingest"

# The five scopes of section 3.7, verbatim.
LIMITS: dict[str, Limit] = {
    SCOPE_DEVICE_REGISTER: Limit(SCOPE_DEVICE_REGISTER, 5, 60 * 60),
    SCOPE_DEVICE: Limit(SCOPE_DEVICE, 120, 60),
    SCOPE_IP: Limit(SCOPE_IP, 600, 60),
    SCOPE_ADMIN_LOGIN: Limit(SCOPE_ADMIN_LOGIN, 10, 15 * 60),
    SCOPE_ADMIN_INGEST: Limit(SCOPE_ADMIN_INGEST, 6, 60 * 60),
}

RATE_LIMITED_CODE = "rate_limited"
RATE_LIMITED_DETAIL = "Too many requests. Slow down and try again shortly."


def limit_for(scope: str) -> Limit:
    """The Limit behind a scope name."""
    try:
        return LIMITS[scope]
    except KeyError:
        raise ValueError(f"unknown rate limit scope: {scope}") from None


def bucket_key(scope: str, identity: str) -> str:
    """The rate_buckets primary key for one caller in one scope."""
    return f"{scope}:{(identity or 'unknown').strip()}"


def consume(
    scope: str,
    identity: str,
    cost: float = 1.0,
    *,
    now: datetime | None = None,
) -> Decision:
    """Take one token from a bucket, refilling it for the elapsed time first.

    Returns a Decision rather than raising, because the HTTP status and the
    response body belong to the dependency layer, not here.
    """
    limit = limit_for(scope)
    key = bucket_key(scope, identity)
    moment = now or utc_now()

    with get_conn(write=True) as conn:
        row = conn.execute(
            "SELECT tokens, updated_at FROM rate_buckets WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            tokens = limit.capacity
        else:
            tokens = float(row["tokens"])
            last = parse_iso_utc(str(row["updated_at"]))
            if last is not None:
                # A clock that moved backwards must not refill the bucket.
                elapsed = max(0.0, (moment - last).total_seconds())
                tokens = min(limit.capacity, tokens + elapsed * limit.refill_per_second)

        allowed = tokens >= cost
        if allowed:
            tokens -= cost

        conn.execute(
            "INSERT INTO rate_buckets (key, tokens, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET tokens = excluded.tokens, "
            "updated_at = excluded.updated_at",
            (key, tokens, iso_utc_precise(moment)),
        )

    if allowed:
        retry_after = 0
    else:
        missing = max(0.0, cost - tokens)
        retry_after = int(math.ceil(missing / limit.refill_per_second))
    return Decision(
        allowed=allowed,
        scope=scope,
        identity=identity,
        remaining=max(0.0, tokens),
        retry_after=retry_after,
    )


def peek(scope: str, identity: str, *, now: datetime | None = None) -> float:
    """Tokens currently available, without spending one. For diagnostics."""
    limit = limit_for(scope)
    moment = now or utc_now()
    with get_conn() as conn:
        try:
            row = conn.execute(
                "SELECT tokens, updated_at FROM rate_buckets WHERE key = ?",
                (bucket_key(scope, identity),),
            ).fetchone()
        except sqlite3.Error:
            return limit.capacity
    if row is None:
        return limit.capacity
    tokens = float(row["tokens"])
    last = parse_iso_utc(str(row["updated_at"]))
    if last is None:
        return tokens
    elapsed = max(0.0, (moment - last).total_seconds())
    return min(limit.capacity, tokens + elapsed * limit.refill_per_second)


def reset(scope: str, identity: str) -> None:
    """Drop one bucket, so the next call starts full again."""
    with get_conn(write=True) as conn:
        conn.execute("DELETE FROM rate_buckets WHERE key = ?", (bucket_key(scope, identity),))


def reset_all() -> None:
    """Drop every bucket. Intended for tests, never for a route."""
    with get_conn(write=True) as conn:
        conn.execute("DELETE FROM rate_buckets")


__all__ = [
    "Decision",
    "LIMITS",
    "Limit",
    "RATE_LIMITED_CODE",
    "RATE_LIMITED_DETAIL",
    "SCOPE_ADMIN_INGEST",
    "SCOPE_ADMIN_LOGIN",
    "SCOPE_DEVICE",
    "SCOPE_DEVICE_REGISTER",
    "SCOPE_IP",
    "bucket_key",
    "consume",
    "limit_for",
    "peek",
    "reset",
    "reset_all",
]
