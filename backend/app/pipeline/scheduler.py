"""Background jobs, started and stopped by the FastAPI lifespan.

Two jobs run on an AsyncIOScheduler:

- ingest, every INGEST_INTERVAL_MINUTES, which runs one full cycle over the
  next slice of the rotating query set. It is scheduled only when
  INGEST_ENABLED is true, because it spends money.
- rescore, every RESCORE_INTERVAL_MINUTES, which recomputes importance scores
  so the feed decays. It only reads and writes the local database, costs
  nothing and therefore always runs.

Both jobs use max_instances=1 and coalesce=True, so a slow cycle can never
pile up behind itself: a missed run is collapsed into one run instead of a
queue of them. The first ingest fires one full interval after startup rather
than immediately, so restarting the API during development does not spend
money on every reload.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.pipeline import ingest

logger = logging.getLogger(__name__)

INGEST_JOB_ID = "finbit_ingest"
RESCORE_JOB_ID = "finbit_rescore"

# A job that misfires by more than this many seconds is skipped, not stacked.
MISFIRE_GRACE_SECONDS = 300

_scheduler: AsyncIOScheduler | None = None


async def ingest_job() -> None:
    """One scheduled ingestion cycle. Never raises into the scheduler."""
    try:
        result = await ingest.run_cycle()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a failed cycle must not stop the schedule
        logger.exception("scheduled ingest cycle failed")
        return
    logger.info(
        "scheduled ingest run %d finished with status %s, %d new and %d merged, "
        "%.5f usd",
        result.run_id,
        result.status,
        result.stories_new,
        result.stories_merged,
        result.cost_usd,
    )


async def rescore_job() -> None:
    """One scheduled decay pass. Never raises into the scheduler."""
    try:
        updated = await asyncio.to_thread(ingest.rescore_recent)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a failed pass must not stop the schedule
        logger.exception("scheduled rescore pass failed")
        return
    logger.info("scheduled rescore pass updated %d articles", updated)


def get_scheduler() -> AsyncIOScheduler | None:
    """The running scheduler, or None when nothing is scheduled."""
    return _scheduler


def is_running() -> bool:
    """True while the scheduler is started."""
    return _scheduler is not None and _scheduler.running


def start_scheduler(app: Any = None) -> AsyncIOScheduler | None:
    """Start the background jobs. Safe to call twice.

    Pass the FastAPI app to have the scheduler stored on app.state.scheduler.
    Returns the scheduler, or None when nothing at all is scheduled.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")

    if settings.ingest_enabled:
        if not settings.has_perplexity_key:
            logger.warning(
                "INGEST_ENABLED is true but PERPLEXITY_API_KEY is not set, so the "
                "ingest job is not scheduled. The API still serves stored articles."
            )
        else:
            scheduler.add_job(
                ingest_job,
                IntervalTrigger(minutes=settings.ingest_interval_minutes, timezone="UTC"),
                id=INGEST_JOB_ID,
                name="FinBit ingest cycle",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=MISFIRE_GRACE_SECONDS,
                replace_existing=True,
            )
            logger.info(
                "ingest job scheduled every %d minutes, %d queries per cycle",
                settings.ingest_interval_minutes,
                settings.ingest_queries_per_cycle,
            )
    else:
        logger.info("INGEST_ENABLED is false, the ingest job is not scheduled")

    scheduler.add_job(
        rescore_job,
        IntervalTrigger(minutes=settings.rescore_interval_minutes, timezone="UTC"),
        id=RESCORE_JOB_ID,
        name="FinBit importance rescore",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    if app is not None:
        try:
            app.state.scheduler = scheduler
        except AttributeError:
            logger.debug("app has no state attribute, scheduler not attached")
    logger.info(
        "scheduler started with %d job(s)", len(scheduler.get_jobs())
    )
    return scheduler


def stop_scheduler() -> None:
    """Shut the scheduler down cleanly. Safe to call twice."""
    global _scheduler
    scheduler = _scheduler
    _scheduler = None
    if scheduler is None:
        return
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("scheduler stopped")
    except Exception:  # noqa: BLE001 - shutdown must never break app teardown
        logger.exception("scheduler shutdown failed")


__all__ = [
    "INGEST_JOB_ID",
    "MISFIRE_GRACE_SECONDS",
    "RESCORE_JOB_ID",
    "get_scheduler",
    "ingest_job",
    "is_running",
    "rescore_job",
    "start_scheduler",
    "stop_scheduler",
]
