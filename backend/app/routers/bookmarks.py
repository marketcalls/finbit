"""Bookmark endpoints, scoped to the calling device.

Contract section 5:
  GET    /api/bookmarks               saved cards, newest saved first
  POST   /api/bookmarks               body {"article_id": 12}, idempotent
  DELETE /api/bookmarks/{article_id}  idempotent

Bookmarks are per device with no login. Phase 2 changes where that device id
comes from, and this is a real security fix rather than a refactor. In phase 1
the id was whatever the caller put in X-Device-Id, so anyone could read or
change another device's bookmarks by guessing one. Now every route here takes
the id from the authenticated device (CONTRACT_MOBILE_ADMIN.md section 4), which
the server issued and the caller proves possession of on every request. A device
can therefore only ever touch its own saved articles.

The response bodies are exactly what phase 1 returned.

All data access goes through app.repo. There is no SQL in this module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field

from app import deps, repo
from app.models import ArticleCard, BookmarkRequest, BookmarkResponse

router = APIRouter(
    prefix="/api", tags=["bookmarks"], dependencies=[deps.MaintenanceGate]
)

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
def list_bookmarks(device: deps.CurrentDevice) -> BookmarkListResponse:
    """Return every article the authenticated device has saved.

    Every item comes back with bookmarked set to true. An article an admin has
    hidden drops out of the list while the bookmark row stays, so unhiding the
    story brings it back where the reader left it.
    """
    rows = repo.list_bookmarks(device.id, limit=repo.DEFAULT_BOOKMARK_LIMIT)
    items = [ArticleCard.model_validate(row) for row in rows]
    return BookmarkListResponse(items=items, count=len(items))


@router.post(
    "/bookmarks",
    summary="Save an article",
    responses={status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND}},
)
def add_bookmark(
    device: deps.CurrentDevice, payload: BookmarkRequest
) -> BookmarkResponse:
    """Save an article for this device. Calling it twice is not an error."""
    saved = repo.add_bookmark(device.id, payload.article_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ARTICLE_NOT_FOUND
        )
    return BookmarkResponse(article_id=payload.article_id, bookmarked=True)


@router.delete(
    "/bookmarks/{article_id}",
    summary="Remove a saved article",
)
def remove_bookmark(
    device: deps.CurrentDevice,
    article_id: Annotated[int, Path(ge=1, description="Article id to unsave.")],
) -> BookmarkResponse:
    """Remove a saved article. Idempotent, so removing twice still returns 200."""
    repo.remove_bookmark(device.id, article_id)
    return BookmarkResponse(article_id=article_id, bookmarked=False)


__all__ = [
    "ARTICLE_NOT_FOUND",
    "BookmarkListResponse",
    "add_bookmark",
    "list_bookmarks",
    "remove_bookmark",
    "router",
]
