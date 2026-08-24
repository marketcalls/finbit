"""Bookmark endpoints, scoped to the calling device.

Contract section 5:
  GET    /api/bookmarks               saved cards, newest saved first
  POST   /api/bookmarks               body {"article_id": 12}, idempotent
  DELETE /api/bookmarks/{article_id}  idempotent

Bookmarks are per device with no login. The writes require the X-Device-Id
header and answer 400 without it. The read treats a missing header as an
anonymous device, which by definition has nothing saved, so it returns an
empty list rather than an error.

All data access goes through app.repo. There is no SQL in this module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field

from app import repo
from app.models import ArticleCard, BookmarkRequest, BookmarkResponse
from app.routers import DeviceId, RequiredDeviceId

router = APIRouter(prefix="/api", tags=["bookmarks"])

ARTICLE_NOT_FOUND = "Article not found"


class BookmarkListResponse(BaseModel):
    """GET /api/bookmarks response body."""

    items: list[ArticleCard] = Field(default_factory=list)
    count: int = 0


@router.get(
    "/bookmarks",
    summary="List saved articles",
    response_description="Saved article cards for this device, newest saved first.",
)
def list_bookmarks(device_id: DeviceId) -> BookmarkListResponse:
    """Return every article this device has saved.

    Without an X-Device-Id header the caller is anonymous and the list is
    empty. Every item comes back with bookmarked set to true.
    """
    if not device_id:
        return BookmarkListResponse(items=[], count=0)
    rows = repo.list_bookmarks(device_id, limit=repo.DEFAULT_BOOKMARK_LIMIT)
    items = [ArticleCard.model_validate(row) for row in rows]
    return BookmarkListResponse(items=items, count=len(items))


@router.post(
    "/bookmarks",
    summary="Save an article",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "X-Device-Id header is required"},
        status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND},
    },
)
def add_bookmark(device_id: RequiredDeviceId, payload: BookmarkRequest) -> BookmarkResponse:
    """Save an article for this device. Calling it twice is not an error."""
    saved = repo.add_bookmark(device_id, payload.article_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ARTICLE_NOT_FOUND
        )
    return BookmarkResponse(article_id=payload.article_id, bookmarked=True)


@router.delete(
    "/bookmarks/{article_id}",
    summary="Remove a saved article",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "X-Device-Id header is required"},
    },
)
def remove_bookmark(
    device_id: RequiredDeviceId,
    article_id: Annotated[int, Path(ge=1, description="Article id to unsave.")],
) -> BookmarkResponse:
    """Remove a saved article. Idempotent, so removing twice still returns 200."""
    repo.remove_bookmark(device_id, article_id)
    return BookmarkResponse(article_id=article_id, bookmarked=False)


__all__ = [
    "ARTICLE_NOT_FOUND",
    "BookmarkListResponse",
    "add_bookmark",
    "list_bookmarks",
    "remove_bookmark",
    "router",
]
