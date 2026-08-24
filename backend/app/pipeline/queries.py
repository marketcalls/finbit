"""The FinBit discovery query set (contract section 9).

Nine fixed queries cover Indian markets, corporate news, the regulators,
earnings, global markets, the Fed, commodities and geopolitics. The scheduler
runs INGEST_QUERIES_PER_CYCLE of them per cycle and rotates through the list,
so with the defaults (4 per cycle, one cycle every 15 minutes) all nine keys are
covered in roughly 35 minutes.

Every entry is a plain dict with the keys key, label, prompt and
category_hint. category_hint is one of the storable category keys from
app.models.CATEGORY_KEYS and is used only as a fallback when the model returns
a category outside the fixed vocabulary.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.models import CATEGORY_KEYS

QUERIES: list[dict[str, str]] = [
    {
        "key": "india_markets",
        "label": "India Markets",
        "prompt": "Indian stock market breaking news today NSE BSE Sensex Nifty",
        "category_hint": "india",
    },
    {
        "key": "corporate",
        "label": "Corporate",
        "prompt": "NSE BSE Indian corporate announcements board meetings deals",
        "category_hint": "stocks",
    },
    {
        "key": "rbi",
        "label": "RBI",
        "prompt": "RBI monetary policy repo rate liquidity banking regulation India",
        "category_hint": "rbi",
    },
    {
        "key": "sebi",
        "label": "SEBI",
        "prompt": "SEBI regulation enforcement IPO approval market rules India",
        "category_hint": "sebi",
    },
    {
        "key": "earnings",
        "label": "Earnings",
        "prompt": "Indian company quarterly results earnings today profit revenue",
        "category_hint": "earnings",
    },
    {
        "key": "global",
        "label": "Global",
        "prompt": "global markets news US Europe Asia equities today",
        "category_hint": "global",
    },
    {
        "key": "fed",
        "label": "Fed",
        "prompt": "US Federal Reserve interest rates inflation data",
        "category_hint": "economy",
    },
    {
        "key": "commodities",
        "label": "Commodities",
        "prompt": "crude oil gold silver commodity prices today",
        "category_hint": "commodities",
    },
    {
        "key": "geopolitics",
        "label": "Geopolitics",
        "prompt": "geopolitical events affecting global markets today",
        "category_hint": "global",
    },
]

QUERY_KEYS: tuple[str, ...] = tuple(q["key"] for q in QUERIES)

_BY_KEY: dict[str, dict[str, str]] = {q["key"]: q for q in QUERIES}

# Guard against a typo in the table above ever reaching the database.
assert all(q["category_hint"] in CATEGORY_KEYS for q in QUERIES), (
    "every query category_hint must be a storable category key"
)


def query_keys() -> tuple[str, ...]:
    """All nine query keys, in rotation order."""
    return QUERY_KEYS


def get_query(key: str) -> dict[str, str] | None:
    """One query definition by key, or None when the key is unknown."""
    if not key:
        return None
    return _BY_KEY.get(str(key).strip().lower())


def resolve_queries(keys: Iterable[str] | None) -> list[dict[str, str]]:
    """Turn a list of keys into query definitions, dropping unknown keys.

    Passing None or an empty iterable returns the whole set, in rotation order.
    Duplicates collapse and the caller's order is preserved.
    """
    if keys is None:
        return list(QUERIES)
    resolved: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in keys:
        query = get_query(str(raw))
        if query is None or query["key"] in seen:
            continue
        seen.add(query["key"])
        resolved.append(query)
    return resolved or list(QUERIES)


def rotate_keys(cycle: int, count: int) -> list[str]:
    """The next `count` query keys for cycle number `cycle`, wrapping around.

    Cycle 0 with count 4 yields the first four keys, cycle 1 the next four,
    cycle 2 the last key plus the first three, and so on. `count` is clamped to
    the size of the query set so a key is never repeated inside one cycle.
    """
    total = len(QUERY_KEYS)
    size = max(1, min(int(count), total))
    start = (int(cycle) * size) % total
    return [QUERY_KEYS[(start + offset) % total] for offset in range(size)]


def select_queries(cycle: int, count: int) -> list[dict[str, str]]:
    """The query definitions for one scheduler cycle."""
    return [_BY_KEY[key] for key in rotate_keys(cycle, count)]


__all__ = [
    "QUERIES",
    "QUERY_KEYS",
    "get_query",
    "query_keys",
    "resolve_queries",
    "rotate_keys",
    "select_queries",
]
