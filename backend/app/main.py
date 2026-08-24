"""FinBit API application.

Run it from the backend directory with:

    uv run uvicorn app.main:app --reload

Startup creates the SQLite schema if needed and starts the background
ingestion scheduler. Both are safe on a machine with no PERPLEXITY_API_KEY:
config never raises on a missing key, and the scheduler is imported lazily so
a pipeline problem cannot stop the API from serving cached articles.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__, repo
from app.config import get_settings
from app.db import init_db
from app.routers import bookmarks, feed, meta, search

API_TITLE = "FinBit API"
API_VERSION = __version__
API_DESCRIPTION = (
    "Inshorts-style financial news for Indian market traders. Impact fields are "
    "AI assessments, not investment advice."
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("finbit.api")

_SCHEDULER_START_NAMES = ("start_scheduler", "start")
_SCHEDULER_STOP_NAMES = ("stop_scheduler", "shutdown_scheduler", "shutdown", "stop")

INTERNAL_ERROR_DETAIL = "Internal server error"


# ---------------------------------------------------------------------------
# Background scheduler wiring (agent B2 owns app/pipeline/scheduler.py)
# ---------------------------------------------------------------------------


def _first_callable(target: Any, names: tuple[str, ...]) -> Callable[..., Any] | None:
    """Return the first attribute of `target` in `names` that is callable."""
    for name in names:
        candidate = getattr(target, name, None)
        if callable(candidate):
            return candidate
    return None


async def _start_scheduler() -> tuple[Any, Any] | None:
    """Start the background scheduler, returning the module and its handle.

    Returns None when the pipeline package is not importable or when starting
    fails. Neither is fatal: the API keeps serving whatever is already in the
    database.

    Whether the paid ingest job is scheduled at all is decided inside
    app.pipeline.scheduler, which skips it when INGEST_ENABLED is false or
    when there is no API key, and logs one clear warning either way (contract
    13.4). The free rescore pass is scheduled regardless, so a feed with
    ingestion turned off still decays.
    """
    settings = get_settings()
    try:
        from app.pipeline import scheduler as scheduler_module
    except Exception as exc:  # noqa: BLE001 - a missing pipeline must not break startup
        logger.warning("background scheduler unavailable: %s", exc)
        return None

    starter = _first_callable(scheduler_module, _SCHEDULER_START_NAMES)
    if starter is None:
        logger.warning("app.pipeline.scheduler exposes no start entry point")
        return None
    try:
        handle = starter()
        if inspect.isawaitable(handle):
            handle = await handle
    except Exception:  # noqa: BLE001 - startup continues without the scheduler
        logger.exception("background scheduler failed to start")
        return None
    logger.info(
        "background scheduler started, ingest every %s min (enabled=%s), rescore "
        "every %s min",
        settings.ingest_interval_minutes,
        settings.ingest_available,
        settings.rescore_interval_minutes,
    )
    return scheduler_module, handle


async def _stop_scheduler(started: tuple[Any, Any] | None) -> None:
    """Stop the ingestion scheduler cleanly. Never raises."""
    if started is None:
        return
    scheduler_module, handle = started
    stopper = _first_callable(scheduler_module, _SCHEDULER_STOP_NAMES)
    if stopper is None and handle is not None:
        stopper = _first_callable(handle, _SCHEDULER_STOP_NAMES)
    if stopper is None:
        logger.warning("app.pipeline.scheduler exposes no stop entry point")
        return
    try:
        result = stopper()
        if inspect.isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 - shutdown must always complete
        logger.exception("background scheduler failed to stop cleanly")
        return
    logger.info("background scheduler stopped")


def _startup_ingest_decision() -> tuple[bool, str]:
    """Decide whether to seed the database at startup (contract 13.2).

    Conditional on purpose: uvicorn --reload restarts the process on every
    file save, and an unconditional startup cycle would spend real money on
    every keystroke. Returns (run_it, why) so the branch taken is always
    logged.
    """
    settings = get_settings()
    if not settings.ingest_on_startup:
        return False, "INGEST_ON_STARTUP is false"
    if not settings.ingest_available:
        return False, settings.ingest_unavailable_reason or "ingestion is unavailable"
    try:
        articles = repo.count_articles()
        finished_at = repo.last_ingest_finished_at()
    except sqlite3.Error as exc:
        return False, f"the database could not be read: {exc}"
    if articles == 0:
        return True, "the database holds no articles"
    if finished_at is None:
        return True, "no ingest run has finished yet"
    last = repo.parse_iso(finished_at)
    if last is None:
        return True, "the last run has an unreadable finished_at"
    age_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60.0
    if age_minutes >= settings.ingest_interval_minutes:
        return True, (
            f"the last run finished {age_minutes:.0f} min ago, over the "
            f"{settings.ingest_interval_minutes} min interval"
        )
    return False, (
        f"the last run finished {age_minutes:.0f} min ago, inside the "
        f"{settings.ingest_interval_minutes} min interval"
    )


async def _startup_ingest_task() -> None:
    """Run one seeding cycle. Never raises into the event loop."""
    try:
        from app.pipeline import ingest as ingest_module

        result = await ingest_module.run_cycle()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a failed seed must not affect the API
        logger.exception("startup ingest cycle failed")
        return
    logger.info(
        "startup ingest run %d finished with status %s, %d new and %d merged, "
        "%.5f usd",
        result.run_id,
        result.status,
        result.stories_new,
        result.stories_merged,
        result.cost_usd,
    )


def _schedule_startup_ingest() -> asyncio.Task[None] | None:
    """Fire the startup cycle onto the loop, never blocking application start."""
    run_it, why = _startup_ingest_decision()
    if not run_it:
        logger.info("startup ingest skipped because %s", why)
        return None
    logger.info("startup ingest scheduled because %s", why)
    return asyncio.create_task(_startup_ingest_task())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the schema, start the scheduler, stop it again on shutdown."""
    db_file = init_db()
    logger.info("database ready at %s", db_file)
    started = await _start_scheduler()
    seed_task = _schedule_startup_ingest()
    try:
        yield
    finally:
        if seed_task is not None and not seed_task.done():
            seed_task.cancel()
        await _stop_scheduler(started)
        logger.info("FinBit API stopped")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    lifespan=lifespan,
)

_settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Response-Time-Ms"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable[[Request], Any]) -> Response:
    """Log method, path, status and duration for every request."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.exception(
            "%s %s failed after %.1f ms", request.method, request.url.path, elapsed_ms
        )
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    logger.info(
        "%s %s %s %.1f ms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Answer any unhandled error with JSON, never an HTML 500 page."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR_DETAIL})


@app.get("/", tags=["meta"], summary="API root")
def root() -> dict[str, str]:
    """Name, version and where to find the interactive documentation."""
    return {"name": API_TITLE, "version": API_VERSION, "docs": "/docs"}


app.include_router(feed.router)
app.include_router(search.router)
app.include_router(bookmarks.router)
app.include_router(meta.router)


__all__ = [
    "API_TITLE",
    "API_VERSION",
    "app",
    "lifespan",
    "root",
]
