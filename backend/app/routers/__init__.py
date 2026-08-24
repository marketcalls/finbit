"""FinBit HTTP routers and the request dependencies they share.

The four router modules (feed, search, bookmarks, meta) implement contract
section 5. This package module holds only the shared dependencies, so the
import graph stays acyclic: routers import from here, never the other way
around, and main.py imports the router modules directly.

Device identity: the frontend generates a UUIDv4 once, keeps it in
localStorage under finbit.device_id and sends it as X-Device-Id on every
request. Article reads treat a missing header as anonymous. Bookmark writes
require it and answer 400 without it.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status

DEVICE_ID_HEADER = "X-Device-Id"
"""Name of the per-device identity header."""

MAX_DEVICE_ID_LENGTH = 128
"""Longest device id accepted. A UUIDv4 is 36 characters."""

MISSING_DEVICE_ID_DETAIL = "X-Device-Id header is required"
"""Body returned as {"detail": ...} when a bookmark write has no device id."""


def get_device_id(
    x_device_id: Annotated[
        Optional[str],
        Header(
            alias=DEVICE_ID_HEADER,
            description="Per-device identity, a UUIDv4 stored in localStorage. Optional.",
        ),
    ] = None,
) -> Optional[str]:
    """Return the calling device id, or None for an anonymous reader.

    Blank and whitespace-only values count as absent. Overlong values are
    truncated rather than rejected, so a misbehaving client cannot make a read
    endpoint fail.
    """
    if x_device_id is None:
        return None
    device = x_device_id.strip()
    if not device:
        return None
    return device[:MAX_DEVICE_ID_LENGTH]


DeviceId = Annotated[Optional[str], Depends(get_device_id)]
"""Optional device id, used by every article-bearing read endpoint."""


def require_device_id(device_id: DeviceId) -> str:
    """Return the calling device id, or raise 400 when the header is absent."""
    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MISSING_DEVICE_ID_DETAIL,
        )
    return device_id


RequiredDeviceId = Annotated[str, Depends(require_device_id)]
"""Mandatory device id, used by the bookmark write endpoints."""


__all__ = [
    "DEVICE_ID_HEADER",
    "DeviceId",
    "MAX_DEVICE_ID_LENGTH",
    "MISSING_DEVICE_ID_DETAIL",
    "RequiredDeviceId",
    "get_device_id",
    "require_device_id",
]
