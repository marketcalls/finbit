"""Admin control of the ingestion pipeline (CONTRACT_MOBILE_ADMIN.md section 6.4).

    GET   /api/admin/pipeline           settings, schedule, availability, last runs
    PATCH /api/admin/pipeline           any subset of the overridable settings
    POST  /api/admin/pipeline/ingest    one cycle now, this one spends money
    POST  /api/admin/pipeline/rescore   recompute importance scores, free
    POST  /api/admin/pipeline/images    resolve missing card images, free
    GET   /api/admin/pipeline/queries   the nine query definitions
    PUT   /api/admin/pipeline/queries   replace the query set

Every route depends on deps.CurrentAdmin, and every mutation writes an
audit_log row through repo.write_audit. Nothing here logs or audits a secret:
the details recorded are setting names, query keys and run ids.

The scheduler and the ingest module are imported inside the handlers rather
than at module scope, the same rule app/routers/meta.py follows, so a pipeline
that fails to import cannot stop the whole API from starting.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from app import deps, repo
from app.config import get_settings
from app.models import (
    ImagesResponse,
    IngestRequest,
    IngestResponse,
    PipelineSettingsPatch,
    PipelineStatusResponse,
    QuerySetResponse,
    RescoreResponse,
)
from app.pipeline import settings_bridge
from app.security import ratelimit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/pipeline", tags=["admin pipeline"])

RECENT_RUNS = 5
"""How much run history the pipeline payload carries (section 6.4)."""

INGEST_DISABLED_DETAIL = (
    "Ingestion from the UI is turned off. Set ALLOW_ADMIN_INGEST_FROM_UI=true, or "
    "seed the database from the backend directory with "
    "uv run python -m app.pipeline.ingest --once"
)

CODE_INGEST_DISABLED = "ingest_disabled"
CODE_INGEST_UNAVAILABLE = "ingest_unavailable"
CODE_INVALID_QUERY_SET = "invalid_query_set"

ACTION_PATCH = "pipeline.settings"
ACTION_INGEST = "pipeline.ingest"
ACTION_RESCORE = "pipeline.rescore"
ACTION_IMAGES = "pipeline.images"
ACTION_QUERIES = "pipeline.queries"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def scheduler_status() -> dict[str, Any]:
    """What the background scheduler is doing, or an all-off answer.

    A pipeline that cannot be imported reports not running rather than raising,
    so the admin screen still renders and shows why.
    """
    try:
        from app.pipeline import scheduler
    except Exception:  # noqa: BLE001 - the screen must still render
        return {"running": False, "next_ingest_at": None, "next_rescore_at": None}
    return scheduler.status()


def ingest_state() -> tuple[bool, str | None]:
    """Whether a cycle could run right now, and why not when it cannot.

    Reads the effective ingest_enabled rather than the .env one, so switching
    ingestion off from the admin screen is reflected here immediately.
    """
    settings = get_settings()
    if not settings.has_perplexity_key:
        return False, settings.missing_key_detail
    if not settings_bridge.effective(
        settings_bridge.KEY_INGEST_ENABLED, settings.ingest_enabled
    ):
        return False, "Ingestion is switched off in the pipeline settings."
    if not settings_bridge.enabled_query_keys():
        return False, "Every query in the set is switched off."
    return True, None


def pipeline_payload() -> dict[str, Any]:
    """The full GET /api/admin/pipeline body."""
    available, reason = ingest_state()
    return {
        "settings": settings_bridge.pipeline_settings(),
        "scheduler": scheduler_status(),
        "ingest_available": available,
        "reason": reason,
        "recent_runs": repo.list_ingest_runs(limit=RECENT_RUNS),
    }


# ---------------------------------------------------------------------------
# Settings and schedule
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="Pipeline settings, schedule and recent runs",
    response_description="Effective settings, scheduler state and the last five runs.",
)
def get_pipeline(admin: deps.CurrentAdmin) -> PipelineStatusResponse:
    """Everything the pipeline screen renders in one call."""
    return PipelineStatusResponse.model_validate(pipeline_payload())


@router.patch(
    "",
    summary="Change pipeline settings",
    response_description="The pipeline payload with the new settings in force.",
)
def patch_pipeline(
    request: Request, admin: deps.CurrentAdmin, patch: PipelineSettingsPatch
) -> PipelineStatusResponse:
    """Store any subset of the overridable settings and reschedule at once.

    The values land in app_settings, which overrides .env, so nothing needs a
    restart. The scheduler is reconciled here rather than on the next tick, so
    a new interval takes effect immediately.
    """
    applied = settings_bridge.apply_patch(
        patch.model_dump(exclude_unset=True), actor=admin.username
    )
    if applied:
        try:
            from app.pipeline import scheduler

            scheduler.apply_settings()
        except Exception:  # noqa: BLE001 - the setting is stored either way
            logger.exception("the schedule could not be updated after a settings patch")
        repo.write_audit(
            admin.username,
            ACTION_PATCH,
            target="pipeline",
            detail=applied,
            ip=deps.client_ip(request),
        )
    return PipelineStatusResponse.model_validate(pipeline_payload())


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@router.post(
    "/ingest",
    summary="Run one ingestion cycle now",
    response_description="The id of the ingest run that was opened.",
    dependencies=[Depends(deps.rate_limit(ratelimit.SCOPE_ADMIN_INGEST))],
    responses={
        status.HTTP_403_FORBIDDEN: {"description": INGEST_DISABLED_DETAIL},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Ingestion cannot run"},
    },
)
def trigger_ingest(
    request: Request,
    admin: deps.CurrentAdmin,
    background_tasks: BackgroundTasks,
    payload: IngestRequest | None = None,
) -> IngestResponse:
    """Start one cycle in the background and return its run id.

    This is the one admin action that spends real money, so it is gated three
    ways: a token bucket of six per hour, the ALLOW_ADMIN_INGEST_FROM_UI switch
    and the same availability check the schedule uses. The web screen asks for
    confirmation before calling it.
    """
    from app.routers.meta import run_ingest_job

    settings = get_settings()
    available, reason = ingest_state()
    if not available:
        raise deps.ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            CODE_INGEST_UNAVAILABLE,
            reason or "Ingestion cannot run right now.",
        )
    if not settings.allow_admin_ingest_from_ui:
        raise deps.ApiError(
            status.HTTP_403_FORBIDDEN, CODE_INGEST_DISABLED, INGEST_DISABLED_DETAIL
        )

    body = payload or IngestRequest()
    keys = [q.strip() for q in (body.queries or []) if isinstance(q, str) and q.strip()]
    limit = body.limit if body.limit and body.limit > 0 else None
    run_id = repo.start_ingest_run()
    background_tasks.add_task(run_ingest_job, run_id, keys or None, limit)
    repo.write_audit(
        admin.username,
        ACTION_INGEST,
        target=str(run_id),
        detail={"queries": keys or "rotation", "limit": limit},
        ip=deps.client_ip(request),
    )
    return IngestResponse(started=True, run_id=run_id)


@router.post(
    "/rescore",
    summary="Recompute importance scores",
    response_description="How many articles changed score.",
)
def trigger_rescore(request: Request, admin: deps.CurrentAdmin) -> RescoreResponse:
    """Run one decay pass over the recent articles. Local only, costs nothing."""
    from app.pipeline import ingest

    updated = ingest.rescore_recent()
    repo.write_audit(
        admin.username,
        ACTION_RESCORE,
        target="articles",
        detail={"updated": updated},
        ip=deps.client_ip(request),
    )
    return RescoreResponse(updated=updated)


@router.post(
    "/images",
    summary="Resolve missing card images",
    response_description="Confirmation that the backfill started.",
)
def trigger_images(
    request: Request, admin: deps.CurrentAdmin, background_tasks: BackgroundTasks
) -> ImagesResponse:
    """Start a card image backfill in the background.

    It reads publisher pages rather than a paid API, so it costs nothing, but
    it is slow enough to belong in the background either way. Articles already
    checked once are never refetched (contract 1, section 14.2).
    """
    from app.pipeline import ingest

    background_tasks.add_task(ingest.backfill_images_blocking)
    repo.write_audit(
        admin.username, ACTION_IMAGES, target="articles", ip=deps.client_ip(request)
    )
    return ImagesResponse(started=True)


# ---------------------------------------------------------------------------
# The query set
# ---------------------------------------------------------------------------


@router.get(
    "/queries",
    summary="The discovery query set",
    response_description="Every query with its prompt and its enabled switch.",
)
def get_queries(admin: deps.CurrentAdmin) -> QuerySetResponse:
    """Return the query set in force, stored or built in."""
    return QuerySetResponse.model_validate(
        {"queries": settings_bridge.query_definitions()}
    )


@router.put(
    "/queries",
    summary="Replace the discovery query set",
    response_description="The stored query set.",
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "The query set is empty"}
    },
)
def put_queries(
    request: Request, admin: deps.CurrentAdmin, payload: QuerySetResponse
) -> QuerySetResponse:
    """Store a new query set, replacing whatever was there.

    A set with no usable entry is refused rather than stored, because an empty
    set would leave the pipeline with nothing to run and no screen to fix it
    from.
    """
    try:
        stored = settings_bridge.set_query_definitions(
            [entry.model_dump() for entry in payload.queries], actor=admin.username
        )
    except ValueError as exc:
        raise deps.ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, CODE_INVALID_QUERY_SET, str(exc)
        ) from None
    repo.write_audit(
        admin.username,
        ACTION_QUERIES,
        target="query_set",
        detail={"keys": [entry["key"] for entry in stored]},
        ip=deps.client_ip(request),
    )
    return QuerySetResponse.model_validate({"queries": stored})


__all__ = [
    "ACTION_IMAGES",
    "ACTION_INGEST",
    "ACTION_PATCH",
    "ACTION_QUERIES",
    "ACTION_RESCORE",
    "INGEST_DISABLED_DETAIL",
    "RECENT_RUNS",
    "get_pipeline",
    "get_queries",
    "ingest_state",
    "patch_pipeline",
    "pipeline_payload",
    "put_queries",
    "router",
    "scheduler_status",
    "trigger_images",
    "trigger_ingest",
    "trigger_rescore",
]
