"""Deterministic importance score (contract section 8).

The score is computed in Python and never taken from the model:

    base          = impact weight: high 40, medium 25, low 12
    + sources     = min(distinct_source_domains, 6) * 3
    + credibility = best publisher tier: tier1 12, tier2 8, tier3 4
    + breaking    = 12 when is_breaking
    + index_rel   = 10 when NIFTY, BANKNIFTY or SENSEX is tagged
    + category    = rbi 8, sebi 6, earnings 6, economy 5, stocks 4, else 0
    - decay       = age_hours * 1.5, capped at 30

The result is clamped to 0 to 100 and rounded to an int. It is recomputed on
every merge and by the periodic rescore pass, which is what makes the feed
decay over time.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from app.pipeline.dedupe import symbol_set
from app.repo import distinct_source_domains, parse_iso

IMPACT_WEIGHTS: dict[str, int] = {"high": 40, "medium": 25, "low": 12}

SOURCE_POINTS_EACH = 3
MAX_COUNTED_SOURCES = 6

TIER_POINTS: dict[int, int] = {1: 12, 2: 8, 3: 4}

BREAKING_POINTS = 12
INDEX_POINTS = 10

CATEGORY_POINTS: dict[str, int] = {
    "rbi": 8,
    "sebi": 6,
    "earnings": 6,
    "economy": 5,
    "stocks": 4,
}

DECAY_PER_HOUR = 1.5
MAX_DECAY = 30.0

INDEX_SYMBOLS: frozenset[str] = frozenset({"NIFTY", "BANKNIFTY", "SENSEX"})

TIER1_HOSTS: tuple[str, ...] = (
    "reuters",
    "bloomberg",
    "rbi.org.in",
    "sebi.gov.in",
    "nseindia",
    "bseindia",
    "ft.com",
    "wsj.com",
)

TIER2_HOSTS: tuple[str, ...] = (
    "economictimes",
    "moneycontrol",
    "business-standard",
    "livemint",
    "mint",
    "cnbctv18",
    "thehindubusinessline",
    "financialexpress",
    "cnbc",
    "ndtvprofit",
)

DEFAULT_TIER = 3


def publisher_tier(url: Any) -> int:
    """Credibility tier of one source, 1 being the most credible.

    Accepts a full URL, a bare hostname or a publisher name. Anything that is
    not a known tier 1 or tier 2 host is tier 3.
    """
    text = str(url or "").strip().lower()
    if not text:
        return DEFAULT_TIER
    try:
        host = urlsplit(text).hostname or ""
    except ValueError:
        host = ""
    haystack = host or text
    for fragment in TIER1_HOSTS:
        if fragment in haystack:
            return 1
    for fragment in TIER2_HOSTS:
        if fragment in haystack:
            return 2
    return DEFAULT_TIER


def best_publisher_tier(sources: Iterable[Any] | None) -> int | None:
    """The best (lowest) tier across a source list, or None when there is none."""
    best: int | None = None
    for item in sources or ():
        if isinstance(item, Mapping):
            url = item.get("url") or item.get("publisher")
        else:
            url = item
        if not url:
            continue
        tier = publisher_tier(url)
        if best is None or tier < best:
            best = tier
        if best == 1:
            break
    return best


def credibility_points(sources: Iterable[Any] | None) -> int:
    """Credibility contribution. A story with no sources gets nothing."""
    tier = best_publisher_tier(sources)
    if tier is None:
        return 0
    return TIER_POINTS.get(tier, TIER_POINTS[DEFAULT_TIER])


def age_hours(published_at: Any, now: datetime | str | None = None) -> float:
    """Hours between publication and `now`, never negative.

    An unparsable published_at is treated as brand new, so a bad timestamp can
    never bury a story.
    """
    moment = _as_datetime(now)
    published = parse_iso(published_at if isinstance(published_at, str) else None)
    if published is None and isinstance(published_at, datetime):
        published = (
            published_at
            if published_at.tzinfo
            else published_at.replace(tzinfo=timezone.utc)
        ).astimezone(timezone.utc)
    if published is None:
        return 0.0
    delta = (moment - published).total_seconds() / 3600.0
    return max(0.0, delta)


def decay_points(published_at: Any, now: datetime | str | None = None) -> float:
    """Age penalty, 1.5 points per hour, capped at 30."""
    return min(MAX_DECAY, age_hours(published_at, now) * DECAY_PER_HOUR)


def round_half_up(value: float) -> int:
    """Round to the nearest int, with .5 always going up.

    Python's built in round() rounds a tie to the nearest even number, which
    would make two categories five points apart differ by six after rounding.
    Half-up keeps every documented weight exact.
    """
    return int(math.floor(float(value) + 0.5))


def _as_datetime(now: datetime | str | None) -> datetime:
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if isinstance(now, str):
        parsed = parse_iso(now)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc)


def _impact_points(article: Mapping[str, Any]) -> int:
    impact = str(article.get("impact") or "low").strip().lower()
    return IMPACT_WEIGHTS.get(impact, IMPACT_WEIGHTS["low"])


def _category_points(article: Mapping[str, Any]) -> int:
    category = str(article.get("category") or "").strip().lower()
    return CATEGORY_POINTS.get(category, 0)


def _index_points(article: Mapping[str, Any]) -> int:
    return INDEX_POINTS if symbol_set(article) & INDEX_SYMBOLS else 0


def breakdown(
    article: Mapping[str, Any], now: datetime | str | None = None
) -> dict[str, float]:
    """Every component of the score, for debugging and for the CLI."""
    sources = article.get("sources") or []
    counted = min(distinct_source_domains(sources), MAX_COUNTED_SOURCES)
    parts: dict[str, float] = {
        "base": float(_impact_points(article)),
        "sources": float(counted * SOURCE_POINTS_EACH),
        "credibility": float(credibility_points(sources)),
        "breaking": float(BREAKING_POINTS if article.get("is_breaking") else 0),
        "index_rel": float(_index_points(article)),
        "category": float(_category_points(article)),
        "decay": -float(decay_points(article.get("published_at"), now)),
    }
    parts["total"] = float(max(0, min(100, round_half_up(sum(parts.values())))))
    return parts


def compute_importance(
    article: Mapping[str, Any], now: datetime | str | None = None
) -> int:
    """Importance score for one article dict, 0 to 100.

    Pure: it reads only the dict and the supplied clock, and touches no
    database. `article` needs impact, category, is_breaking, published_at,
    symbols and sources. Missing keys simply contribute nothing.
    """
    if not article:
        return 0
    sources = article.get("sources") or []
    counted = min(distinct_source_domains(sources), MAX_COUNTED_SOURCES)
    total = (
        _impact_points(article)
        + counted * SOURCE_POINTS_EACH
        + credibility_points(sources)
        + (BREAKING_POINTS if article.get("is_breaking") else 0)
        + _index_points(article)
        + _category_points(article)
        - decay_points(article.get("published_at"), now)
    )
    return max(0, min(100, round_half_up(total)))


__all__ = [
    "BREAKING_POINTS",
    "CATEGORY_POINTS",
    "DECAY_PER_HOUR",
    "DEFAULT_TIER",
    "IMPACT_WEIGHTS",
    "INDEX_POINTS",
    "INDEX_SYMBOLS",
    "MAX_COUNTED_SOURCES",
    "MAX_DECAY",
    "SOURCE_POINTS_EACH",
    "TIER1_HOSTS",
    "TIER2_HOSTS",
    "TIER_POINTS",
    "age_hours",
    "best_publisher_tier",
    "breakdown",
    "compute_importance",
    "credibility_points",
    "decay_points",
    "publisher_tier",
    "round_half_up",
]
