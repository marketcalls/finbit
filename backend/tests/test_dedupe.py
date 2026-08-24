"""Deduplication tests (contract section 7).

The three cases the contract names are covered twice: once against the pure
functions in dedupe.py, and once through ingest.persist_stories so the real
database path is proved as well. Nothing here touches the network.
"""

from __future__ import annotations

from typing import Any

from app import repo
from app.pipeline import dedupe, ingest

from tests.conftest import make_story


# ---------------------------------------------------------------------------
# In-memory clustering, the same decision order the pipeline uses
# ---------------------------------------------------------------------------


def cluster_stories(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster stories exactly the way ingest does, without a database."""
    clusters: list[dict[str, Any]] = []
    for story in stories:
        key = dedupe.dedupe_key(story["headline"])
        target: dict[str, Any] | None = None
        for existing in clusters:
            if existing["dedupe_key"] == key:
                target = existing
                break
        if target is None:
            target, _score = dedupe.best_match(story, clusters)
        if target is None:
            fresh = dict(story)
            fresh["id"] = len(clusters) + 1
            fresh["dedupe_key"] = key
            fresh["story_cluster_id"] = key
            clusters.append(fresh)
            continue
        for index, existing in enumerate(clusters):
            if existing["id"] == target["id"]:
                clusters[index] = dedupe.merge_articles(existing, story)
                break
    return clusters


# ---------------------------------------------------------------------------
# Headline normalization
# ---------------------------------------------------------------------------


def test_normalize_headline_drops_stopwords_and_punctuation() -> None:
    tokens = dedupe.normalize_headline("The RBI, at last, is holding the repo rate")
    assert "the" not in tokens
    assert "at" not in tokens
    assert "is" not in tokens
    assert "reservebank" in tokens
    assert "repo" in tokens


def test_normalize_headline_expands_the_contract_aliases() -> None:
    assert "reliance" in dedupe.normalize_headline("RIL board meets today")
    assert "statebank" in dedupe.normalize_headline("SBI raises deposit rates")
    assert "reservebank" in dedupe.normalize_headline("RBI holds repo rate")
    assert "percent" in dedupe.normalize_headline("Nifty up 2 pct")
    assert "percent" in dedupe.normalize_headline("Nifty up 2%")


def test_normalize_headline_keeps_quarter_tokens() -> None:
    assert "q1" in dedupe.normalize_headline("Infosys Q1 revenue in line")
    assert "q3" in dedupe.normalize_headline("Wipro Q3 margin holds")


def test_dedupe_key_is_stable_and_order_independent() -> None:
    first = dedupe.dedupe_key("Nifty ends higher as banks rally")
    second = dedupe.dedupe_key("As banks rally, Nifty ends higher")
    assert first == second
    assert len(first) == dedupe.DEDUPE_KEY_LENGTH
    assert first == dedupe.dedupe_key("Nifty ends higher as banks rally")


def test_jaccard_treats_two_empty_sets_as_zero() -> None:
    assert dedupe.jaccard(set(), set()) == 0.0
    assert dedupe.jaccard({"a"}, set()) == 0.0
    assert dedupe.jaccard({"a", "b"}, {"a"}) == 0.5


# ---------------------------------------------------------------------------
# Case 1: an exact duplicate merges
# ---------------------------------------------------------------------------


def test_exact_duplicate_shares_a_dedupe_key() -> None:
    original = "Reliance Q1 profit rises 12%"
    restated = "Reliance Q1 profit rises 12 pct!"
    assert dedupe.dedupe_key(original) == dedupe.dedupe_key(restated)


def test_exact_duplicate_merges_into_one_cluster() -> None:
    stories = [
        make_story("Reliance Q1 profit rises 12%", slug="wire"),
        make_story("Reliance Q1 profit rises 12 pct", slug="paraphrase"),
    ]
    clusters = cluster_stories(stories)
    assert len(clusters) == 1


def test_exact_duplicate_merges_in_the_database() -> None:
    stories = [
        make_story("Reliance Q1 profit rises 12%", slug="wire", hours_ago=4.0),
        make_story("Reliance Q1 profit rises 12 pct", slug="paraphrase", hours_ago=3.0),
    ]
    new_count, merged_count = ingest.persist_stories(stories)
    assert (new_count, merged_count) == (1, 1)
    assert repo.count_articles() == 1


# ---------------------------------------------------------------------------
# Case 2: the four Reliance earnings paraphrases collapse to one cluster
# ---------------------------------------------------------------------------


def test_four_reliance_paraphrases_collapse_to_one_cluster(
    reliance_stories: list[dict[str, Any]],
) -> None:
    clusters = cluster_stories(reliance_stories)
    assert len(clusters) == 1, [c["headline"] for c in clusters]

    merged = clusters[0]
    # The cluster identity is the dedupe key of the first article in it.
    assert merged["story_cluster_id"] == dedupe.dedupe_key(
        reliance_stories[0]["headline"]
    )
    # The earliest publication time wins.
    assert merged["published_at"] == reliance_stories[0]["published_at"]
    # Sources are unioned and source_count is the distinct domain count.
    assert len(merged["sources"]) == 8
    assert merged["source_count"] == 2


def test_every_reliance_pair_scores_over_the_threshold(
    reliance_stories: list[dict[str, Any]],
) -> None:
    first = reliance_stories[0]
    for other in reliance_stories[1:]:
        score = dedupe.similarity(first, other)
        assert score >= dedupe.SIMILARITY_THRESHOLD, (other["headline"], score)


def test_four_reliance_paraphrases_become_one_row(
    reliance_stories: list[dict[str, Any]],
) -> None:
    new_count, merged_count = ingest.persist_stories(reliance_stories)
    assert (new_count, merged_count) == (1, 3)
    assert repo.count_articles() == 1

    feed = repo.list_feed(sort="latest")
    assert len(feed["items"]) == 1
    article = feed["items"][0]
    assert article["headline"] == reliance_stories[0]["headline"]
    assert article["source_count"] == 2
    assert article["published_at"] == reliance_stories[0]["published_at"]
    assert {s["symbol"] for s in article["symbols"]} == {"RELIANCE"}


# ---------------------------------------------------------------------------
# Case 3: two genuinely different stories stay separate
# ---------------------------------------------------------------------------


def test_two_different_stories_stay_separate() -> None:
    stories = [
        make_story(
            "RBI keeps repo rate unchanged at 5.50%",
            slug="rbi-policy",
            category="rbi",
            symbols=("BANKNIFTY",),
        ),
        make_story(
            "TCS wins a large cloud deal in Europe",
            slug="tcs-deal",
            category="stocks",
            symbols=("TCS",),
        ),
    ]
    assert dedupe.similarity(stories[0], stories[1]) < dedupe.SIMILARITY_THRESHOLD
    assert len(cluster_stories(stories)) == 2


def test_two_different_stories_stay_separate_in_the_database() -> None:
    stories = [
        make_story(
            "RBI keeps repo rate unchanged at 5.50%",
            slug="rbi-policy",
            category="rbi",
            symbols=("BANKNIFTY",),
        ),
        make_story(
            "TCS wins a large cloud deal in Europe",
            slug="tcs-deal",
            category="stocks",
            symbols=("TCS",),
        ),
    ]
    new_count, merged_count = ingest.persist_stories(stories)
    assert (new_count, merged_count) == (2, 0)
    assert repo.count_articles() == 2


def test_same_company_different_events_stay_separate() -> None:
    stories = [
        make_story("Reliance Q1 profit rises 12%", slug="earnings"),
        make_story(
            "Reliance announces a new retail expansion plan",
            slug="retail",
            category="stocks",
        ),
    ]
    assert dedupe.similarity(stories[0], stories[1]) < dedupe.SIMILARITY_THRESHOLD
    assert len(cluster_stories(stories)) == 2


# ---------------------------------------------------------------------------
# Merge rules
# ---------------------------------------------------------------------------


def test_merge_articles_follows_every_contract_rule() -> None:
    existing = make_story(
        "Reliance Q1 profit rises 12%",
        slug="wire",
        hours_ago=6.0,
        impact="low",
        why_it_matters="Short note.",
        topics=("Q1 Earnings",),
        domains=("reuters.com",),
        impact_map=[{"name": "NIFTY", "direction": "positive"}],
    )
    existing["id"] = 7
    existing["story_cluster_id"] = "abc123"
    existing["dedupe_key"] = "abc123"
    existing["is_breaking"] = False

    incoming = make_story(
        "Reliance Q1 earnings jump 12%",
        slug="follow-up",
        hours_ago=2.0,
        impact="high",
        why_it_matters=(
            "A longer read-through: heavier index weight means the Nifty follows "
            "Reliance on results day."
        ),
        symbols=("RELIANCE", "NIFTY"),
        topics=("Oil and Gas",),
        domains=("moneycontrol.com",),
        impact_map=[{"name": "Refiners", "direction": "positive"}],
    )
    incoming["is_breaking"] = True

    merged = dedupe.merge_articles(existing, incoming)

    assert merged["id"] == 7
    assert merged["story_cluster_id"] == "abc123"
    assert merged["dedupe_key"] == "abc123"
    assert merged["headline"] == existing["headline"]
    assert merged["published_at"] == existing["published_at"]
    assert merged["impact"] == "high"
    assert merged["is_breaking"] is True
    assert merged["why_it_matters"] == incoming["why_it_matters"]
    assert {s["symbol"] for s in merged["symbols"]} == {"RELIANCE", "NIFTY"}
    assert merged["topics"] == ["Q1 Earnings", "Oil and Gas"]
    assert len(merged["sources"]) == 2
    assert merged["source_count"] == 2
    assert [entry["name"] for entry in merged["impact_map"]] == ["NIFTY", "Refiners"]


def test_merge_keeps_the_higher_impact_either_way() -> None:
    high = make_story("Reliance Q1 profit rises 12%", impact="high")
    low = make_story("Reliance Q1 profit rises 12%", impact="low")
    assert dedupe.merge_articles(high, low)["impact"] == "high"
    assert dedupe.merge_articles(low, high)["impact"] == "high"


def test_merge_updates_the_stored_row(
    reliance_stories: list[dict[str, Any]],
) -> None:
    ingest.persist_stories(reliance_stories[:1])
    stored = repo.list_feed(sort="latest")["items"][0]
    assert stored["source_count"] == 2

    ingest.persist_stories(reliance_stories[1:])
    assert repo.count_articles() == 1
    updated = repo.get_article(stored["id"])
    assert updated is not None
    assert len(updated["sources"]) == 8
    assert updated["story_cluster_id"] == stored["story_cluster_id"]
