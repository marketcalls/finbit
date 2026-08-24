"""SQLite connection handling and schema bootstrap.

One connection per request or per repository call. FastAPI runs sync route
handlers in a threadpool, so connections are created with
check_same_thread=False and every write is serialised behind a process-wide
lock. SQLite itself is in WAL mode, so readers never block the writer.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import SCHEMA_FILE, get_settings

# Serialises writes across the FastAPI threadpool and the scheduler threads.
_WRITE_LOCK = threading.RLock()

# Tests point the whole process at a temporary database through set_db_path().
_db_path_override: Path | None = None
_PATH_LOCK = threading.RLock()

BUSY_TIMEOUT_MS = 5000


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


def init_db(path: str | Path | None = None) -> Path:
    """Create every table, index and the FTS index if they do not exist.

    Idempotent: safe to call on every process start. Returns the database path.
    """
    if path is not None:
        set_db_path(path)
    db_file = get_db_path()
    with _WRITE_LOCK:
        conn = connect(db_file)
        try:
            conn.executescript(read_schema_sql())
            conn.commit()
        finally:
            conn.close()
    return db_file


def database_exists() -> bool:
    """True when the database file is present on disk."""
    return get_db_path().exists()


__all__ = [
    "BUSY_TIMEOUT_MS",
    "connect",
    "database_exists",
    "get_conn",
    "get_db_path",
    "init_db",
    "read_schema_sql",
    "set_db_path",
]
