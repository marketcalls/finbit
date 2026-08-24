"""Shared fixtures for the FinBit backend test suite.

Two guarantees apply to every test in this directory:

- the database is a fresh temporary file with the real schema applied, so no
  test can ever read or damage backend/finbit.db,
- live Perplexity calls are disabled, so no test can spend money. Any code
  path that reaches the agent endpoint raises instead.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from app import db, repo
from app.pipeline import perplexity

# A realistic 58 word summary, comfortably over the 20 word floor that
# extract.py enforces.
SAMPLE_SUMMARY = (
    "Reliance Industries reported consolidated net profit of 19,878 crore rupees "
    "for the first quarter, up 12 percent from a year earlier. Revenue rose to "
    "2.58 lakh crore rupees on stronger retail and digital services growth. "
    "Refining margins held steady while telecom average revenue per user "
    "improved. The board did not announce an interim dividend. Management "
    "guided to steady capital expenditure for the rest of the year."
)


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path) -> Iterator[Path]:
    """Point the whole process at a fresh temporary database with the schema."""
    path = tmp_path / "finbit_test.db"
    db.set_db_path(path)
    db.init_db(path)
    try:
        yield db.get_db_path()
    finally:
        db.set_db_path(None)


@pytest.fixture(autouse=True)
def no_live_api_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn any accidental live agent call into a loud failure, never a cost."""

    async def _blocked(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(
            "live Perplexity calls are disabled in tests, patch the pipeline instead"
        )

    monkeypatch.setattr(perplexity.PerplexityClient, "run_agent", _blocked)


def make_sources(
    domains: Sequence[str], slug: str, published_at: str | None = None
) -> list[dict[str, Any]]:
    """One source link per domain, all pointing at the same story."""
    return [
        {
            "publisher": domain.split(".")[0],
            "title": slug.replace("-", " "),
            "url": f"https://{domain}/markets/{slug}",
            "published_at": published_at,
        }
        for domain in domains
    ]


def make_story(
    headline: str,
    *,
    slug: str = "story",
    summary: str = SAMPLE_SUMMARY,
    why_it_matters: str | None = "Read-through for Indian equities.",
    category: str = "earnings",
    sentiment: str = "positive",
    impact: str = "medium",
    impact_direction: str = "bullish",
    is_breaking: bool = False,
    symbols: Sequence[str] = ("RELIANCE",),
    topics: Sequence[str] = ("Q1 Earnings",),
    domains: Sequence[str] = ("reuters.com", "moneycontrol.com"),
    hours_ago: float = 3.0,
    impact_map: Sequence[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """A normalized story dict shaped exactly like extract.normalize_story output."""
    published_at = repo.iso_hours_ago(hours_ago)
    sources = make_sources(domains, slug, published_at)
    return {
        "headline": headline,
        "summary": summary,
        "why_it_matters": why_it_matters,
        "category": category,
        "sentiment": sentiment,
        "impact": impact,
        "impact_direction": impact_direction,
        "is_breaking": is_breaking,
        "symbols": [
            {"symbol": s, "exchange": "NSE", "kind": "stock"} for s in symbols
        ],
        "topics": list(topics),
        "sources": sources,
        "impact_map": list(impact_map or [{"name": "NIFTY", "direction": "positive"}]),
        "published_at": published_at,
        "source_count": len(set(domains)),
    }


# The four paraphrases of one Reliance earnings story from the MVP spec. They
# share source domains because extract.py merges the same search_results list
# into every story of a batch, which is exactly what happens in production.
RELIANCE_PARAPHRASES: tuple[str, ...] = (
    "Reliance Q1 profit rises 12%",
    "Reliance reports 12% profit growth",
    "RIL Q1 earnings beat expectations",
    "Reliance earnings: profit jumps 12%",
)


@pytest.fixture()
def reliance_stories() -> list[dict[str, Any]]:
    """The four Reliance earnings paraphrases as normalized story dicts.

    The first one is the oldest, the way a wire story lands before the
    paraphrases that follow it.
    """
    return [
        make_story(headline, slug=f"reliance-q1-{index}", hours_ago=3.0 - index * 0.25)
        for index, headline in enumerate(RELIANCE_PARAPHRASES)
    ]


@pytest.fixture()
def story_factory():
    """The make_story helper, exposed as a fixture."""
    return make_story
