"""Metadata and dev admin endpoints.

Contract section 5:
  GET  /api/health         status, article count and last ingest outcome
  GET  /api/categories     categories with counts plus the market quick filters
  POST /api/admin/ingest   dev trigger, starts one pipeline cycle in background
  GET  /api/admin/runs     the last 20 ingest runs, newest first

All data access goes through app.repo. There is no SQL in this module. The
ingestion pipeline is imported lazily inside the background job so the API
still imports and serves cached articles when the pipeline is unavailable or
when PERPLEXITY_API_KEY is not configured.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app import repo
from app.config import get_settings
from app.models import (
    CategoriesResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    IngestRun,
)

router = APIRouter(prefix="/api", tags=["meta"])

logger = logging.getLogger(__name__)

_INGEST_ENTRY_POINTS = (
    "run_ingest_cycle",
    "run_cycle",
    "run_once",
    "ingest_once",
    "run_ingest",
    "ingest",
    "run",
)
"""Candidate callables in app.pipeline.ingest, tried in this order."""

_PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "run_id": ("run_id",),
    "queries": ("queries", "query_keys", "keys"),
    "limit": ("limit", "max_stories", "max_stories_per_query"),
}
"""How the router's arguments map onto whatever the pipeline entry point names."""

_COUNT_FIELDS = (
    "queries_run",
    "stories_seen",
    "stories_new",
    "stories_merged",
    "cost_usd",
)

ADMIN_INGEST_DISABLED_DETAIL = (
    "Ingestion from the UI is turned off. Set ALLOW_ADMIN_INGEST_FROM_UI=true, or "
    "seed the database from the backend directory with "
    "uv run python -m app.pipeline.ingest --once"
)
"""Body returned as {"detail": ...} when the UI trigger is gated off."""


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    summary="Service health",
    response_description="Status, stored article count and the last ingest outcome.",
)
def health() -> HealthResponse:
    """Report liveness, ingestion freshness and whether ingestion can run.

    Safe on an empty database and on a database that has not been created yet:
    a storage error degrades the status instead of raising a 500, so a monitor
    always gets a parseable body. ingest_enabled and reason let the cold start
    empty state say the key is missing rather than blaming the network
    (contract 13.4 and 13.5).
    """
    settings = get_settings()
    ingest_enabled = settings.ingest_available
    reason = settings.ingest_unavailable_reason
    try:
        stats = repo.health_stats()
    except sqlite3.Error as exc:
        logger.warning("health check could not read the database: %s", exc)
        return HealthResponse(
            status="degraded",
            articles=0,
            last_ingest_at=None,
            last_ingest_status=None,
            ingest_running=False,
            ingest_enabled=ingest_enabled,
            reason=reason or "The article database could not be read.",
        )
    return HealthResponse.model_validate(
        {**stats, "ingest_enabled": ingest_enabled, "reason": reason}
    )


@router.get(
    "/categories",
    summary="Categories and market filters",
    response_description="Category keys with counts, plus the market quick filter chips.",
)
def categories() -> CategoriesResponse:
    """Return the category tabs with live counts and the market filter chips."""
    return CategoriesResponse(
        categories=repo.category_counts(),
        market_filters=repo.market_filters(),
    )


# ---------------------------------------------------------------------------
# Dev admin
# ---------------------------------------------------------------------------


def _first_callable(module: Any, names: tuple[str, ...]) -> Callable[..., Any] | None:
    """Return the first attribute of `module` in `names` that is callable."""
    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def _pipeline_kwargs(func: Callable[..., Any], values: dict[str, Any]) -> dict[str, Any]:
    """Map router arguments onto the parameter names the pipeline actually uses."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return {}
    accepts_var_keyword = any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()
    )
    kwargs: dict[str, Any] = {}
    for canonical, aliases in _PARAM_ALIASES.items():
        value = values.get(canonical)
        if value is None:
            continue
        target = next((alias for alias in aliases if alias in params), None)
        if target is None and accepts_var_keyword:
            target = canonical
        if target is not None:
            kwargs[target] = value
    return kwargs


def _counts_from_result(result: Any) -> dict[str, Any]:
    """Pull run counters off whatever the pipeline returned, if anything."""
    counts: dict[str, Any] = {}
    for field in _COUNT_FIELDS:
        if isinstance(result, dict):
            value = result.get(field)
        else:
            value = getattr(result, field, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            counts[field] = value
    return counts


def _close_run_if_open(run_id: int, status: str, result: Any = None, error: str | None = None) -> None:
    """Close the run row when the pipeline did not close it itself."""
    try:
        run = repo.get_ingest_run(run_id)
        if run is None or run["status"] != "running":
            return
        repo.finish_ingest_run(
            run_id, status=status, error=error, **_counts_from_result(result)
        )
    except sqlite3.Error as exc:
        logger.error("could not close ingest run %s: %s", run_id, exc)


def run_ingest_job(run_id: int, queries: list[str] | None, limit: int | None) -> None:
    """Background job: run one pipeline cycle and make sure the run row closes.

    The pipeline is imported here, not at module import time, so a broken or
    missing pipeline cannot stop the API from starting. Whatever happens, the
    ingest_runs row opened by the endpoint ends up with a final status.
    """
    try:
        from app.pipeline import ingest as ingest_module
    except Exception as exc:  # noqa: BLE001 - any import failure must be reported
        logger.error("ingest run %s cannot start, pipeline unavailable: %s", run_id, exc)
        _close_run_if_open(run_id, "error", error=f"pipeline unavailable: {exc}")
        return

    runner = _first_callable(ingest_module, _INGEST_ENTRY_POINTS)
    if runner is None:
        message = "app.pipeline.ingest exposes no cycle entry point"
        logger.error("ingest run %s cannot start: %s", run_id, message)
        _close_run_if_open(run_id, "error", error=message)
        return

    kwargs = _pipeline_kwargs(
        runner, {"run_id": run_id, "queries": queries, "limit": limit}
    )
    logger.info("ingest run %s starting via %s", run_id, getattr(runner, "__name__", "runner"))
    try:
        result = runner(**kwargs)
        if inspect.isawaitable(result):
            result = asyncio.run(_resolve(result))
    except Exception as exc:  # noqa: BLE001 - the run row records the failure
        logger.exception("ingest run %s failed", run_id)
        _close_run_if_open(run_id, "error", error=str(exc)[:500])
        return
    logger.info("ingest run %s finished", run_id)
    _close_run_if_open(run_id, "ok", result=result)


async def _resolve(awaitable: Any) -> Any:
    """Await an awaitable returned by an async pipeline entry point."""
    return await awaitable


@router.post(
    "/admin/ingest",
    summary="Trigger one ingestion cycle",
    response_description="The id of the ingest run that was opened.",
    responses={
        status.HTTP_403_FORBIDDEN: {"description": ADMIN_INGEST_DISABLED_DETAIL},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "PERPLEXITY_API_KEY is not set"},
    },
)
def trigger_ingest(background_tasks: BackgroundTasks, payload: IngestRequest | None = None) -> IngestResponse:
    """Start one pipeline cycle in the background and return immediately.

    Both body fields are optional: queries selects which query keys to run and
    limit caps the stories per query. Progress, cost and any failure land on
    the run row, readable through GET /api/admin/runs.

    Because a cycle spends real money it is gated twice (contract 13.3, 13.4):
    503 when there is no API key, 403 when ALLOW_ADMIN_INGEST_FROM_UI is
    false. Neither case opens a run row.
    """
    settings = get_settings()
    if not settings.has_perplexity_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=settings.missing_key_detail,
        )
    if not settings.allow_admin_ingest_from_ui:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ADMIN_INGEST_DISABLED_DETAIL,
        )
    body = payload or IngestRequest()
    queries = [q.strip() for q in (body.queries or []) if isinstance(q, str) and q.strip()]
    limit = body.limit if body.limit and body.limit > 0 else None
    run_id = repo.start_ingest_run()
    background_tasks.add_task(run_ingest_job, run_id, queries or None, limit)
    return IngestResponse(started=True, run_id=run_id)


@router.get(
    "/admin/runs",
    summary="Recent ingest runs",
    response_description="The last twenty ingest runs, newest first, with counts and cost.",
)
def list_runs() -> list[IngestRun]:
    """Return the most recent ingestion runs with their real USD cost."""
    rows = repo.list_ingest_runs(limit=repo.DEFAULT_RUNS_LIMIT)
    return [IngestRun.model_validate(row) for row in rows]


__all__ = [
    "ADMIN_INGEST_DISABLED_DETAIL",
    "categories",
    "health",
    "list_runs",
    "router",
    "run_ingest_job",
    "trigger_ingest",
]
