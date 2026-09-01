"""Access and refresh tokens (contract 2, section 3.6).

Two different things, on purpose.

An access token is a short lived HS256 JWT with an audience, so a device token
can never be replayed against an admin route. It is stateless: nothing about it
is stored, and it is meant to be held in memory and refetched.

A refresh token is opaque: 32 random bytes, handed out once and stored here
only as its sha256, so a leaked database cannot be turned back into a session.
Every use rotates it. A second use of an already used token is treated as a
theft signal: the whole family for that subject and kind is revoked and the
caller is sent back to registration or to the login screen.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import timedelta

import jwt

from app.config import get_settings, is_placeholder
from app.db import get_conn
from app.security import iso_utc, parse_iso_utc, utc_now

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"

AUDIENCE_DEVICE = "device"
AUDIENCE_ADMIN = "admin"
AUDIENCES: tuple[str, ...] = (AUDIENCE_DEVICE, AUDIENCE_ADMIN)

KIND_DEVICE_REFRESH = "device-refresh"
KIND_ADMIN_REFRESH = "admin-refresh"
REFRESH_KINDS: tuple[str, ...] = (KIND_DEVICE_REFRESH, KIND_ADMIN_REFRESH)

# Lifetimes from the table in section 3.6.
DEVICE_ACCESS_TTL_SECONDS = 15 * 60
ADMIN_ACCESS_TTL_SECONDS = 30 * 60
DEVICE_REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60
ADMIN_REFRESH_TTL_SECONDS = 12 * 60 * 60

ACCESS_TTL_BY_AUDIENCE: dict[str, int] = {
    AUDIENCE_DEVICE: DEVICE_ACCESS_TTL_SECONDS,
    AUDIENCE_ADMIN: ADMIN_ACCESS_TTL_SECONDS,
}

REFRESH_TTL_BY_KIND: dict[str, int] = {
    KIND_DEVICE_REFRESH: DEVICE_REFRESH_TTL_SECONDS,
    KIND_ADMIN_REFRESH: ADMIN_REFRESH_TTL_SECONDS,
}

REFRESH_KIND_BY_AUDIENCE: dict[str, str] = {
    AUDIENCE_DEVICE: KIND_DEVICE_REFRESH,
    AUDIENCE_ADMIN: KIND_ADMIN_REFRESH,
}

# 32 bytes of entropy, url safe so it survives every transport the clients use.
REFRESH_TOKEN_BYTES = 32

# One shared code for every refresh failure. The client's move is the same in
# all of them, and a distinct code per cause would tell an attacker whether a
# guessed token ever existed.
INVALID_REFRESH_CODE = "invalid_refresh_token"

_process_secret: str | None = None


class TokenError(Exception):
    """Base class for every token failure, carrying an API code string."""

    code = "invalid_token"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class InvalidAccessToken(TokenError):
    """The bearer token is missing, malformed, expired or for another audience."""

    code = "invalid_token"


class InvalidRefreshToken(TokenError):
    """The refresh token is unknown, revoked or past its expiry."""

    code = INVALID_REFRESH_CODE


class RefreshTokenReuse(InvalidRefreshToken):
    """An already used refresh token came back.

    Same code and same response as any other invalid refresh, because the
    client cannot do anything different. The distinct type exists so the caller
    can write an audit row for what is very likely a stolen token.
    """


@dataclass(frozen=True)
class IssuedRefreshToken:
    """A freshly minted refresh token, raw for the client and hashed for us."""

    token: str
    token_hash: str
    subject: str
    kind: str
    expires_at: str


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


def _signing_secret() -> str:
    """JWT_SECRET, or a per-process random secret when it is not configured.

    Falling back keeps an unsigned development run working, and because the
    fallback dies with the process every token is invalidated on restart, so
    nobody can mistake it for a usable deployment. The value is never logged.
    """
    global _process_secret
    configured = get_settings().jwt_secret.strip()
    if not is_placeholder(configured):
        return configured
    if _process_secret is None:
        _process_secret = secrets.token_urlsafe(48)
        logger.warning(
            "JWT_SECRET is not configured. Using a random secret that lasts "
            "only for this process, so every token expires on restart."
        )
    return _process_secret


def access_ttl_seconds(audience: str) -> int:
    """Lifetime in seconds for an audience, defaulting to the device value."""
    return ACCESS_TTL_BY_AUDIENCE.get(audience, DEVICE_ACCESS_TTL_SECONDS)


def issue_access_token(
    subject: str, audience: str, ttl_seconds: int | None = None
) -> tuple[str, int]:
    """Sign an access token for a subject. Returns the token and its lifetime.

    subject is the device id for the device audience and the username for the
    admin audience, matching what the refresh token family is keyed on.
    """
    if audience not in AUDIENCES:
        raise ValueError(f"unknown token audience: {audience}")
    identifier = (subject or "").strip()
    if not identifier:
        raise ValueError("a token subject is required")
    ttl = int(ttl_seconds if ttl_seconds is not None else access_ttl_seconds(audience))
    issued = utc_now()
    payload = {
        "sub": identifier,
        "aud": audience,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=ttl)).timestamp()),
        "jti": secrets.token_urlsafe(12),
        "typ": "access",
    }
    token = jwt.encode(payload, _signing_secret(), algorithm=ALGORITHM)
    return token, ttl


def decode_access_token(token: str | None, audience: str) -> dict[str, object]:
    """Verify a bearer token for one audience and return its claims.

    Raises InvalidAccessToken for every failure, with no detail about which
    one, so the caller cannot use the API as an oracle.
    """
    presented = (token or "").strip()
    if not presented:
        raise InvalidAccessToken("no access token was presented")
    try:
        claims = jwt.decode(
            presented,
            _signing_secret(),
            algorithms=[ALGORITHM],
            audience=audience,
            options={"require": ["exp", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        # The message names the failure class only, never the token.
        raise InvalidAccessToken(f"the access token was rejected: {type(exc).__name__}")
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise InvalidAccessToken("the access token carries no subject")
    return claims


def subject_of(token: str | None, audience: str) -> str:
    """The verified subject of an access token."""
    return str(decode_access_token(token, audience)["sub"])


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------


def hash_refresh_token(token: str) -> str:
    """sha256 hex of a refresh token. Only this ever reaches the database."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def refresh_ttl_seconds(kind: str) -> int:
    """Lifetime in seconds for a refresh kind."""
    return REFRESH_TTL_BY_KIND.get(kind, DEVICE_REFRESH_TTL_SECONDS)


def _insert_refresh_token(
    conn: sqlite3.Connection, subject: str, kind: str
) -> IssuedRefreshToken:
    """Write one new refresh row. The caller owns the transaction."""
    token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    token_hash = hash_refresh_token(token)
    now = utc_now()
    expires_at = iso_utc(now + timedelta(seconds=refresh_ttl_seconds(kind)))
    conn.execute(
        "INSERT INTO refresh_tokens (token_hash, subject, kind, created_at, "
        "expires_at, used_at, revoked) VALUES (?, ?, ?, ?, ?, NULL, 0)",
        (token_hash, subject, kind, iso_utc(now), expires_at),
    )
    return IssuedRefreshToken(
        token=token,
        token_hash=token_hash,
        subject=subject,
        kind=kind,
        expires_at=expires_at,
    )


def issue_refresh_token(subject: str, kind: str) -> IssuedRefreshToken:
    """Mint and store a refresh token for a subject."""
    if kind not in REFRESH_KINDS:
        raise ValueError(f"unknown refresh token kind: {kind}")
    identifier = (subject or "").strip()
    if not identifier:
        raise ValueError("a refresh token subject is required")
    with get_conn(write=True) as conn:
        return _insert_refresh_token(conn, identifier, kind)


def revoke_subject_tokens(subject: str, kind: str) -> int:
    """Revoke every refresh token of one subject and kind. Returns the count."""
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE subject = ? AND kind = ? "
            "AND revoked = 0",
            ((subject or "").strip(), kind),
        )
        return int(cursor.rowcount or 0)


def revoke_refresh_token(token: str, kind: str) -> bool:
    """Revoke one refresh token, used by logout. Idempotent."""
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ? AND kind = ?",
            (hash_refresh_token(token), kind),
        )
        return bool(cursor.rowcount)


def rotate_refresh_token(token: str, kind: str) -> IssuedRefreshToken:
    """Spend a refresh token once and hand back its replacement.

    The whole check and swap runs inside one write transaction so two parallel
    refreshes cannot both succeed.

    A token that was already spent is a theft signal: everything issued to that
    subject and kind is revoked and RefreshTokenReuse is raised, which the
    router answers with 401.
    """
    if kind not in REFRESH_KINDS:
        raise ValueError(f"unknown refresh token kind: {kind}")
    presented = (token or "").strip()
    if not presented:
        raise InvalidRefreshToken("no refresh token was presented")

    token_hash = hash_refresh_token(presented)
    with get_conn(write=True) as conn:
        row = conn.execute(
            "SELECT token_hash, subject, kind, expires_at, used_at, revoked "
            "FROM refresh_tokens WHERE token_hash = ? AND kind = ?",
            (token_hash, kind),
        ).fetchone()
        if row is None:
            raise InvalidRefreshToken("the refresh token is not known")

        subject = str(row["subject"])
        if row["used_at"] is not None:
            conn.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE subject = ? AND kind = ?",
                (subject, kind),
            )
            # Committed before the raise on purpose: get_conn rolls back when an
            # exception leaves the block, which would undo the revocation that
            # the reuse just earned.
            conn.commit()
            logger.warning(
                "refresh token reuse detected, revoked the %s family for one subject",
                kind,
            )
            raise RefreshTokenReuse("the refresh token was already used")
        if int(row["revoked"] or 0):
            raise InvalidRefreshToken("the refresh token was revoked")
        expires_at = parse_iso_utc(str(row["expires_at"]))
        if expires_at is None or expires_at <= utc_now():
            raise InvalidRefreshToken("the refresh token has expired")

        conn.execute(
            "UPDATE refresh_tokens SET used_at = ? WHERE token_hash = ?",
            (iso_utc(), token_hash),
        )
        return _insert_refresh_token(conn, subject, kind)


def prune_refresh_tokens() -> int:
    """Delete rows that can never be used again. Returns how many went."""
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "DELETE FROM refresh_tokens WHERE expires_at < ?", (iso_utc(),)
        )
        return int(cursor.rowcount or 0)


__all__ = [
    "ACCESS_TTL_BY_AUDIENCE",
    "ADMIN_ACCESS_TTL_SECONDS",
    "ADMIN_REFRESH_TTL_SECONDS",
    "ALGORITHM",
    "AUDIENCES",
    "AUDIENCE_ADMIN",
    "AUDIENCE_DEVICE",
    "DEVICE_ACCESS_TTL_SECONDS",
    "DEVICE_REFRESH_TTL_SECONDS",
    "INVALID_REFRESH_CODE",
    "InvalidAccessToken",
    "InvalidRefreshToken",
    "IssuedRefreshToken",
    "KIND_ADMIN_REFRESH",
    "KIND_DEVICE_REFRESH",
    "REFRESH_KINDS",
    "REFRESH_KIND_BY_AUDIENCE",
    "REFRESH_TTL_BY_KIND",
    "RefreshTokenReuse",
    "TokenError",
    "access_ttl_seconds",
    "decode_access_token",
    "hash_refresh_token",
    "issue_access_token",
    "issue_refresh_token",
    "prune_refresh_tokens",
    "refresh_ttl_seconds",
    "revoke_refresh_token",
    "revoke_subject_tokens",
    "rotate_refresh_token",
    "subject_of",
]
