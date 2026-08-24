"""Importance score tests (contract section 8).

The two properties the contract names are covered first: adding sources never
lowers the score, and an older article scores below an otherwise identical
newer one. The rest pin the weights, the publisher tiers, the decay cap and
the 0 to 100 clamp. Nothing here touches the network or the database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.pipeline import score

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


def iso(hours_ago: float) -> str:
    """A published_at that many hours before the fixed test clock."""
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def article(**overrides: Any) -> dict[str, Any]:
    """A plain article dict with everything the score reads."""
    base: dict[str, Any] = {
        "headline": "Reliance Q1 profit rises 12 percent",
        "category": "earnings",
        "impact": "medium",
        "is_breaking": False,
        "published_at": iso(1),
        "symbols": [{"symbol": "RELIANCE", "exchange": "NSE", "kind": "stock"}],
        "sources": [{"publisher": "Reuters", "url": "https://reuters.com/a"}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Property 1: adding sources never lowers the score
# ---------------------------------------------------------------------------

SOURCE_POOL: tuple[str, ...] = (
    "https://smallblog.example/one",
    "https://anotherblog.example/two",
    "https://moneycontrol.com/three",
    "https://economictimes.indiatimes.com/four",
    "https://reuters.com/five",
    "https://bloomberg.com/six",
    "https://livemint.com/seven",
    "https://business-standard.com/eight",
    "https://reuters.com/nine-same-domain",
)


def test_adding_sources_never_lowers_the_score() -> None:
    story = article(sources=[])
    previous = score.compute_importance(story, NOW)
    for count in range(1, len(SOURCE_POOL) + 1):
        story["sources"] = [
            {"publisher": "x", "url": url} for url in SOURCE_POOL[:count]
        ]
        current = score.compute_importance(story, NOW)
        assert current >= previous, (count, previous, current)
        previous = current


def test_source_points_cap_at_six_distinct_domains() -> None:
    six = article(
        sources=[{"publisher": "x", "url": url} for url in SOURCE_POOL[:6]]
    )
    nine = article(
        sources=[{"publisher": "x", "url": url} for url in SOURCE_POOL[:9]]
    )
    # Domains seven and eight add nothing because the count is already capped
    # and the best tier is already tier 1.
    assert score.compute_importance(nine, NOW) == score.compute_importance(six, NOW)


def test_a_repeated_domain_counts_once() -> None:
    single = article(sources=[{"publisher": "Reuters", "url": "https://reuters.com/a"}])
    repeated = article(
        sources=[
            {"publisher": "Reuters", "url": "https://reuters.com/a"},
            {"publisher": "Reuters", "url": "https://reuters.com/b"},
            {"publisher": "Reuters", "url": "https://www.reuters.com/c"},
        ]
    )
    assert score.compute_importance(repeated, NOW) == score.compute_importance(
        single, NOW
    )


# ---------------------------------------------------------------------------
# Property 2: an older article scores below an identical newer one
# ---------------------------------------------------------------------------


def test_older_article_scores_below_an_identical_newer_one() -> None:
    newer = article(published_at=iso(1))
    older = article(published_at=iso(9))
    assert score.compute_importance(older, NOW) < score.compute_importance(newer, NOW)


def test_score_decays_strictly_hour_by_hour_until_the_cap() -> None:
    previous = score.compute_importance(article(impact="high", published_at=iso(0)), NOW)
    for hours in range(1, 20):
        current = score.compute_importance(
            article(impact="high", published_at=iso(hours)), NOW
        )
        assert current < previous, (hours, previous, current)
        previous = current


def test_decay_is_capped_at_thirty_points() -> None:
    assert score.decay_points(iso(48), NOW) == score.MAX_DECAY
    assert score.decay_points(iso(96), NOW) == score.MAX_DECAY
    old = score.compute_importance(article(published_at=iso(48)), NOW)
    ancient = score.compute_importance(article(published_at=iso(96)), NOW)
    assert old == ancient


def test_a_future_timestamp_is_not_rewarded() -> None:
    future = score.compute_importance(article(published_at=iso(-5)), NOW)
    fresh = score.compute_importance(article(published_at=iso(0)), NOW)
    assert future == fresh


# ---------------------------------------------------------------------------
# Publisher tiers
# ---------------------------------------------------------------------------


def test_publisher_tiers_match_the_contract() -> None:
    assert score.publisher_tier("https://www.reuters.com/world/india/x") == 1
    assert score.publisher_tier("https://www.bloomberg.com/news/x") == 1
    assert score.publisher_tier("https://www.rbi.org.in/press") == 1
    assert score.publisher_tier("https://www.sebi.gov.in/media") == 1
    assert score.publisher_tier("https://www.nseindia.com/x") == 1
    assert score.publisher_tier("https://www.ft.com/content/x") == 1
    assert score.publisher_tier("https://economictimes.indiatimes.com/x") == 2
    assert score.publisher_tier("https://www.moneycontrol.com/news/x") == 2
    assert score.publisher_tier("https://www.livemint.com/x") == 2
    assert score.publisher_tier("https://www.cnbctv18.com/x") == 2
    assert score.publisher_tier("https://www.ndtvprofit.com/x") == 2
    assert score.publisher_tier("https://randomblog.example/x") == 3
    assert score.publisher_tier("") == 3


def test_a_better_tier_raises_the_score() -> None:
    tier3 = article(sources=[{"publisher": "Blog", "url": "https://blog.example/a"}])
    tier1 = article(sources=[{"publisher": "Reuters", "url": "https://reuters.com/a"}])
    assert score.compute_importance(tier1, NOW) > score.compute_importance(tier3, NOW)


def test_no_sources_means_no_credibility_points() -> None:
    assert score.credibility_points([]) == 0
    assert score.credibility_points(None) == 0
    assert score.credibility_points(["https://reuters.com/a"]) == 12


# ---------------------------------------------------------------------------
# Weights, bonuses and clamping
# ---------------------------------------------------------------------------


def test_impact_weight_ordering() -> None:
    high = score.compute_importance(article(impact="high"), NOW)
    medium = score.compute_importance(article(impact="medium"), NOW)
    low = score.compute_importance(article(impact="low"), NOW)
    assert high > medium > low
    assert high - medium == score.IMPACT_WEIGHTS["high"] - score.IMPACT_WEIGHTS["medium"]


def test_breaking_adds_twelve_points() -> None:
    plain = score.compute_importance(article(), NOW)
    breaking = score.compute_importance(article(is_breaking=True), NOW)
    assert breaking - plain == score.BREAKING_POINTS


def test_an_index_tag_adds_ten_points() -> None:
    plain = score.compute_importance(article(), NOW)
    with_index = score.compute_importance(
        article(
            symbols=[
                {"symbol": "RELIANCE", "exchange": "NSE", "kind": "stock"},
                {"symbol": "NIFTY", "exchange": "INDEX", "kind": "index"},
            ]
        ),
        NOW,
    )
    assert with_index - plain == score.INDEX_POINTS


def test_category_weights_match_the_contract() -> None:
    baseline = score.compute_importance(article(category="crypto"), NOW)
    for category, points in score.CATEGORY_POINTS.items():
        value = score.compute_importance(article(category=category), NOW)
        assert value - baseline == points, category


def test_the_score_is_clamped_to_zero_and_one_hundred() -> None:
    best = article(
        impact="high",
        category="rbi",
        is_breaking=True,
        published_at=iso(0),
        symbols=[{"symbol": "NIFTY", "exchange": "INDEX", "kind": "index"}],
        sources=[
            {"publisher": "Reuters", "url": f"https://reuters{n}.com/a"} for n in range(3)
        ]
        + [{"publisher": "Reuters", "url": "https://reuters.com/a"}]
        + [{"publisher": "Mint", "url": f"https://livemint{n}.com/a"} for n in range(3)],
    )
    assert score.compute_importance(best, NOW) == 100

    worst = article(
        impact="low",
        category="crypto",
        published_at=iso(200),
        symbols=[],
        sources=[],
    )
    assert score.compute_importance(worst, NOW) == 0


def test_breakdown_components_sum_to_the_total() -> None:
    story = article(impact="high", is_breaking=True)
    parts = score.breakdown(story, NOW)
    total = parts.pop("total")
    assert score.round_half_up(sum(parts.values())) == total
    assert total == score.compute_importance(story, NOW)


def test_an_unparsable_timestamp_is_treated_as_brand_new() -> None:
    unknown = score.compute_importance(article(published_at="not a date"), NOW)
    fresh = score.compute_importance(article(published_at=iso(0)), NOW)
    assert unknown == fresh
