"""The boot payload both apps read (CONTRACT_MOBILE_ADMIN.md section 6.2).

    GET /api/config    categories, market filters, default sort, maintenance

This is the one device-authenticated route that deliberately does not take the
maintenance gate. When maintenance mode is on every content route answers 503,
so if this route answered 503 too the apps would have no way to learn why and
would show a network error instead of the message an admin wrote.

The module also owns the feature flag vocabulary, because the flag keys and the
config payload are the same thing seen from two sides: app/routers/admin_flags.py
writes through the helpers here so the admin screens and the apps can never
disagree about what a key is called.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app import deps, repo
from app.models import (
    CATEGORIES,
    CATEGORY_LABELS,
    MARKET_FILTER_LABELS,
    MARKET_FILTERS,
    PublicConfigResponse,
)

router = APIRouter(prefix="/api", tags=["config"])

# Flag key vocabulary. The two maintenance rows come from app.deps because the
# gate reads them there, and reusing the constants is what keeps the writer and
# the reader on the same key.
FLAG_CATEGORY_PREFIX = "category:"
FLAG_MARKET_FILTER_PREFIX = "market_filter:"
FLAG_DEFAULT_SORT = "default_sort"
FLAG_MIN_MOBILE_VERSION = "min_mobile_version"
FLAG_MAINTENANCE_MODE = deps.FLAG_MAINTENANCE_MODE
FLAG_MAINTENANCE_MESSAGE = deps.FLAG_MAINTENANCE_MESSAGE

DEFAULT_SORT = "top"
SORT_MODES = ("top", "latest")

# 'all' is a UI-only pseudo-category (contract 1, section 4). It is not a
# switchable flag and it is not in this payload: the apps prepend it to the tab
# strip themselves, exactly as they do for /api/categories.
SWITCHABLE_CATEGORIES: tuple[str, ...] = tuple(
    entry["key"] for entry in CATEGORIES if entry["key"] != "all"
)
SWITCHABLE_MARKET_FILTERS: tuple[str, ...] = tuple(
    entry["key"] for entry in MARKET_FILTERS
)


def category_flag_key(key: str) -> str:
    """The feature_flags row name for one category."""
    return f"{FLAG_CATEGORY_PREFIX}{key}"


def market_filter_flag_key(key: str) -> str:
    """The feature_flags row name for one market quick filter."""
    return f"{FLAG_MARKET_FILTER_PREFIX}{key}"


def default_flag_rows() -> list[tuple[str, bool, str | None]]:
    """Every flag row a fresh database needs, as (key, enabled, value).

    Startup seeds these once. Seeding never touches a row that already exists,
    so a category an admin switched off stays off across restarts.
    """
    rows: list[tuple[str, bool, str | None]] = [
        (category_flag_key(key), True, None) for key in SWITCHABLE_CATEGORIES
    ]
    rows += [
        (market_filter_flag_key(key), True, None)
        for key in SWITCHABLE_MARKET_FILTERS
    ]
    rows += [
        (FLAG_DEFAULT_SORT, True, DEFAULT_SORT),
        (FLAG_MAINTENANCE_MODE, False, None),
        (FLAG_MAINTENANCE_MESSAGE, True, None),
        (FLAG_MIN_MOBILE_VERSION, True, None),
    ]
    return rows


def _enabled(flags: dict[str, dict[str, Any]], key: str, default: bool = True) -> bool:
    """Whether a switch is on, defaulting to on when the row is missing.

    A missing row means the flag has never been written, which happens on a
    database seeded before a key existed. Defaulting to on is the safe
    direction: a new category appears rather than silently vanishing.
    """
    row = flags.get(key)
    return bool(row["enabled"]) if row is not None else default


def _value(flags: dict[str, dict[str, Any]], key: str) -> str | None:
    """The text a flag carries, or None when the row is missing or blank."""
    row = flags.get(key)
    if row is None:
        return None
    text = (row.get("value") or "").strip()
    return text or None


def config_payload(flags: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build the /api/config body from the feature flag rows.

    Pass an already loaded flag map to avoid a second read, which is what the
    admin flags route does.
    """
    rows = repo.all_feature_flags() if flags is None else flags
    sort = (_value(rows, FLAG_DEFAULT_SORT) or DEFAULT_SORT).lower()
    if sort not in SORT_MODES:
        sort = DEFAULT_SORT
    maintenance = _enabled(rows, FLAG_MAINTENANCE_MODE, default=False)
    message = _value(rows, FLAG_MAINTENANCE_MESSAGE)
    return {
        "categories": [
            {
                "key": key,
                "label": CATEGORY_LABELS.get(key, key),
                "enabled": _enabled(rows, category_flag_key(key)),
            }
            for key in SWITCHABLE_CATEGORIES
        ],
        "market_filters": [
            {
                "key": key,
                "label": MARKET_FILTER_LABELS.get(key, key),
                "enabled": _enabled(rows, market_filter_flag_key(key)),
            }
            for key in SWITCHABLE_MARKET_FILTERS
        ],
        "default_sort": sort,
        "maintenance_mode": maintenance,
        "maintenance_message": (
            message or deps.DEFAULT_MAINTENANCE_MESSAGE if maintenance else message
        ),
        "min_mobile_version": _value(rows, FLAG_MIN_MOBILE_VERSION),
    }


@router.get(
    "/config",
    summary="App configuration and feature flags",
    response_description=(
        "Enabled categories and market filters, the default sort and the "
        "maintenance state."
    ),
)
def public_config(device: deps.CurrentDevice) -> PublicConfigResponse:
    """Return what the apps need before they can render anything.

    Answers even while maintenance mode is on, so both clients can show the
    message rather than a failure.
    """
    return PublicConfigResponse.model_validate(config_payload())


__all__ = [
    "DEFAULT_SORT",
    "FLAG_CATEGORY_PREFIX",
    "FLAG_DEFAULT_SORT",
    "FLAG_MAINTENANCE_MESSAGE",
    "FLAG_MAINTENANCE_MODE",
    "FLAG_MARKET_FILTER_PREFIX",
    "FLAG_MIN_MOBILE_VERSION",
    "SORT_MODES",
    "SWITCHABLE_CATEGORIES",
    "SWITCHABLE_MARKET_FILTERS",
    "category_flag_key",
    "config_payload",
    "default_flag_rows",
    "market_filter_flag_key",
    "public_config",
    "router",
]
