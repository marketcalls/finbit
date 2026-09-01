"""The admin surface: sign in, the pipeline, moderation, flags and the audit log.

The admin screens are the only part of this API that authenticates a person
rather than an install, so the tests here are about two different risks.

The first is the door. A login route that answers differently for an unknown
username than for a wrong password is an account enumeration tool, and one with
no lockout is a password guessing tool. Both are asserted below on the response
body rather than on a clock, because a timing assertion in a test suite is a
flake waiting to happen: the equal work is checked by counting the argon2
verification instead.

The second is blast radius. Every admin route changes what every reader sees,
so each of the four screens is driven end to end and then checked from the
public side: an article an admin hides really does leave the feed, a category
an admin switches off really does leave /api/config, and maintenance mode
really does take the content routes down while leaving /api/config answering.
Every one of those mutations has to leave an audit_log row behind
(CONTRACT_MOBILE_ADMIN.md section 3.8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import admin_cli, config, db, deps, repo
from app.routers import admin_auth
from app.security import passwords, tokens
from tests.conftest import (
    HEADER_TEST_UNSIGNED,
    SAMPLE_SUMMARY,
    SignedClient,
    audit_rows,
)

USERNAME = "finbit-admin"
PASSWORD = "correct-horse-battery-staple"
WRONG_PASSWORD = "incorrect-horse-battery-staple"

LOGIN = "/api/admin/auth/login"
CONFIG = "/api/config"
FEED = "/api/feed"

# Every admin route, so the token sweep cannot miss one that was added later.
# A body is sent where one is required, but it never gets that far: the
# dependency raises before FastAPI validates it.
ADMIN_ROUTES: tuple[tuple[str, str, Any], ...] = (
    ("GET", "/api/admin/pipeline", None),
    ("PATCH", "/api/admin/pipeline", {}),
    ("POST", "/api/admin/pipeline/ingest", {}),
    ("POST", "/api/admin/pipeline/rescore", None),
    ("POST", "/api/admin/pipeline/images", None),
    ("GET", "/api/admin/pipeline/queries", None),
    ("PUT", "/api/admin/pipeline/queries", {"queries": []}),
    ("GET", "/api/admin/articles", None),
    ("PATCH", "/api/admin/articles/1", {"hidden": True}),
    ("DELETE", "/api/admin/articles/1", None),
    ("POST", "/api/admin/articles/1/rescore", None),
    ("POST", "/api/admin/articles/1/refresh-image", None),
    ("GET", "/api/admin/articles/1/cluster", None),
    ("GET", "/api/admin/flags", None),
    ("PUT", "/api/admin/flags", {}),
    ("GET", "/api/admin/auth/me", None),
    ("POST", "/api/admin/auth/logout", None),
)


def failure(response: Any) -> tuple[int, str]:
    """The status and the contract code of a refused request."""
    body = response.json()
    assert set(body) >= {"detail", "code"}, body
    return response.status_code, body["code"]


@dataclass
class AdminSession:
    """A signed in admin. Bearer only: no app key and no signature.

    The admin screens hold a short lived token in memory and authenticate with
    a password, so adding a signature there would put a shared secret in a
    browser bundle for nothing (app/deps.py).
    """

    client: TestClient
    username: str
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            HEADER_TEST_UNSIGNED: "1",
        }

    def request(self, method: str, path: str, body: Any = None) -> Any:
        return self.client.request(
            method, path, json=body, headers=self.headers
        )

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, body)

    def patch(self, path: str, body: Any = None) -> Any:
        return self.request("PATCH", path, body)

    def put(self, path: str, body: Any = None) -> Any:
        return self.request("PUT", path, body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)


def unauthenticated(client: TestClient, method: str, path: str, body: Any = None) -> Any:
    """A call with no Authorization header at all."""
    return client.request(
        method, path, json=body, headers={HEADER_TEST_UNSIGNED: "1"}
    )


def login(client: TestClient, username: str, password: str) -> Any:
    """One sign in attempt, unsigned and unauthenticated by design."""
    return client.post(
        LOGIN,
        json={"username": username, "password": password},
        headers={HEADER_TEST_UNSIGNED: "1"},
    )


@pytest.fixture()
def admin_account(api_client: TestClient) -> str:
    """One admin account, created the only way the contract allows: the CLI."""
    return admin_cli.create_admin(USERNAME, PASSWORD)


@pytest.fixture()
def admin(api_client: TestClient, admin_account: str) -> AdminSession:
    """A signed in admin session over the real login route."""
    response = login(api_client, USERNAME, PASSWORD)
    assert response.status_code == 200, response.text
    body = response.json()
    return AdminSession(
        client=api_client,
        username=body["username"],
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
    )


@pytest.fixture()
def article_id(api_client: TestClient) -> int:
    """One visible article for the moderation and feed assertions."""
    return repo.insert_article(
        {
            "story_cluster_id": "admincluster0001",
            "dedupe_key": "admincluster0001",
            "headline": "RBI keeps the repo rate unchanged at 5.50 percent",
            "summary": SAMPLE_SUMMARY,
            "why_it_matters": "Rate sensitive lenders keep their assumptions.",
            "category": "rbi",
            "sentiment": "neutral",
            "impact": "high",
            "impact_direction": "neutral",
            "importance_score": 80,
            "is_breaking": True,
            "symbols": [{"symbol": "NIFTY", "exchange": "INDEX", "kind": "index"}],
            "topics": ["Monetary Policy"],
            "sources": [
                {
                    "publisher": "Reuters",
                    "title": "RBI holds rates",
                    "url": "https://www.reuters.com/india/rbi-holds",
                    "published_at": None,
                }
            ],
            "impact_map": [{"name": "NIFTY", "direction": "neutral"}],
            "published_at": repo.iso_hours_ago(1),
        }
    )


# ---------------------------------------------------------------------------
# Sign in (section 3.8)
# ---------------------------------------------------------------------------


def test_login_succeeds_and_opens_a_session(
    api_client: TestClient, admin_account: str
) -> None:
    response = login(api_client, USERNAME, PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "refresh_token", "expires_in", "username"}
    assert body["username"] == USERNAME
    assert body["expires_in"] == tokens.ADMIN_ACCESS_TTL_SECONDS

    me = api_client.get(
        "/api/admin/auth/me",
        headers={
            "Authorization": f"Bearer {body['access_token']}",
            HEADER_TEST_UNSIGNED: "1",
        },
    )
    assert me.status_code == 200
    assert me.json()["username"] == USERNAME
    assert me.json()["last_login_at"]


def test_a_wrong_username_and_a_wrong_password_are_indistinguishable(
    api_client: TestClient, admin_account: str
) -> None:
    """Identical status, identical body, identical shape. No oracle."""
    unknown = login(api_client, "no-such-admin", PASSWORD)
    wrong = login(api_client, USERNAME, WRONG_PASSWORD)

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert set(unknown.json()) == {"detail", "code"}
    assert unknown.json()["code"] == admin_auth.CODE_INVALID_CREDENTIALS
    assert USERNAME not in unknown.text
    assert USERNAME not in wrong.text


def test_a_blank_username_answers_the_same_way(
    api_client: TestClient, admin_account: str
) -> None:
    blank = login(api_client, "", PASSWORD)
    wrong = login(api_client, USERNAME, WRONG_PASSWORD)
    assert blank.status_code == 401
    assert blank.json() == wrong.json()


def test_an_unknown_username_still_burns_an_argon2_verification(
    api_client: TestClient, admin_account: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The equal work that makes the two paths equally slow.

    Counted rather than timed, because a wall clock assertion in a test suite
    fails on a busy machine and proves nothing on a fast one.
    """
    calls: list[int] = []
    original = passwords.dummy_verify
    monkeypatch.setattr(
        passwords, "dummy_verify", lambda: (calls.append(1), original())[1]
    )

    assert login(api_client, "no-such-admin", PASSWORD).status_code == 401
    assert calls, "the unknown username path skipped the timing equaliser"


def test_five_failures_lock_the_account(
    api_client: TestClient, admin_account: str
) -> None:
    """Section 3.8: five consecutive failures, then fifteen minutes locked."""
    for attempt in range(admin_auth.MAX_FAILED_ATTEMPTS):
        assert login(api_client, USERNAME, WRONG_PASSWORD).status_code == 401, attempt

    locked = deps.load_admin(USERNAME)
    assert locked is not None
    assert locked.failed_count == admin_auth.MAX_FAILED_ATTEMPTS
    assert locked.locked_until is not None
    assert locked.is_locked is True

    # The correct password is refused while the lock is running, with the same
    # body as any other failure, so the lock itself does not confirm the name.
    refused = login(api_client, USERNAME, PASSWORD)
    wrong = login(api_client, "no-such-admin", PASSWORD)
    assert refused.status_code == 401
    assert refused.json() == wrong.json()


def test_four_failures_do_not_lock_the_account(
    api_client: TestClient, admin_account: str
) -> None:
    """One below the threshold still signs in, and the counter then resets."""
    for _ in range(admin_auth.MAX_FAILED_ATTEMPTS - 1):
        assert login(api_client, USERNAME, WRONG_PASSWORD).status_code == 401

    assert login(api_client, USERNAME, PASSWORD).status_code == 200
    after = deps.load_admin(USERNAME)
    assert after is not None
    assert after.failed_count == 0
    assert after.locked_until is None


def test_login_never_echoes_the_password_or_the_hash(
    api_client: TestClient, admin_account: str
) -> None:
    """Not in the success body, not in the failure body, not in the audit row."""
    good = login(api_client, USERNAME, PASSWORD)
    bad = login(api_client, USERNAME, WRONG_PASSWORD)
    for response in (good, bad):
        assert PASSWORD not in response.text
        assert WRONG_PASSWORD not in response.text
        assert "argon2" not in response.text

    for row in audit_rows():
        rendered = str(row)
        assert PASSWORD not in rendered
        assert WRONG_PASSWORD not in rendered


def test_a_successful_login_writes_an_audit_row(
    api_client: TestClient, admin_account: str
) -> None:
    assert audit_rows(admin_auth.ACTION_LOGIN) == []
    assert login(api_client, USERNAME, PASSWORD).status_code == 200
    rows = audit_rows(admin_auth.ACTION_LOGIN)
    assert len(rows) == 1
    assert rows[0]["actor"] == USERNAME


def test_the_admin_refresh_token_rotates_once(admin: AdminSession) -> None:
    response = admin.client.post(
        "/api/admin/auth/refresh",
        json={"refresh_token": admin.refresh_token},
        headers={HEADER_TEST_UNSIGNED: "1"},
    )
    assert response.status_code == 200
    assert response.json()["refresh_token"] != admin.refresh_token

    reused = admin.client.post(
        "/api/admin/auth/refresh",
        json={"refresh_token": admin.refresh_token},
        headers={HEADER_TEST_UNSIGNED: "1"},
    )
    assert failure(reused) == (401, tokens.INVALID_REFRESH_CODE)


def test_logout_revokes_the_session_and_is_audited(admin: AdminSession) -> None:
    response = admin.post(
        "/api/admin/auth/logout", {"refresh_token": admin.refresh_token}
    )
    assert response.status_code == 204

    refused = admin.client.post(
        "/api/admin/auth/refresh",
        json={"refresh_token": admin.refresh_token},
        headers={HEADER_TEST_UNSIGNED: "1"},
    )
    assert refused.status_code == 401
    assert audit_rows(admin_auth.ACTION_LOGOUT)


# ---------------------------------------------------------------------------
# Every admin route needs an admin token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    ADMIN_ROUTES,
    ids=[f"{method} {path}" for method, path, _body in ADMIN_ROUTES],
)
def test_admin_routes_reject_a_missing_token(
    api_client: TestClient, admin_account: str, method: str, path: str, body: Any
) -> None:
    assert failure(unauthenticated(api_client, method, path, body)) == (
        401,
        deps.CODE_INVALID_TOKEN,
    )


@pytest.mark.parametrize(
    ("method", "path", "body"),
    ADMIN_ROUTES,
    ids=[f"{method} {path}" for method, path, _body in ADMIN_ROUTES],
)
def test_admin_routes_reject_a_device_token(
    api_client: TestClient,
    admin_account: str,
    signed: SignedClient,
    method: str,
    path: str,
    body: Any,
) -> None:
    """A device access token is minted for the device audience, not this one."""
    response = api_client.request(
        method,
        path,
        json=body,
        headers={
            "Authorization": f"Bearer {signed.credentials.access_token}",
            HEADER_TEST_UNSIGNED: "1",
        },
    )
    assert failure(response) == (401, deps.CODE_INVALID_TOKEN)


def test_an_admin_token_for_a_deleted_account_is_refused(
    api_client: TestClient, admin: AdminSession
) -> None:
    """The token is stateless, so the row is what ends the session."""
    with db.get_conn(write=True) as conn:
        conn.execute("DELETE FROM admin_users WHERE username = ?", (USERNAME,))
    assert failure(admin.get("/api/admin/flags")) == (401, deps.CODE_INVALID_TOKEN)


# ---------------------------------------------------------------------------
# Pipeline settings (sections 5 and 6.4)
# ---------------------------------------------------------------------------


def test_pipeline_patch_persists_and_is_reflected_by_get(
    admin: AdminSession,
) -> None:
    """A stored override beats .env, with no restart (section 5)."""
    before = admin.get("/api/admin/pipeline")
    assert before.status_code == 200
    assert before.json()["settings"]["ingest_interval_minutes"] != 42

    patched = admin.patch(
        "/api/admin/pipeline",
        {"ingest_interval_minutes": 42, "ingest_queries_per_cycle": 7},
    )
    assert patched.status_code == 200
    assert patched.json()["settings"]["ingest_interval_minutes"] == 42

    after = admin.get("/api/admin/pipeline").json()
    assert after["settings"]["ingest_interval_minutes"] == 42
    assert after["settings"]["ingest_queries_per_cycle"] == 7
    assert repo.get_app_setting("ingest_interval_minutes") is not None


def test_a_pipeline_patch_does_not_touch_the_settings_it_was_not_given(
    admin: AdminSession,
) -> None:
    """An absent field means no opinion, not a default."""
    baseline = admin.get("/api/admin/pipeline").json()["settings"]
    admin.patch("/api/admin/pipeline", {"ingest_interval_minutes": 33})
    after = admin.get("/api/admin/pipeline").json()["settings"]
    assert after["ingest_interval_minutes"] == 33
    assert (
        after["ingest_max_stories_per_query"]
        == baseline["ingest_max_stories_per_query"]
    )


def test_a_pipeline_patch_writes_an_audit_row(admin: AdminSession) -> None:
    admin.patch("/api/admin/pipeline", {"ingest_interval_minutes": 21})
    rows = audit_rows("pipeline.settings")
    assert len(rows) == 1
    assert rows[0]["actor"] == USERNAME
    assert "ingest_interval_minutes" in str(rows[0]["detail"])


def test_the_query_set_can_be_replaced_and_is_audited(admin: AdminSession) -> None:
    existing = admin.get("/api/admin/pipeline/queries")
    assert existing.status_code == 200
    queries = existing.json()["queries"]
    assert queries

    trimmed = [dict(queries[0]), dict(queries[1])]
    trimmed[1]["enabled"] = False
    response = admin.put("/api/admin/pipeline/queries", {"queries": trimmed})
    assert response.status_code == 200
    stored = response.json()["queries"]
    assert [entry["key"] for entry in stored] == [
        trimmed[0]["key"],
        trimmed[1]["key"],
    ]
    assert stored[1]["enabled"] is False
    assert audit_rows("pipeline.queries")


def test_an_empty_query_set_is_refused(admin: AdminSession) -> None:
    """An empty set would leave the pipeline with nothing to run."""
    response = admin.put("/api/admin/pipeline/queries", {"queries": []})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_query_set"


def test_rescore_and_images_are_audited(admin: AdminSession, article_id: int) -> None:
    assert admin.post("/api/admin/pipeline/rescore").status_code == 200
    assert admin.post("/api/admin/pipeline/images").status_code == 200
    assert audit_rows("pipeline.rescore")
    assert audit_rows("pipeline.images")


def test_the_ingest_trigger_is_audited(
    admin: AdminSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one action that spends money still leaves a row naming the run."""
    from app.routers import meta

    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key-not-real")
    config.reset_settings_cache()
    monkeypatch.setattr(meta, "run_ingest_job", lambda *_args, **_kwargs: None)

    response = admin.post("/api/admin/pipeline/ingest", {"queries": ["rbi"], "limit": 1})
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    rows = audit_rows("pipeline.ingest")
    assert len(rows) == 1
    assert rows[0]["target"] == str(run_id)


def test_the_ingest_trigger_is_refused_without_a_key(
    admin: AdminSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PERPLEXITY_API_KEY", "")
    config.reset_settings_cache()
    response = admin.post("/api/admin/pipeline/ingest", {})
    assert response.status_code == 503
    assert response.json()["code"] == "ingest_unavailable"
    assert audit_rows("pipeline.ingest") == []


# ---------------------------------------------------------------------------
# Content moderation (section 6.5)
# ---------------------------------------------------------------------------


def test_hiding_an_article_removes_it_from_the_public_feed(
    admin: AdminSession, signed: SignedClient, article_id: int
) -> None:
    """The whole point of moderation, checked from the reader's side."""
    visible = signed.get(f"{FEED}?limit=50").json()
    assert article_id in [item["id"] for item in visible["items"]]

    hidden = admin.patch(f"/api/admin/articles/{article_id}", {"hidden": True})
    assert hidden.status_code == 200
    assert hidden.json()["hidden"] is True
    assert hidden.json()["moderated_by"] == USERNAME
    assert hidden.json()["moderated_at"]

    after = signed.get(f"{FEED}?limit=50").json()
    assert [item["id"] for item in after["items"]] == []
    # The deep link closes with it, and search stops returning it.
    assert signed.get(f"/api/articles/{article_id}").status_code == 404
    assert signed.get("/api/search?q=repo").json()["items"] == []

    # The admin table still sees it, which is how it gets unhidden.
    listed = admin.get("/api/admin/articles").json()
    assert [item["id"] for item in listed["items"]] == [article_id]


def test_unhiding_an_article_brings_it_back(
    admin: AdminSession, signed: SignedClient, article_id: int
) -> None:
    admin.patch(f"/api/admin/articles/{article_id}", {"hidden": True})
    assert signed.get(f"{FEED}?limit=50").json()["items"] == []

    admin.patch(f"/api/admin/articles/{article_id}", {"hidden": False})
    back = signed.get(f"{FEED}?limit=50").json()["items"]
    assert [item["id"] for item in back] == [article_id]


def test_moderation_writes_an_audit_row(
    admin: AdminSession, article_id: int
) -> None:
    admin.patch(f"/api/admin/articles/{article_id}", {"hidden": True, "pinned": True})
    rows = audit_rows("article.update")
    assert len(rows) == 1
    assert rows[0]["target"] == str(article_id)
    assert rows[0]["actor"] == USERNAME


def test_editing_the_copy_is_audited_and_reindexed(
    admin: AdminSession, signed: SignedClient, article_id: int
) -> None:
    """An edit reaches search, so the index cannot drift from the article."""
    response = admin.patch(
        f"/api/admin/articles/{article_id}",
        {"headline": "SEBI tightens disclosure rules for listed companies"},
    )
    assert response.status_code == 200
    assert response.json()["headline"].startswith("SEBI tightens")

    found = signed.get("/api/search?q=disclosure").json()["items"]
    assert [item["id"] for item in found] == [article_id]
    assert audit_rows("article.update")


def test_deleting_an_article_is_audited_and_cascades(
    admin: AdminSession, signed: SignedClient, article_id: int
) -> None:
    assert admin.delete(f"/api/admin/articles/{article_id}").status_code == 204
    assert signed.get(f"/api/articles/{article_id}").status_code == 404
    assert signed.get(f"{FEED}?limit=50").json()["items"] == []

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sources WHERE article_id = ?", (article_id,)
        ).fetchone()
    assert int(row["n"]) == 0

    rows = audit_rows("article.delete")
    assert len(rows) == 1
    assert rows[0]["target"] == str(article_id)


def test_rescoring_one_article_is_audited(
    admin: AdminSession, article_id: int
) -> None:
    response = admin.post(f"/api/admin/articles/{article_id}/rescore")
    assert response.status_code == 200
    assert 0 <= response.json()["importance_score"] <= 100
    assert audit_rows("article.rescore")


def test_refreshing_one_image_is_audited(
    admin: AdminSession, article_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolver reads publisher pages, so it is stubbed rather than run."""
    from app.pipeline import images

    async def fake_resolve(_sources: Any) -> tuple[str | None, str | None]:
        return "https://cdn.example.com/lead.jpg", "https://example.com/story"

    monkeypatch.setattr(images, "resolve_image", fake_resolve)

    response = admin.post(f"/api/admin/articles/{article_id}/refresh-image")
    assert response.status_code == 200
    assert response.json()["image_url"] == "https://cdn.example.com/lead.jpg"
    assert audit_rows("article.image")


def test_a_missing_article_is_a_404_with_a_code(admin: AdminSession) -> None:
    assert failure(admin.patch("/api/admin/articles/999999", {"hidden": True})) == (
        404,
        "article_not_found",
    )


# ---------------------------------------------------------------------------
# Feature flags (section 6.6)
# ---------------------------------------------------------------------------


def test_disabling_a_category_is_reflected_by_public_config(
    admin: AdminSession, signed: SignedClient
) -> None:
    """The admin screen and the apps read the same rows."""
    before = signed.get(CONFIG).json()
    assert {entry["key"]: entry["enabled"] for entry in before["categories"]}["rbi"]

    response = admin.put("/api/admin/flags", {"categories": {"rbi": False}})
    assert response.status_code == 200

    after = signed.get(CONFIG).json()
    enabled = {entry["key"]: entry["enabled"] for entry in after["categories"]}
    assert enabled["rbi"] is False
    # Nothing else moved.
    assert all(value for key, value in enabled.items() if key != "rbi")


def test_disabling_a_market_filter_and_setting_the_sort(
    admin: AdminSession, signed: SignedClient
) -> None:
    response = admin.put(
        "/api/admin/flags",
        {"market_filters": {"GOLD": False}, "default_sort": "latest"},
    )
    assert response.status_code == 200

    body = signed.get(CONFIG).json()
    filters = {entry["key"]: entry["enabled"] for entry in body["market_filters"]}
    assert filters["GOLD"] is False
    assert body["default_sort"] == "latest"


def test_a_flag_change_writes_an_audit_row(admin: AdminSession) -> None:
    admin.put("/api/admin/flags", {"categories": {"crypto": False}})
    rows = audit_rows("flags.update")
    assert len(rows) == 1
    assert rows[0]["actor"] == USERNAME
    assert "crypto" in str(rows[0]["detail"])


def test_the_admin_flags_view_carries_a_timestamp_per_key(
    admin: AdminSession,
) -> None:
    admin.put("/api/admin/flags", {"categories": {"sebi": False}})
    body = admin.get("/api/admin/flags").json()
    sebi = next(entry for entry in body["categories"] if entry["key"] == "sebi")
    assert sebi["enabled"] is False
    assert sebi["updated_at"]


def test_an_unknown_flag_key_is_ignored_rather_than_stored(
    admin: AdminSession,
) -> None:
    """A stale client cannot create a flag row that nothing reads."""
    assert admin.put(
        "/api/admin/flags", {"categories": {"not-a-category": False}}
    ).status_code == 200
    assert repo.get_feature_flag("category:not-a-category") is None


# ---------------------------------------------------------------------------
# Maintenance mode (section 6.2)
# ---------------------------------------------------------------------------


MAINTENANCE_MESSAGE = "FinBit is down for a short database migration."


@pytest.fixture()
def maintenance(admin: AdminSession) -> None:
    """Turn maintenance mode on through the admin route, as an admin would."""
    response = admin.put(
        "/api/admin/flags",
        {"maintenance_mode": True, "maintenance_message": MAINTENANCE_MESSAGE},
    )
    assert response.status_code == 200
    assert response.json()["maintenance_mode"] is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/feed",
        "/api/articles/1",
        "/api/search?q=rbi",
        "/api/trending",
        "/api/bookmarks",
    ],
)
def test_maintenance_mode_takes_the_content_routes_down(
    signed: SignedClient, maintenance: None, path: str
) -> None:
    response = signed.get(path)
    assert failure(response) == (503, deps.CODE_MAINTENANCE)
    assert response.json()["detail"] == MAINTENANCE_MESSAGE


def test_maintenance_mode_leaves_config_answering(
    signed: SignedClient, maintenance: None
) -> None:
    """Otherwise the apps would see a failure and could not show the message."""
    response = signed.get(CONFIG)
    assert response.status_code == 200
    body = response.json()
    assert body["maintenance_mode"] is True
    assert body["maintenance_message"] == MAINTENANCE_MESSAGE


def test_maintenance_mode_leaves_the_admin_screens_working(
    admin: AdminSession, maintenance: None
) -> None:
    """The screen that turned it on has to be able to turn it off again."""
    assert admin.get("/api/admin/flags").status_code == 200
    assert admin.get("/api/admin/articles").status_code == 200

    admin.put("/api/admin/flags", {"maintenance_mode": False})
    assert admin.get("/api/admin/flags").json()["maintenance_mode"] is False


def test_turning_maintenance_off_restores_the_feed(
    admin: AdminSession, signed: SignedClient, maintenance: None, article_id: int
) -> None:
    assert signed.get(FEED).status_code == 503
    admin.put("/api/admin/flags", {"maintenance_mode": False})
    response = signed.get(f"{FEED}?limit=50")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [article_id]


# ---------------------------------------------------------------------------
# The audit log as a whole (section 3.8)
# ---------------------------------------------------------------------------


def test_every_admin_mutation_leaves_an_audit_row(
    admin: AdminSession, article_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One pass over every mutating route, then one look at the log."""
    from app.pipeline import images

    async def fake_resolve(_sources: Any) -> tuple[str | None, str | None]:
        return None, None

    monkeypatch.setattr(images, "resolve_image", fake_resolve)

    admin.patch("/api/admin/pipeline", {"ingest_queries_per_cycle": 3})
    admin.post("/api/admin/pipeline/rescore")
    admin.post("/api/admin/pipeline/images")
    queries = admin.get("/api/admin/pipeline/queries").json()["queries"]
    admin.put("/api/admin/pipeline/queries", {"queries": queries[:3]})
    admin.put("/api/admin/flags", {"categories": {"global": False}})
    admin.patch(f"/api/admin/articles/{article_id}", {"pinned": True})
    admin.post(f"/api/admin/articles/{article_id}/rescore")
    admin.post(f"/api/admin/articles/{article_id}/refresh-image")
    admin.delete(f"/api/admin/articles/{article_id}")

    actions = {row["action"] for row in audit_rows()}
    assert actions >= {
        "admin.login",
        "pipeline.settings",
        "pipeline.rescore",
        "pipeline.images",
        "pipeline.queries",
        "flags.update",
        "article.update",
        "article.rescore",
        "article.image",
        "article.delete",
    }
    assert all(row["actor"] == USERNAME for row in audit_rows())
    assert all(row["at"].endswith("Z") for row in audit_rows())


def test_a_read_only_admin_call_writes_nothing(admin: AdminSession) -> None:
    """The log is for mutations. A screen refresh must not fill it."""
    before = len(audit_rows())
    admin.get("/api/admin/pipeline")
    admin.get("/api/admin/flags")
    admin.get("/api/admin/articles")
    admin.get("/api/admin/auth/me")
    assert len(audit_rows()) == before


def test_an_audit_row_carries_the_caller_address(admin: AdminSession) -> None:
    admin.put("/api/admin/flags", {"categories": {"india": False}})
    row = audit_rows("flags.update")[0]
    assert row["ip"] == "testclient"


def test_the_bootstrap_admin_is_created_only_when_none_exists(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 3.8: a restart never resets a password someone has changed."""
    monkeypatch.setenv("ADMIN_BOOTSTRAP_USERNAME", "bootstrap-admin")
    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "bootstrap-pass-word")
    config.reset_settings_cache()

    assert admin_cli.ensure_bootstrap_admin() == "bootstrap-admin"
    assert admin_cli.admin_count() == 1
    assert admin_cli.ensure_bootstrap_admin() is None
    assert admin_cli.admin_count() == 1
