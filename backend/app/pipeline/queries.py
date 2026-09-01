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

The nine below are the defaults, not the last word. An admin can edit the set
from the admin screens, which stores it in app_settings under query_set, and
every lookup here prefers that stored set when it exists. The hardcoded table
is what a fresh database runs on and what the pipeline falls back to when the
stored set cannot be read, so ingestion never ends up with no queries because
of one unreadable row.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.models import CATEGORY_KEYS

logger = logging.getLogger(__name__)

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


def active_queries() -> list[dict[str, str]]:
    """The query set actually in force, enabled entries only.

    Prefers the admin-edited set stored in app_settings and falls back to the
    hardcoded table above. settings_bridge is imported here rather than at
    module scope because it reads this module back for its own defaults, and a
    lazy import is what keeps that pair from becoming a cycle.

    Returns an empty list only when an admin has switched every query off,
    which is a deliberate state: a cycle then runs nothing instead of quietly
    spending money on nine queries nobody asked for.
    """
    try:
        from app.pipeline import settings_bridge

        return [
            {
                "key": entry["key"],
                "label": entry.get("label", entry["key"]),
                "prompt": entry.get("prompt", ""),
                "category_hint": entry.get("category_hint") or "",
            }
            for entry in settings_bridge.query_definitions()
            if entry.get("enabled", True)
        ]
    except Exception:  # noqa: BLE001 - an unreadable override falls back
        logger.warning(
            "the stored query set could not be read, using the built-in queries"
        )
        return list(QUERIES)


def query_keys() -> tuple[str, ...]:
    """The keys of every active query, in rotation order."""
    return tuple(query["key"] for query in active_queries())


def get_query(key: str) -> dict[str, str] | None:
    """One active query definition by key, or None when the key is unknown.

    A query an admin has switched off reads as unknown here, so naming it
    explicitly in an ingest trigger does not run it.
    """
    if not key:
        return None
    wanted = str(key).strip().lower()
    for query in active_queries():
        if query["key"] == wanted:
            return query
    return None


def resolve_queries(keys: Iterable[str] | None) -> list[dict[str, str]]:
    """Turn a list of keys into query definitions, dropping unknown keys.

    Passing None or an empty iterable returns the whole active set, in
    rotation order. Duplicates collapse and the caller's order is preserved.
    """
    active = active_queries()
    if keys is None:
        return active
    by_key = {query["key"]: query for query in active}
    resolved: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in keys:
        query = by_key.get(str(raw).strip().lower())
        if query is None or query["key"] in seen:
            continue
        seen.add(query["key"])
        resolved.append(query)
    return resolved or active


def rotate_keys(cycle: int, count: int) -> list[str]:
    """The next `count` query keys for cycle number `cycle`, wrapping around.

    Cycle 0 with count 4 yields the first four keys, cycle 1 the next four,
    cycle 2 the last key plus the first three, and so on. `count` is clamped to
    the size of the active query set so a key is never repeated inside one
    cycle.
    """
    keys = query_keys()
    total = len(keys)
    if not total:
        return []
    size = max(1, min(int(count), total))
    start = (int(cycle) * size) % total
    return [keys[(start + offset) % total] for offset in range(size)]


def select_queries(cycle: int, count: int) -> list[dict[str, str]]:
    """The query definitions for one scheduler cycle."""
    by_key = {query["key"]: query for query in active_queries()}
    return [by_key[key] for key in rotate_keys(cycle, count) if key in by_key]


__all__ = [
    "QUERIES",
    "QUERY_KEYS",
    "active_queries",
    "get_query",
    "query_keys",
    "resolve_queries",
    "rotate_keys",
    "select_queries",
]
