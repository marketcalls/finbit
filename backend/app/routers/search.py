"""Search endpoints: full text search and trending symbols and topics.

Contract section 5:
  GET /api/search    q (min length 2), limit (default 30, max 50)
  GET /api/trending  most frequent symbols and topics over the last 48 hours

Phase 2 puts both behind an authenticated device and the maintenance gate
(CONTRACT_MOBILE_ADMIN.md section 6). The response bodies are unchanged.

All data access goes through app.repo. There is no SQL in this module.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app import deps, repo
from app.models import ArticleCard, SearchResponse, TrendingResponse

router = APIRouter(prefix="/api", tags=["search"], dependencies=[deps.MaintenanceGate])

MIN_QUERY_LENGTH = 2


@router.get(
    "/search",
    summary="Search articles",
    response_description="Matching article cards, most relevant first.",
)
def search(
    device: deps.CurrentDevice,
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
    Bookmark state for the authenticated device is resolved in one batched
    query, and hidden articles never appear in the results.
    """
    rows = repo.search_articles(q, limit=limit, device_id=device.id)
    items = [ArticleCard.model_validate(row) for row in rows]
    return SearchResponse(query=q, items=items, count=len(items))


@router.get(
    "/trending",
    summary="Trending symbols and topics",
    response_description="Up to twelve symbols and twelve topics from the last 48 hours.",
)
def trending(device: deps.CurrentDevice) -> TrendingResponse:
    """Return the most frequent symbols and topics inside the trending window.

    Hidden articles do not count towards a chip, so tapping one always leads
    somewhere.
    """
    data = repo.trending(
        window_hours=repo.TRENDING_WINDOW_HOURS, limit=repo.DEFAULT_TRENDING_LIMIT
    )
    return TrendingResponse.model_validate(data)


__all__ = ["MIN_QUERY_LENGTH", "router", "search", "trending"]
