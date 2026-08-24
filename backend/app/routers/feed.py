"""Feed endpoints: the paginated card feed and single article lookup.

Contract section 5:
  GET /api/feed            cursor paginated ArticleCard list
  GET /api/articles/{id}   one ArticleCard, 404 when the id is unknown

All data access goes through app.repo. There is no SQL in this module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app import repo
from app.models import ArticleCard, FeedResponse
from app.routers import DeviceId

router = APIRouter(prefix="/api", tags=["feed"])

ARTICLE_NOT_FOUND = "Article not found"

_CATEGORY_VALUES = "all, india, global, stocks, economy, rbi, sebi, earnings, commodities, crypto"


@router.get(
    "/feed",
    summary="Paginated news feed",
    response_description="One page of article cards plus the cursor for the next page.",
)
def get_feed(
    device_id: DeviceId,
    category: Annotated[
        str,
        Query(description=f"Category filter. One of: {_CATEGORY_VALUES}."),
    ] = "all",
    symbol: Annotated[
        str | None,
        Query(description="Market quick filter, for example NIFTY or RELIANCE."),
    ] = None,
    sort: Annotated[
        str,
        Query(description="Ordering: top (importance first) or latest (newest first)."),
    ] = "top",
    cursor: Annotated[
        str | None,
        Query(description="Opaque keyset cursor from the previous page. Ignored when unparsable."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=repo.MAX_FEED_LIMIT, description="Page size."),
    ] = repo.DEFAULT_FEED_LIMIT,
) -> FeedResponse:
    """Return one page of the feed.

    An unknown category, an unknown sort mode and an unparsable cursor are all
    treated as absent by the repository, so a stale client never gets a 500.
    The per-article bookmarked flag is resolved for the calling device in one
    batched query inside repo.list_feed.
    """
    page = repo.list_feed(
        category=category,
        symbol=symbol,
        sort=sort,
        cursor=cursor,
        limit=limit,
        device_id=device_id,
    )
    return FeedResponse.model_validate(page)


@router.get(
    "/articles/{article_id}",
    summary="One article card",
    responses={status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND}},
)
def get_article(
    device_id: DeviceId,
    article_id: Annotated[int, Path(ge=1, description="Article id.")],
) -> ArticleCard:
    """Return a single article, or 404 when the id does not exist."""
    article = repo.get_article(article_id, device_id=device_id)
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ARTICLE_NOT_FOUND
        )
    return ArticleCard.model_validate(article)


__all__ = ["ARTICLE_NOT_FOUND", "get_article", "get_feed", "router"]
