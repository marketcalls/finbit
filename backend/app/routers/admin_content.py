"""Admin content moderation (CONTRACT_MOBILE_ADMIN.md section 6.5).

    GET    /api/admin/articles                 the moderation table
    PATCH  /api/admin/articles/{id}            hide, pin or edit the copy
    DELETE /api/admin/articles/{id}            remove it and everything under it
    POST   /api/admin/articles/{id}/rescore    recompute one importance score
    POST   /api/admin/articles/{id}/refresh-image   resolve the card image again
    GET    /api/admin/articles/{id}/cluster    what the deduplication decided

These are the only article reads in the API that see a hidden article. Every
route depends on deps.CurrentAdmin and every mutation writes an audit_log row.

The scoring and image modules are imported inside the handlers, the same rule
app/routers/meta.py follows, so a pipeline that fails to import cannot stop the
API from starting.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response, status

from app import deps, repo
from app.models import (
    ADMIN_ARTICLE_SORTS,
    AdminArticle,
    AdminArticleList,
    AdminArticlePatch,
    ArticleClusterResponse,
    ArticleImageResponse,
    ArticleScoreResponse,
    CATEGORY_KEYS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/articles", tags=["admin content"])

ARTICLE_NOT_FOUND = "Article not found"
CODE_ARTICLE_NOT_FOUND = "article_not_found"
CODE_NOT_MIGRATED = "moderation_unavailable"

NOT_MIGRATED_DETAIL = (
    "The moderation columns are missing from this database. Start the API once, "
    "or run uv run python -m app.admin_cli list-admins, to apply the migration."
)

ACTION_UPDATE = "article.update"
ACTION_DELETE = "article.delete"
ACTION_RESCORE = "article.rescore"
ACTION_IMAGE = "article.image"

# The copy fields an admin may edit. Kept separate from the moderation flags
# because they take different paths into the repository: these go through
# update_article, which also reindexes the article for search.
EDITABLE_FIELDS = ("category", "headline", "summary", "why_it_matters")

_CATEGORY_VALUES = ", ".join(CATEGORY_KEYS)
_SORT_VALUES = ", ".join(ADMIN_ARTICLE_SORTS)


def _load(article_id: int) -> dict[str, Any]:
    """One article including hidden ones, or a 404 with the contract's code."""
    article = repo.admin_get_article(article_id)
    if article is None:
        raise deps.ApiError(
            status.HTTP_404_NOT_FOUND, CODE_ARTICLE_NOT_FOUND, ARTICLE_NOT_FOUND
        )
    return article


@router.get(
    "",
    summary="List articles for moderation",
    response_description="One page of articles with their moderation state.",
)
def list_articles(
    admin: deps.CurrentAdmin,
    q: Annotated[
        str | None, Query(description="Text to match in the headline or summary.")
    ] = None,
    category: Annotated[
        str | None, Query(description=f"Category filter. One of: {_CATEGORY_VALUES}.")
    ] = None,
    hidden: Annotated[
        bool | None, Query(description="Only hidden or only visible articles.")
    ] = None,
    pinned: Annotated[
        bool | None, Query(description="Only pinned or only unpinned articles.")
    ] = None,
    sort: Annotated[
        str, Query(description=f"Ordering. One of: {_SORT_VALUES}.")
    ] = "latest",
    cursor: Annotated[
        str | None, Query(description="Opaque keyset cursor. Ignored when unparsable.")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=repo.MAX_ADMIN_ARTICLE_LIMIT, description="Page size.")
    ] = repo.DEFAULT_ADMIN_ARTICLE_LIMIT,
) -> AdminArticleList:
    """Return the moderation table, hidden articles included.

    Unknown filter values are ignored rather than rejected, the same rule the
    public feed follows, so a stale admin screen never gets a 500.
    """
    page = repo.admin_list_articles(
        q=q,
        category=category,
        hidden=hidden,
        pinned=pinned,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )
    return AdminArticleList.model_validate(page)


@router.patch(
    "/{article_id}",
    summary="Hide, pin or edit one article",
    responses={status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND}},
)
def patch_article(
    request: Request,
    admin: deps.CurrentAdmin,
    article_id: Annotated[int, Path(ge=1, description="Article id.")],
    patch: AdminArticlePatch,
) -> AdminArticle:
    """Apply any subset of the moderation flags and the editable copy.

    An edit stamps moderated_at and moderated_by even when only the copy
    changed, so the table always shows who touched a story last.
    """
    _load(article_id)
    changes = patch.model_dump(exclude_unset=True)
    edits = {
        field: value
        for field, value in changes.items()
        if field in EDITABLE_FIELDS and value is not None
    }
    if edits:
        repo.update_article(article_id, edits)

    flags_changed = "hidden" in changes or "pinned" in changes
    if flags_changed or edits:
        stamped = repo.mark_moderated(
            article_id,
            hidden=changes.get("hidden"),
            pinned=changes.get("pinned"),
            actor=admin.username,
        )
        if not stamped and flags_changed:
            raise deps.ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                CODE_NOT_MIGRATED,
                NOT_MIGRATED_DETAIL,
            )
        repo.write_audit(
            admin.username,
            ACTION_UPDATE,
            target=str(article_id),
            detail={
                "fields": sorted(changes),
                "hidden": changes.get("hidden"),
                "pinned": changes.get("pinned"),
            },
            ip=deps.client_ip(request),
        )
    return AdminArticle.model_validate(_load(article_id))


@router.delete(
    "/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one article",
    responses={status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND}},
)
def delete_article(
    request: Request,
    admin: deps.CurrentAdmin,
    article_id: Annotated[int, Path(ge=1, description="Article id.")],
) -> Response:
    """Remove an article, its sources, symbols, topics, impacts and bookmarks.

    The child rows go with it through ON DELETE CASCADE and the search index
    entry is removed by the repository. There is no undo, which is why the web
    screen asks for confirmation first.
    """
    article = _load(article_id)
    if not repo.delete_article(article_id):
        raise deps.ApiError(
            status.HTTP_404_NOT_FOUND, CODE_ARTICLE_NOT_FOUND, ARTICLE_NOT_FOUND
        )
    repo.write_audit(
        admin.username,
        ACTION_DELETE,
        target=str(article_id),
        detail={"headline": article.get("headline", "")[:120]},
        ip=deps.client_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{article_id}/rescore",
    summary="Recompute one importance score",
    responses={status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND}},
)
def rescore_article(
    request: Request,
    admin: deps.CurrentAdmin,
    article_id: Annotated[int, Path(ge=1, description="Article id.")],
) -> ArticleScoreResponse:
    """Recompute the deterministic importance score for one article."""
    from app.pipeline import score

    article = _load(article_id)
    fresh = score.compute_importance(article)
    repo.set_importance_score(article_id, fresh)
    repo.write_audit(
        admin.username,
        ACTION_RESCORE,
        target=str(article_id),
        detail={"score": fresh},
        ip=deps.client_ip(request),
    )
    return ArticleScoreResponse(importance_score=fresh)


@router.post(
    "/{article_id}/refresh-image",
    summary="Resolve the card image again",
    responses={status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND}},
)
async def refresh_article_image(
    request: Request,
    admin: deps.CurrentAdmin,
    article_id: Annotated[int, Path(ge=1, description="Article id.")],
) -> ArticleImageResponse:
    """Re-read the Open Graph tags on this article's source pages.

    This is the one way past the image_checked_at guard that normally stops a
    miss being retried, so it exists for the case where a publisher added the
    tag after the pipeline looked. A failure stores the miss and answers with a
    null image rather than an error.
    """
    from app.pipeline import images

    article = _load(article_id)
    image_url, page_url = await images.resolve_image(article.get("sources"))
    repo.set_article_image(article_id, image_url, page_url)
    repo.write_audit(
        admin.username,
        ACTION_IMAGE,
        target=str(article_id),
        detail={"found": bool(image_url)},
        ip=deps.client_ip(request),
    )
    return ArticleImageResponse(image_url=image_url)


@router.get(
    "/{article_id}/cluster",
    summary="What deduplication decided for one article",
    responses={status.HTTP_404_NOT_FOUND: {"description": ARTICLE_NOT_FOUND}},
)
def article_cluster(
    admin: deps.CurrentAdmin,
    article_id: Annotated[int, Path(ge=1, description="Article id.")],
) -> ArticleClusterResponse:
    """Return the article, its sources and any other row in the same cluster.

    A sibling means two rows carry one story, which is the deduplication miss
    this view exists to make visible.
    """
    article = _load(article_id)
    return ArticleClusterResponse.model_validate(
        {
            "article": article,
            "sources": article.get("sources", []),
            "dedupe_key": article.get("dedupe_key", ""),
            "story_cluster_id": article.get("story_cluster_id", ""),
            "siblings": repo.article_siblings(
                article_id,
                article.get("story_cluster_id", ""),
                article.get("dedupe_key", ""),
            ),
        }
    )


__all__ = [
    "ACTION_DELETE",
    "ACTION_IMAGE",
    "ACTION_RESCORE",
    "ACTION_UPDATE",
    "ARTICLE_NOT_FOUND",
    "EDITABLE_FIELDS",
    "article_cluster",
    "delete_article",
    "list_articles",
    "patch_article",
    "refresh_article_image",
    "rescore_article",
    "router",
]
