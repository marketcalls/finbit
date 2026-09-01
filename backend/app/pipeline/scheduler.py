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

The schedule is not fixed at startup. Every interval and the ingest on/off
switch are read through app.pipeline.settings_bridge, so an admin PATCH takes
effect without a restart: apply_settings() reconciles the running jobs with
the effective settings, and each job calls it after it finishes so a change
made while a cycle was running is still picked up.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.pipeline import ingest, queries, settings_bridge

logger = logging.getLogger(__name__)

INGEST_JOB_ID = "finbit_ingest"
RESCORE_JOB_ID = "finbit_rescore"

# A job that misfires by more than this many seconds is skipped, not stacked.
MISFIRE_GRACE_SECONDS = 300

_scheduler: AsyncIOScheduler | None = None


# ---------------------------------------------------------------------------
# Effective settings (contract 2, section 5)
# ---------------------------------------------------------------------------


def ingest_interval_minutes() -> int:
    """Minutes between ingest cycles, admin override first."""
    return int(
        settings_bridge.effective(
            settings_bridge.KEY_INGEST_INTERVAL_MINUTES,
            get_settings().ingest_interval_minutes,
        )
    )


def rescore_interval_minutes() -> int:
    """Minutes between rescore passes, admin override first."""
    return int(
        settings_bridge.effective(
            settings_bridge.KEY_RESCORE_INTERVAL_MINUTES,
            get_settings().rescore_interval_minutes,
        )
    )


def queries_per_cycle() -> int:
    """How many queries one cycle runs, admin override first."""
    return int(
        settings_bridge.effective(
            settings_bridge.KEY_INGEST_QUERIES_PER_CYCLE,
            get_settings().ingest_queries_per_cycle,
        )
    )


def max_stories_per_query() -> int:
    """Story cap per query, admin override first."""
    return int(
        settings_bridge.effective(
            settings_bridge.KEY_INGEST_MAX_STORIES_PER_QUERY,
            get_settings().ingest_max_stories_per_query,
        )
    )


def ingest_enabled() -> bool:
    """Whether scheduled ingestion is switched on, admin override first."""
    return bool(
        settings_bridge.effective(
            settings_bridge.KEY_INGEST_ENABLED, get_settings().ingest_enabled
        )
    )


def ingest_wanted() -> bool:
    """Whether the paid ingest job should be on the schedule at all.

    Being switched on is not enough: without an API key a cycle can only fail,
    so the job is left off and the reason is logged once.
    """
    return ingest_enabled() and get_settings().has_perplexity_key


async def ingest_job() -> None:
    """One scheduled ingestion cycle. Never raises into the scheduler.

    The rotation slice and the per query story cap are read from the effective
    settings on every tick, so a change to either applies to the next cycle
    without a restart.
    """
    keys = queries.rotate_keys(ingest.next_cycle_index(), queries_per_cycle())
    if not keys:
        logger.info("every query is switched off, skipping this ingest cycle")
        apply_settings()
        return
    try:
        result = await ingest.run_cycle(query_keys=keys, limit=max_stories_per_query())
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a failed cycle must not stop the schedule
        logger.exception("scheduled ingest cycle failed")
        apply_settings()
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
    apply_settings()


async def rescore_job() -> None:
    """One scheduled decay pass. Never raises into the scheduler."""
    try:
        updated = await asyncio.to_thread(ingest.rescore_recent)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a failed pass must not stop the schedule
        logger.exception("scheduled rescore pass failed")
        apply_settings()
        return
    logger.info("scheduled rescore pass updated %d articles", updated)
    apply_settings()


def get_scheduler() -> AsyncIOScheduler | None:
    """The running scheduler, or None when nothing is scheduled."""
    return _scheduler


def is_running() -> bool:
    """True while the scheduler is started."""
    return _scheduler is not None and _scheduler.running


def _add_ingest_job(scheduler: AsyncIOScheduler, minutes: int) -> None:
    """Put the paid ingest cycle on the schedule at this interval."""
    scheduler.add_job(
        ingest_job,
        IntervalTrigger(minutes=minutes, timezone="UTC"),
        id=INGEST_JOB_ID,
        name="FinBit ingest cycle",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        replace_existing=True,
    )


def _add_rescore_job(scheduler: AsyncIOScheduler, minutes: int) -> None:
    """Put the free rescore pass on the schedule at this interval."""
    scheduler.add_job(
        rescore_job,
        IntervalTrigger(minutes=minutes, timezone="UTC"),
        id=RESCORE_JOB_ID,
        name="FinBit importance rescore",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        replace_existing=True,
    )


def _trigger_minutes(job: Any) -> int | None:
    """The interval a scheduled job currently runs at, in whole minutes."""
    interval = getattr(getattr(job, "trigger", None), "interval", None)
    if interval is None:
        return None
    try:
        return int(round(interval.total_seconds() / 60.0))
    except (AttributeError, TypeError, ValueError):
        return None


def apply_settings() -> list[str]:
    """Reconcile the running jobs with the effective settings.

    This is what makes a PATCH to the schedule take hold without a restart:
    the admin route calls it straight after writing the override, and each job
    calls it when it finishes. Returns a short description of every change, so
    the caller can log exactly what moved. Safe to call when nothing is
    running, in which case it does nothing and returns an empty list.
    """
    scheduler = _scheduler
    if scheduler is None or not scheduler.running:
        return []

    changes: list[str] = []
    try:
        wanted = ingest_wanted()
        job = scheduler.get_job(INGEST_JOB_ID)
        minutes = ingest_interval_minutes()
        if wanted and job is None:
            _add_ingest_job(scheduler, minutes)
            changes.append(f"ingest job scheduled every {minutes} min")
        elif not wanted and job is not None:
            scheduler.remove_job(INGEST_JOB_ID)
            changes.append("ingest job removed")
        elif wanted and job is not None and _trigger_minutes(job) != minutes:
            scheduler.reschedule_job(
                INGEST_JOB_ID, trigger=IntervalTrigger(minutes=minutes, timezone="UTC")
            )
            changes.append(f"ingest interval is now {minutes} min")

        rescore_minutes = rescore_interval_minutes()
        rescore = scheduler.get_job(RESCORE_JOB_ID)
        if rescore is None:
            _add_rescore_job(scheduler, rescore_minutes)
            changes.append(f"rescore job scheduled every {rescore_minutes} min")
        elif _trigger_minutes(rescore) != rescore_minutes:
            scheduler.reschedule_job(
                RESCORE_JOB_ID,
                trigger=IntervalTrigger(minutes=rescore_minutes, timezone="UTC"),
            )
            changes.append(f"rescore interval is now {rescore_minutes} min")
    except Exception:  # noqa: BLE001 - a reschedule must never break a request
        logger.exception("the schedule could not be reconciled with the settings")
        return changes

    for change in changes:
        logger.info("schedule updated: %s", change)
    return changes


def next_run_at(job_id: str) -> str | None:
    """When a job runs next, ISO 8601 UTC with a trailing Z, or None."""
    scheduler = _scheduler
    if scheduler is None or not scheduler.running:
        return None
    try:
        job = scheduler.get_job(job_id)
    except Exception:  # noqa: BLE001 - status must never raise
        return None
    moment = getattr(job, "next_run_time", None) if job is not None else None
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status() -> dict[str, Any]:
    """The scheduler block of the admin pipeline payload (section 6.4)."""
    return {
        "running": is_running(),
        "next_ingest_at": next_run_at(INGEST_JOB_ID),
        "next_rescore_at": next_run_at(RESCORE_JOB_ID),
    }


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

    if ingest_enabled():
        if not settings.has_perplexity_key:
            logger.warning(
                "ingestion is enabled but PERPLEXITY_API_KEY is not set, so the "
                "ingest job is not scheduled. The API still serves stored articles."
            )
        else:
            _add_ingest_job(scheduler, ingest_interval_minutes())
            logger.info(
                "ingest job scheduled every %d minutes, %d queries per cycle",
                ingest_interval_minutes(),
                queries_per_cycle(),
            )
    else:
        logger.info("ingestion is switched off, the ingest job is not scheduled")

    _add_rescore_job(scheduler, rescore_interval_minutes())

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
    "apply_settings",
    "get_scheduler",
    "ingest_enabled",
    "ingest_interval_minutes",
    "ingest_job",
    "ingest_wanted",
    "is_running",
    "max_stories_per_query",
    "next_run_at",
    "queries_per_cycle",
    "rescore_interval_minutes",
    "rescore_job",
    "start_scheduler",
    "status",
    "stop_scheduler",
]
