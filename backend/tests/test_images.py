"""Card image resolution and the image column migration (contract section 14).

Nothing here touches the network. The parser tests run over saved HTML, and
the fetch tests drive a httpx.MockTransport, so the whole file is free and
deterministic.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import db, repo
from app.models import ArticleCard
from app.pipeline import images, ingest

# ---------------------------------------------------------------------------
# Saved HTML fixtures, trimmed to the head the resolver actually reads.
# ---------------------------------------------------------------------------

PAGE_URL = "https://www.reuters.com/markets/india/rbi-holds-rates-2026-08-24/"

OG_IMAGE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>RBI holds the repo rate</title>
  <meta property="og:title" content="RBI holds the repo rate">
  <meta property="og:image" content="https://cdn.reuters.com/resizer/rbi-lead.jpg?w=1200&amp;h=630">
  <meta property="og:image:width" content="1200">
</head>
<body><p>Body text the resolver must never read.</p></body>
</html>
"""

SECURE_URL_HTML = """
<head>
  <meta property="og:image" content="http://images.example.com/plain.jpg">
  <meta property="og:image:secure_url" content="https://images.example.com/secure.jpg">
  <meta name="twitter:image" content="https://images.example.com/twitter.jpg">
</head>
"""

TWITTER_ONLY_HTML = """
<head>
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="https://img.moneycontrol.com/lead-1200x630.jpg">
</head>
"""

TWITTER_IMAGE_SRC_HTML = """
<head>
  <meta name="twitter:image:src" content="https://img.livemint.com/story-lead.jpg">
</head>
"""

NAME_ATTRIBUTE_HTML = """
<head>
  <meta name="og:image" content="https://images.business-standard.com/lead.jpg">
</head>
"""

PROTOCOL_RELATIVE_HTML = """
<head>
  <meta property='og:image' content='//images.cnbctv18.com/wp-content/lead.jpg'>
</head>
"""

RELATIVE_PATH_HTML = """
<head>
  <meta property="og:image" content="/static/2026/08/lead.jpg">
</head>
"""

DATA_URI_HTML = """
<head>
  <meta property="og:image" content="data:image/gif;base64,R0lGODlhAQABAAAAACw=">
  <meta name="twitter:image" content="https://img.financialexpress.com/real-lead.jpg">
</head>
"""

DATA_URI_ONLY_HTML = """
<head>
  <meta property="og:image" content="data:image/png;base64,iVBORw0KGgo=">
</head>
"""

NO_TAG_HTML = """
<head>
  <title>Watch this video</title>
  <meta name="description" content="A page with no card image at all.">
</head>
<body><h1>No Open Graph tags here</h1></body>
"""

EMPTY_CONTENT_HTML = """
<head>
  <meta property="og:image" content="">
  <meta property="og:image:secure_url" content="   ">
  <meta name="twitter:image" content="https://img.ndtvprofit.com/fallback.jpg">
</head>
"""


# ---------------------------------------------------------------------------
# extract_og_image: pure and network free
# ---------------------------------------------------------------------------


def test_og_image_is_extracted() -> None:
    assert (
        images.extract_og_image(OG_IMAGE_HTML, PAGE_URL)
        == "https://cdn.reuters.com/resizer/rbi-lead.jpg?w=1200&h=630"
    )


def test_secure_url_wins_over_plain_og_image() -> None:
    assert (
        images.extract_og_image(SECURE_URL_HTML, PAGE_URL)
        == "https://images.example.com/secure.jpg"
    )


def test_twitter_image_is_the_fallback() -> None:
    assert (
        images.extract_og_image(TWITTER_ONLY_HTML, PAGE_URL)
        == "https://img.moneycontrol.com/lead-1200x630.jpg"
    )


def test_twitter_image_src_is_accepted() -> None:
    assert (
        images.extract_og_image(TWITTER_IMAGE_SRC_HTML, PAGE_URL)
        == "https://img.livemint.com/story-lead.jpg"
    )


def test_name_attribute_is_matched_as_well_as_property() -> None:
    assert (
        images.extract_og_image(NAME_ATTRIBUTE_HTML, PAGE_URL)
        == "https://images.business-standard.com/lead.jpg"
    )


def test_protocol_relative_url_resolves_against_https() -> None:
    assert (
        images.extract_og_image(PROTOCOL_RELATIVE_HTML, PAGE_URL)
        == "https://images.cnbctv18.com/wp-content/lead.jpg"
    )


def test_relative_path_resolves_against_the_page_url() -> None:
    assert (
        images.extract_og_image(RELATIVE_PATH_HTML, PAGE_URL)
        == "https://www.reuters.com/static/2026/08/lead.jpg"
    )


def test_data_uri_is_rejected_and_the_next_tag_wins() -> None:
    assert (
        images.extract_og_image(DATA_URI_HTML, PAGE_URL)
        == "https://img.financialexpress.com/real-lead.jpg"
    )


def test_a_data_uri_on_its_own_resolves_to_nothing() -> None:
    assert images.extract_og_image(DATA_URI_ONLY_HTML, PAGE_URL) is None


def test_page_with_no_tag_resolves_to_nothing() -> None:
    assert images.extract_og_image(NO_TAG_HTML, PAGE_URL) is None
    assert images.extract_og_image("", PAGE_URL) is None


def test_empty_content_falls_through_to_the_next_key() -> None:
    assert (
        images.extract_og_image(EMPTY_CONTENT_HTML, PAGE_URL)
        == "https://img.ndtvprofit.com/fallback.jpg"
    )


def test_javascript_and_relative_values_without_a_base_are_rejected() -> None:
    assert images.normalize_image_url("javascript:alert(1)") is None
    assert images.normalize_image_url("/static/lead.jpg") is None
    assert images.normalize_image_url(None) is None
    assert images.normalize_image_url("") is None


def test_head_end_marker_truncates_the_document() -> None:
    html = "<head><meta property='og:image' content='https://x.test/a.jpg'></head>"
    html += "<body>" + "z" * 5000 + "</body>"
    truncated = images.truncate_at_head_end(html)
    assert truncated.endswith("</head>")
    assert "z" not in truncated


# ---------------------------------------------------------------------------
# Candidate ordering
# ---------------------------------------------------------------------------


def test_candidates_are_tier_ordered_capped_and_deduplicated() -> None:
    sources = [
        {"publisher": "Some Blog", "url": "https://randomblog.example/story"},
        {"publisher": "Moneycontrol", "url": "https://www.moneycontrol.com/news/a"},
        {"publisher": "Reuters", "url": "https://www.reuters.com/markets/b"},
        {"publisher": "Reuters", "url": "https://www.reuters.com/markets/b"},
        {"publisher": "Mint", "url": "https://www.livemint.com/market/c"},
        {"publisher": "NSE", "url": "https://nsearchives.nseindia.com/circular.pdf"},
    ]
    urls = images.candidate_urls(sources)
    assert urls == [
        "https://www.reuters.com/markets/b",
        "https://www.moneycontrol.com/news/a",
        "https://www.livemint.com/market/c",
    ]


def test_candidates_ignore_unusable_urls() -> None:
    assert images.candidate_urls([]) == []
    assert images.candidate_urls(None) == []
    assert images.candidate_urls([{"url": "not a url"}, {"url": ""}]) == []
    assert images.candidate_urls(["https://www.reuters.com/a"]) == [
        "https://www.reuters.com/a"
    ]


# ---------------------------------------------------------------------------
# resolve_image over a mock transport
# ---------------------------------------------------------------------------


def mock_client(handler) -> httpx.AsyncClient:
    """An AsyncClient wired to a handler instead of the network."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers=images.REQUEST_HEADERS,
    )


def html_response(body: str, content_type: str = "text/html; charset=utf-8"):
    return httpx.Response(200, content=body.encode("utf-8"), headers={"content-type": content_type})


async def test_resolve_image_uses_the_best_tier_that_has_one() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        assert request.headers["user-agent"] == images.USER_AGENT
        return html_response(OG_IMAGE_HTML)

    sources = [
        {"url": "https://www.moneycontrol.com/news/a"},
        {"url": "https://www.reuters.com/markets/b"},
    ]
    async with mock_client(handler) as client:
        image_url, source_url = await images.resolve_image(sources, client)

    assert image_url == "https://cdn.reuters.com/resizer/rbi-lead.jpg?w=1200&h=630"
    assert source_url == "https://www.reuters.com/markets/b"
    assert seen == ["https://www.reuters.com/markets/b"]


async def test_a_403_falls_through_to_the_next_candidate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "investing.com" in str(request.url):
            return httpx.Response(403, content=b"forbidden")
        return html_response(TWITTER_ONLY_HTML)

    sources = [
        {"url": "https://in.investing.com/news/a"},
        {"url": "https://www.moneycontrol.com/news/b"},
    ]
    async with mock_client(handler) as client:
        image_url, source_url = await images.resolve_image(sources, client)

    assert image_url == "https://img.moneycontrol.com/lead-1200x630.jpg"
    assert source_url == "https://www.moneycontrol.com/news/b"


async def test_a_non_html_content_type_is_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "feeds" in str(request.url):
            return httpx.Response(
                200,
                content=b"%PDF-1.7 binary",
                headers={"content-type": "application/pdf"},
            )
        return html_response(TWITTER_IMAGE_SRC_HTML)

    sources = [
        {"url": "https://feeds.example.com/report"},
        {"url": "https://www.livemint.com/market/c"},
    ]
    async with mock_client(handler) as client:
        image_url, source_url = await images.resolve_image(sources, client)

    assert image_url == "https://img.livemint.com/story-lead.jpg"
    assert source_url == "https://www.livemint.com/market/c"


async def test_a_redirect_chain_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/short":
            return httpx.Response(301, headers={"location": "/hop"})
        if path == "/hop":
            return httpx.Response(302, headers={"location": "/final"})
        return html_response(OG_IMAGE_HTML)

    async with mock_client(handler) as client:
        image_url, source_url = await images.resolve_image(
            [{"url": "https://www.reuters.com/short"}], client
        )

    assert image_url == "https://cdn.reuters.com/resizer/rbi-lead.jpg?w=1200&h=630"
    # The recorded page is the source link, which is what the card credits.
    assert source_url == "https://www.reuters.com/short"


async def test_a_connection_timeout_is_not_fatal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    async with mock_client(handler) as client:
        assert await images.resolve_image(
            [{"url": "https://www.reuters.com/slow"}], client
        ) == (None, None)


async def test_a_page_with_no_tag_resolves_to_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return html_response(NO_TAG_HTML)

    async with mock_client(handler) as client:
        assert await images.resolve_image(
            [{"url": "https://www.youtube.com/watch"}], client
        ) == (None, None)


async def test_no_candidate_means_no_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("an article with no usable source must not fetch")

    async with mock_client(handler) as client:
        assert await images.resolve_image([], client) == (None, None)


async def test_reading_stops_at_the_head_end() -> None:
    body = "<body>" + ("x" * 400_000) + "</body>"

    def handler(request: httpx.Request) -> httpx.Response:
        return html_response(OG_IMAGE_HTML + body)

    async with mock_client(handler) as client:
        html = await images.fetch_head_html("https://www.reuters.com/a", client)

    assert html is not None
    assert html.endswith("</head>")
    assert len(html) < 2000


async def test_a_tag_past_the_byte_cap_is_not_read() -> None:
    filler = "<!-- " + ("y" * (images.MAX_HEAD_BYTES + 1000)) + " -->"
    page = "<html><head>" + filler + OG_IMAGE_HTML

    def handler(request: httpx.Request) -> httpx.Response:
        return html_response(page)

    async with mock_client(handler) as client:
        html = await images.fetch_head_html("https://www.reuters.com/a", client)

    assert html is not None
    assert len(html) <= images.MAX_HEAD_BYTES
    assert images.extract_og_image(html, "https://www.reuters.com/a") is None


async def test_resolve_images_keeps_input_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "reuters" in str(request.url):
            return html_response(OG_IMAGE_HTML)
        return html_response(NO_TAG_HTML)

    async with mock_client(handler) as client:
        results = await images.resolve_images(
            [
                [{"url": "https://www.youtube.com/watch"}],
                [{"url": "https://www.reuters.com/markets/b"}],
                [],
            ],
            concurrency=2,
            client=client,
        )

    assert results == [
        (None, None),
        (
            "https://cdn.reuters.com/resizer/rbi-lead.jpg?w=1200&h=630",
            "https://www.reuters.com/markets/b",
        ),
        (None, None),
    ]


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

LEGACY_ARTICLES_DDL = """
CREATE TABLE IF NOT EXISTS articles (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  story_cluster_id  TEXT    NOT NULL UNIQUE,
  headline          TEXT    NOT NULL,
  summary           TEXT    NOT NULL,
  why_it_matters    TEXT,
  category          TEXT    NOT NULL,
  sentiment         TEXT    NOT NULL DEFAULT 'neutral',
  impact            TEXT    NOT NULL DEFAULT 'low',
  impact_direction  TEXT    NOT NULL DEFAULT 'neutral',
  importance_score  INTEGER NOT NULL DEFAULT 0,
  is_breaking       INTEGER NOT NULL DEFAULT 0,
  source_count      INTEGER NOT NULL DEFAULT 0,
  published_at      TEXT    NOT NULL,
  created_at        TEXT    NOT NULL,
  updated_at        TEXT    NOT NULL,
  dedupe_key        TEXT    NOT NULL
);
"""

LEGACY_ROW = (
    "cluster-legacy-01",
    "RBI holds the repo rate at 5.50%",
    "A summary written before the card image columns existed.",
    "rbi",
    "2026-08-24T09:15:00Z",
    "2026-08-24T09:22:11Z",
    "2026-08-24T09:22:11Z",
    "cluster-legacy-01",
)


def _write_legacy_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(LEGACY_ARTICLES_DDL)
        conn.execute(
            "INSERT INTO articles (story_cluster_id, headline, summary, category, "
            "published_at, created_at, updated_at, dedupe_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            LEGACY_ROW,
        )
        conn.commit()
    finally:
        conn.close()


def test_migrate_adds_the_columns_once_and_is_a_no_op_after(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    _write_legacy_db(legacy)

    conn = sqlite3.connect(str(legacy))
    conn.row_factory = sqlite3.Row
    try:
        assert "image_url" not in db.table_columns(conn, "articles")

        added = db.migrate(conn)
        conn.commit()
        assert added == [
            "articles.image_url",
            "articles.image_source_url",
            "articles.image_checked_at",
        ]

        columns = db.table_columns(conn, "articles")
        for column in ("image_url", "image_source_url", "image_checked_at"):
            assert column in columns

        # The second run must add nothing and must not raise.
        assert db.migrate(conn) == []
        assert db.table_columns(conn, "articles") == columns

        row = conn.execute("SELECT * FROM articles").fetchone()
        assert row["headline"] == LEGACY_ROW[1]
        assert row["summary"] == LEGACY_ROW[2]
        assert row["dedupe_key"] == LEGACY_ROW[7]
        assert row["image_url"] is None
        assert row["image_checked_at"] is None
    finally:
        conn.close()


def test_init_db_migrates_an_existing_database_without_losing_rows(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy_init.db"
    _write_legacy_db(legacy)
    original = db.get_db_path()
    try:
        db.init_db(legacy)
        conn = db.connect(legacy)
        try:
            assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
            row = conn.execute("SELECT * FROM articles").fetchone()
            assert row["headline"] == LEGACY_ROW[1]
            assert row["image_source_url"] is None
        finally:
            conn.close()
        # A second init_db on the same file is still a no-op.
        db.init_db(legacy)
    finally:
        db.set_db_path(original)


def test_a_fresh_database_already_carries_the_columns() -> None:
    conn = db.connect()
    try:
        columns = db.table_columns(conn, "articles")
        assert "image_url" in columns
        assert "image_source_url" in columns
        assert "image_checked_at" in columns
        assert db.migrate(conn) == []
    finally:
        conn.close()


def test_migrate_ignores_a_table_that_does_not_exist(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "empty.db"))
    try:
        assert db.migrate(conn) == []
        assert db.table_columns(conn, "articles") == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Persistence and the API surface
# ---------------------------------------------------------------------------


def _article(story_factory, **overrides: Any) -> dict[str, Any]:
    story = story_factory(overrides.pop("headline", "RBI holds the repo rate"))
    story["story_cluster_id"] = overrides.pop("story_cluster_id", "cluster-image-01")
    story["dedupe_key"] = story["story_cluster_id"]
    story.update(overrides)
    return story


def test_image_columns_round_trip(story_factory) -> None:
    record = _article(
        story_factory,
        image_url="https://cdn.reuters.com/lead.jpg",
        image_source_url="https://www.reuters.com/markets/b",
        image_checked_at="2026-08-24T10:00:00Z",
    )
    article_id = repo.insert_article(record)

    stored = repo.get_article(article_id)
    assert stored is not None
    assert stored["image_url"] == "https://cdn.reuters.com/lead.jpg"
    assert stored["image_source_url"] == "https://www.reuters.com/markets/b"
    assert stored["image_checked_at"] == "2026-08-24T10:00:00Z"


def test_image_url_is_on_the_card_and_the_internals_are_not(story_factory) -> None:
    article_id = repo.insert_article(
        _article(
            story_factory,
            image_url="https://cdn.reuters.com/lead.jpg",
            image_source_url="https://www.reuters.com/markets/b",
            image_checked_at="2026-08-24T10:00:00Z",
        )
    )
    card = ArticleCard.model_validate(repo.get_article(article_id))
    payload = card.model_dump()

    assert payload["image_url"] == "https://cdn.reuters.com/lead.jpg"
    assert "image_source_url" not in payload
    assert "image_checked_at" not in payload


def test_feed_endpoint_exposes_image_url_only(story_factory) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    repo.insert_article(
        _article(
            story_factory,
            image_url="https://cdn.reuters.com/lead.jpg",
            image_source_url="https://www.reuters.com/markets/b",
            image_checked_at="2026-08-24T10:00:00Z",
        )
    )
    with TestClient(app) as client:
        body = client.get("/api/feed").json()

    item = body["items"][0]
    assert item["image_url"] == "https://cdn.reuters.com/lead.jpg"
    assert "image_source_url" not in item
    assert "image_checked_at" not in item


def test_an_article_without_an_image_reports_null(story_factory) -> None:
    article_id = repo.insert_article(_article(story_factory))
    card = ArticleCard.model_validate(repo.get_article(article_id))
    assert card.image_url is None


def test_set_article_image_stamps_a_miss(story_factory) -> None:
    article_id = repo.insert_article(_article(story_factory))
    assert repo.set_article_image(article_id, None, None) is True

    stored = repo.get_article(article_id)
    assert stored is not None
    assert stored["image_url"] is None
    assert stored["image_checked_at"] is not None
    assert repo.set_article_image(999_999, None, None) is False


def test_articles_needing_images_skips_checked_ones(story_factory) -> None:
    unchecked = repo.insert_article(
        _article(story_factory, headline="First RBI story", story_cluster_id="c-1")
    )
    checked = repo.insert_article(
        _article(story_factory, headline="Second RBI story", story_cluster_id="c-2")
    )
    repo.set_article_image(checked, None, None)

    pending = [row["id"] for row in repo.articles_needing_images()]
    assert pending == [unchecked]


def test_image_checked_keys_reports_only_checked_clusters(story_factory) -> None:
    first = repo.insert_article(
        _article(story_factory, headline="First RBI story", story_cluster_id="c-1")
    )
    repo.insert_article(
        _article(story_factory, headline="Second RBI story", story_cluster_id="c-2")
    )
    repo.set_article_image(first, "https://cdn.example.com/a.jpg", "https://a.test/x")

    assert repo.image_checked_keys(["c-1", "c-2", "c-3"]) == {"c-1"}
    assert repo.image_checked_keys([]) == set()
    assert repo.image_checked_keys(None) == set()


def test_update_article_can_clear_an_image(story_factory) -> None:
    article_id = repo.insert_article(
        _article(story_factory, image_url="https://cdn.reuters.com/lead.jpg")
    )
    assert repo.update_article(article_id, {"image_url": None}) is True
    stored = repo.get_article(article_id)
    assert stored is not None
    assert stored["image_url"] is None


# ---------------------------------------------------------------------------
# Merge and ingest behaviour
# ---------------------------------------------------------------------------


def test_merge_keeps_the_existing_image(story_factory) -> None:
    existing = {
        "image_url": "https://cdn.reuters.com/kept.jpg",
        "image_source_url": "https://www.reuters.com/a",
        "image_checked_at": "2026-08-24T10:00:00Z",
    }
    incoming = {
        "image_url": "https://img.moneycontrol.com/new.jpg",
        "image_source_url": "https://www.moneycontrol.com/b",
        "image_checked_at": "2026-08-24T12:00:00Z",
    }
    merged = dict(existing)
    ingest._merge_image(merged, existing, incoming)

    assert merged["image_url"] == "https://cdn.reuters.com/kept.jpg"
    assert merged["image_source_url"] == "https://www.reuters.com/a"
    assert merged["image_checked_at"] == "2026-08-24T10:00:00Z"


def test_merge_takes_the_incoming_image_when_there_is_none(story_factory) -> None:
    existing = {
        "image_url": None,
        "image_source_url": None,
        "image_checked_at": None,
    }
    incoming = {
        "image_url": "https://img.moneycontrol.com/new.jpg",
        "image_source_url": "https://www.moneycontrol.com/b",
        "image_checked_at": "2026-08-24T12:00:00Z",
    }
    merged = dict(existing)
    ingest._merge_image(merged, existing, incoming)

    assert merged["image_url"] == "https://img.moneycontrol.com/new.jpg"
    assert merged["image_source_url"] == "https://www.moneycontrol.com/b"
    assert merged["image_checked_at"] == "2026-08-24T12:00:00Z"


def test_persisting_a_story_stores_its_resolved_image(story_factory) -> None:
    story = story_factory("Nifty ends higher on banking strength")
    story["image_url"] = "https://cdn.reuters.com/lead.jpg"
    story["image_source_url"] = "https://www.reuters.com/markets/b"
    story["image_checked_at"] = "2026-08-24T10:00:00Z"

    new_count, merged_count = ingest.persist_stories([story])
    assert (new_count, merged_count) == (1, 0)

    stored = repo.list_feed()["items"][0]
    assert stored["image_url"] == "https://cdn.reuters.com/lead.jpg"


async def test_resolve_story_images_skips_a_checked_cluster(
    story_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.pipeline import dedupe

    checked_headline = "RBI keeps the repo rate unchanged"
    stored_id = repo.insert_article(
        _article(
            story_factory,
            headline=checked_headline,
            story_cluster_id=dedupe.dedupe_key(checked_headline),
        )
    )
    repo.update_article(
        stored_id, {"dedupe_key": dedupe.dedupe_key(checked_headline)}
    )
    repo.set_article_image(stored_id, None, None)

    calls: list[list[Any]] = []

    async def fake_resolve_images(source_lists, concurrency=1, client=None):
        calls.append(list(source_lists))
        return [("https://cdn.example.com/lead.jpg", "https://a.test/page")] * len(
            source_lists
        )

    monkeypatch.setattr(images, "resolve_images", fake_resolve_images)

    already_checked = story_factory(checked_headline)
    fresh = story_factory("Sensex jumps 400 points on IT buying")
    found = await ingest.resolve_story_images([already_checked, fresh])

    assert found == 1
    assert len(calls) == 1 and len(calls[0]) == 1
    assert "image_url" not in already_checked
    assert fresh["image_url"] == "https://cdn.example.com/lead.jpg"
    assert fresh["image_source_url"] == "https://a.test/page"
    assert fresh["image_checked_at"]


async def test_resolve_story_images_survives_a_resolver_failure(story_factory) -> None:
    story = story_factory("Rupee steadies against the dollar")

    async def boom(*args: Any, **kwargs: Any):
        raise RuntimeError("publisher unreachable")

    original = images.resolve_images
    images.resolve_images = boom  # type: ignore[assignment]
    try:
        assert await ingest.resolve_story_images([story]) == 0
    finally:
        images.resolve_images = original  # type: ignore[assignment]

    assert await ingest.resolve_story_images([]) == 0


async def test_backfill_resolves_stored_articles_once(
    story_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.insert_article(
        _article(story_factory, headline="First RBI story", story_cluster_id="c-1")
    )
    repo.insert_article(
        _article(story_factory, headline="Second RBI story", story_cluster_id="c-2")
    )

    async def fake_resolve_images(source_lists, concurrency=1, client=None):
        return [("https://cdn.example.com/lead.jpg", "https://a.test/page")] + [
            (None, None)
        ] * (len(source_lists) - 1)

    monkeypatch.setattr(images, "resolve_images", fake_resolve_images)

    assert await ingest.backfill_images() == 1
    # Every article is stamped, so the second pass has nothing left to do.
    assert repo.articles_needing_images() == []
    assert await ingest.backfill_images() == 0
