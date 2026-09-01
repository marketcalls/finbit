"""Admin sign in and the one-time account bootstrap.

    GET  /api/admin/auth/status           is registration still open
    POST /api/admin/auth/register         create the one admin account
    POST /api/admin/auth/login            username and password, argon2 verified
    POST /api/admin/auth/refresh          rotate the admin refresh token
    POST /api/admin/auth/logout           204, revokes the presented refresh token
    POST /api/admin/auth/change-password  204, ends every other admin session
    GET  /api/admin/auth/me               who the current session belongs to

The first four lines are CONTRACT_MOBILE_ADMIN.md section 6.3; the registration
pair and the password change are CONTRACT_ADMIN_REGISTRATION.md section 3.

Four decisions here are security decisions rather than style ones.

A wrong username and a wrong password produce the identical body and comparable
work: the unknown username path still burns one argon2 verification
(app.security.passwords.dummy_verify), so response time cannot separate the two
and the route cannot be used to enumerate accounts.

Five consecutive failures lock the account for fifteen minutes. The lockout is
answered with that same identical body, so a caller cannot use the lock itself
to confirm that a username exists.

Nothing on any path logs a password, a password hash, a bootstrap token, an
access token, a refresh token or the reason a login failed beyond the failure
counter in the row. The only account detail that reaches a log line is the
username of a successful login or of the account this created, which the audit
row already carries.

Exactly one admin account exists for the life of a deployment. It is created
once through POST /register, while admin_users is empty, guarded by the token
main.py prints to the console at startup. The moment that account exists the
route answers 404, with the body an unknown path returns, rather than 403: a
403 would confirm the route is there, and a route that can mint an
administrator is worth finding. There is no invite, no second account and no
route that creates one. app/admin_cli.py stays as the recovery path for a
forgotten password, and the ADMIN_BOOTSTRAP_ variables keep creating the
account at startup exactly as phase 2 built them, in which case no bootstrap
token is ever minted and nothing is printed.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response, status

from app import deps, repo
from app.admin_cli import normalize_username
from app.db import get_conn
from app.models import (
    ADMIN_USERNAME_MAX_LENGTH,
    ADMIN_USERNAME_MIN_LENGTH,
    ADMIN_USERNAME_PATTERN,
    AdminLoginRequest,
    AdminMeResponse,
    AdminPasswordChangeRequest,
    AdminRegisterRequest,
    AdminRegistrationStatus,
    AdminTokenResponse,
    RefreshRequest,
)
from app.security import iso_utc, utc_now
from app.security import bootstrap, passwords, ratelimit, tokens

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
ACTION_REGISTER = "admin.register"
ACTION_CHANGE_PASSWORD = "admin.change_password"

# The closed-route answer (CONTRACT_ADMIN_REGISTRATION.md section 3.2). It is
# the body an unrouted path returns, which main.py shapes to match, so a caller
# cannot tell a route that closed from one that never existed.
CODE_NOT_FOUND = "not_found"
NOT_FOUND_DETAIL = "Not found"

CODE_INVALID_BOOTSTRAP_TOKEN = "invalid_bootstrap_token"
INVALID_BOOTSTRAP_TOKEN_DETAIL = (
    "That bootstrap token was not accepted. Use the one this API printed when "
    "it started."
)

# Section 3.2 asks for the failing rule by name, because it is the caller's own
# new password: being specific here helps them and tells an attacker nothing
# the registration form does not already state.
CODE_WEAK_PASSWORD = "weak_password"

CODE_INVALID_USERNAME = "invalid_username"
INVALID_USERNAME_DETAIL = (
    f"The username must be {ADMIN_USERNAME_MIN_LENGTH} to "
    f"{ADMIN_USERNAME_MAX_LENGTH} characters, using letters, digits, dots, "
    "underscores and hyphens only."
)

_USERNAME_RE = re.compile(ADMIN_USERNAME_PATTERN)

# Section 3.1 and 3.2 give these two routes their own budgets: five
# registration attempts per IP per hour and thirty status reads per IP per
# minute. They are registered into the phase 2 bucket registry rather than
# implemented again, so every limit in the process still refills from one
# table with one algorithm.
SCOPE_ADMIN_REGISTER = "admin_register"
SCOPE_ADMIN_AUTH_STATUS = "admin_auth_status"

ratelimit.LIMITS.setdefault(
    SCOPE_ADMIN_REGISTER, ratelimit.Limit(SCOPE_ADMIN_REGISTER, 5, 60 * 60)
)
ratelimit.LIMITS.setdefault(
    SCOPE_ADMIN_AUTH_STATUS, ratelimit.Limit(SCOPE_ADMIN_AUTH_STATUS, 30, 60)
)


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


def _closed_route() -> deps.ApiError:
    """The 404 a closed registration route answers with.

    Built as a value rather than raised here so every caller raises it from its
    own line. The body matches an unknown path exactly, which is the whole
    point: once the account exists this route must be indistinguishable from
    one that was never mounted.
    """
    return deps.ApiError(404, CODE_NOT_FOUND, NOT_FOUND_DETAIL)


def _validated_username(username: str) -> str:
    """The stored form of a username, or a 422 naming the rule it broke.

    Normalized with the same helper the CLI uses, which trims and lowercases.
    Section 3.2 asks for case-insensitive comparison, and a single lowercase
    form in the table is how phase 2 already delivers that: every lookup, the
    JWT subject and the audit rows agree on one spelling, so an account created
    here signs in with any capitalisation of its name.
    """
    name = normalize_username(username)
    too_short = len(name) < ADMIN_USERNAME_MIN_LENGTH
    too_long = len(name) > ADMIN_USERNAME_MAX_LENGTH
    if too_short or too_long or not _USERNAME_RE.match(name):
        raise deps.ApiError(422, CODE_INVALID_USERNAME, INVALID_USERNAME_DETAIL)
    return name


@router.get(
    "/status",
    response_model=AdminRegistrationStatus,
    summary="Whether the one-time admin registration is still open",
    response_description=(
        "One boolean: true only while no admin account exists yet."
    ),
)
def admin_auth_status(
    _ip_limit: None = Depends(deps.rate_limit(ratelimit.SCOPE_IP)),
    _status_limit: None = Depends(deps.rate_limit(SCOPE_ADMIN_AUTH_STATUS)),
) -> AdminRegistrationStatus:
    """Tell the login screen which of its two faces to render.

    Public and unauthenticated, because the screen has to ask before anyone can
    sign in. It answers from the row count alone: no username, and deliberately
    no reading of app.state, so the reply cannot hint at whether a bootstrap
    token is currently live or ever was.
    """
    return AdminRegistrationStatus(registration_open=repo.registration_open())


@router.post(
    "/register",
    response_model=AdminTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the one admin account, once",
    response_description=(
        "A signed-in admin session, so the browser goes straight to the "
        "dashboard."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "An admin account already exists, so this route is gone."
        }
    },
)
def admin_register(
    request: Request,
    payload: AdminRegisterRequest,
) -> AdminTokenResponse:
    """Claim the instance, while admin_users is empty and with the right token.

    The order of the checks is the design. The row count runs first, so a
    caller who arrives after the account exists learns only that there is no
    such route. The bootstrap token runs next, so someone without it never
    reaches the password rules or the cost of an argon2 hash.

    The two budgets are spent here rather than through Depends, and that is the
    reason this route has no dependency list. A dependency runs before the
    handler, so a drained bucket would answer a closed route with 429 while an
    unknown path still answered 404, and the difference would say that the
    route is real. Charging only after the row count means a closed route costs
    one COUNT(*) and is indistinguishable from a path that was never mounted.

    The count is then taken a third time, inside the write transaction, by
    repo.create_first_admin. That is what makes two simultaneous registrations
    safe: the check above is only an early exit, the one that decides is the
    one holding the write lock. Losing that race is answered with the same 404
    as arriving late, because by then it is the same situation.

    On success the in-memory token is dropped immediately, so it cannot create
    a second account even inside its thirty minute window.
    """
    if not repo.registration_open():
        raise _closed_route()

    caller = deps.client_ip(request)
    deps.enforce_rate_limit(ratelimit.SCOPE_IP, caller)
    deps.enforce_rate_limit(SCOPE_ADMIN_REGISTER, caller)

    token = bootstrap.current(request.app.state)
    if not bootstrap.verify(token, payload.bootstrap_token):
        raise deps.ApiError(
            401, CODE_INVALID_BOOTSTRAP_TOKEN, INVALID_BOOTSTRAP_TOKEN_DETAIL
        )

    username = _validated_username(payload.username)
    problem = passwords.policy_problem(payload.password, username)
    if problem is not None:
        raise deps.ApiError(422, CODE_WEAK_PASSWORD, problem)

    created = repo.create_first_admin(username, passwords.hash_password(payload.password))
    if not created:
        raise _closed_route()

    bootstrap.clear(request.app.state)
    repo.write_audit(username, ACTION_REGISTER, target=username, ip=caller)
    logger.info("admin account created: %s", username)
    return _issue_session(username)


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


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the admin password",
    response_description="No content. Every other admin session has ended.",
)
def admin_change_password(
    request: Request,
    admin: deps.CurrentAdmin,
    payload: AdminPasswordChangeRequest,
) -> Response:
    """Verify the current password, apply the policy and rehash (section 3.3).

    Every admin refresh token is revoked afterwards, including the one this
    session is holding. That is deliberate: a password change is what someone
    does when they think a session is not theirs any more, and it would be
    worth very little if the other tabs kept working. The caller signs in again
    with the new password.

    A wrong current password answers with the login route's body, so the two
    cannot be told apart by a caller who got hold of an access token.
    """
    stored = _stored_hash(admin.username)
    if not passwords.verify_password(stored, payload.current_password):
        raise deps.ApiError(401, CODE_INVALID_CREDENTIALS, INVALID_CREDENTIALS_DETAIL)

    problem = passwords.policy_problem(payload.new_password, admin.username)
    if problem is not None:
        raise deps.ApiError(422, CODE_WEAK_PASSWORD, problem)

    repo.set_admin_password(
        admin.username, passwords.hash_password(payload.new_password)
    )
    tokens.revoke_subject_tokens(admin.username, tokens.KIND_ADMIN_REFRESH)
    repo.write_audit(
        admin.username,
        ACTION_CHANGE_PASSWORD,
        target=admin.username,
        ip=deps.client_ip(request),
    )
    logger.info("admin %s changed the account password", admin.username)
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
    "ACTION_CHANGE_PASSWORD",
    "ACTION_LOGIN",
    "ACTION_LOGOUT",
    "ACTION_REGISTER",
    "CODE_INVALID_BOOTSTRAP_TOKEN",
    "CODE_INVALID_CREDENTIALS",
    "CODE_INVALID_USERNAME",
    "CODE_NOT_FOUND",
    "CODE_WEAK_PASSWORD",
    "INVALID_BOOTSTRAP_TOKEN_DETAIL",
    "INVALID_CREDENTIALS_DETAIL",
    "INVALID_USERNAME_DETAIL",
    "LOCKOUT_MINUTES",
    "MAX_FAILED_ATTEMPTS",
    "NOT_FOUND_DETAIL",
    "REFRESH_DETAIL",
    "SCOPE_ADMIN_AUTH_STATUS",
    "SCOPE_ADMIN_REGISTER",
    "admin_auth_status",
    "admin_change_password",
    "admin_login",
    "admin_logout",
    "admin_me",
    "admin_refresh",
    "admin_register",
    "router",
]
