"""Admin sign in (CONTRACT_MOBILE_ADMIN.md section 6.3).

    POST /api/admin/auth/login     username and password, argon2 verified
    POST /api/admin/auth/refresh   rotate the admin refresh token
    POST /api/admin/auth/logout    204, revokes the presented refresh token
    GET  /api/admin/auth/me        who the current session belongs to

Three decisions here are security decisions rather than style ones.

A wrong username and a wrong password produce the identical body and comparable
work: the unknown username path still burns one argon2 verification
(app.security.passwords.dummy_verify), so response time cannot separate the two
and the route cannot be used to enumerate accounts.

Five consecutive failures lock the account for fifteen minutes. The lockout is
answered with that same identical body, so a caller cannot use the lock itself
to confirm that a username exists.

Nothing on any path logs a username with a password, a password hash, a token
or the reason a login failed beyond the failure counter in the row. The only
account detail that reaches a log line is the username of a successful login,
which the audit row already carries.

There is deliberately no route that creates an admin. The first account comes
from app/admin_cli.py or from the ADMIN_BOOTSTRAP_ variables at startup.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response, status

from app import deps, repo
from app.admin_cli import normalize_username
from app.db import get_conn
from app.models import (
    AdminLoginRequest,
    AdminMeResponse,
    AdminTokenResponse,
    RefreshRequest,
)
from app.security import iso_utc, utc_now
from app.security import passwords, ratelimit, tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/auth", tags=["admin auth"])

# Section 3.8: five consecutive failures, then fifteen minutes locked.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# One code and one sentence for every way a sign in can fail. Splitting them
# would turn the route into an oracle for which usernames exist.
CODE_INVALID_CREDENTIALS = "invalid_credentials"
INVALID_CREDENTIALS_DETAIL = "That username and password combination was not accepted."

# The refresh and logout failures reuse the shared refresh code from
# app.security.tokens, so the admin screens can treat a device refresh failure
# and an admin one with the same branch.
REFRESH_DETAIL = "The admin session has ended. Sign in again."

ACTION_LOGIN = "admin.login"
ACTION_LOGOUT = "admin.logout"


def _record_failure(username: str) -> None:
    """Count one failed attempt and lock the account at the threshold.

    Runs for a username that exists. An unknown username has no row to count
    against, which is fine: the per IP budget on this route is what limits
    guessing at names.
    """
    locked_until = iso_utc(utc_now() + timedelta(minutes=LOCKOUT_MINUTES))
    with get_conn(write=True) as conn:
        conn.execute(
            "UPDATE admin_users SET failed_count = failed_count + 1, "
            "locked_until = CASE WHEN failed_count + 1 >= ? THEN ? "
            "ELSE locked_until END WHERE username = ?",
            (MAX_FAILED_ATTEMPTS, locked_until, username),
        )


def _record_success(username: str, rehash: bool, password: str) -> str:
    """Clear the failure counter, stamp the login and return the timestamp.

    A hash written under older argon2 parameters is rewritten here, which is
    the only moment the plaintext is available to do it with. It is never
    stored, never logged and goes out of scope with this call.
    """
    now = iso_utc()
    new_hash = passwords.hash_password(password) if rehash else None
    with get_conn(write=True) as conn:
        if new_hash is None:
            conn.execute(
                "UPDATE admin_users SET failed_count = 0, locked_until = NULL, "
                "last_login_at = ? WHERE username = ?",
                (now, username),
            )
        else:
            conn.execute(
                "UPDATE admin_users SET failed_count = 0, locked_until = NULL, "
                "last_login_at = ?, password_hash = ? WHERE username = ?",
                (now, new_hash, username),
            )
    return now


def _stored_hash(username: str) -> str | None:
    """The argon2 hash for a username, or None when there is no such row.

    Kept out of app.deps.AdminUser on purpose, so the hash only ever exists
    inside the one function that verifies it.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM admin_users WHERE username = ?", (username,)
        ).fetchone()
    return None if row is None else str(row["password_hash"])


def _issue_session(username: str) -> AdminTokenResponse:
    """Mint the access and refresh pair an admin screen holds."""
    access_token, expires_in = tokens.issue_access_token(
        username, tokens.AUDIENCE_ADMIN
    )
    refresh = tokens.issue_refresh_token(username, tokens.KIND_ADMIN_REFRESH)
    return AdminTokenResponse(
        access_token=access_token,
        refresh_token=refresh.token,
        expires_in=expires_in,
        username=username,
    )


@router.post(
    "/login",
    response_model=AdminTokenResponse,
    summary="Sign in to the admin screens",
    response_description=(
        "An admin access token, a rotating refresh token and the username."
    ),
)
def admin_login(
    request: Request,
    payload: AdminLoginRequest,
    _ip_limit: None = Depends(deps.rate_limit(ratelimit.SCOPE_IP)),
    _login_limit: None = Depends(deps.rate_limit(ratelimit.SCOPE_ADMIN_LOGIN)),
) -> AdminTokenResponse:
    """Verify a password with argon2 and open an admin session.

    All four ways this can fail (unknown username, wrong password, locked
    account, a stored hash that is not usable) raise the identical status, code
    and sentence, and each one first spends comparable work. That is what keeps
    them indistinguishable to a caller by body or by timing.
    """
    username = normalize_username(payload.username)
    admin = deps.load_admin(username) if username else None

    if admin is None:
        # Burn a comparable amount of work so an unknown username does not
        # answer measurably faster than a wrong password.
        passwords.dummy_verify()
        raise deps.ApiError(401, CODE_INVALID_CREDENTIALS, INVALID_CREDENTIALS_DETAIL)

    if admin.is_locked:
        passwords.dummy_verify()
        raise deps.ApiError(401, CODE_INVALID_CREDENTIALS, INVALID_CREDENTIALS_DETAIL)

    stored = _stored_hash(username)
    if not passwords.verify_password(stored, payload.password):
        _record_failure(username)
        raise deps.ApiError(401, CODE_INVALID_CREDENTIALS, INVALID_CREDENTIALS_DETAIL)

    _record_success(username, passwords.needs_rehash(stored), payload.password)
    repo.write_audit(
        username, ACTION_LOGIN, target=username, ip=deps.client_ip(request)
    )
    logger.info("admin %s signed in", username)
    return _issue_session(username)


@router.post(
    "/refresh",
    response_model=AdminTokenResponse,
    summary="Rotate an admin refresh token",
    response_description=(
        "A new admin access token and the refresh token that replaces the "
        "spent one."
    ),
)
def admin_refresh(
    payload: RefreshRequest,
    _ip_limit: None = Depends(deps.rate_limit(ratelimit.SCOPE_IP)),
) -> AdminTokenResponse:
    """Spend an admin refresh token once and issue its replacement.

    A reused token has already had its whole family revoked by
    tokens.rotate_refresh_token, so the session behind it is gone and the
    screens fall back to the login form.
    """
    try:
        rotated = tokens.rotate_refresh_token(
            payload.refresh_token, tokens.KIND_ADMIN_REFRESH
        )
    except tokens.InvalidRefreshToken:
        raise deps.ApiError(401, tokens.INVALID_REFRESH_CODE, REFRESH_DETAIL)

    admin = deps.load_admin(rotated.subject)
    if admin is None:
        tokens.revoke_subject_tokens(rotated.subject, tokens.KIND_ADMIN_REFRESH)
        raise deps.ApiError(401, tokens.INVALID_REFRESH_CODE, REFRESH_DETAIL)

    access_token, expires_in = tokens.issue_access_token(
        admin.username, tokens.AUDIENCE_ADMIN
    )
    return AdminTokenResponse(
        access_token=access_token,
        refresh_token=rotated.token,
        expires_in=expires_in,
        username=admin.username,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End an admin session",
    response_description="No content. The refresh token is revoked.",
)
def admin_logout(
    request: Request,
    admin: deps.CurrentAdmin,
    payload: RefreshRequest | None = None,
) -> Response:
    """Revoke the presented refresh token, or the whole family without one.

    Idempotent, and deliberately never fails on an unknown token: a sign out
    that can error is a sign out a user cannot trust, and the access token
    expires by itself either way.
    """
    if payload is not None and payload.refresh_token:
        tokens.revoke_refresh_token(payload.refresh_token, tokens.KIND_ADMIN_REFRESH)
    else:
        tokens.revoke_subject_tokens(admin.username, tokens.KIND_ADMIN_REFRESH)
    repo.write_audit(
        admin.username,
        ACTION_LOGOUT,
        target=admin.username,
        ip=deps.client_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=AdminMeResponse,
    summary="The signed in admin",
    response_description=(
        "The username of the current session and when it last signed in."
    ),
)
def admin_me(admin: deps.CurrentAdmin) -> AdminMeResponse:
    """Who the bearer token belongs to, for the shell header and a reload."""
    return AdminMeResponse(username=admin.username, last_login_at=admin.last_login_at)


__all__ = [
    "ACTION_LOGIN",
    "ACTION_LOGOUT",
    "CODE_INVALID_CREDENTIALS",
    "INVALID_CREDENTIALS_DETAIL",
    "LOCKOUT_MINUTES",
    "MAX_FAILED_ATTEMPTS",
    "REFRESH_DETAIL",
    "admin_login",
    "admin_logout",
    "admin_me",
    "admin_refresh",
    "router",
]
