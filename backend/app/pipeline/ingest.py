"""One ingestion cycle, end to end (contract section 9).

A cycle opens an ingest_runs row, runs the selected queries against the
Perplexity Agent API with bounded concurrency, normalizes the stories, then
for each story either merges it into the cluster it duplicates or inserts it
as a new article. Every write goes through B1's repo functions, and the real
USD cost of every call is summed into the run row.

One failing query never kills the cycle: its error is recorded on the query
outcome and the other queries still persist their stories.

Command line, run from the backend directory:

    uv run python -m app.pipeline.ingest --once
    uv run python -m app.pipeline.ingest --queries india_markets,rbi --limit 3
    uv run python -m app.pipeline.ingest --rescore
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app import db, repo
from app.config import get_settings
from app.pipeline import dedupe, extract, queries, score
from app.pipeline.perplexity import PerplexityClient, PerplexityError

logger = logging.getLogger(__name__)

# How many recent articles a story is scored against, per persist batch.
CANDIDATE_LIMIT = 500

# Hard ceiling on stories requested from one query, whatever config says.
MAX_STORIES_PER_QUERY = 20

# The article fields a merge writes back. Identity columns are never touched.
MERGE_FIELDS: tuple[str, ...] = (
    "headline",
    "summary",
    "why_it_matters",
    "category",
    "sentiment",
    "impact",
    "impact_direction",
    "importance_score",
    "is_breaking",
    "source_count",
    "published_at",
    "symbols",
    "topics",
    "sources",
    "impact_map",
)

# Rotates the query set across scheduled cycles.
_cycle_counter = 0

# Serialises the persist step so dedupe always sees the previous batch. The
# loop it belongs to is tracked because a test runner or a second CLI call can
# create a fresh event loop, and a lock may not cross loops.
_persist_lock: asyncio.Lock | None = None
_persist_lock_loop: asyncio.AbstractEventLoop | None = None


@dataclass(slots=True)
class QueryOutcome:
    """What one query produced."""

    key: str
    label: str = ""
    stories_seen: int = 0
    stories_new: int = 0
    stories_merged: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    error: str | None = None

    @property
    def status(self) -> str:
        return "error" if self.error else "ok"


@dataclass(slots=True)
class CycleResult:
    """The outcome of one full cycle, mirroring the ingest_runs row."""

    run_id: int
    status: str = "ok"
    started_at: str = ""
    finished_at: str = ""
    queries: list[QueryOutcome] = field(default_factory=list)
    error: str | None = None

    @property
    def queries_run(self) -> int:
        return len(self.queries)

    @property
    def stories_seen(self) -> int:
        return sum(q.stories_seen for q in self.queries)

    @property
    def stories_new(self) -> int:
        return sum(q.stories_new for q in self.queries)

    @property
    def stories_merged(self) -> int:
        return sum(q.stories_merged for q in self.queries)

    @property
    def cost_usd(self) -> float:
        return round(sum(q.cost_usd for q in self.queries), 6)


# ---------------------------------------------------------------------------
# Persistence, all synchronous repo work
# ---------------------------------------------------------------------------


def _new_record(story: dict[str, Any], key: str) -> dict[str, Any]:
    """Build the row for a story that starts a new cluster."""
    record = {
        "story_cluster_id": key,
        "dedupe_key": key,
        "headline": story.get("headline"),
        "summary": story.get("summary"),
        "why_it_matters": story.get("why_it_matters"),
        "category": story.get("category"),
        "sentiment": story.get("sentiment"),
        "impact": story.get("impact"),
        "impact_direction": story.get("impact_direction"),
        "is_breaking": bool(story.get("is_breaking")),
        "source_count": story.get("source_count"),
        "published_at": story.get("published_at"),
        "symbols": story.get("symbols") or [],
        "topics": story.get("topics") or [],
        "sources": story.get("sources") or [],
        "impact_map": story.get("impact_map") or [],
    }
    record["importance_score"] = score.compute_importance(record)
    return record


def _apply_merge(existing: dict[str, Any], story: dict[str, Any]) -> dict[str, Any]:
    """Merge a story into a stored cluster and write the result back."""
    merged = dedupe.merge_articles(existing, story)
    merged["importance_score"] = score.compute_importance(merged)
    changes = {name: merged.get(name) for name in MERGE_FIELDS}
    repo.update_article(int(existing["id"]), changes)
    return merged


def _persist_one(
    story: dict[str, Any], candidates: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    """Store one normalized story. Returns ('new' or 'merged', record)."""
    key = dedupe.dedupe_key(story.get("headline"))

    existing = repo.get_article_by_dedupe_key(key)
    matched_score = 1.0
    if existing is None:
        existing, matched_score = dedupe.best_match(story, candidates)

    if existing is not None:
        merged = _apply_merge(existing, story)
        logger.info(
            "merge into cluster id=%s score=%.3f headline=%s",
            merged.get("id"),
            matched_score,
            story.get("headline"),
        )
        return "merged", merged

    record = _new_record(story, key)
    try:
        article_id = repo.insert_article(record)
    except sqlite3.IntegrityError:
        # The cluster id was taken between the lookup and the insert.
        clashing = repo.get_article_by_cluster_id(key)
        if clashing is None:
            raise
        merged = _apply_merge(clashing, story)
        return "merged", merged
    record["id"] = article_id
    logger.info("new article id=%d headline=%s", article_id, record["headline"])
    return "new", record


def persist_stories(stories: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """Store a batch of normalized stories. Returns (new, merged) counts.

    Synchronous on purpose: the caller runs it in a worker thread so the event
    loop keeps serving while SQLite writes.
    """
    if not stories:
        return 0, 0
    candidates = repo.find_dedupe_candidates(
        window_hours=dedupe.DEDUPE_WINDOW_HOURS, limit=CANDIDATE_LIMIT
    )
    new_count = 0
    merged_count = 0
    for story in stories:
        try:
            outcome, record = _persist_one(story, candidates)
        except (sqlite3.Error, ValueError, KeyError, TypeError):
            logger.exception("could not store story: %s", story.get("headline"))
            continue
        if outcome == "new":
            new_count += 1
            candidates.insert(0, record)
        else:
            merged_count += 1
            article_id = record.get("id")
            for index, candidate in enumerate(candidates):
                if candidate.get("id") == article_id:
                    candidates[index] = record
                    break
            else:
                candidates.insert(0, record)
    return new_count, merged_count


def rescore_recent(window_hours: int | None = None, limit: int | None = None) -> int:
    """Recompute the importance score of recent articles so the feed decays.

    Returns the number of articles whose score actually changed.
    """
    articles = repo.recent_articles_for_rescore(
        window_hours=window_hours or repo.DEFAULT_RESCORE_WINDOW_HOURS,
        limit=limit or repo.DEFAULT_RESCORE_LIMIT,
    )
    now = datetime.now(timezone.utc)
    updated = 0
    for article in articles:
        fresh = score.compute_importance(article, now)
        try:
            current = int(article.get("importance_score") or 0)
        except (TypeError, ValueError):
            current = 0
        if fresh != current and repo.set_importance_score(int(article["id"]), fresh):
            updated += 1
    logger.info("rescore pass: %d of %d articles updated", updated, len(articles))
    return updated


# ---------------------------------------------------------------------------
# The cycle
# ---------------------------------------------------------------------------


def open_run() -> int:
    """Open an ingest_runs row and return its id.

    The admin route calls this first so it can answer with a run id and let
    the cycle finish in the background.
    """
    return repo.start_ingest_run()


def next_cycle_index() -> int:
    """Advance and return the rotation counter for the query set."""
    global _cycle_counter
    index = _cycle_counter
    _cycle_counter += 1
    return index


def _lock() -> asyncio.Lock:
    """The persist lock for the running event loop, created on first use."""
    global _persist_lock, _persist_lock_loop
    loop = asyncio.get_running_loop()
    if _persist_lock is None or _persist_lock_loop is not loop:
        _persist_lock = asyncio.Lock()
        _persist_lock_loop = loop
    return _persist_lock


def _selected_queries(query_keys: Sequence[str] | None) -> list[dict[str, str]]:
    settings = get_settings()
    if query_keys:
        return queries.resolve_queries(query_keys)
    return queries.select_queries(next_cycle_index(), settings.ingest_queries_per_cycle)


async def _run_one_query(
    query: dict[str, str],
    limit: int,
    client: PerplexityClient,
    semaphore: asyncio.Semaphore,
) -> QueryOutcome:
    """Fetch, normalize and persist one query. Never raises."""
    outcome = QueryOutcome(key=query["key"], label=query.get("label", ""))
    started = time.perf_counter()
    try:
        async with semaphore:
            extraction = await extract.fetch_stories(query, limit, client=client)
        outcome.cost_usd = extraction.cost_usd
        outcome.stories_seen = len(extraction.stories)
        async with _lock():
            new_count, merged_count = await asyncio.to_thread(
                persist_stories, extraction.stories
            )
        outcome.stories_new = new_count
        outcome.stories_merged = merged_count
    except PerplexityError as exc:
        outcome.error = str(exc)
        logger.warning("query %s failed: %s", query["key"], exc)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - one query must never kill the cycle
        outcome.error = f"{type(exc).__name__}: {exc}"
        logger.exception("query %s failed", query["key"])
    outcome.latency_seconds = time.perf_counter() - started
    return outcome


async def run_cycle(
    query_keys: Sequence[str] | None = None,
    limit: int | None = None,
    run_id: int | None = None,
) -> CycleResult:
    """Run one full ingestion cycle and close its ingest_runs row."""
    settings = get_settings()
    started_at = repo.utcnow_iso()
    if run_id is None:
        run_id = await asyncio.to_thread(open_run)

    selected = _selected_queries(query_keys)
    per_query = int(limit or settings.ingest_max_stories_per_query)
    per_query = max(1, min(MAX_STORIES_PER_QUERY, per_query))
    result = CycleResult(run_id=run_id, started_at=started_at)

    if not settings.has_perplexity_key:
        result.status = "error"
        result.error = (
            "PERPLEXITY_API_KEY is not set. Add it to the .env file at the repo "
            "root before running the ingestion pipeline."
        )
        result.finished_at = repo.utcnow_iso()
        await asyncio.to_thread(
            repo.finish_ingest_run, run_id, "error", 0, 0, 0, 0, 0.0, result.error
        )
        logger.error("ingest cycle %d aborted: no API key", run_id)
        return result

    logger.info(
        "ingest cycle %d starting: queries=%s limit=%d concurrency=%d",
        run_id,
        ",".join(q["key"] for q in selected),
        per_query,
        settings.ingest_concurrency,
    )

    semaphore = asyncio.Semaphore(max(1, settings.ingest_concurrency))
    try:
        async with PerplexityClient() as client:
            outcomes = await asyncio.gather(
                *(
                    _run_one_query(query, per_query, client, semaphore)
                    for query in selected
                )
            )
        result.queries = list(outcomes)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the run row must always be closed
        result.error = f"{type(exc).__name__}: {exc}"
        result.status = "error"
        logger.exception("ingest cycle %d failed", run_id)

    failures = [q for q in result.queries if q.error]
    if result.status != "error":
        result.status = "error" if failures and len(failures) == len(result.queries) else "ok"
    if failures and not result.error:
        result.error = "; ".join(f"{q.key}: {q.error}" for q in failures)[:1000]
    result.finished_at = repo.utcnow_iso()

    await asyncio.to_thread(
        repo.finish_ingest_run,
        run_id,
        result.status,
        result.queries_run,
        result.stories_seen,
        result.stories_new,
        result.stories_merged,
        result.cost_usd,
        result.error,
    )
    logger.info(
        "ingest cycle %d finished: status=%s queries=%d seen=%d new=%d merged=%d "
        "cost=%.5f usd",
        run_id,
        result.status,
        result.queries_run,
        result.stories_seen,
        result.stories_new,
        result.stories_merged,
        result.cost_usd,
    )
    return result


def run_cycle_blocking(
    query_keys: Sequence[str] | None = None,
    limit: int | None = None,
    run_id: int | None = None,
) -> CycleResult:
    """Run one cycle from synchronous code, for the CLI and background tasks."""
    return asyncio.run(run_cycle(query_keys, limit, run_id))


# ---------------------------------------------------------------------------
# Command line entry point
# ---------------------------------------------------------------------------


def format_summary(result: CycleResult) -> str:
    """The per-query summary table printed by the CLI."""
    header = f"{'query':<16}{'seen':>6}{'new':>6}{'merged':>8}{'cost usd':>11}  status"
    rule = "-" * len(header)
    lines = [header, rule]
    for outcome in result.queries:
        lines.append(
            f"{outcome.key:<16}{outcome.stories_seen:>6}{outcome.stories_new:>6}"
            f"{outcome.stories_merged:>8}{outcome.cost_usd:>11.5f}  {outcome.status}"
        )
    lines.append(rule)
    lines.append(
        f"{'total':<16}{result.stories_seen:>6}{result.stories_new:>6}"
        f"{result.stories_merged:>8}{result.cost_usd:>11.5f}  {result.status}"
    )
    lines.append(f"run id {result.run_id}, total cost {result.cost_usd:.5f} USD")
    for outcome in result.queries:
        if outcome.error:
            lines.append(f"error in {outcome.key}: {outcome.error}")
    if result.error and not any(o.error for o in result.queries):
        lines.append(f"error: {result.error}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline.ingest",
        description="Run one FinBit ingestion cycle against the Perplexity Agent API.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run exactly one cycle and exit. This is the default behaviour.",
    )
    parser.add_argument(
        "--queries",
        default="",
        help=(
            "comma separated query keys, for example india_markets,rbi. "
            f"Known keys: {','.join(queries.QUERY_KEYS)}"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum stories requested per query (default INGEST_MAX_STORIES_PER_QUERY).",
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="only recompute importance scores, no API calls and no cost.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log every HTTP call and every merge decision.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    db.init_db()

    if args.rescore:
        updated = rescore_recent()
        print(f"rescored {updated} articles")
        return 0

    keys = [key.strip() for key in str(args.queries).split(",") if key.strip()]
    unknown = [key for key in keys if queries.get_query(key) is None]
    if unknown:
        print(f"unknown query keys: {', '.join(unknown)}")
        print(f"known keys: {', '.join(queries.QUERY_KEYS)}")
        return 2

    result = run_cycle_blocking(keys or None, args.limit)
    print(format_summary(result))
    return 0 if result.status == "ok" else 1


__all__ = [
    "CANDIDATE_LIMIT",
    "CycleResult",
    "MERGE_FIELDS",
    "QueryOutcome",
    "build_parser",
    "format_summary",
    "main",
    "next_cycle_index",
    "open_run",
    "persist_stories",
    "rescore_recent",
    "run_cycle",
    "run_cycle_blocking",
]


if __name__ == "__main__":
    sys.exit(main())
