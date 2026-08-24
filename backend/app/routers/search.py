"""Search endpoints: full text search and trending symbols and topics.

Contract section 5:
  GET /api/search    q (min length 2), limit (default 30, max 50)
  GET /api/trending  most frequent symbols and topics over the last 48 hours

All data access goes through app.repo. There is no SQL in this module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app import repo
from app.models import ArticleCard, SearchResponse, TrendingResponse
from app.routers import DeviceId

router = APIRouter(prefix="/api", tags=["search"])

MIN_QUERY_LENGTH = 2


@router.get(
    "/search",
    summary="Search articles",
    response_description="Matching article cards, most relevant first.",
)
def search(
    device_id: DeviceId,
    q: Annotated[
        str,
        Query(
            min_length=MIN_QUERY_LENGTH,
            description="Search text. Shorter than two characters returns 422.",
        ),
    ],
    limit: Annotated[
        int,
        Query(ge=1, le=repo.MAX_SEARCH_LIMIT, description="Maximum results."),
    ] = repo.DEFAULT_SEARCH_LIMIT,
) -> SearchResponse:
    """Search headlines, summaries, why it matters, symbols and topics.

    The repository uses the FTS5 index and falls back to a LIKE scan when the
    query is not valid FTS syntax, so punctuation in the box never raises.
    Bookmark state for the calling device is resolved in one batched query.
    """
    rows = repo.search_articles(q, limit=limit, device_id=device_id)
    items = [ArticleCard.model_validate(row) for row in rows]
    return SearchResponse(query=q, items=items, count=len(items))


@router.get(
    "/trending",
    summary="Trending symbols and topics",
    response_description="Up to twelve symbols and twelve topics from the last 48 hours.",
)
def trending() -> TrendingResponse:
    """Return the most frequent symbols and topics inside the trending window."""
    data = repo.trending(
        window_hours=repo.TRENDING_WINDOW_HOURS, limit=repo.DEFAULT_TRENDING_LIMIT
    )
    return TrendingResponse.model_validate(data)


__all__ = ["MIN_QUERY_LENGTH", "router", "search", "trending"]
