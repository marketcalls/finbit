"""Admin account management from the command line.

    uv run python -m app.admin_cli create-admin --username alice
    uv run python -m app.admin_cli list-admins
    uv run python -m app.admin_cli reset-password --username alice

There is no HTTP route that creates the first admin, on purpose: an endpoint
that can mint an administrator is an endpoint someone can find. The password is
read twice through getpass, so it is never echoed, never sits in shell history
and never reaches a log line. Only the username is ever printed.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sqlite3
import sys
from dataclasses import dataclass

from app.config import get_settings
from app.db import get_conn, init_db
from app.migrate import run_migrations
from app.security import iso_utc
from app.security.passwords import MIN_PASSWORD_LENGTH, hash_password

logger = logging.getLogger(__name__)

PROMPT_FIRST = "New password: "
PROMPT_SECOND = "Repeat password: "


@dataclass(frozen=True)
class AdminRow:
    """One admin_users row, without the hash. Safe to print."""

    id: int
    username: str
    created_at: str
    last_login_at: str | None
    failed_count: int
    locked_until: str | None


def _prepare_database() -> None:
    """Create the schema and apply the phase 2 migration before touching it.

    The CLI is often the very first thing run against a fresh checkout, so it
    cannot assume the API has already started once.
    """
    init_db()
    with get_conn(write=True) as conn:
        run_migrations(conn)


def normalize_username(username: str) -> str:
    """Trim and lowercase a username, the form stored in the table."""
    return (username or "").strip().lower()


def admin_exists(username: str) -> bool:
    """True when that username is taken."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM admin_users WHERE username = ?", (normalize_username(username),)
        ).fetchone()
    return row is not None


def admin_count() -> int:
    """How many admin accounts exist."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()
    return int(row["n"] if row is not None else 0)


def list_admins() -> list[AdminRow]:
    """Every admin account, oldest first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, created_at, last_login_at, failed_count, "
            "locked_until FROM admin_users ORDER BY id"
        ).fetchall()
    return [
        AdminRow(
            id=int(row["id"]),
            username=str(row["username"]),
            created_at=str(row["created_at"]),
            last_login_at=row["last_login_at"],
            failed_count=int(row["failed_count"] or 0),
            locked_until=row["locked_until"],
        )
        for row in rows
    ]


def create_admin(username: str, password: str) -> str:
    """Create one admin account. Returns the stored username.

    Raises ValueError for a bad username, a short password or a name that is
    already taken. The password is hashed before it goes anywhere near SQL.
    """
    name = normalize_username(username)
    if not name:
        raise ValueError("a username is required")
    password_hash = hash_password(password)
    try:
        with get_conn(write=True) as conn:
            conn.execute(
                "INSERT INTO admin_users (username, password_hash, created_at, "
                "failed_count) VALUES (?, ?, ?, 0)",
                (name, password_hash, iso_utc()),
            )
    except sqlite3.IntegrityError:
        raise ValueError(f"the username {name} already exists") from None
    return name


def set_password(username: str, password: str) -> str:
    """Replace an admin password and clear any lockout. Returns the username."""
    name = normalize_username(username)
    password_hash = hash_password(password)
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "UPDATE admin_users SET password_hash = ?, failed_count = 0, "
            "locked_until = NULL WHERE username = ?",
            (password_hash, name),
        )
        if not cursor.rowcount:
            raise ValueError(f"no admin named {name} exists")
    return name


def ensure_bootstrap_admin() -> str | None:
    """Create the bootstrap admin at startup when one is configured.

    Runs only when ADMIN_BOOTSTRAP_USERNAME and ADMIN_BOOTSTRAP_PASSWORD are
    both set and no admin exists yet, so a restart never resets a password
    someone has since changed. Logs the username and nothing else.
    """
    settings = get_settings()
    if not settings.has_admin_bootstrap:
        return None
    if admin_count() > 0:
        return None
    try:
        username = create_admin(
            settings.admin_bootstrap_username, settings.admin_bootstrap_password
        )
    except ValueError as exc:
        logger.warning("the bootstrap admin was not created: %s", exc)
        return None
    logger.info("created the bootstrap admin account %s", username)
    return username


def _read_new_password() -> str:
    """Prompt twice, never echoing, and refuse anything under the floor."""
    first = getpass.getpass(PROMPT_FIRST)
    if len(first) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"the password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    second = getpass.getpass(PROMPT_SECOND)
    if first != second:
        raise ValueError("the two passwords do not match")
    return first


def _cmd_create_admin(args: argparse.Namespace) -> int:
    _prepare_database()
    name = normalize_username(args.username)
    if not name:
        print("a username is required", file=sys.stderr)
        return 2
    if admin_exists(name):
        print(f"the username {name} already exists", file=sys.stderr)
        return 1
    try:
        password = _read_new_password()
        created = create_admin(name, password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("cancelled", file=sys.stderr)
        return 1
    print(created)
    return 0


def _cmd_reset_password(args: argparse.Namespace) -> int:
    _prepare_database()
    name = normalize_username(args.username)
    if not admin_exists(name):
        print(f"no admin named {name} exists", file=sys.stderr)
        return 1
    try:
        password = _read_new_password()
        changed = set_password(name, password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("cancelled", file=sys.stderr)
        return 1
    print(changed)
    return 0


def _cmd_list_admins(_args: argparse.Namespace) -> int:
    _prepare_database()
    rows = list_admins()
    if not rows:
        print("no admin accounts exist yet")
        return 0
    print(f"{'username':<24} {'created':<21} {'last login':<21} {'failed':>6}")
    for row in rows:
        print(
            f"{row.username:<24} {row.created_at:<21} "
            f"{(row.last_login_at or '-'):<21} {row.failed_count:>6}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The argparse tree. One subcommand per operation."""
    parser = argparse.ArgumentParser(
        prog="python -m app.admin_cli",
        description="Manage FinBit admin accounts. Passwords are never echoed.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-admin", help="create an admin account")
    create.add_argument("--username", required=True)
    create.set_defaults(handler=_cmd_create_admin)

    listing = sub.add_parser("list-admins", help="list the admin accounts")
    listing.set_defaults(handler=_cmd_list_admins)

    reset = sub.add_parser("reset-password", help="set a new password")
    reset.add_argument("--username", required=True)
    reset.set_defaults(handler=_cmd_reset_password)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AdminRow",
    "admin_count",
    "admin_exists",
    "build_parser",
    "create_admin",
    "ensure_bootstrap_admin",
    "list_admins",
    "main",
    "normalize_username",
    "set_password",
]
