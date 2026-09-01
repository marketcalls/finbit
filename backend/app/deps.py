"""FastAPI dependencies shared by every secured route.

The verification order in contract 2 section 3.5 is a security decision, not a
style one: the cheap checks run first so an unauthenticated flood is rejected
before it can cost a token decode or an argon2 verification, and each failure
short-circuits with its own code so the client knows what to fix without the
API becoming an oracle.

Failures raise ApiError, which carries the machine readable code. The response
body is shaped {"detail", "code"} by the handler that
app.security.middleware.install_security registers, so main.py must call it.

Nothing here logs a token, a signature, a device secret or a password.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request

from app.config import get_settings
from app.db import get_conn
from app.security import iso_utc, parse_iso_utc, unix_seconds, utc_now
from app.security import keys, ratelimit, signing, tokens

logger = logging.getLogger(__name__)

# Request headers (contract 2, section 3.5).
HEADER_APP_KEY = "X-App-Key"
HEADER_DEVICE_ID = "X-Device-Id"
HEADER_TIMESTAMP = "X-Timestamp"
HEADER_NONCE = "X-Nonce"
HEADER_SIGNATURE = "X-Signature"
HEADER_AUTHORIZATION = "Authorization"

# Error codes, exactly as the table in section 3.5 spells them.
CODE_INVALID_APP_KEY = "invalid_app_key"
CODE_RATE_LIMITED = ratelimit.RATE_LIMITED_CODE
CODE_MISSING_SIGNATURE_HEADERS = "missing_signature_headers"
CODE_STALE_REQUEST = "stale_request"
CODE_REPLAYED_REQUEST = "replayed_request"
CODE_INVALID_TOKEN = "invalid_token"
CODE_DEVICE_REVOKED = "device_revoked"
CODE_BAD_SIGNATURE = "bad_signature"
CODE_MAINTENANCE = "maintenance"

# Feature flag rows the maintenance gate reads. The flags router owns writing
# them; the gate lives here so every content route can depend on it without
# importing a router. maintenance_mode uses the enabled column,
# maintenance_message uses the value column.
FLAG_MAINTENANCE_MODE = "maintenance_mode"
FLAG_MAINTENANCE_MESSAGE = "maintenance_message"
DEFAULT_MAINTENANCE_MESSAGE = (
    "FinBit is briefly down for maintenance. Please try again shortly."
)

# A nonce longer than this is not a client, it is someone probing. Rejected
# before it can be written to the nonces table.
MAX_NONCE_HEADER_LENGTH = signing.MAX_NONCE_LENGTH


class ApiError(HTTPException):
    """HTTPException that also carries the contract's code string.

    app.security.middleware turns it into {"detail": ..., "code": ...}. An
    HTTPException without a code keeps the stock FastAPI body, so phase 1
    responses are untouched.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


@dataclass(frozen=True)
class Device:
    """One row of the devices table, as routes see it."""

    id: str
    platform: str
    app_id: str
    created_at: str
    last_seen_at: str | None
    revoked: bool
    request_count: int


@dataclass(frozen=True)
class AdminUser:
    """One row of admin_users, without the password hash.

    The hash stays out on purpose: a route that never receives it cannot leak
    it into a response model or a log line.
    """

    id: int
    username: str
    created_at: str
    last_login_at: str | None
    failed_count: int
    locked_until: str | None

    @property
    def is_locked(self) -> bool:
        """True while a lockout from repeated failures is still running."""
        until = parse_iso_utc(self.locked_until)
        return until is not None and until > utc_now()


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def client_ip(request: Request) -> str:
    """The caller's IP for rate limiting.

    Deliberately the socket address and never X-Forwarded-For: with no trusted
    proxy configured, honouring that header would let any caller pick its own
    rate limit bucket. Put the real client IP here by terminating TLS in front
    of the app and running it with uvicorn --proxy-headers.
    """
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def path_with_query(request: Request) -> str:
    """The path and query exactly as the client signed them.

    The raw path is preferred over the decoded one so a percent encoded segment
    still hashes to the same bytes on both sides. Some ASGI servers put the
    query into raw_path and some do not, so it is split off either way.
    """
    raw = request.scope.get("raw_path")
    if raw:
        path = raw.decode("ascii", "ignore").split("?", 1)[0]
    else:
        path = str(request.scope.get("path") or request.url.path)
    query = request.scope.get("query_string") or b""
    query_text = query.decode("ascii", "ignore") if isinstance(query, bytes) else str(query)
    return f"{path}?{query_text}" if query_text else path


def bearer_token(request: Request) -> str:
    """The bearer token from the Authorization header, or an empty string."""
    header = request.headers.get(HEADER_AUTHORIZATION, "")
    scheme, _, value = header.partition(" ")
    if scheme.strip().lower() != "bearer":
        return ""
    return value.strip()


def enforce_rate_limit(scope: str, identity: str) -> None:
    """Spend one token in a bucket, or raise 429 with a Retry-After."""
    decision = ratelimit.consume(scope, identity)
    if decision.allowed:
        return
    raise ApiError(
        429,
        CODE_RATE_LIMITED,
        ratelimit.RATE_LIMITED_DETAIL,
        headers={"Retry-After": decision.retry_after_header},
    )


def rate_limit(scope: str) -> Callable[[Request], None]:
    """Build a dependency that rate limits by caller IP in one scope.

    Used by the routes that have their own budget: device registration, admin
    login and the admin ingest trigger.
    """

    def dependency(request: Request) -> None:
        enforce_rate_limit(scope, client_ip(request))

    return dependency


# ---------------------------------------------------------------------------
# Replay protection
# ---------------------------------------------------------------------------


def prune_nonces(conn: sqlite3.Connection) -> int:
    """Drop nonces older than the TTL. Keeps the table at one window of traffic."""
    cutoff = utc_now() - timedelta(seconds=get_settings().nonce_ttl_seconds)
    cursor = conn.execute("DELETE FROM nonces WHERE seen_at < ?", (iso_utc(cutoff),))
    return int(cursor.rowcount or 0)


def claim_nonce(nonce: str, device_id: str) -> bool:
    """Record a nonce, returning False when it has been seen before.

    The primary key does the work: a replay loses the insert race rather than
    a read-then-write that two parallel requests could both pass.
    """
    with get_conn(write=True) as conn:
        prune_nonces(conn)
        try:
            conn.execute(
                "INSERT INTO nonces (nonce, device_id, seen_at) VALUES (?, ?, ?)",
                (nonce, device_id, iso_utc()),
            )
        except sqlite3.IntegrityError:
            return False
    return True


# ---------------------------------------------------------------------------
# Row loaders
# ---------------------------------------------------------------------------


def load_device(device_id: str) -> Device | None:
    """Read one device row, or None when it does not exist."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, platform, app_id, created_at, last_seen_at, revoked, "
            "request_count FROM devices WHERE id = ?",
            ((device_id or "").strip(),),
        ).fetchone()
    if row is None:
        return None
    return Device(
        id=str(row["id"]),
        platform=str(row["platform"]),
        app_id=str(row["app_id"]),
        created_at=str(row["created_at"]),
        last_seen_at=row["last_seen_at"],
        revoked=bool(row["revoked"]),
        request_count=int(row["request_count"] or 0),
    )


def touch_device(device_id: str) -> None:
    """Stamp last_seen_at and count the request. Never fails a request."""
    try:
        with get_conn(write=True) as conn:
            conn.execute(
                "UPDATE devices SET last_seen_at = ?, request_count = request_count + 1 "
                "WHERE id = ?",
                (iso_utc(), device_id),
            )
    except sqlite3.Error:
        logger.debug("could not stamp last_seen_at for a device")


def load_admin(username: str) -> AdminUser | None:
    """Read one admin row by username, without the password hash."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, created_at, last_login_at, failed_count, "
            "locked_until FROM admin_users WHERE username = ?",
            ((username or "").strip(),),
        ).fetchone()
    if row is None:
        return None
    return AdminUser(
        id=int(row["id"]),
        username=str(row["username"]),
        created_at=str(row["created_at"]),
        last_login_at=row["last_login_at"],
        failed_count=int(row["failed_count"] or 0),
        locked_until=row["locked_until"],
    )


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def require_app_key(request: Request) -> str:
    """Check 1: X-App-Key is one of the two configured keys.

    Returns the app id it belongs to, 'mobile' or 'web', and stashes it on the
    request so a route can tell the clients apart.
    """
    app_id = keys.app_id_for_key(request.headers.get(HEADER_APP_KEY))
    if app_id is None:
        raise ApiError(
            401, CODE_INVALID_APP_KEY, "The app key is missing or not recognised."
        )
    request.state.app_id = app_id
    return app_id


async def current_device(request: Request) -> Device:
    """Run the full device verification of section 3.5, checks 1 to 9.

    The raw body is read once here and Starlette caches it on the request, so
    the route's own pydantic body model still parses after this dependency has
    consumed the stream. Reading it any other way would leave the route with an
    empty body.
    """
    settings = get_settings()
    app_id = require_app_key(request)  # 1

    ip = client_ip(request)
    enforce_rate_limit(ratelimit.SCOPE_IP, ip)  # 2

    # Cached by Starlette on request._body, which is what request.body() in the
    # route handler reads afterwards.
    raw_body = await request.body()
    request.state.raw_body = raw_body

    signed = bool(settings.require_signed_requests)
    token = bearer_token(request)
    device_header = request.headers.get(HEADER_DEVICE_ID, "").strip()
    timestamp = request.headers.get(HEADER_TIMESTAMP, "").strip()
    nonce = request.headers.get(HEADER_NONCE, "").strip()
    signature = request.headers.get(HEADER_SIGNATURE, "").strip()

    # 3. Required headers present. In unsigned development mode the signature
    # headers are not required, but the bearer token always is.
    missing = not token
    if signed:
        missing = missing or not (device_header and timestamp and nonce and signature)
        missing = missing or not signing.looks_like_nonce(nonce)
    if missing:
        raise ApiError(
            401,
            CODE_MISSING_SIGNATURE_HEADERS,
            "The request is missing the headers this API requires.",
        )

    if signed:
        _check_timestamp(timestamp, settings.signature_skew_seconds)  # 4

    # 5. Nonce unseen. Claimed before the token is decoded because that is the
    # contract's order: the cheap replay check runs first.
    if signed and not claim_nonce(nonce, device_header):
        raise ApiError(
            401, CODE_REPLAYED_REQUEST, "This request has already been seen."
        )

    # 6. Access token valid, audience device, subject equal to X-Device-Id.
    try:
        subject = tokens.subject_of(token, tokens.AUDIENCE_DEVICE)
    except tokens.TokenError:
        raise ApiError(401, CODE_INVALID_TOKEN, "The access token is not valid.")
    if device_header and subject != device_header:
        raise ApiError(401, CODE_INVALID_TOKEN, "The access token is not valid.")
    device_id = device_header or subject

    # 7. Device row exists and is not revoked.
    device = load_device(device_id)
    if device is None or device.revoked:
        raise ApiError(
            401, CODE_DEVICE_REVOKED, "This device is no longer registered."
        )

    # 8. Signature matches.
    if signed:
        secret = keys.derive_device_secret(device_id)
        ok = signing.verify_request(
            secret=secret.raw,
            timestamp=timestamp,
            nonce=nonce,
            method=request.method,
            path_with_query=path_with_query(request),
            body=raw_body,
            signature=signature,
        )
        if not ok:
            raise ApiError(
                401, CODE_BAD_SIGNATURE, "The request signature does not match."
            )

    enforce_rate_limit(ratelimit.SCOPE_DEVICE, device_id)  # 9

    touch_device(device_id)
    request.state.device_id = device_id
    request.state.app_id = app_id
    return device


def _check_timestamp(timestamp: str, skew_seconds: int) -> None:
    """Check 4: the signed timestamp is within the allowed skew of now."""
    try:
        sent = int(timestamp)
    except (TypeError, ValueError):
        raise ApiError(
            401, CODE_STALE_REQUEST, "The request timestamp is not usable."
        )
    if abs(unix_seconds() - sent) > int(skew_seconds):
        raise ApiError(
            401,
            CODE_STALE_REQUEST,
            "The request timestamp is too far from the server clock.",
        )


def current_admin(request: Request) -> AdminUser:
    """Bearer only, audience admin, resolved to the admin_users row.

    No app key and no signature: the admin screens authenticate with a password
    and hold a short lived token in memory, and adding a signature there would
    put a shared secret in a browser bundle for no gain.
    """
    enforce_rate_limit(ratelimit.SCOPE_IP, client_ip(request))
    try:
        username = tokens.subject_of(bearer_token(request), tokens.AUDIENCE_ADMIN)
    except tokens.TokenError:
        raise ApiError(401, CODE_INVALID_TOKEN, "The admin session is not valid.")
    admin = load_admin(username)
    if admin is None:
        raise ApiError(401, CODE_INVALID_TOKEN, "The admin session is not valid.")
    request.state.admin_username = admin.username
    return admin


def maintenance_state() -> tuple[bool, str | None]:
    """Whether maintenance mode is on, and the message to show.

    Reads the feature_flags rows directly. A database that cannot be read is
    treated as not in maintenance: taking the whole API down because one flag
    row is unreadable would be the wrong failure.
    """
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT key, enabled, value FROM feature_flags WHERE key IN (?, ?)",
                (FLAG_MAINTENANCE_MODE, FLAG_MAINTENANCE_MESSAGE),
            ).fetchall()
    except sqlite3.Error:
        return False, None
    by_key = {str(row["key"]): row for row in rows}
    mode_row = by_key.get(FLAG_MAINTENANCE_MODE)
    if mode_row is None or not int(mode_row["enabled"] or 0):
        return False, None
    message_row = by_key.get(FLAG_MAINTENANCE_MESSAGE)
    message = None
    if message_row is not None:
        message = (message_row["value"] or "").strip() or None
    if message is None and mode_row["value"]:
        message = str(mode_row["value"]).strip() or None
    return True, message or DEFAULT_MAINTENANCE_MESSAGE


def maintenance_gate() -> None:
    """503 every content route while maintenance mode is on.

    GET /api/config never takes this dependency, so the apps can still read the
    flag and render the maintenance screen instead of an error.
    """
    active, message = maintenance_state()
    if active:
        raise ApiError(503, CODE_MAINTENANCE, message or DEFAULT_MAINTENANCE_MESSAGE)


# Annotated aliases, so a route reads `device: CurrentDevice` and the
# dependency graph stays in one place.
RequireAppKey = Annotated[str, Depends(require_app_key)]
CurrentDevice = Annotated[Device, Depends(current_device)]
CurrentAdmin = Annotated[AdminUser, Depends(current_admin)]

# For router level use: dependencies=[MaintenanceGate]
MaintenanceGate = Depends(maintenance_gate)


__all__ = [
    "AdminUser",
    "ApiError",
    "CODE_BAD_SIGNATURE",
    "CODE_DEVICE_REVOKED",
    "CODE_INVALID_APP_KEY",
    "CODE_INVALID_TOKEN",
    "CODE_MAINTENANCE",
    "CODE_MISSING_SIGNATURE_HEADERS",
    "CODE_RATE_LIMITED",
    "CODE_REPLAYED_REQUEST",
    "CODE_STALE_REQUEST",
    "CurrentAdmin",
    "CurrentDevice",
    "DEFAULT_MAINTENANCE_MESSAGE",
    "Device",
    "FLAG_MAINTENANCE_MESSAGE",
    "FLAG_MAINTENANCE_MODE",
    "HEADER_APP_KEY",
    "HEADER_AUTHORIZATION",
    "HEADER_DEVICE_ID",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "MaintenanceGate",
    "RequireAppKey",
    "bearer_token",
    "claim_nonce",
    "client_ip",
    "current_admin",
    "current_device",
    "enforce_rate_limit",
    "load_admin",
    "load_device",
    "maintenance_gate",
    "maintenance_state",
    "path_with_query",
    "prune_nonces",
    "rate_limit",
    "require_app_key",
    "touch_device",
]
