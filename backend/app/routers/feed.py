"""Feed endpoints: the paginated card feed and single article lookup.

Contract section 5:
  GET /api/feed            cursor paginated ArticleCard list
  GET /api/articles/{id}   one ArticleCard, 404 when the id is unknown

Phase 2 adds two things and changes nothing else. Both routes now require an
authenticated device (CONTRACT_MOBILE_ADMIN.md section 6), so the device id
behind the bookmarked flag is one the server issued rather than a header the
caller picked, and both sit behind the maintenance gate. The response bodies
are byte for byte what phase 1 returned.

All data access goes through app.repo. There is no SQL in this module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app import deps, repo
from app.models import ArticleCard, FeedResponse

router = APIRouter(prefix="/api", tags=["feed"], dependencies=[deps.MaintenanceGate])

ARTICLE_NOT_FOUND = "Article not found"

_CATEGORY_VALUES = "all, india, global, stocks, economy, rbi, sebi, earnings, commodities, crypto"


@router.get(
    "/feed",
    summary="Paginated news feed",
    response_description="One page of article cards plus the cursor for the next page.",
)
def get_feed(
    device: deps.CurrentDevice,
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
    The per-article bookmarked flag is resolved for the authenticated device in
    one batched query inside repo.list_feed. Hidden articles are filtered out
    there and pinned ones lead the page.
    """
    page = repo.list_feed(
        category=category,
        symbol=symbol,
        sort=sort,
        cursor=cursor,
        limit=limit,
        device_id=device.id,
    )
    return FeedResponse.model_validate(page)


@router.get(
    "/articles/{article_id}",
    summary="One article card",
    responses={status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND}},
)
def get_article(
    device: deps.CurrentDevice,
    article_id: Annotated[int, Path(ge=1, description="Article id.")],
) -> ArticleCard:
    """Return a single article, or 404 when the id does not exist.

    An article an admin has hidden reads as missing here too, so moderating a
    story also closes the deep link to it.
    """
    article = repo.get_article(article_id, device_id=device.id)
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ARTICLE_NOT_FOUND
        )
    return ArticleCard.model_validate(article)


__all__ = ["ARTICLE_NOT_FOUND", "get_article", "get_feed", "router"]
