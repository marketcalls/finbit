"""HTTP API tests for FinBit.

Every test runs against a throwaway SQLite file created by pytest, seeded
through the repository functions. Nothing here touches the network: the
background scheduler is disabled through INGEST_ENABLED and the ingestion
endpoint is never called.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, db, repo

DEVICE = "test-device-0001"
OTHER_DEVICE = "test-device-0002"
DEVICE_HEADERS = {"X-Device-Id": DEVICE}

# Seed fixtures. hours_ago drives published_at, so index 0 is the newest.
SEED: list[dict[str, Any]] = [
    {
        "hours_ago": 1,
        "headline": "RBI keeps the repo rate unchanged at 5.50 percent",
        "summary": (
            "The Monetary Policy Committee voted to hold the repo rate steady and kept "
            "the stance unchanged, pointing to a balanced inflation outlook and steady "
            "growth momentum across the domestic economy."
        ),
        "why_it_matters": "Rate sensitive lenders keep their existing margin assumptions.",
        "category": "rbi",
        "sentiment": "neutral",
        "impact": "high",
        "impact_direction": "neutral",
        "importance_score": 40,
        "is_breaking": True,
        "symbols": [
            {"symbol": "NIFTY", "exchange": "INDEX", "kind": "index"},
            {"symbol": "BANKNIFTY", "exchange": "INDEX", "kind": "index"},
        ],
        "topics": ["Monetary Policy", "Banking"],
        "sources": [
            {
                "publisher": "Reuters",
                "title": "RBI holds rates",
                "url": "https://www.reuters.com/india/rbi-holds",
                "published_at": None,
            }
        ],
        "impact_map": [{"name": "NIFTY", "direction": "neutral"}],
    },
    {
        "hours_ago": 2,
        "headline": "Reliance Industries posts a higher quarterly profit",
        "summary": (
            "Reliance Industries reported a rise in consolidated quarterly profit helped "
            "by its retail and digital services businesses, while the oil to chemicals "
            "segment held broadly steady on firmer refining margins."
        ),
        "why_it_matters": "Reliance carries the single largest weight on the headline index.",
        "category": "earnings",
        "sentiment": "positive",
        "impact": "high",
        "impact_direction": "bullish",
        "importance_score": 90,
        "is_breaking": False,
        "symbols": [{"symbol": "RELIANCE", "exchange": "NSE", "kind": "stock"}],
        "topics": ["Q1 Earnings"],
        "sources": [
            {
                "publisher": "Moneycontrol",
                "title": "Reliance Q1 profit rises",
                "url": "https://www.moneycontrol.com/reliance-q1",
                "published_at": None,
            },
            {
                "publisher": "Livemint",
                "title": None,
                "url": "https://www.livemint.com/reliance-q1",
                "published_at": None,
            },
        ],
        "impact_map": [{"name": "NIFTY", "direction": "positive"}],
    },
    {
        "hours_ago": 3,
        "headline": "TCS wins a large European deal",
        "summary": (
            "Tata Consultancy Services announced a multi year contract with a European "
            "client covering cloud migration and managed services, adding to an order "
            "book that the company says remains healthy this quarter."
        ),
        "why_it_matters": "Deal wins support the sector view on information technology spending.",
        "category": "stocks",
        "sentiment": "positive",
        "impact": "medium",
        "impact_direction": "bullish",
        "importance_score": 55,
        "is_breaking": False,
        "symbols": [
            {"symbol": "TCS", "exchange": "NSE", "kind": "stock"},
            {"symbol": "NIFTY", "exchange": "INDEX", "kind": "index"},
        ],
        "topics": ["IT Services"],
        "sources": [
            {
                "publisher": "Business Standard",
                "title": "TCS bags Europe contract",
                "url": "https://www.business-standard.com/tcs-deal",
                "published_at": None,
            }
        ],
        "impact_map": [{"name": "IT", "direction": "positive"}],
    },
    {
        "hours_ago": 4,
        "headline": "RBI tightens liquidity coverage norms for banks",
        "summary": (
            "The central bank issued revised liquidity coverage guidelines that raise the "
            "run off assumptions on digitally accessible deposits, giving lenders a "
            "transition window before the rules take effect."
        ),
        "why_it_matters": "Banks may hold more government securities, trimming lendable funds.",
        "category": "rbi",
        "sentiment": "mixed",
        "impact": "medium",
        "impact_direction": "bearish",
        "importance_score": 90,
        "is_breaking": False,
        "symbols": [{"symbol": "BANKNIFTY", "exchange": "INDEX", "kind": "index"}],
        "topics": ["Banking"],
        "sources": [
            {
                "publisher": "RBI",
                "title": "Draft liquidity norms",
                "url": "https://www.rbi.org.in/liquidity-norms",
                "published_at": None,
            }
        ],
        "impact_map": [{"name": "Banks", "direction": "negative"}],
    },
    {
        "hours_ago": 5,
        "headline": "Wall Street closes higher on softer inflation data",
        "summary": (
            "United States equity benchmarks finished the session higher after a cooler "
            "than expected inflation print revived expectations of an easier policy path, "
            "with technology shares leading the advance."
        ),
        "why_it_matters": None,
        "category": "global",
        "sentiment": "positive",
        "impact": "low",
        "impact_direction": "bullish",
        "importance_score": 20,
        "is_breaking": False,
        "symbols": [{"symbol": "AAPL", "exchange": "NASDAQ", "kind": "stock"}],
        "topics": ["US Markets"],
        "sources": [
            {
                "publisher": "Bloomberg",
                "title": "Stocks rally",
                "url": "https://www.bloomberg.com/us-close",
                "published_at": None,
            }
        ],
        "impact_map": [{"name": "NIFTY", "direction": "positive"}],
    },
    {
        "hours_ago": 6,
        "headline": "Gold holds near a record high as the dollar eases",
        "summary": (
            "Spot gold traded close to its record level as the dollar index slipped and "
            "traders positioned for a softer rate path, while domestic prices tracked the "
            "overseas move through the session."
        ),
        "why_it_matters": "Higher bullion prices lift jewellery input costs at home.",
        "category": "commodities",
        "sentiment": "positive",
        "impact": "medium",
        "impact_direction": "bullish",
        "importance_score": 70,
        "is_breaking": False,
        "symbols": [
            {"symbol": "GOLD", "exchange": "COMMODITY", "kind": "commodity"},
            {"symbol": "CRUDE", "exchange": "COMMODITY", "kind": "commodity"},
        ],
        "topics": ["Commodities"],
        "sources": [
            {
                "publisher": "Reuters",
                "title": "Gold steady",
                "url": "https://www.reuters.com/markets/gold-steady",
                "published_at": None,
            }
        ],
        "impact_map": [{"name": "GOLD", "direction": "positive"}],
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _no_background_ingest():
    """Keep the scheduler off for the whole session so no test can hit the network."""
    previous = os.environ.get("INGEST_ENABLED")
    os.environ["INGEST_ENABLED"] = "false"
    config.reset_settings_cache()
    yield
    if previous is None:
        os.environ.pop("INGEST_ENABLED", None)
    else:
        os.environ["INGEST_ENABLED"] = previous
    config.reset_settings_cache()


@pytest.fixture()
def client(tmp_path, _no_background_ingest):
    """A TestClient bound to an empty temporary database, lifespan included."""
    from app.main import app

    previous_db_path = getattr(db, "_db_path_override", None)
    db.set_db_path(tmp_path / "finbit-test.db")
    db.init_db()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        # Restore exactly what was set before, so a database path chosen by
        # another test module survives this fixture.
        db.set_db_path(previous_db_path)


@pytest.fixture()
def seeded_ids(client) -> list[int]:
    """Insert the seed articles and return their ids in seed order."""
    ids: list[int] = []
    for index, spec in enumerate(SEED):
        article = dict(spec)
        hours_ago = article.pop("hours_ago")
        article["published_at"] = repo.iso_hours_ago(hours_ago)
        article["story_cluster_id"] = f"seedcluster{index:04d}"
        article["dedupe_key"] = f"seedcluster{index:04d}"
        ids.append(repo.insert_article(article))
    return ids


def expected_order(ids: list[int], sort: str) -> list[int]:
    """Ids in the order the feed should return them for a given sort mode."""
    rows = [
        (ids[i], SEED[i]["importance_score"], SEED[i]["hours_ago"])
        for i in range(len(SEED))
    ]
    if sort == "top":
        rows.sort(key=lambda row: (-row[1], row[2], -row[0]))
    else:
        rows.sort(key=lambda row: (row[2], -row[0]))
    return [row[0] for row in rows]


def walk_feed(client: TestClient, params: dict[str, Any], page_size: int) -> list[int]:
    """Page through the whole feed and return the ids in the order seen."""
    seen: list[int] = []
    cursor: str | None = None
    for _ in range(20):
        query = dict(params)
        query["limit"] = page_size
        if cursor:
            query["cursor"] = cursor
        response = client.get("/api/feed", params=query)
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) <= page_size
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if not body["has_more"]:
            assert cursor is None
            break
        assert cursor
    return seen


# ---------------------------------------------------------------------------
# Root and health
# ---------------------------------------------------------------------------


def test_root_reports_name_and_docs(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["name"] == "FinBit API"
    assert body["docs"] == "/docs"
    assert body["version"]


def test_health_on_empty_database(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    # INGEST_ENABLED is false for the whole test session, so ingestion reports
    # itself as unavailable with a reason (contract 13.4 and 13.5).
    assert body == {
        "status": "ok",
        "articles": 0,
        "last_ingest_at": None,
        "last_ingest_status": None,
        "ingest_running": False,
        "ingest_enabled": False,
        "reason": body["reason"],
    }
    assert body["reason"]


def test_health_reports_a_running_ingest(client: TestClient) -> None:
    repo.start_ingest_run()
    body = client.get("/api/health").json()
    assert body["ingest_running"] is True
    assert body["last_ingest_status"] == "running"


def test_health_reports_ingest_enabled_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INGEST_ENABLED", "true")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key-not-real")
    config.reset_settings_cache()
    try:
        body = client.get("/api/health").json()
        assert body["ingest_enabled"] is True
        assert body["reason"] is None
    finally:
        config.reset_settings_cache()


def test_health_counts_articles_and_last_run(client: TestClient, seeded_ids: list[int]) -> None:
    run_id = repo.start_ingest_run()
    repo.finish_ingest_run(run_id, status="ok", queries_run=2, stories_new=1, cost_usd=0.012)
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["articles"] == len(seeded_ids)
    assert body["last_ingest_status"] == "ok"
    assert body["last_ingest_at"]


def test_feed_is_empty_on_empty_database(client: TestClient) -> None:
    body = client.get("/api/feed").json()
    assert body == {"items": [], "next_cursor": None, "has_more": False}


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------


def test_feed_card_shape(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/feed", params={"sort": "latest", "limit": 1}).json()
    card = body["items"][0]
    assert card["id"] == seeded_ids[0]
    assert card["headline"] == SEED[0]["headline"]
    assert card["category"] == "rbi"
    assert card["is_breaking"] is True
    assert card["bookmarked"] is False
    assert card["published_at"].endswith("Z")
    assert card["symbols"] == [
        {"symbol": "BANKNIFTY", "exchange": "INDEX", "kind": "index"},
        {"symbol": "NIFTY", "exchange": "INDEX", "kind": "index"},
    ]
    assert card["topics"] == ["Banking", "Monetary Policy"]
    assert card["sources"][0]["publisher"] == "Reuters"
    assert card["impact_map"] == [{"name": "NIFTY", "direction": "neutral"}]
    assert "dedupe_key" not in card
    assert "updated_at" not in card


def test_feed_pagination_top(client: TestClient, seeded_ids: list[int]) -> None:
    assert walk_feed(client, {"sort": "top"}, 2) == expected_order(seeded_ids, "top")


def test_feed_pagination_latest(client: TestClient, seeded_ids: list[int]) -> None:
    assert walk_feed(client, {"sort": "latest"}, 2) == expected_order(seeded_ids, "latest")


def test_feed_first_page_reports_more(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/feed", params={"limit": 2}).json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True
    assert body["next_cursor"]


def test_feed_category_filter(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/feed", params={"category": "rbi", "sort": "latest"}).json()
    assert [item["id"] for item in body["items"]] == [seeded_ids[0], seeded_ids[3]]
    assert body["has_more"] is False
    assert all(item["category"] == "rbi" for item in body["items"])


def test_feed_symbol_filter(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/feed", params={"symbol": "NIFTY", "sort": "latest"}).json()
    assert [item["id"] for item in body["items"]] == [seeded_ids[0], seeded_ids[2]]


def test_feed_unknown_category_falls_back_to_all(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/feed", params={"category": "not-a-category"}).json()
    assert len(body["items"]) == len(seeded_ids)


def test_feed_unparsable_cursor_returns_first_page(client: TestClient, seeded_ids: list[int]) -> None:
    first = client.get("/api/feed", params={"limit": 3}).json()
    for junk in ("not-a-cursor", "!!!!", "eyJ", "%%%"):
        response = client.get("/api/feed", params={"limit": 3, "cursor": junk})
        assert response.status_code == 200
        assert response.json() == first


def test_feed_limit_out_of_range_is_rejected(client: TestClient) -> None:
    assert client.get("/api/feed", params={"limit": 0}).status_code == 422
    assert client.get("/api/feed", params={"limit": 51}).status_code == 422


# ---------------------------------------------------------------------------
# Single article
# ---------------------------------------------------------------------------


def test_get_article(client: TestClient, seeded_ids: list[int]) -> None:
    response = client.get(f"/api/articles/{seeded_ids[1]}")
    assert response.status_code == 200
    card = response.json()
    assert card["id"] == seeded_ids[1]
    assert card["headline"] == SEED[1]["headline"]
    assert card["source_count"] == 2
    assert len(card["sources"]) == 2


def test_get_article_missing_returns_404(client: TestClient) -> None:
    response = client.get("/api/articles/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Article not found"}


def test_get_article_nullable_fields(client: TestClient, seeded_ids: list[int]) -> None:
    card = client.get(f"/api/articles/{seeded_ids[4]}").json()
    assert card["why_it_matters"] is None
    assert card["sources"][0]["published_at"] is None
    assert card["topics"] == ["US Markets"]


# ---------------------------------------------------------------------------
# Search and trending
# ---------------------------------------------------------------------------


def test_search_finds_a_headline_term(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/search", params={"q": "reliance"}).json()
    assert body["query"] == "reliance"
    assert body["count"] == len(body["items"])
    assert seeded_ids[1] in [item["id"] for item in body["items"]]


def test_search_matches_a_symbol(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/search", params={"q": "BANKNIFTY"}).json()
    found = {item["id"] for item in body["items"]}
    assert {seeded_ids[0], seeded_ids[3]} <= found


def test_search_short_query_returns_422(client: TestClient) -> None:
    assert client.get("/api/search", params={"q": "a"}).status_code == 422
    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_search_missing_query_returns_422(client: TestClient) -> None:
    assert client.get("/api/search").status_code == 422


def test_search_punctuation_does_not_raise(client: TestClient, seeded_ids: list[int]) -> None:
    for query in ('""', 'gold OR "', "rbi AND (", "50% *", "a*b", "**"):
        response = client.get("/api/search", params={"q": query})
        assert response.status_code == 200
        assert isinstance(response.json()["items"], list)


def test_search_respects_limit(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/search", params={"q": "the", "limit": 2}).json()
    assert len(body["items"]) <= 2
    assert client.get("/api/search", params={"q": "the", "limit": 51}).status_code == 422


def test_trending_on_empty_database(client: TestClient) -> None:
    assert client.get("/api/trending").json() == {"symbols": [], "topics": []}


def test_trending_ranks_symbols_and_topics(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/trending").json()
    # NIFTY and BANKNIFTY are tagged twice each, so they lead, ties broken by name.
    assert set(body["symbols"][:2]) == {"BANKNIFTY", "NIFTY"}
    assert "RELIANCE" in body["symbols"]
    assert body["topics"][0] == "Banking"
    assert "Monetary Policy" in body["topics"]
    assert len(body["symbols"]) <= 12
    assert len(body["topics"]) <= 12


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def test_categories_on_empty_database(client: TestClient) -> None:
    body = client.get("/api/categories").json()
    assert [entry["key"] for entry in body["categories"]][:3] == ["all", "india", "global"]
    assert all(entry["count"] == 0 for entry in body["categories"])
    assert [entry["key"] for entry in body["market_filters"]] == [
        "NIFTY",
        "BANKNIFTY",
        "SENSEX",
        "USDINR",
        "GOLD",
        "CRUDE",
    ]


def test_categories_counts(client: TestClient, seeded_ids: list[int]) -> None:
    body = client.get("/api/categories").json()
    counts = {entry["key"]: entry["count"] for entry in body["categories"]}
    assert counts["all"] == len(seeded_ids)
    assert counts["rbi"] == 2
    assert counts["crypto"] == 0
    labels = {entry["key"]: entry["label"] for entry in body["categories"]}
    assert labels["all"] == "All"
    assert labels["sebi"] == "SEBI"


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------


def test_bookmark_add_list_remove_cycle(client: TestClient, seeded_ids: list[int]) -> None:
    article_id = seeded_ids[2]

    added = client.post("/api/bookmarks", json={"article_id": article_id}, headers=DEVICE_HEADERS)
    assert added.status_code == 200
    assert added.json() == {"article_id": article_id, "bookmarked": True}

    # Idempotent: saving twice is not an error and does not duplicate the row.
    again = client.post("/api/bookmarks", json={"article_id": article_id}, headers=DEVICE_HEADERS)
    assert again.json() == {"article_id": article_id, "bookmarked": True}

    listed = client.get("/api/bookmarks", headers=DEVICE_HEADERS).json()
    assert listed["count"] == 1
    assert listed["items"][0]["id"] == article_id
    assert listed["items"][0]["bookmarked"] is True

    removed = client.delete(f"/api/bookmarks/{article_id}", headers=DEVICE_HEADERS)
    assert removed.status_code == 200
    assert removed.json() == {"article_id": article_id, "bookmarked": False}

    # Removing twice stays a 200 with the same body.
    removed_again = client.delete(f"/api/bookmarks/{article_id}", headers=DEVICE_HEADERS)
    assert removed_again.json() == {"article_id": article_id, "bookmarked": False}

    emptied = client.get("/api/bookmarks", headers=DEVICE_HEADERS).json()
    assert emptied == {"items": [], "count": 0}


def test_bookmarks_are_per_device(client: TestClient, seeded_ids: list[int]) -> None:
    article_id = seeded_ids[0]
    client.post("/api/bookmarks", json={"article_id": article_id}, headers=DEVICE_HEADERS)

    mine = client.get("/api/bookmarks", headers=DEVICE_HEADERS).json()
    theirs = client.get("/api/bookmarks", headers={"X-Device-Id": OTHER_DEVICE}).json()
    assert mine["count"] == 1
    assert theirs["count"] == 0


def test_feed_carries_the_bookmarked_flag(client: TestClient, seeded_ids: list[int]) -> None:
    article_id = seeded_ids[5]
    client.post("/api/bookmarks", json={"article_id": article_id}, headers=DEVICE_HEADERS)

    body = client.get("/api/feed", params={"limit": 50}, headers=DEVICE_HEADERS).json()
    flags = {item["id"]: item["bookmarked"] for item in body["items"]}
    assert flags[article_id] is True
    assert all(value is False for key, value in flags.items() if key != article_id)

    anonymous = client.get("/api/feed", params={"limit": 50}).json()
    assert all(item["bookmarked"] is False for item in anonymous["items"])

    single = client.get(f"/api/articles/{article_id}", headers=DEVICE_HEADERS).json()
    assert single["bookmarked"] is True

    found = client.get("/api/search", params={"q": "gold"}, headers=DEVICE_HEADERS).json()
    assert any(item["id"] == article_id and item["bookmarked"] for item in found["items"])


def test_bookmark_write_without_device_header_returns_400(
    client: TestClient, seeded_ids: list[int]
) -> None:
    response = client.post("/api/bookmarks", json={"article_id": seeded_ids[0]})
    assert response.status_code == 400
    assert response.json() == {"detail": "X-Device-Id header is required"}

    blank = client.post(
        "/api/bookmarks",
        json={"article_id": seeded_ids[0]},
        headers={"X-Device-Id": "   "},
    )
    assert blank.status_code == 400

    deleted = client.delete(f"/api/bookmarks/{seeded_ids[0]}")
    assert deleted.status_code == 400


def test_bookmark_list_without_device_header_is_anonymous(
    client: TestClient, seeded_ids: list[int]
) -> None:
    assert client.get("/api/bookmarks").json() == {"items": [], "count": 0}


def test_bookmark_unknown_article_returns_404(client: TestClient) -> None:
    response = client.post("/api/bookmarks", json={"article_id": 999999}, headers=DEVICE_HEADERS)
    assert response.status_code == 404
    assert response.json() == {"detail": "Article not found"}


def test_bookmark_body_must_carry_an_article_id(client: TestClient) -> None:
    assert client.post("/api/bookmarks", json={}, headers=DEVICE_HEADERS).status_code == 422


# ---------------------------------------------------------------------------
# Admin runs
# ---------------------------------------------------------------------------


def test_admin_runs_empty(client: TestClient) -> None:
    assert client.get("/api/admin/runs").json() == []


def test_admin_ingest_without_a_key_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract 13.4: no key means 503 naming the key, and no run row."""
    monkeypatch.setenv("PERPLEXITY_API_KEY", "")
    config.reset_settings_cache()
    try:
        response = client.post("/api/admin/ingest", json={})
        assert response.status_code == 503
        assert "PERPLEXITY_API_KEY" in response.json()["detail"]
        assert client.get("/api/admin/runs").json() == []
    finally:
        config.reset_settings_cache()


def test_admin_ingest_gated_off_returns_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract 13.3: the money-spending trigger can be turned off."""
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ALLOW_ADMIN_INGEST_FROM_UI", "false")
    config.reset_settings_cache()
    try:
        response = client.post("/api/admin/ingest", json={})
        assert response.status_code == 403
        assert "ALLOW_ADMIN_INGEST_FROM_UI" in response.json()["detail"]
        assert client.get("/api/admin/runs").json() == []
    finally:
        config.reset_settings_cache()


# ---------------------------------------------------------------------------
# Startup ingest decision (contract 13.2). Pure decision logic, no API calls.
# ---------------------------------------------------------------------------


@pytest.fixture()
def startup_env(monkeypatch: pytest.MonkeyPatch):
    """Settings with ingestion fully available, so only the guard is under test.

    These tests never build a TestClient, so no lifespan runs and no cycle can
    ever be scheduled by them.
    """
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key-not-real")
    monkeypatch.setenv("INGEST_ENABLED", "true")
    monkeypatch.setenv("INGEST_ON_STARTUP", "true")
    monkeypatch.setenv("INGEST_INTERVAL_MINUTES", "15")
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


def seed_one_article() -> int:
    """Insert a single article straight through the repository."""
    spec = dict(SEED[0])
    spec.pop("hours_ago")
    spec["published_at"] = repo.iso_hours_ago(1)
    spec["story_cluster_id"] = "startupcluster0001"
    spec["dedupe_key"] = "startupcluster0001"
    return repo.insert_article(spec)


def test_startup_ingest_runs_on_an_empty_database(startup_env) -> None:
    from app.main import _startup_ingest_decision

    run_it, why = _startup_ingest_decision()
    assert run_it is True
    assert "no articles" in why


def test_startup_ingest_skips_a_recent_run(startup_env) -> None:
    from app.main import _startup_ingest_decision

    seed_one_article()
    run_id = repo.start_ingest_run()
    repo.finish_ingest_run(run_id, status="ok", queries_run=4)
    run_it, why = _startup_ingest_decision()
    assert run_it is False
    assert "inside the 15 min interval" in why


def test_startup_ingest_runs_when_the_last_run_is_stale(
    startup_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main as main_module

    seed_one_article()
    repo.start_ingest_run()
    monkeypatch.setattr(
        main_module.repo, "last_ingest_finished_at", lambda: repo.iso_hours_ago(2)
    )
    run_it, why = main_module._startup_ingest_decision()
    assert run_it is True
    assert "over the 15 min interval" in why


def test_startup_ingest_fires_and_does_not_block_startup(
    startup_env, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seeding cycle runs on the loop while the API already answers.

    run_cycle is replaced, so this never reaches the network. conftest also
    blocks the agent call itself, so a failed patch cannot spend money.
    """
    from app.main import app
    from app.pipeline import ingest as ingest_module

    calls: list[int] = []

    async def fake_run_cycle(*args, **kwargs):
        calls.append(1)
        run_id = repo.start_ingest_run()
        repo.finish_ingest_run(run_id, status="ok", queries_run=4, cost_usd=0.0237)
        return ingest_module.CycleResult(run_id=run_id, status="ok")

    monkeypatch.setattr(ingest_module, "run_cycle", fake_run_cycle)

    previous_db_path = getattr(db, "_db_path_override", None)
    db.set_db_path(tmp_path / "finbit-startup.db")
    db.init_db()
    try:
        with TestClient(app) as test_client:
            for _ in range(40):
                # The API answers while the seed cycle is still in flight.
                assert test_client.get("/api/health").status_code == 200
                if calls:
                    break
                time.sleep(0.05)
            assert calls, "the startup ingest cycle never ran"
            assert test_client.get("/api/admin/runs").json()[0]["status"] == "ok"
    finally:
        db.set_db_path(previous_db_path)


def test_startup_ingest_respects_the_off_switch(
    startup_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import _startup_ingest_decision

    monkeypatch.setenv("INGEST_ON_STARTUP", "false")
    config.reset_settings_cache()
    run_it, why = _startup_ingest_decision()
    assert run_it is False
    assert "INGEST_ON_STARTUP is false" in why


def test_startup_ingest_skipped_without_a_key(
    startup_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import _startup_ingest_decision

    monkeypatch.setenv("PERPLEXITY_API_KEY", "")
    config.reset_settings_cache()
    run_it, why = _startup_ingest_decision()
    assert run_it is False
    assert "PERPLEXITY_API_KEY" in why


def test_admin_runs_newest_first(client: TestClient) -> None:
    first = repo.start_ingest_run()
    repo.finish_ingest_run(
        first,
        status="ok",
        queries_run=4,
        stories_seen=18,
        stories_new=6,
        stories_merged=3,
        cost_usd=0.0241,
    )
    second = repo.start_ingest_run()
    repo.finish_ingest_run(second, status="error", error="upstream timeout")

    rows = client.get("/api/admin/runs").json()
    assert [row["id"] for row in rows] == [second, first]
    assert rows[0]["status"] == "error"
    assert rows[0]["error"] == "upstream timeout"
    assert rows[1]["cost_usd"] == pytest.approx(0.0241)
    assert rows[1]["queries_run"] == 4
    assert rows[1]["stories_merged"] == 3
