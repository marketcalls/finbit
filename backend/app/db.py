"""SQLite connection handling and schema bootstrap.

One connection per request or per repository call. FastAPI runs sync route
handlers in a threadpool, so connections are created with
check_same_thread=False and every write is serialised behind a process-wide
lock. SQLite itself is in WAL mode, so readers never block the writer.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import SCHEMA_FILE, get_settings

logger = logging.getLogger(__name__)

# Serialises writes across the FastAPI threadpool and the scheduler threads.
_WRITE_LOCK = threading.RLock()

# Tests point the whole process at a temporary database through set_db_path().
_db_path_override: Path | None = None
_PATH_LOCK = threading.RLock()

BUSY_TIMEOUT_MS = 5000

# Columns added after the first release (contract section 14.3). schema.sql
# carries them inline for a fresh database, and init_db() adds them to a
# database that predates them. Adding a column never rewrites existing rows,
# so the data already stored survives untouched.
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("articles", "image_url", "TEXT"),
    ("articles", "image_source_url", "TEXT"),
    ("articles", "image_checked_at", "TEXT"),
)


def get_db_path() -> Path:
    """Return the active database file path."""
    with _PATH_LOCK:
        if _db_path_override is not None:
            return _db_path_override
    return get_settings().db_path


def set_db_path(path: str | Path | None) -> None:
    """Override the database file path for the whole process.

    Passing None restores the configured path. Intended for tests and for the
    command line ingestion entry point.
    """
    global _db_path_override
    with _PATH_LOCK:
        _db_path_override = Path(path).expanduser().resolve() if path is not None else None


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open a configured connection. The caller owns closing it."""
    db_file = Path(path) if path is not None else get_db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_file),
        check_same_thread=False,
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level="DEFERRED",
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


@contextmanager
def get_conn(write: bool = False) -> Iterator[sqlite3.Connection]:
    """Connection per request or per repository call.

    Reads run concurrently. Writes take the process write lock, commit on a
    clean exit and roll back on any exception.
    """
    if write:
        _WRITE_LOCK.acquire()
    conn = connect()
    try:
        yield conn
        if write:
            conn.commit()
    except BaseException:
        if write:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        raise
    finally:
        try:
            conn.close()
        finally:
            if write:
                _WRITE_LOCK.release()


def read_schema_sql() -> str:
    """Return the DDL text shipped in app/schema.sql."""
    return SCHEMA_FILE.read_text(encoding="utf-8")


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Column names of a table, or an empty list when it does not exist."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return []
    return [str(row[1]) for row in rows]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Add any missing column from MIGRATIONS. Returns what was added.

    Idempotent by construction: PRAGMA table_info is read first and an ALTER
    is issued only for a column that is genuinely absent, so a second run does
    nothing and never raises. The caller commits.
    """
    added: list[str] = []
    columns_by_table: dict[str, list[str]] = {}
    for table, column, column_type in MIGRATIONS:
        if table not in columns_by_table:
            columns_by_table[table] = table_columns(conn, table)
        existing = columns_by_table[table]
        if not existing or column in existing:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        existing.append(column)
        added.append(f"{table}.{column}")
    return added


def init_db(path: str | Path | None = None) -> Path:
    """Create every table, index and the FTS index if they do not exist.

    Runs the idempotent column migrations afterwards, so a database written by
    an earlier build gains the newer columns with its rows intact.

    Idempotent: safe to call on every process start. Returns the database path.
    """
    if path is not None:
        set_db_path(path)
    db_file = get_db_path()
    with _WRITE_LOCK:
        conn = connect(db_file)
        try:
            conn.executescript(read_schema_sql())
            added = migrate(conn)
            conn.commit()
        finally:
            conn.close()
    if added:
        logger.info("database migration added: %s", ", ".join(added))
    return db_file


def database_exists() -> bool:
    """True when the database file is present on disk."""
    return get_db_path().exists()


__all__ = [
    "BUSY_TIMEOUT_MS",
    "MIGRATIONS",
    "connect",
    "database_exists",
    "get_conn",
    "get_db_path",
    "init_db",
    "migrate",
    "read_schema_sql",
    "set_db_path",
    "table_columns",
]
