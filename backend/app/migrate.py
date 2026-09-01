"""Idempotent schema migrations for an existing populated database.

schema.sql can only carry statements that are safe to replay, and ALTER TABLE
has no IF NOT EXISTS form. So the moderation columns added to articles in phase
2 live here instead: PRAGMA table_info(articles) is read first and an ALTER is
issued only for a column that is genuinely absent.

The visibility index is created here too rather than in schema.sql, because it
covers hidden and pinned and would fail on a database where those columns have
not been added yet.

Safe to call on every startup and against a database full of phase 1 rows.
Adding a column never rewrites existing rows, so nothing already stored moves.
"""

from __future__ import annotations

import logging
import sqlite3

from app.db import get_conn, table_columns

logger = logging.getLogger(__name__)

# (column, DDL type with its default). A NOT NULL column can only be added when
# it carries a default, which is why hidden and pinned have one.
ARTICLE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("pinned", "INTEGER NOT NULL DEFAULT 0"),
    ("moderated_at", "TEXT"),
    ("moderated_by", "TEXT"),
)

INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_articles_visible "
    "ON articles(hidden, pinned DESC, importance_score DESC)",
)


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply every missing phase 2 change. Returns what was applied.

    The caller commits, matching the convention of app.db.migrate. Returns an
    empty list when the database is already current, which is the normal case
    on every start after the first.
    """
    applied: list[str] = []
    existing = table_columns(conn, "articles")
    if not existing:
        # A database with no articles table has not been created yet. init_db()
        # runs schema.sql before this, so this only happens if the caller is
        # holding a connection to something else entirely.
        logger.warning("articles table is missing, skipping the phase 2 migration")
        return applied

    for column, ddl in ARTICLE_COLUMNS:
        if column in existing:
            continue
        conn.execute(f"ALTER TABLE articles ADD COLUMN {column} {ddl}")
        existing.append(column)
        applied.append(f"articles.{column}")

    for statement in INDEX_STATEMENTS:
        conn.execute(statement)

    return applied


def migrate_database() -> list[str]:
    """Run the migration on its own write connection and commit.

    This is the entry point for application startup and for the admin CLI. It
    logs what changed, once, at info level.
    """
    with get_conn(write=True) as conn:
        applied = run_migrations(conn)
    if applied:
        logger.info("phase 2 migration added: %s", ", ".join(applied))
    return applied


__all__ = [
    "ARTICLE_COLUMNS",
    "INDEX_STATEMENTS",
    "migrate_database",
    "run_migrations",
]
