"""FinBit API application.

Run it from the backend directory with:

    uv run uvicorn app.main:app --reload

Startup runs in a fixed order, and the order is the design rather than an
accident (CONTRACT_MOBILE_ADMIN.md sections 3.9 and 6):

1. create the schema, then apply the phase 2 migration, so every later step can
   assume articles.hidden and the security tables exist,
2. validate the security configuration and refuse to start when a signed
   deployment is missing a secret, before anything is served,
3. seed the feature flag defaults, so /api/config answers on a fresh database,
4. create the bootstrap admin when one is configured,
5. start the scheduler and the conditional startup ingest.

Steps 1 to 3 are safe on a machine with no PERPLEXITY_API_KEY: config never
raises on a missing key, and the scheduler is imported lazily so a pipeline
problem cannot stop the API from serving cached articles.
"""

from __future__ import annotations

import asyncio
import importlib
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

from app import __version__, admin_cli, repo
from app.config import UNSIGNED_MODE_WARNING, get_settings
from app.db import init_db
from app.migrate import migrate_database
from app.routers import (
    admin_content,
    admin_flags,
    admin_pipeline,
    bookmarks,
    config_public,
    feed,
    meta,
    search,
)
from app.security.middleware import install_security

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

SECURITY_REFUSED_MESSAGE = (
    "FinBit refused to start because the security configuration is incomplete. "
    "Fix the variables listed above in the .env file at the repo root."
)

# The device-authenticated routers written by another agent. They are imported
# by name rather than with a normal import so a checkout where they do not
# exist yet still starts and still serves the public routes, with one warning
# naming what is missing. The same pattern the scheduler wiring below uses.
_OPTIONAL_ROUTERS: tuple[tuple[str, str], ...] = (
    ("app.routers.auth_device", "POST /api/auth/device and POST /api/auth/refresh"),
    ("app.routers.admin_auth", "the /api/admin/auth routes"),
)

# Request headers the browser clients send. Listed rather than left as "*" so
# the allowlist reads as documentation of the wire protocol.
CORS_HEADERS: list[str] = [
    "Authorization",
    "Content-Type",
    "X-App-Key",
    "X-Device-Id",
    "X-Nonce",
    "X-Signature",
    "X-Timestamp",
]

CORS_METHODS: list[str] = ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]


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


def _effective_interval_minutes() -> int:
    """The ingest interval in force, admin override first, .env second."""
    settings = get_settings()
    try:
        from app.pipeline import settings_bridge

        return int(
            settings_bridge.effective(
                settings_bridge.KEY_INGEST_INTERVAL_MINUTES,
                settings.ingest_interval_minutes,
            )
        )
    except Exception:  # noqa: BLE001 - a missing override is not a startup problem
        return int(settings.ingest_interval_minutes)


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
    interval_minutes = _effective_interval_minutes()
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
    if age_minutes >= interval_minutes:
        return True, (
            f"the last run finished {age_minutes:.0f} min ago, over the "
            f"{interval_minutes} min interval"
        )
    return False, (
        f"the last run finished {age_minutes:.0f} min ago, inside the "
        f"{interval_minutes} min interval"
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


# ---------------------------------------------------------------------------
# Startup steps (CONTRACT_MOBILE_ADMIN.md sections 3.9 and 6.6)
# ---------------------------------------------------------------------------


def enforce_security_configuration() -> None:
    """Refuse to start a signed deployment that is missing a secret.

    Section 3.9 makes this a hard stop rather than a warning, because a process
    that starts with an empty DEVICE_MASTER_KEY would derive every device
    secret from nothing and look perfectly healthy while doing it. The messages
    name the variable and never its value, so they are safe in a log.

    With REQUIRE_SIGNED_REQUESTS false there is nothing to validate and the
    development-only warning is logged instead.
    """
    settings = get_settings()
    problems = settings.validate_security()
    if not problems:
        if not settings.require_signed_requests:
            logger.warning(UNSIGNED_MODE_WARNING)
        return
    for problem in problems:
        logger.error("%s", problem)
    raise RuntimeError(SECURITY_REFUSED_MESSAGE)


def seed_feature_flags() -> int:
    """Create any missing feature flag row. Returns how many were added.

    Idempotent, and it never touches a row that already exists, so a category
    an admin switched off stays off across restarts.
    """
    try:
        added = repo.seed_feature_flags(config_public.default_flag_rows())
    except sqlite3.Error:
        logger.exception("the feature flag defaults could not be seeded")
        return 0
    if added:
        logger.info("seeded %d feature flag default(s)", added)
    return added


def bootstrap_admin() -> str | None:
    """Create the configured bootstrap admin when there is no admin yet.

    A no-op unless both ADMIN_BOOTSTRAP_USERNAME and ADMIN_BOOTSTRAP_PASSWORD
    are set and admin_users is empty. Only the username is ever logged.
    """
    try:
        return admin_cli.ensure_bootstrap_admin()
    except sqlite3.Error:
        logger.exception("the bootstrap admin could not be created")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bring the application up in the order section 3.9 requires.

    The security check runs before anything is served and after the schema is
    in place, so a refusal is a clean startup failure rather than a half open
    API.
    """
    db_file = init_db()
    applied = migrate_database()
    logger.info(
        "database ready at %s%s",
        db_file,
        f", migration applied: {', '.join(applied)}" if applied else "",
    )
    enforce_security_configuration()
    seed_feature_flags()
    bootstrap_admin()
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

# Security headers, the 256 KB body cap and the {"detail", "code"} error body.
# Without this call every coded failure still returns the right status, but the
# contract's code strings vanish from the body.
#
# Installed before CORS on purpose. add_middleware puts the newest layer
# outermost, so adding CORS after this puts it outside the body cap, and the
# 413 that cap answers with still carries the CORS headers a browser needs to
# read it.
install_security(app)

# Strict CORS (contract 2, section 3.2). The origin list is explicit and never
# "*", and allow_credentials stays false because this API authenticates with a
# bearer header rather than a cookie: with no cookie to protect there is
# nothing to gain from credentialed requests and plenty to lose.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=False,
    allow_methods=CORS_METHODS,
    allow_headers=CORS_HEADERS,
    expose_headers=["X-Response-Time-Ms", "Retry-After"],
    max_age=600,
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


def include_optional_routers(application: FastAPI) -> list[str]:
    """Mount the routers another agent owns, if they are present.

    Returns the module names that were mounted. A module that is not there yet
    costs one warning naming the routes it would have provided, rather than an
    import error that would take the whole API down with it.
    """
    mounted: list[str] = []
    for module_name, description in _OPTIONAL_ROUTERS:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            logger.warning(
                "%s is not present, so %s are not available", module_name, description
            )
            continue
        except Exception:  # noqa: BLE001 - a broken module must not stop startup
            logger.exception("%s could not be imported", module_name)
            continue
        router = getattr(module, "router", None)
        if router is None:
            logger.warning("%s exposes no router", module_name)
            continue
        application.include_router(router)
        mounted.append(module_name)
    return mounted


app.include_router(feed.router)
app.include_router(search.router)
app.include_router(bookmarks.router)
app.include_router(meta.router)
app.include_router(config_public.router)
app.include_router(admin_pipeline.router)
app.include_router(admin_content.router)
app.include_router(admin_flags.router)
include_optional_routers(app)


__all__ = [
    "API_TITLE",
    "API_VERSION",
    "CORS_HEADERS",
    "CORS_METHODS",
    "SECURITY_REFUSED_MESSAGE",
    "app",
    "bootstrap_admin",
    "enforce_security_configuration",
    "include_optional_routers",
    "lifespan",
    "root",
    "seed_feature_flags",
]
