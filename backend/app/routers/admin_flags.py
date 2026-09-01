"""Admin feature flags (CONTRACT_MOBILE_ADMIN.md section 6.6).

    GET /api/admin/flags    the /api/config shape with updated_at per key
    PUT /api/admin/flags    switch categories and market filters, set the sort,
                            turn maintenance mode on and off

The flag vocabulary lives in app/routers/config_public.py, which is what the
apps read. Writing through the helpers there is what stops this screen and the
apps disagreeing about what a key is called.

Maintenance mode is the one flag with teeth: app.deps.maintenance_gate reads
the same two rows this route writes, so turning it on takes every content route
to 503 on the next request while /api/config keeps answering.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from app import deps, repo
from app.models import (
    AdminFlagsResponse,
    AdminFlagsUpdate,
    CATEGORY_LABELS,
    MARKET_FILTER_LABELS,
)
from app.routers.config_public import (
    FLAG_DEFAULT_SORT,
    FLAG_MAINTENANCE_MESSAGE,
    FLAG_MAINTENANCE_MODE,
    FLAG_MIN_MOBILE_VERSION,
    SWITCHABLE_CATEGORIES,
    SWITCHABLE_MARKET_FILTERS,
    category_flag_key,
    config_payload,
    market_filter_flag_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/flags", tags=["admin flags"])

ACTION_FLAGS = "flags.update"

MAX_MESSAGE_LENGTH = 400
MAX_VERSION_LENGTH = 32


def _flag_states(
    flags: dict[str, dict[str, Any]],
    keys: tuple[str, ...],
    labels: dict[str, str],
    key_for: Any,
) -> list[dict[str, Any]]:
    """Turn one family of flags into the FlagState list the screen renders."""
    states: list[dict[str, Any]] = []
    for key in keys:
        row = flags.get(key_for(key)) or {}
        states.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "enabled": bool(row.get("enabled", True)),
                "updated_at": row.get("updated_at"),
            }
        )
    return states


def flags_payload() -> dict[str, Any]:
    """The GET /api/admin/flags body: the config shape plus per key stamps."""
    flags = repo.all_feature_flags()
    config = config_payload(flags)
    latest = [
        row.get("updated_at") for row in flags.values() if row.get("updated_at")
    ]
    return {
        "categories": _flag_states(
            flags, SWITCHABLE_CATEGORIES, CATEGORY_LABELS, category_flag_key
        ),
        "market_filters": _flag_states(
            flags,
            SWITCHABLE_MARKET_FILTERS,
            MARKET_FILTER_LABELS,
            market_filter_flag_key,
        ),
        "default_sort": config["default_sort"],
        "maintenance_mode": config["maintenance_mode"],
        "maintenance_message": config["maintenance_message"],
        "min_mobile_version": config["min_mobile_version"],
        "updated_at": max(latest) if latest else None,
    }


@router.get(
    "",
    summary="Feature flags with their last change",
    response_description="Categories, market filters, sort and maintenance state.",
)
def get_flags(admin: deps.CurrentAdmin) -> AdminFlagsResponse:
    """Return every switch the apps read, with when each was last changed."""
    return AdminFlagsResponse.model_validate(flags_payload())


@router.put(
    "",
    summary="Update feature flags",
    response_description="The flags as they now stand.",
)
def put_flags(
    request: Request, admin: deps.CurrentAdmin, payload: AdminFlagsUpdate
) -> AdminFlagsResponse:
    """Write the flags that are present in the body and leave the rest alone.

    An absent field means no opinion, not false, so a screen that only toggles
    maintenance mode cannot switch every category off by omission. Unknown
    category and market filter keys are ignored rather than stored, so a stale
    client cannot create a flag row nothing reads.
    """
    actor = admin.username
    changed: dict[str, Any] = {}

    for key, enabled in (payload.categories or {}).items():
        if key in SWITCHABLE_CATEGORIES:
            repo.set_feature_flag(category_flag_key(key), enabled=bool(enabled), actor=actor)
            changed[category_flag_key(key)] = bool(enabled)

    for key, enabled in (payload.market_filters or {}).items():
        if key in SWITCHABLE_MARKET_FILTERS:
            repo.set_feature_flag(
                market_filter_flag_key(key), enabled=bool(enabled), actor=actor
            )
            changed[market_filter_flag_key(key)] = bool(enabled)

    if payload.default_sort is not None:
        repo.set_feature_flag(FLAG_DEFAULT_SORT, value=payload.default_sort, actor=actor)
        changed[FLAG_DEFAULT_SORT] = payload.default_sort

    if payload.maintenance_mode is not None:
        repo.set_feature_flag(
            FLAG_MAINTENANCE_MODE, enabled=bool(payload.maintenance_mode), actor=actor
        )
        changed[FLAG_MAINTENANCE_MODE] = bool(payload.maintenance_mode)
        if payload.maintenance_mode:
            logger.warning("maintenance mode was switched on by %s", actor)

    if payload.maintenance_message is not None:
        repo.set_feature_flag(
            FLAG_MAINTENANCE_MESSAGE,
            value=payload.maintenance_message.strip()[:MAX_MESSAGE_LENGTH],
            actor=actor,
        )
        changed[FLAG_MAINTENANCE_MESSAGE] = True

    if payload.min_mobile_version is not None:
        repo.set_feature_flag(
            FLAG_MIN_MOBILE_VERSION,
            value=payload.min_mobile_version.strip()[:MAX_VERSION_LENGTH],
            actor=actor,
        )
        changed[FLAG_MIN_MOBILE_VERSION] = payload.min_mobile_version.strip()

    if changed:
        repo.write_audit(
            actor,
            ACTION_FLAGS,
            target="feature_flags",
            detail=changed,
            ip=deps.client_ip(request),
        )
    return AdminFlagsResponse.model_validate(flags_payload())


__all__ = [
    "ACTION_FLAGS",
    "MAX_MESSAGE_LENGTH",
    "MAX_VERSION_LENGTH",
    "flags_payload",
    "get_flags",
    "put_flags",
    "router",
]
