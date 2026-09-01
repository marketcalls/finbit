"""Every database read and write for FinBit.

Routers and the ingestion pipeline never write SQL of their own, they call the
functions here. Anything that returns article data returns a fully hydrated
dict shaped like models.ArticleCard, with symbols, topics, sources and
impact_map filled in through batched IN queries, never N+1 lookups.

This module also owns keeping the contentless articles_fts index in sync and
the opaque feed cursor format.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from app.db import get_conn, get_db_path, table_columns
from app.models import (
    CATEGORIES,
    CATEGORY_KEYS,
    IMPACT_DIRECTIONS,
    IMPACT_ENTRY_DIRECTIONS,
    IMPACTS,
    MARKET_FILTERS,
    SENTIMENTS,
    SYMBOL_KINDS,
)

# SQLite allows many bound variables, but chunking keeps IN queries well inside
# every supported limit.
_MAX_VARIABLES = 400

DEFAULT_FEED_LIMIT = 20
MAX_FEED_LIMIT = 50
DEFAULT_SEARCH_LIMIT = 30
MAX_SEARCH_LIMIT = 50
DEFAULT_TRENDING_LIMIT = 12
TRENDING_WINDOW_HOURS = 48
DEFAULT_DEDUPE_WINDOW_HOURS = 48
DEFAULT_RESCORE_WINDOW_HOURS = 72
DEFAULT_RESCORE_LIMIT = 500
DEFAULT_BOOKMARK_LIMIT = 100
DEFAULT_RUNS_LIMIT = 20
DEFAULT_IMAGE_BACKFILL_LIMIT = 50

_SORT_MODES = ("top", "latest")
_FEED_CATEGORY_KEYS = tuple(c["key"] for c in CATEGORIES)

_ARTICLE_COLUMNS = """
    a.id, a.story_cluster_id, a.headline, a.summary, a.why_it_matters,
    a.category, a.sentiment, a.impact, a.impact_direction, a.importance_score,
    a.is_breaking, a.source_count, a.published_at, a.created_at, a.updated_at,
    a.dedupe_key, a.image_url, a.image_source_url, a.image_checked_at
"""

_SCALAR_COLUMNS = (
    "story_cluster_id",
    "headline",
    "summary",
    "why_it_matters",
    "category",
    "sentiment",
    "impact",
    "impact_direction",
    "importance_score",
    "is_breaking",
    "source_count",
    "published_at",
    "dedupe_key",
    "image_url",
    "image_source_url",
    "image_checked_at",
)

# Card image columns (contract section 14.3). image_url reaches the API
# through ArticleCard, the other two are internal to the pipeline.
_IMAGE_COLUMNS = ("image_url", "image_source_url", "image_checked_at")

_FTS_COLUMNS = ("headline", "summary", "why_it_matters", "symbols_text", "topics_text")

_SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
_WORD_RE = re.compile(r"[A-Za-z0-9&]+")

# ---------------------------------------------------------------------------
# Moderation visibility (contract 2, sections 4 and 6)
#
# articles.hidden and articles.pinned are added by app/migrate.py, not by
# schema.sql, because ALTER TABLE has no IF NOT EXISTS form. A database that
# has not been migrated yet therefore has neither column, and a query naming
# them would fail with "no such column" rather than simply returning rows.
#
# Every public read below asks _moderation_ready() first and falls back to the
# phase 1 SQL when the columns are absent, so the reads keep working against an
# older database and against any caller that creates a schema without running
# the migration. Only a positive answer is cached: once the columns exist they
# never go away, while a negative answer must be rechecked because the very
# next thing that happens may be the migration adding them.
# ---------------------------------------------------------------------------

_MODERATION_READY: set[str] = set()

_MODERATION_COLUMNS = ("hidden", "pinned", "moderated_at", "moderated_by")

_ADMIN_ARTICLE_COLUMNS = (
    _ARTICLE_COLUMNS + ", a.hidden, a.pinned, a.moderated_at, a.moderated_by"
)

_ADMIN_SORT_MODES = ("top", "latest", "oldest")

# The feed rank for sort=top, folding the pin flag into the score so one
# integer orders pinned articles first. importance_score is clamped to 0..100
# on every write, so the 1000 step can never be reached by a score alone.
_PIN_RANK_STEP = 1000
_FEED_RANK_TOP = f"(a.pinned * {_PIN_RANK_STEP} + a.importance_score)"

DEFAULT_ADMIN_ARTICLE_LIMIT = 50
MAX_ADMIN_ARTICLE_LIMIT = 200
DEFAULT_AUDIT_LIMIT = 50
MAX_AUDIT_DETAIL_LENGTH = 2000


def _moderation_ready(conn: sqlite3.Connection) -> bool:
    """True when articles carries the phase 2 moderation columns."""
    path = str(get_db_path())
    if path in _MODERATION_READY:
        return True
    columns = set(table_columns(conn, "articles"))
    ready = all(name in columns for name in _MODERATION_COLUMNS)
    if ready:
        _MODERATION_READY.add(path)
    return ready


def _visible_clause(conn: sqlite3.Connection, alias: str = "a") -> str:
    """The hidden filter for a public read, or an empty string before migration.

    Pass an empty alias for a query with no table alias.
    """
    if not _moderation_ready(conn):
        return ""
    return f"{alias}.hidden = 0" if alias else "hidden = 0"


def reset_moderation_cache() -> None:
    """Forget which databases are known to be migrated. For tests only."""
    _MODERATION_READY.clear()


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def utcnow_iso() -> str:
    """Current UTC time as ISO 8601 with a trailing Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_hours_ago(hours: float) -> str:
    """UTC timestamp `hours` in the past, ISO 8601 with a trailing Z."""
    moment = datetime.now(timezone.utc) - timedelta(hours=max(0.0, float(hours)))
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp, returning None when it is unusable."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso_z(value: Any) -> str:
    """Coerce a datetime or a loose timestamp string to ISO 8601 UTC with Z."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parsed = parse_iso(value if isinstance(value, str) else None)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    return utcnow_iso()


# ---------------------------------------------------------------------------
# Cursor helpers. These never raise on bad input.
# ---------------------------------------------------------------------------


def encode_cursor(primary: Any, published_at: str, article_id: int) -> str:
    """Encode the keyset cursor '<primary>|<published_at>|<id>' as base64."""
    raw = f"{primary}|{published_at}|{int(article_id)}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[str, str, int] | None:
    """Decode a feed cursor. Any malformed value decodes to None, never raises."""
    if not cursor or not isinstance(cursor, str):
        return None
    text = cursor.strip()
    if not text:
        return None
    try:
        padded = text + "=" * (-len(text) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, UnicodeEncodeError, ValueError):
        return None
    parts = raw.split("|")
    if len(parts) != 3:
        return None
    primary, published_at, id_text = (part.strip() for part in parts)
    if not published_at:
        return None
    try:
        article_id = int(id_text)
    except (TypeError, ValueError):
        return None
    if article_id <= 0:
        return None
    return primary, published_at, article_id


# ---------------------------------------------------------------------------
# Normalizers used by the write path
# ---------------------------------------------------------------------------


def _chunked(values: Sequence[Any], size: int = _MAX_VARIABLES) -> Iterator[list[Any]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _domain(url: str) -> str:
    """Lowercase hostname of a URL without the www prefix, or an empty string."""
    try:
        host = urlsplit(str(url)).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _one_of(value: Any, allowed: Sequence[str], fallback: str) -> str:
    text = _text(value).lower()
    return text if text in allowed else fallback


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = _text(value).lower()
    return text in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbols(symbols: Iterable[Any] | None) -> list[dict[str, str]]:
    """Accept dicts or bare strings and return clean symbol tag dicts."""
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in symbols or []:
        if isinstance(item, str):
            symbol, exchange, kind = item, "NSE", "stock"
        elif isinstance(item, dict):
            symbol = _text(item.get("symbol"))
            exchange = _text(item.get("exchange"), "NSE")
            kind = _one_of(item.get("kind"), SYMBOL_KINDS, "stock")
        else:
            continue
        symbol = _text(symbol).upper()
        if not symbol or not _SYMBOL_RE.match(symbol) or symbol in seen:
            continue
        seen.add(symbol)
        result.append(
            {"symbol": symbol, "exchange": _text(exchange, "NSE").upper(), "kind": kind}
        )
    return result


def normalize_topics(topics: Iterable[Any] | None) -> list[str]:
    """Trim topic names, drop blanks and case-insensitive duplicates."""
    result: list[str] = []
    seen: set[str] = set()
    for item in topics or []:
        name = _text(item)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name[:80])
    return result


def normalize_sources(sources: Iterable[Any] | None) -> list[dict[str, str | None]]:
    """Keep sources that carry a URL, deriving the publisher from the host."""
    result: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for item in sources or []:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        url = _text(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        publisher = _text(item.get("publisher")) or _domain(url) or "Unknown"
        result.append(
            {
                "publisher": publisher,
                "title": _optional_text(item.get("title")),
                "url": url,
                "published_at": _optional_text(item.get("published_at")),
            }
        )
    return result


def normalize_impact_map(entries: Iterable[Any] | None) -> list[dict[str, str]]:
    """Clean the market impact map, one direction per named market."""
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "name": name[:60],
                "direction": _one_of(
                    item.get("direction"), IMPACT_ENTRY_DIRECTIONS, "neutral"
                ),
            }
        )
    return result


def distinct_source_domains(sources: Iterable[Any] | None) -> int:
    """Number of distinct publisher hostnames behind a story."""
    domains = {
        _domain(s.get("url", "")) if isinstance(s, dict) else _domain(str(s))
        for s in sources or []
    }
    domains.discard("")
    return len(domains)


# ---------------------------------------------------------------------------
# FTS5 sync. articles_fts is contentless, so a row is removed with the
# 'delete' command carrying the exact values that were indexed.
# ---------------------------------------------------------------------------


def _fts_values(conn: sqlite3.Connection, article_id: int) -> dict[str, str] | None:
    """Build the FTS payload for an article from what is currently stored."""
    row = conn.execute(
        "SELECT headline, summary, why_it_matters FROM articles WHERE id = ?",
        (article_id,),
    ).fetchone()
    if row is None:
        return None
    symbols = [
        r["symbol"]
        for r in conn.execute(
            "SELECT symbol FROM article_symbols WHERE article_id = ? ORDER BY symbol",
            (article_id,),
        )
    ]
    topics = [
        r["name"]
        for r in conn.execute(
            "SELECT t.name FROM article_topics at "
            "JOIN topics t ON t.id = at.topic_id "
            "WHERE at.article_id = ? ORDER BY t.name",
            (article_id,),
        )
    ]
    return {
        "headline": row["headline"] or "",
        "summary": row["summary"] or "",
        "why_it_matters": row["why_it_matters"] or "",
        "symbols_text": " ".join(symbols),
        "topics_text": " ".join(topics),
    }


def _fts_insert(conn: sqlite3.Connection, article_id: int, values: dict[str, str]) -> None:
    conn.execute(
        "INSERT INTO articles_fts(rowid, headline, summary, why_it_matters, "
        "symbols_text, topics_text) VALUES (?, ?, ?, ?, ?, ?)",
        (article_id, *(values[c] for c in _FTS_COLUMNS)),
    )


def _fts_delete(conn: sqlite3.Connection, article_id: int, values: dict[str, str]) -> None:
    try:
        conn.execute(
            "INSERT INTO articles_fts(articles_fts, rowid, headline, summary, "
            "why_it_matters, symbols_text, topics_text) "
            "VALUES ('delete', ?, ?, ?, ?, ?, ?)",
            (article_id, *(values[c] for c in _FTS_COLUMNS)),
        )
    except sqlite3.Error:
        # A stale index entry only costs a duplicate hit, which the search
        # query groups away. Never fail a write because of the search index.
        pass


# ---------------------------------------------------------------------------
# Child table writes
# ---------------------------------------------------------------------------


def _write_symbols(
    conn: sqlite3.Connection, article_id: int, symbols: Iterable[Any] | None
) -> None:
    conn.execute("DELETE FROM article_symbols WHERE article_id = ?", (article_id,))
    rows = [
        (article_id, s["symbol"], s["exchange"], s["kind"])
        for s in normalize_symbols(symbols)
    ]
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO article_symbols(article_id, symbol, exchange, kind) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )


def _write_topics(
    conn: sqlite3.Connection, article_id: int, topics: Iterable[Any] | None
) -> None:
    conn.execute("DELETE FROM article_topics WHERE article_id = ?", (article_id,))
    for name in normalize_topics(topics):
        conn.execute("INSERT OR IGNORE INTO topics(name) VALUES (?)", (name,))
        row = conn.execute("SELECT id FROM topics WHERE name = ?", (name,)).fetchone()
        if row is None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO article_topics(article_id, topic_id) VALUES (?, ?)",
            (article_id, int(row["id"])),
        )


def _write_sources(
    conn: sqlite3.Connection, article_id: int, sources: Iterable[Any] | None
) -> None:
    conn.execute("DELETE FROM sources WHERE article_id = ?", (article_id,))
    rows = [
        (article_id, s["publisher"], s["title"], s["url"], s["published_at"])
        for s in normalize_sources(sources)
    ]
    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO sources(article_id, publisher, title, url, published_at) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )


def _write_impacts(
    conn: sqlite3.Connection, article_id: int, impact_map: Iterable[Any] | None
) -> None:
    conn.execute("DELETE FROM article_impacts WHERE article_id = ?", (article_id,))
    rows = [(article_id, e["name"], e["direction"]) for e in normalize_impact_map(impact_map)]
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO article_impacts(article_id, name, direction) "
            "VALUES (?, ?, ?)",
            rows,
        )


# ---------------------------------------------------------------------------
# Hydration
# ---------------------------------------------------------------------------


def _base_card(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    card: dict[str, Any] = {
        "id": int(row["id"]),
        "story_cluster_id": row["story_cluster_id"],
        "headline": row["headline"],
        "summary": row["summary"],
        "why_it_matters": row["why_it_matters"],
        "category": row["category"],
        "sentiment": row["sentiment"],
        "impact": row["impact"],
        "impact_direction": row["impact_direction"],
        "importance_score": int(row["importance_score"] or 0),
        "is_breaking": bool(row["is_breaking"]),
        "source_count": int(row["source_count"] or 0),
        "published_at": row["published_at"],
        "created_at": row["created_at"],
        "image_url": row["image_url"] if "image_url" in keys else None,
        "bookmarked": False,
        "symbols": [],
        "topics": [],
        "sources": [],
        "impact_map": [],
    }
    if "updated_at" in keys:
        card["updated_at"] = row["updated_at"]
    if "dedupe_key" in keys:
        card["dedupe_key"] = row["dedupe_key"]
    # Internal only, like updated_at and dedupe_key above: ArticleCard ignores
    # extra keys, so these never reach the API (contract section 14.4).
    if "image_source_url" in keys:
        card["image_source_url"] = row["image_source_url"]
    if "image_checked_at" in keys:
        card["image_checked_at"] = row["image_checked_at"]
    return card


def _hydrate(
    conn: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
    device_id: str | None = None,
    bookmarked: bool | None = None,
) -> list[dict[str, Any]]:
    """Attach symbols, topics, sources, impact map and bookmark state in batches."""
    cards = [_base_card(row) for row in rows]
    if not cards:
        return []
    by_id = {card["id"]: card for card in cards}
    ids = list(by_id)

    for chunk in _chunked(ids):
        marks = ",".join("?" for _ in chunk)
        for r in conn.execute(
            f"SELECT article_id, symbol, exchange, kind FROM article_symbols "
            f"WHERE article_id IN ({marks}) ORDER BY article_id, symbol",
            chunk,
        ):
            by_id[int(r["article_id"])]["symbols"].append(
                {"symbol": r["symbol"], "exchange": r["exchange"], "kind": r["kind"]}
            )
        for r in conn.execute(
            f"SELECT at.article_id AS article_id, t.name AS name FROM article_topics at "
            f"JOIN topics t ON t.id = at.topic_id "
            f"WHERE at.article_id IN ({marks}) ORDER BY at.article_id, t.name",
            chunk,
        ):
            by_id[int(r["article_id"])]["topics"].append(r["name"])
        for r in conn.execute(
            f"SELECT article_id, publisher, title, url, published_at FROM sources "
            f"WHERE article_id IN ({marks}) ORDER BY article_id, publisher, id",
            chunk,
        ):
            by_id[int(r["article_id"])]["sources"].append(
                {
                    "publisher": r["publisher"],
                    "title": r["title"],
                    "url": r["url"],
                    "published_at": r["published_at"],
                }
            )
        for r in conn.execute(
            f"SELECT article_id, name, direction FROM article_impacts "
            f"WHERE article_id IN ({marks}) ORDER BY article_id, name",
            chunk,
        ):
            by_id[int(r["article_id"])]["impact_map"].append(
                {"name": r["name"], "direction": r["direction"]}
            )

    if bookmarked is not None:
        for card in cards:
            card["bookmarked"] = bookmarked
    elif device_id:
        marked = _bookmarked_ids(conn, device_id, ids)
        for card in cards:
            card["bookmarked"] = card["id"] in marked
    return cards


def _bookmarked_ids(
    conn: sqlite3.Connection, device_id: str, article_ids: Sequence[int]
) -> set[int]:
    device = _text(device_id)
    if not device or not article_ids:
        return set()
    found: set[int] = set()
    for chunk in _chunked(list(article_ids)):
        marks = ",".join("?" for _ in chunk)
        found.update(
            int(r["article_id"])
            for r in conn.execute(
                f"SELECT article_id FROM bookmarks WHERE device_id = ? "
                f"AND article_id IN ({marks})",
                [device, *chunk],
            )
        )
    return found


# ---------------------------------------------------------------------------
# Article writes
# ---------------------------------------------------------------------------


def insert_article(article: dict[str, Any]) -> int:
    """Insert one article plus its children and index it for search.

    Required keys: story_cluster_id, headline, summary, category, published_at,
    dedupe_key. Enum-valued fields fall back to their schema defaults when the
    caller passes something outside the vocabulary, so the pipeline should
    normalize first. source_count defaults to the distinct source domain count.

    Raises sqlite3.IntegrityError when story_cluster_id already exists.
    """
    headline = _text(article.get("headline"))
    summary = _text(article.get("summary"))
    story_cluster_id = _text(article.get("story_cluster_id"))
    dedupe_key = _text(article.get("dedupe_key")) or story_cluster_id
    if not headline or not summary or not story_cluster_id:
        raise ValueError("insert_article needs headline, summary and story_cluster_id")

    sources = normalize_sources(article.get("sources"))
    now = utcnow_iso()
    values = (
        story_cluster_id,
        headline,
        summary,
        _optional_text(article.get("why_it_matters")),
        _one_of(article.get("category"), CATEGORY_KEYS, "india"),
        _one_of(article.get("sentiment"), SENTIMENTS, "neutral"),
        _one_of(article.get("impact"), IMPACTS, "low"),
        _one_of(article.get("impact_direction"), IMPACT_DIRECTIONS, "neutral"),
        max(0, min(100, _as_int(article.get("importance_score"), 0))),
        1 if _as_bool(article.get("is_breaking")) else 0,
        _as_int(article.get("source_count"), distinct_source_domains(sources)),
        to_iso_z(article.get("published_at")),
        to_iso_z(article.get("created_at") or now),
        now,
        dedupe_key,
        _optional_text(article.get("image_url")),
        _optional_text(article.get("image_source_url")),
        _optional_text(article.get("image_checked_at")),
    )

    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "INSERT INTO articles (story_cluster_id, headline, summary, why_it_matters, "
            "category, sentiment, impact, impact_direction, importance_score, is_breaking, "
            "source_count, published_at, created_at, updated_at, dedupe_key, "
            "image_url, image_source_url, image_checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        article_id = int(cursor.lastrowid or 0)
        _write_symbols(conn, article_id, article.get("symbols"))
        _write_topics(conn, article_id, article.get("topics"))
        _write_sources(conn, article_id, sources)
        _write_impacts(conn, article_id, article.get("impact_map"))
        fts = _fts_values(conn, article_id)
        if fts is not None:
            _fts_insert(conn, article_id, fts)
    return article_id


def update_article(article_id: int, changes: dict[str, Any]) -> bool:
    """Update an article in place and reindex it. Returns False when it is gone.

    Scalar columns are updated only when present in `changes`. The keys
    symbols, topics, sources and impact_map replace the stored child rows
    wholesale, so a merge must pass the already unioned lists.
    """
    article_id = int(article_id)
    with get_conn(write=True) as conn:
        old_fts = _fts_values(conn, article_id)
        if old_fts is None:
            return False

        assignments: list[str] = []
        params: list[Any] = []
        for column in _SCALAR_COLUMNS:
            if column not in changes:
                continue
            value = changes[column]
            if column == "why_it_matters":
                value = _optional_text(value)
            elif column == "category":
                value = _one_of(value, CATEGORY_KEYS, "india")
            elif column == "sentiment":
                value = _one_of(value, SENTIMENTS, "neutral")
            elif column == "impact":
                value = _one_of(value, IMPACTS, "low")
            elif column == "impact_direction":
                value = _one_of(value, IMPACT_DIRECTIONS, "neutral")
            elif column == "importance_score":
                value = max(0, min(100, _as_int(value, 0)))
            elif column == "is_breaking":
                value = 1 if _as_bool(value) else 0
            elif column == "source_count":
                value = max(0, _as_int(value, 0))
            elif column == "published_at":
                value = to_iso_z(value)
            elif column in _IMAGE_COLUMNS:
                value = _optional_text(value)
            else:
                value = _text(value)
            assignments.append(f"{column} = ?")
            params.append(value)

        assignments.append("updated_at = ?")
        params.append(utcnow_iso())
        params.append(article_id)
        conn.execute(
            f"UPDATE articles SET {', '.join(assignments)} WHERE id = ?", params
        )

        if "symbols" in changes:
            _write_symbols(conn, article_id, changes["symbols"])
        if "topics" in changes:
            _write_topics(conn, article_id, changes["topics"])
        if "sources" in changes:
            _write_sources(conn, article_id, changes["sources"])
        if "impact_map" in changes:
            _write_impacts(conn, article_id, changes["impact_map"])

        new_fts = _fts_values(conn, article_id)
        _fts_delete(conn, article_id, old_fts)
        if new_fts is not None:
            _fts_insert(conn, article_id, new_fts)
    return True


def set_importance_score(article_id: int, score: int) -> bool:
    """Store a recomputed importance score. Returns False when the id is gone."""
    clamped = max(0, min(100, _as_int(score, 0)))
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "UPDATE articles SET importance_score = ?, updated_at = ? WHERE id = ?",
            (clamped, utcnow_iso(), int(article_id)),
        )
        return cursor.rowcount > 0


def set_article_image(
    article_id: int,
    image_url: str | None = None,
    image_source_url: str | None = None,
    checked_at: str | None = None,
) -> bool:
    """Record the card image resolution for one article (contract 14.2).

    `checked_at` defaults to now, and it is always written, even when no image
    was found, because a non-null image_checked_at is what stops the resolver
    from refetching a miss on every later pass. Returns False when the id is
    gone.
    """
    stamp = _optional_text(checked_at) or utcnow_iso()
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "UPDATE articles SET image_url = ?, image_source_url = ?, "
            "image_checked_at = ?, updated_at = ? WHERE id = ?",
            (
                _optional_text(image_url),
                _optional_text(image_source_url),
                stamp,
                utcnow_iso(),
                int(article_id),
            ),
        )
        return cursor.rowcount > 0


def articles_needing_images(
    limit: int = DEFAULT_IMAGE_BACKFILL_LIMIT,
) -> list[dict[str, Any]]:
    """Hydrated articles that have never been checked for a card image.

    Only image_checked_at IS NULL qualifies, so a checked article with no
    image is never fetched again. Newest first, because that is what the feed
    shows.
    """
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_ARTICLE_COLUMNS} FROM articles a WHERE a.image_checked_at IS NULL "
            f"ORDER BY a.published_at DESC, a.id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return _hydrate(conn, rows)


def image_checked_keys(dedupe_keys: Iterable[str] | None) -> set[str]:
    """Which of these dedupe keys already belong to an image-checked article.

    The ingest pipeline uses this to skip resolution for a story that maps to
    a cluster which has already been looked at, hit or miss.
    """
    wanted = [key for key in {_text(k) for k in dedupe_keys or ()} if key]
    if not wanted:
        return set()
    found: set[str] = set()
    with get_conn() as conn:
        for chunk in _chunked(wanted):
            marks = ",".join("?" for _ in chunk)
            found.update(
                str(row["dedupe_key"])
                for row in conn.execute(
                    f"SELECT dedupe_key FROM articles WHERE dedupe_key IN ({marks}) "
                    f"AND image_checked_at IS NOT NULL",
                    chunk,
                )
            )
    return found


def delete_article(article_id: int) -> bool:
    """Remove an article, its children and its search index entry."""
    article_id = int(article_id)
    with get_conn(write=True) as conn:
        fts = _fts_values(conn, article_id)
        if fts is None:
            return False
        _fts_delete(conn, article_id, fts)
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    return True


# ---------------------------------------------------------------------------
# Article reads
# ---------------------------------------------------------------------------


def get_article(article_id: int, device_id: str | None = None) -> dict[str, Any] | None:
    """One hydrated article, or None when the id does not exist.

    A hidden article reads as missing here, so moderating a story also closes
    the deep link to it. The admin screens use admin_get_article, which sees
    everything.
    """
    with get_conn() as conn:
        visible = _visible_clause(conn)
        clause = f" AND {visible}" if visible else ""
        row = conn.execute(
            f"SELECT {_ARTICLE_COLUMNS} FROM articles a WHERE a.id = ?{clause}",
            (int(article_id),),
        ).fetchone()
        if row is None:
            return None
        return _hydrate(conn, [row], device_id)[0]


def get_article_by_cluster_id(
    story_cluster_id: str, device_id: str | None = None
) -> dict[str, Any] | None:
    """One hydrated article looked up by its story cluster id."""
    key = _text(story_cluster_id)
    if not key:
        return None
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {_ARTICLE_COLUMNS} FROM articles a WHERE a.story_cluster_id = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _hydrate(conn, [row], device_id)[0]


def get_article_by_dedupe_key(
    dedupe_key: str, device_id: str | None = None
) -> dict[str, Any] | None:
    """Newest hydrated article carrying this dedupe key, the exact-match merge path."""
    key = _text(dedupe_key)
    if not key:
        return None
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {_ARTICLE_COLUMNS} FROM articles a WHERE a.dedupe_key = ? "
            f"ORDER BY a.published_at DESC, a.id DESC LIMIT 1",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _hydrate(conn, [row], device_id)[0]


def find_dedupe_candidates(
    window_hours: int = DEFAULT_DEDUPE_WINDOW_HOURS,
    limit: int = 500,
    device_id: str | None = None,
) -> list[dict[str, Any]]:
    """Hydrated articles published inside the dedupe window, newest first.

    The pipeline scores a new story against these candidates. Every candidate
    carries symbols and sources, which the similarity score needs.
    """
    cutoff = iso_hours_ago(window_hours)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_ARTICLE_COLUMNS} FROM articles a WHERE a.published_at >= ? "
            f"ORDER BY a.published_at DESC, a.id DESC LIMIT ?",
            (cutoff, max(1, int(limit))),
        ).fetchall()
        return _hydrate(conn, rows, device_id)


def recent_articles_for_rescore(
    window_hours: int = DEFAULT_RESCORE_WINDOW_HOURS,
    limit: int = DEFAULT_RESCORE_LIMIT,
) -> list[dict[str, Any]]:
    """Hydrated articles the periodic rescore pass should recompute."""
    cutoff = iso_hours_ago(window_hours)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_ARTICLE_COLUMNS} FROM articles a WHERE a.published_at >= ? "
            f"ORDER BY a.published_at DESC, a.id DESC LIMIT ?",
            (cutoff, max(1, int(limit))),
        ).fetchall()
        return _hydrate(conn, rows)


def list_feed(
    category: str = "all",
    symbol: str | None = None,
    sort: str = "top",
    cursor: str | None = None,
    limit: int = DEFAULT_FEED_LIMIT,
    device_id: str | None = None,
) -> dict[str, Any]:
    """Cursor paginated feed. Returns {items, next_cursor, has_more}.

    sort='top' orders by importance_score DESC, published_at DESC, id DESC.
    sort='latest' orders by published_at DESC, id DESC.
    An unknown category, an unknown sort or an unparsable cursor is ignored
    rather than raising.

    Hidden articles never appear, and pinned ones sort ahead of the rest inside
    whichever mode was asked for. The cursor keeps its phase 1 shape, so the
    rank it carries folds the pin flag into one comparable value: pinned adds
    1000 to a score that can only reach 100, which orders exactly the same way
    as pinned DESC, importance_score DESC without needing a fourth cursor
    field. In latest mode the rank slot carries the pin flag on its own.
    """
    key = _text(category, "all").lower()
    if key not in _FEED_CATEGORY_KEYS:
        key = "all"
    mode = _text(sort, "top").lower()
    if mode not in _SORT_MODES:
        mode = "top"
    size = max(1, min(MAX_FEED_LIMIT, _as_int(limit, DEFAULT_FEED_LIMIT)))
    decoded = decode_cursor(cursor)

    with get_conn() as conn:
        moderated = _moderation_ready(conn)
        rank = _FEED_RANK_TOP if moderated else "a.importance_score"

        where: list[str] = []
        params: list[Any] = []
        if moderated:
            where.append("a.hidden = 0")
        if key != "all":
            where.append("a.category = ?")
            params.append(key)
        ticker = _text(symbol).upper()
        if ticker:
            where.append(
                "EXISTS (SELECT 1 FROM article_symbols s "
                "WHERE s.article_id = a.id AND s.symbol = ?)"
            )
            params.append(ticker)

        if decoded is not None:
            primary, published_at, last_id = decoded
            try:
                marker: int | None = int(primary)
            except (TypeError, ValueError):
                marker = None
            if mode == "top" and marker is not None:
                where.append(
                    f"({rank} < ? OR "
                    f"({rank} = ? AND a.published_at < ?) OR "
                    f"({rank} = ? AND a.published_at = ? AND a.id < ?))"
                )
                params.extend(
                    [marker, marker, published_at, marker, published_at, last_id]
                )
            elif mode == "latest" and moderated and marker is not None:
                # A phase 1 cursor carries the timestamp in this slot, so an
                # unparsable marker falls through to the plain comparison
                # below rather than dropping the page.
                where.append(
                    "(a.pinned < ? OR "
                    "(a.pinned = ? AND a.published_at < ?) OR "
                    "(a.pinned = ? AND a.published_at = ? AND a.id < ?))"
                )
                params.extend(
                    [marker, marker, published_at, marker, published_at, last_id]
                )
            elif mode == "latest":
                where.append("(a.published_at < ? OR (a.published_at = ? AND a.id < ?))")
                params.extend([published_at, published_at, last_id])

        pin_first = "a.pinned DESC, " if moderated else ""
        order = (
            f"{pin_first}a.importance_score DESC, a.published_at DESC, a.id DESC"
            if mode == "top"
            else f"{pin_first}a.published_at DESC, a.id DESC"
        )
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(size + 1)

        marker_column = rank if mode == "top" else ("a.pinned" if moderated else "0")
        rows = conn.execute(
            f"SELECT {_ARTICLE_COLUMNS}, {marker_column} AS feed_rank "
            f"FROM articles a {clause} ORDER BY {order} LIMIT ?",
            params,
        ).fetchall()
        has_more = len(rows) > size
        rows = rows[:size]
        items = _hydrate(conn, rows, device_id)

    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        if mode == "top" or moderated:
            primary_value: Any = int(rows[-1]["feed_rank"] or 0)
        else:
            primary_value = last["published_at"]
        next_cursor = encode_cursor(primary_value, last["published_at"], last["id"])
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


def search_articles(
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    device_id: str | None = None,
) -> list[dict[str, Any]]:
    """Full text search over headline, summary, why it matters, symbols and topics.

    Uses the FTS5 index and falls back to a LIKE scan when the index is empty
    or the query is not valid FTS syntax. Never raises on user input.

    Hidden articles are filtered out and pinned ones lead the results, so a
    moderation decision applies to search exactly as it does to the feed.
    """
    text = _text(query)
    size = max(1, min(MAX_SEARCH_LIMIT, _as_int(limit, DEFAULT_SEARCH_LIMIT)))
    if not text:
        return []

    terms = _WORD_RE.findall(text)
    with get_conn() as conn:
        visible = _visible_clause(conn)
        fts_filter = f" AND {visible}" if visible else ""
        like_filter = f"{visible} AND " if visible else ""
        pin_first = "a.pinned DESC, " if visible else ""
        rows: list[sqlite3.Row] = []
        if terms:
            match = " ".join(f'"{term}"*' for term in terms[:12])
            try:
                found = conn.execute(
                    f"SELECT {_ARTICLE_COLUMNS}, bm25(articles_fts) AS rank_score "
                    f"FROM articles_fts JOIN articles a ON a.id = articles_fts.rowid "
                    f"WHERE articles_fts MATCH ?{fts_filter} "
                    f"ORDER BY {pin_first}rank_score ASC, a.published_at DESC LIMIT ?",
                    (match, size * 2),
                ).fetchall()
            except sqlite3.Error:
                found = []
            # A stale index entry can repeat a rowid, so keep the first hit only.
            seen_ids: set[int] = set()
            for row in found:
                article_id = int(row["id"])
                if article_id in seen_ids:
                    continue
                seen_ids.add(article_id)
                rows.append(row)
                if len(rows) >= size:
                    break
        if not rows:
            pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = conn.execute(
                f"SELECT {_ARTICLE_COLUMNS} FROM articles a WHERE {like_filter}("
                f"a.headline LIKE ? ESCAPE '\\' OR a.summary LIKE ? ESCAPE '\\' "
                f"OR IFNULL(a.why_it_matters, '') LIKE ? ESCAPE '\\' "
                f"OR EXISTS (SELECT 1 FROM article_symbols s WHERE s.article_id = a.id "
                f"AND s.symbol LIKE ? ESCAPE '\\') "
                f"OR EXISTS (SELECT 1 FROM article_topics at JOIN topics t "
                f"ON t.id = at.topic_id WHERE at.article_id = a.id "
                f"AND t.name LIKE ? ESCAPE '\\')) "
                f"ORDER BY {pin_first}a.importance_score DESC, a.published_at DESC, "
                f"a.id DESC LIMIT ?",
                (pattern, pattern, pattern, pattern, pattern, size),
            ).fetchall()
        return _hydrate(conn, rows, device_id)


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------


def list_bookmarks(
    device_id: str, limit: int = DEFAULT_BOOKMARK_LIMIT
) -> list[dict[str, Any]]:
    """Hydrated bookmarked articles for one device, newest saved first.

    A hidden article drops out of the saved list too. The bookmark row stays,
    so unhiding the story brings it back where the reader left it.
    """
    device = _text(device_id)
    if not device:
        return []
    with get_conn() as conn:
        visible = _visible_clause(conn)
        clause = f" AND {visible}" if visible else ""
        pin_first = "a.pinned DESC, " if visible else ""
        rows = conn.execute(
            f"SELECT {_ARTICLE_COLUMNS} FROM bookmarks b "
            f"JOIN articles a ON a.id = b.article_id WHERE b.device_id = ?{clause} "
            f"ORDER BY {pin_first}b.created_at DESC, b.id DESC LIMIT ?",
            (device, max(1, int(limit))),
        ).fetchall()
        return _hydrate(conn, rows, device_id=device, bookmarked=True)


def add_bookmark(device_id: str, article_id: int) -> bool:
    """Save an article for a device. Idempotent.

    Returns False when the article does not exist, so the router can 404.
    """
    device = _text(device_id)
    if not device:
        return False
    with get_conn(write=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM articles WHERE id = ?", (int(article_id),)
        ).fetchone()
        if exists is None:
            return False
        conn.execute(
            "INSERT OR IGNORE INTO bookmarks(device_id, article_id, created_at) "
            "VALUES (?, ?, ?)",
            (device, int(article_id), utcnow_iso()),
        )
    return True


def remove_bookmark(device_id: str, article_id: int) -> bool:
    """Remove a saved article. Idempotent, True when a row was actually removed."""
    device = _text(device_id)
    if not device:
        return False
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "DELETE FROM bookmarks WHERE device_id = ? AND article_id = ?",
            (device, int(article_id)),
        )
        return cursor.rowcount > 0


def bookmarked_ids_for_device(
    device_id: str, article_ids: Sequence[int] | None = None
) -> set[int]:
    """Ids this device has bookmarked, optionally restricted to a candidate set."""
    device = _text(device_id)
    if not device:
        return set()
    with get_conn() as conn:
        if article_ids is None:
            return {
                int(r["article_id"])
                for r in conn.execute(
                    "SELECT article_id FROM bookmarks WHERE device_id = ?", (device,)
                )
            }
        return _bookmarked_ids(conn, device, list(article_ids))


# ---------------------------------------------------------------------------
# Metadata: categories, trending, health
# ---------------------------------------------------------------------------


def category_counts() -> list[dict[str, Any]]:
    """Every category in display order with its article count, 'all' first.

    Hidden articles are left out of the counts, so a tab never advertises
    stories the feed will not show.
    """
    with get_conn() as conn:
        visible = _visible_clause(conn, alias="")
        clause = f" WHERE {visible}" if visible else ""
        rows = conn.execute(
            f"SELECT category, COUNT(*) AS n FROM articles{clause} GROUP BY category"
        ).fetchall()
        total_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM articles{clause}"
        ).fetchone()
    counts = {r["category"]: int(r["n"]) for r in rows}
    total = int(total_row["n"]) if total_row else 0
    result: list[dict[str, Any]] = []
    for entry in CATEGORIES:
        key = entry["key"]
        result.append(
            {
                "key": key,
                "label": entry["label"],
                "count": total if key == "all" else counts.get(key, 0),
            }
        )
    return result


def market_filters() -> list[dict[str, str]]:
    """The market quick filter chips, key plus label."""
    return [dict(entry) for entry in MARKET_FILTERS]


def trending(
    window_hours: int = TRENDING_WINDOW_HOURS, limit: int = DEFAULT_TRENDING_LIMIT
) -> dict[str, list[str]]:
    """Most frequent symbols and topics inside the window. Returns {symbols, topics}.

    Hidden articles do not count, so a trending chip never leads to an empty
    result list.
    """
    cutoff = iso_hours_ago(window_hours)
    size = max(1, int(limit))
    with get_conn() as conn:
        visible = _visible_clause(conn)
        clause = f" AND {visible}" if visible else ""
        symbols = [
            r["symbol"]
            for r in conn.execute(
                f"SELECT s.symbol AS symbol, COUNT(*) AS n FROM article_symbols s "
                f"JOIN articles a ON a.id = s.article_id WHERE a.published_at >= ?"
                f"{clause} GROUP BY s.symbol ORDER BY n DESC, s.symbol ASC LIMIT ?",
                (cutoff, size),
            )
        ]
        topics = [
            r["name"]
            for r in conn.execute(
                f"SELECT t.name AS name, COUNT(*) AS n FROM article_topics at "
                f"JOIN topics t ON t.id = at.topic_id "
                f"JOIN articles a ON a.id = at.article_id WHERE a.published_at >= ?"
                f"{clause} GROUP BY t.name ORDER BY n DESC, t.name ASC LIMIT ?",
                (cutoff, size),
            )
        ]
    return {"symbols": symbols, "topics": topics}


def health_stats() -> dict[str, Any]:
    """Article count plus the most recent ingest run outcome.

    ingest_running is true while the newest run row is still open, which is
    what the cold start empty state polls on (contract 13.1).
    """
    with get_conn() as conn:
        total_row = conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()
        run = conn.execute(
            "SELECT started_at, finished_at, status FROM ingest_runs "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        "status": "ok",
        "articles": int(total_row["n"]) if total_row else 0,
        "last_ingest_at": (run["finished_at"] or run["started_at"]) if run else None,
        "last_ingest_status": run["status"] if run else None,
        "ingest_running": bool(run is not None and run["status"] == "running"),
    }


def last_ingest_finished_at() -> str | None:
    """When the most recent finished run ended, or None if none has finished.

    The startup ingest decision in contract 13.2 reads this so a uvicorn
    --reload restart does not spend money on every file save.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT finished_at FROM ingest_runs WHERE finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["finished_at"] if row is not None else None


def count_articles() -> int:
    """Total number of stored articles."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------------------
# Ingest runs
# ---------------------------------------------------------------------------


def _run_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "status": row["status"],
        "queries_run": int(row["queries_run"] or 0),
        "stories_seen": int(row["stories_seen"] or 0),
        "stories_new": int(row["stories_new"] or 0),
        "stories_merged": int(row["stories_merged"] or 0),
        "cost_usd": float(row["cost_usd"] or 0.0),
        "error": row["error"],
    }


def start_ingest_run(started_at: str | None = None) -> int:
    """Open a run row with status 'running' and return its id."""
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "INSERT INTO ingest_runs (started_at, status) VALUES (?, 'running')",
            (to_iso_z(started_at) if started_at else utcnow_iso(),),
        )
        return int(cursor.lastrowid or 0)


def finish_ingest_run(
    run_id: int,
    status: str = "ok",
    queries_run: int = 0,
    stories_seen: int = 0,
    stories_new: int = 0,
    stories_merged: int = 0,
    cost_usd: float = 0.0,
    error: str | None = None,
) -> bool:
    """Close a run row with its counts, real USD cost and optional error text."""
    final_status = _one_of(status, ("running", "ok", "error"), "ok")
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "UPDATE ingest_runs SET finished_at = ?, status = ?, queries_run = ?, "
            "stories_seen = ?, stories_new = ?, stories_merged = ?, cost_usd = ?, "
            "error = ? WHERE id = ?",
            (
                utcnow_iso(),
                final_status,
                max(0, _as_int(queries_run)),
                max(0, _as_int(stories_seen)),
                max(0, _as_int(stories_new)),
                max(0, _as_int(stories_merged)),
                max(0.0, _as_float(cost_usd)),
                _optional_text(error),
                int(run_id),
            ),
        )
        return cursor.rowcount > 0


def get_ingest_run(run_id: int) -> dict[str, Any] | None:
    """One ingest run row, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ingest_runs WHERE id = ?", (int(run_id),)
        ).fetchone()
    return _run_to_dict(row) if row is not None else None


def list_ingest_runs(limit: int = DEFAULT_RUNS_LIMIT) -> list[dict[str, Any]]:
    """The most recent ingest runs, newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ingest_runs ORDER BY id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [_run_to_dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Admin content moderation (contract 2, section 6.5)
#
# These are the only reads that see a hidden article. Everything above filters
# them out, so the split is deliberate: a route that wants the moderation view
# has to ask for it by name.
# ---------------------------------------------------------------------------


def _admin_columns(conn: sqlite3.Connection) -> str:
    """The select list for an admin read, with the moderation columns if present."""
    return _ADMIN_ARTICLE_COLUMNS if _moderation_ready(conn) else _ARTICLE_COLUMNS


def _attach_moderation(
    cards: list[dict[str, Any]], rows: Sequence[sqlite3.Row]
) -> list[dict[str, Any]]:
    """Copy hidden, pinned and the moderation stamps onto hydrated cards.

    A database that predates the migration has none of these columns, so the
    fields fall back to the same values a fresh row would carry and the admin
    screens still render.
    """
    by_id = {int(row["id"]): row for row in rows}
    for card in cards:
        row = by_id.get(card["id"])
        keys = row.keys() if row is not None else ()
        card["hidden"] = bool(row["hidden"]) if "hidden" in keys else False
        card["pinned"] = bool(row["pinned"]) if "pinned" in keys else False
        card["moderated_at"] = row["moderated_at"] if "moderated_at" in keys else None
        card["moderated_by"] = row["moderated_by"] if "moderated_by" in keys else None
        card.setdefault("dedupe_key", "")
    return cards


def admin_get_article(article_id: int) -> dict[str, Any] | None:
    """One hydrated article including hidden ones, with its moderation state."""
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {_admin_columns(conn)} FROM articles a WHERE a.id = ?",
            (int(article_id),),
        ).fetchone()
        if row is None:
            return None
        return _attach_moderation(_hydrate(conn, [row]), [row])[0]


def admin_list_articles(
    q: str | None = None,
    category: str | None = None,
    hidden: bool | None = None,
    pinned: bool | None = None,
    sort: str = "latest",
    cursor: str | None = None,
    limit: int = DEFAULT_ADMIN_ARTICLE_LIMIT,
) -> dict[str, Any]:
    """The moderation table: {items, next_cursor, has_more}.

    Every filter is optional and an unknown value is ignored rather than
    raising, the same rule the public feed follows. sort is top, latest or
    oldest, and the cursor is the same opaque keyset format the feed uses.
    """
    mode = _text(sort, "latest").lower()
    if mode not in _ADMIN_SORT_MODES:
        mode = "latest"
    size = max(1, min(MAX_ADMIN_ARTICLE_LIMIT, _as_int(limit, DEFAULT_ADMIN_ARTICLE_LIMIT)))
    decoded = decode_cursor(cursor)

    with get_conn() as conn:
        moderated = _moderation_ready(conn)
        where: list[str] = []
        params: list[Any] = []

        text = _text(q)
        if text:
            pattern = (
                "%"
                + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            where.append(
                "(a.headline LIKE ? ESCAPE '\\' OR a.summary LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern])

        key = _text(category).lower()
        if key and key in CATEGORY_KEYS:
            where.append("a.category = ?")
            params.append(key)

        if moderated and hidden is not None:
            where.append("a.hidden = ?")
            params.append(1 if hidden else 0)
        if moderated and pinned is not None:
            where.append("a.pinned = ?")
            params.append(1 if pinned else 0)

        if decoded is not None:
            primary, published_at, last_id = decoded
            if mode == "top":
                try:
                    marker = int(primary)
                except (TypeError, ValueError):
                    marker = None
                if marker is not None:
                    where.append(
                        "(a.importance_score < ? OR "
                        "(a.importance_score = ? AND a.published_at < ?) OR "
                        "(a.importance_score = ? AND a.published_at = ? AND a.id < ?))"
                    )
                    params.extend(
                        [marker, marker, published_at, marker, published_at, last_id]
                    )
            elif mode == "oldest":
                where.append("(a.published_at > ? OR (a.published_at = ? AND a.id > ?))")
                params.extend([published_at, published_at, last_id])
            else:
                where.append("(a.published_at < ? OR (a.published_at = ? AND a.id < ?))")
                params.extend([published_at, published_at, last_id])

        if mode == "top":
            order = "a.importance_score DESC, a.published_at DESC, a.id DESC"
        elif mode == "oldest":
            order = "a.published_at ASC, a.id ASC"
        else:
            order = "a.published_at DESC, a.id DESC"

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(size + 1)
        rows = conn.execute(
            f"SELECT {_admin_columns(conn)} FROM articles a {clause} "
            f"ORDER BY {order} LIMIT ?",
            params,
        ).fetchall()
        has_more = len(rows) > size
        rows = rows[:size]
        items = _attach_moderation(_hydrate(conn, rows), rows)

    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        primary_value = last["importance_score"] if mode == "top" else last["published_at"]
        next_cursor = encode_cursor(primary_value, last["published_at"], last["id"])
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


def mark_moderated(
    article_id: int,
    hidden: bool | None = None,
    pinned: bool | None = None,
    actor: str | None = None,
) -> bool:
    """Set the hidden and pinned flags and stamp who moderated the article.

    Passing neither flag still records the moderation stamp, which is what an
    edit to the headline or the summary needs. Returns False when the id is
    gone.
    """
    with get_conn(write=True) as conn:
        if not _moderation_ready(conn):
            return False
        assignments = ["moderated_at = ?", "moderated_by = ?", "updated_at = ?"]
        stamp = utcnow_iso()
        params: list[Any] = [stamp, _optional_text(actor), stamp]
        if hidden is not None:
            assignments.insert(0, "hidden = ?")
            params.insert(0, 1 if hidden else 0)
        if pinned is not None:
            assignments.insert(0, "pinned = ?")
            params.insert(0, 1 if pinned else 0)
        params.append(int(article_id))
        cursor = conn.execute(
            f"UPDATE articles SET {', '.join(assignments)} WHERE id = ?", params
        )
        return cursor.rowcount > 0


def article_siblings(
    article_id: int, story_cluster_id: str, dedupe_key: str
) -> list[dict[str, Any]]:
    """Other articles in the same cluster, newest first.

    A cluster is normally one row, because the pipeline merges rather than
    inserts. A sibling therefore means the deduplication let two rows through,
    which is exactly what the admin cluster view exists to show.
    """
    cluster = _text(story_cluster_id)
    key = _text(dedupe_key)
    if not cluster and not key:
        return []
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_admin_columns(conn)} FROM articles a "
            f"WHERE a.id != ? AND (a.story_cluster_id = ? OR a.dedupe_key = ?) "
            f"ORDER BY a.published_at DESC, a.id DESC LIMIT 20",
            (int(article_id), cluster, key),
        ).fetchall()
        return _attach_moderation(_hydrate(conn, rows), rows)


# ---------------------------------------------------------------------------
# Runtime settings (contract 2, section 5)
#
# The value column holds JSON text. Encoding and decoding belongs to
# app.pipeline.settings_bridge, which owns which keys are overridable at all.
# ---------------------------------------------------------------------------


def get_app_setting(key: str) -> str | None:
    """The raw stored text of one setting, or None when there is no override."""
    name = _text(key)
    if not name:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (name,)
        ).fetchone()
    return str(row["value"]) if row is not None else None


def all_app_settings() -> dict[str, str]:
    """Every stored override as raw text, keyed by setting name."""
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def set_app_setting(key: str, value: str, actor: str | None = None) -> None:
    """Write one override, recording who changed it and when."""
    name = _text(key)
    if not name:
        raise ValueError("an app setting needs a key")
    with get_conn(write=True) as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, updated_at = excluded.updated_at, "
            "updated_by = excluded.updated_by",
            (name, str(value), utcnow_iso(), _optional_text(actor)),
        )


def delete_app_setting(key: str) -> bool:
    """Drop one override so the .env value takes over again."""
    with get_conn(write=True) as conn:
        cursor = conn.execute("DELETE FROM app_settings WHERE key = ?", (_text(key),))
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Feature flags (contract 2, section 6.6)
#
# A switchable key uses the enabled column. A key that carries text, such as
# the maintenance message or the minimum mobile version, uses the value column
# and leaves enabled at its default. app.deps reads the maintenance rows with
# exactly this convention.
# ---------------------------------------------------------------------------


def all_feature_flags() -> dict[str, dict[str, Any]]:
    """Every flag row keyed by flag name."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, enabled, value, updated_at, updated_by FROM feature_flags"
        ).fetchall()
    return {
        str(row["key"]): {
            "key": str(row["key"]),
            "enabled": bool(row["enabled"]),
            "value": row["value"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }
        for row in rows
    }


def get_feature_flag(key: str) -> dict[str, Any] | None:
    """One flag row, or None when it has never been written."""
    return all_feature_flags().get(_text(key))


def set_feature_flag(
    key: str,
    enabled: bool | None = None,
    value: str | None = None,
    actor: str | None = None,
) -> None:
    """Write one flag. Passing only one of enabled or value leaves the other."""
    name = _text(key)
    if not name:
        raise ValueError("a feature flag needs a key")
    with get_conn(write=True) as conn:
        row = conn.execute(
            "SELECT enabled, value FROM feature_flags WHERE key = ?", (name,)
        ).fetchone()
        current_enabled = bool(row["enabled"]) if row is not None else True
        current_value = row["value"] if row is not None else None
        conn.execute(
            "INSERT INTO feature_flags (key, enabled, value, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
            "enabled = excluded.enabled, value = excluded.value, "
            "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (
                name,
                1 if (current_enabled if enabled is None else enabled) else 0,
                current_value if value is None else _optional_text(value),
                utcnow_iso(),
                _optional_text(actor),
            ),
        )


def seed_feature_flags(defaults: Iterable[tuple[str, bool, str | None]]) -> int:
    """Create any flag row that does not exist yet. Returns how many were added.

    Idempotent, so startup can call it every time. An existing row is never
    touched, which is what stops a restart from turning a category an admin
    switched off back on.
    """
    added = 0
    now = utcnow_iso()
    with get_conn(write=True) as conn:
        for key, enabled, value in defaults:
            name = _text(key)
            if not name:
                continue
            cursor = conn.execute(
                "INSERT OR IGNORE INTO feature_flags "
                "(key, enabled, value, updated_at, updated_by) VALUES (?, ?, ?, ?, ?)",
                (name, 1 if enabled else 0, _optional_text(value), now, None),
            )
            added += int(cursor.rowcount or 0)
    return added


# ---------------------------------------------------------------------------
# Audit log (contract 2, section 3.8)
# ---------------------------------------------------------------------------


def write_audit(
    actor: str,
    action: str,
    target: str | None = None,
    detail: Any = None,
    ip: str | None = None,
) -> int:
    """Record one admin mutation. Returns the audit row id, or 0 on failure.

    A dict detail is stored as JSON so a later reader gets structure rather
    than a repr. Never raises: an audit write that fails must not turn a
    successful mutation into a 500, it is logged by the caller instead.

    Callers must not pass a password, a token or a signature in detail. The
    admin routers pass field names and article ids only.
    """
    if isinstance(detail, (dict, list, tuple)):
        try:
            detail_text: str | None = json.dumps(detail, default=str)
        except (TypeError, ValueError):
            detail_text = None
    else:
        detail_text = _optional_text(detail)
    if detail_text and len(detail_text) > MAX_AUDIT_DETAIL_LENGTH:
        detail_text = detail_text[:MAX_AUDIT_DETAIL_LENGTH]
    try:
        with get_conn(write=True) as conn:
            cursor = conn.execute(
                "INSERT INTO audit_log (at, actor, action, target, detail, ip) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    utcnow_iso(),
                    _text(actor, "unknown"),
                    _text(action, "unknown"),
                    _optional_text(target),
                    detail_text,
                    _optional_text(ip),
                ),
            )
            return int(cursor.lastrowid or 0)
    except sqlite3.Error:
        return 0


def list_audit(limit: int = DEFAULT_AUDIT_LIMIT) -> list[dict[str, Any]]:
    """The most recent audit rows, newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, at, actor, action, target, detail, ip FROM audit_log "
            "ORDER BY id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "at": row["at"],
            "actor": row["actor"],
            "action": row["action"],
            "target": row["target"],
            "detail": row["detail"],
            "ip": row["ip"],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Admin accounts (CONTRACT_ADMIN_REGISTRATION.md sections 3.1 to 3.3)
# ---------------------------------------------------------------------------


def admin_account_count() -> int:
    """How many admin accounts exist. The whole of the registration gate."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()
    return int(row["n"] if row is not None else 0)


def registration_open() -> bool:
    """True only while admin_users is empty (section 3.1)."""
    return admin_account_count() == 0


def create_first_admin(
    username: str, password_hash: str, created_at: str | None = None
) -> bool:
    """Insert the one admin account, but only while there is none.

    Returns True when this call created it and False when it lost the race to
    another caller. False is not an error: the router answers it with the same
    404 any late caller gets, because by then the route genuinely is closed.

    Two different races are covered, and they need two different locks.
    get_conn(write=True) holds the process write lock, which is what stops two
    threads of one uvicorn worker from interleaving. BEGIN IMMEDIATE takes
    SQLite's write lock on the file before the count is read, which is what
    stops two separate processes on the same database from both seeing zero.
    Counting inside that transaction rather than before it is the point: a
    count read outside the write lock is a number that can already be stale by
    the time the insert runs.

    The UNIQUE constraint on username is caught as well, so a second account
    can never appear through this function even if the count were somehow
    wrong.
    """
    with get_conn(write=True) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT COUNT(*) AS n FROM admin_users").fetchone()
        if int(row["n"] if row is not None else 0):
            return False
        try:
            conn.execute(
                "INSERT INTO admin_users (username, password_hash, created_at, "
                "failed_count) VALUES (?, ?, ?, 0)",
                (username, password_hash, created_at or utcnow_iso()),
            )
        except sqlite3.IntegrityError:
            return False
    return True


def set_admin_password(username: str, password_hash: str) -> bool:
    """Replace an admin password hash and clear any lockout.

    Returns False when there is no such row. Takes an already hashed value, so
    a plaintext password never reaches this module at all.
    """
    with get_conn(write=True) as conn:
        cursor = conn.execute(
            "UPDATE admin_users SET password_hash = ?, failed_count = 0, "
            "locked_until = NULL WHERE username = ?",
            (password_hash, username),
        )
        return bool(cursor.rowcount)


__all__ = [
    "DEFAULT_ADMIN_ARTICLE_LIMIT",
    "DEFAULT_AUDIT_LIMIT",
    "DEFAULT_BOOKMARK_LIMIT",
    "DEFAULT_DEDUPE_WINDOW_HOURS",
    "DEFAULT_FEED_LIMIT",
    "DEFAULT_IMAGE_BACKFILL_LIMIT",
    "DEFAULT_RESCORE_LIMIT",
    "DEFAULT_RESCORE_WINDOW_HOURS",
    "DEFAULT_RUNS_LIMIT",
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_TRENDING_LIMIT",
    "MAX_ADMIN_ARTICLE_LIMIT",
    "MAX_FEED_LIMIT",
    "MAX_SEARCH_LIMIT",
    "TRENDING_WINDOW_HOURS",
    "add_bookmark",
    "admin_account_count",
    "admin_get_article",
    "admin_list_articles",
    "all_app_settings",
    "all_feature_flags",
    "article_siblings",
    "articles_needing_images",
    "bookmarked_ids_for_device",
    "category_counts",
    "create_first_admin",
    "delete_app_setting",
    "get_app_setting",
    "get_feature_flag",
    "list_audit",
    "mark_moderated",
    "registration_open",
    "reset_moderation_cache",
    "seed_feature_flags",
    "set_admin_password",
    "set_app_setting",
    "set_feature_flag",
    "write_audit",
    "count_articles",
    "decode_cursor",
    "delete_article",
    "distinct_source_domains",
    "encode_cursor",
    "find_dedupe_candidates",
    "finish_ingest_run",
    "get_article",
    "get_article_by_cluster_id",
    "get_article_by_dedupe_key",
    "get_ingest_run",
    "health_stats",
    "insert_article",
    "image_checked_keys",
    "iso_hours_ago",
    "last_ingest_finished_at",
    "list_bookmarks",
    "list_feed",
    "list_ingest_runs",
    "market_filters",
    "normalize_impact_map",
    "normalize_sources",
    "normalize_symbols",
    "normalize_topics",
    "parse_iso",
    "recent_articles_for_rescore",
    "remove_bookmark",
    "search_articles",
    "set_article_image",
    "set_importance_score",
    "start_ingest_run",
    "to_iso_z",
    "trending",
    "update_article",
    "utcnow_iso",
]
