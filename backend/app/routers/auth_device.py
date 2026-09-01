"""Anonymous device handshake (CONTRACT_MOBILE_ADMIN.md section 6.1).

    POST /api/auth/device     register once, receive the device credentials
    POST /api/auth/refresh    rotate the refresh token, get a new access token

Both routes take X-App-Key and no signature. A device that has never registered
has no secret to sign with, and a refreshing one is proving possession of the
refresh token instead. That is exactly why registration carries its own tight
per IP budget on top of the global one: it is the only unsigned way in.

The device secret is handed over once, in the registration response, and never
again. The server derives it from the device id on every later request
(app/security/keys.py) and stores nothing, so a copy of the database holds
nothing that can sign a request. Nothing here logs the secret, either token or
the install id.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends

from app import deps
from app.db import get_conn
from app.models import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    RefreshRequest,
    TokenPairResponse,
)
from app.security import iso_utc
from app.security import keys, ratelimit, tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["device auth"])

# An app_id in the body that disagrees with the key in the header is answered
# with the app key code rather than a code of its own. The two are one claim:
# "I am the mobile app". Splitting them would tell a caller which half it got
# right.
CODE_APP_ID_MISMATCH = deps.CODE_INVALID_APP_KEY

# A platform this client cannot register on, for example the web bundle asking
# for an ios device row. Its own code because it is a client bug, not an
# authentication failure, and the app can log it and fix the call.
CODE_INVALID_PLATFORM = "invalid_platform"

# The database refused the insert. A 503 rather than a 500 because the client's
# correct response is to retry the handshake, which is what the apps already do
# behind their splash screen.
CODE_REGISTRATION_FAILED = "registration_failed"

APP_KEY_DETAIL = "The app key is missing or does not match this request."
PLATFORM_DETAIL = "This client cannot register a device on that platform."
REFRESH_DETAIL = "The refresh token is not valid. Register this device again."


def _create_device(app_id: str, platform: str) -> str:
    """Insert one device row and return its id.

    The id is generated here rather than by the database because it is handed
    to the client and used as a token subject: an opaque uuid4 carries nothing
    about the device, where an autoincrement integer would leak how many
    devices have registered.
    """
    device_id = keys.new_device_id()
    with get_conn(write=True) as conn:
        conn.execute(
            "INSERT INTO devices (id, platform, app_id, created_at, last_seen_at, "
            "revoked, request_count) VALUES (?, ?, ?, ?, ?, 0, 0)",
            (device_id, platform, app_id, iso_utc(), iso_utc()),
        )
    return device_id


@router.post(
    "/device",
    response_model=DeviceRegisterResponse,
    summary="Register an anonymous device",
    response_description=(
        "The device id, its secret, a short lived access token and a rotating "
        "refresh token."
    ),
)
def register_device(
    payload: DeviceRegisterRequest,
    app_id: deps.RequireAppKey,
    _ip_limit: None = Depends(deps.rate_limit(ratelimit.SCOPE_IP)),
    _register_limit: None = Depends(deps.rate_limit(ratelimit.SCOPE_DEVICE_REGISTER)),
) -> DeviceRegisterResponse:
    """Create a device and hand back everything it needs to sign requests.

    There is no login and no account. The apps call this once on first launch
    and keep the credentials, so a lost device row means a new anonymous device
    rather than a locked out user.
    """
    if payload.app_id != app_id:
        raise deps.ApiError(401, CODE_APP_ID_MISMATCH, APP_KEY_DETAIL)

    if not keys.platform_allowed(app_id, payload.platform):
        raise deps.ApiError(400, CODE_INVALID_PLATFORM, PLATFORM_DETAIL)

    try:
        device_id = _create_device(app_id, payload.platform)
    except sqlite3.Error:
        logger.exception("a device row could not be created")
        raise deps.ApiError(
            503,
            CODE_REGISTRATION_FAILED,
            "Registration is unavailable. Try again shortly.",
        )

    secret = keys.derive_device_secret(device_id)
    access_token, expires_in = tokens.issue_access_token(
        device_id, tokens.AUDIENCE_DEVICE
    )
    refresh = tokens.issue_refresh_token(device_id, tokens.KIND_DEVICE_REFRESH)

    # The id is safe to log and is the only handle support has on a device with
    # no account behind it. The secret and both tokens never appear in a log.
    logger.info("registered a %s device on %s", app_id, payload.platform)

    return DeviceRegisterResponse(
        device_id=device_id,
        device_secret=secret.b64,
        access_token=access_token,
        refresh_token=refresh.token,
        expires_in=expires_in,
    )


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Rotate a device refresh token",
    response_description=(
        "A new access token and the refresh token that replaces the spent one."
    ),
)
def refresh_device_token(
    payload: RefreshRequest,
    _app_id: deps.RequireAppKey,
    _ip_limit: None = Depends(deps.rate_limit(ratelimit.SCOPE_IP)),
) -> TokenPairResponse:
    """Spend a refresh token once and issue its replacement.

    An unknown token, an expired one and a reused one all answer with the same
    body, so the route cannot be used to test whether a guessed token ever
    existed. A revoked device gets its own code instead, because reaching that
    branch already required a valid refresh token, so there is nothing left to
    guess and the client learns that an admin took the device out rather than
    that its token went stale.
    """
    try:
        rotated = tokens.rotate_refresh_token(
            payload.refresh_token, tokens.KIND_DEVICE_REFRESH
        )
    except tokens.RefreshTokenReuse:
        # tokens.rotate_refresh_token has already revoked the family and logged
        # the reuse without naming the token.
        raise deps.ApiError(401, tokens.INVALID_REFRESH_CODE, REFRESH_DETAIL)
    except tokens.InvalidRefreshToken:
        raise deps.ApiError(401, tokens.INVALID_REFRESH_CODE, REFRESH_DETAIL)

    device = deps.load_device(rotated.subject)
    if device is None or device.revoked:
        tokens.revoke_subject_tokens(rotated.subject, tokens.KIND_DEVICE_REFRESH)
        raise deps.ApiError(401, deps.CODE_DEVICE_REVOKED, REFRESH_DETAIL)

    access_token, expires_in = tokens.issue_access_token(
        device.id, tokens.AUDIENCE_DEVICE
    )
    return TokenPairResponse(
        access_token=access_token,
        refresh_token=rotated.token,
        expires_in=expires_in,
    )


__all__ = [
    "APP_KEY_DETAIL",
    "CODE_APP_ID_MISMATCH",
    "CODE_INVALID_PLATFORM",
    "CODE_REGISTRATION_FAILED",
    "PLATFORM_DETAIL",
    "REFRESH_DETAIL",
    "refresh_device_token",
    "register_device",
    "router",
]
