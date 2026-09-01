"""The anonymous device handshake and what it is actually for.

Registration itself is short: an app key in, a device id and a secret out
(CONTRACT_MOBILE_ADMIN.md section 6.1). The tests around it matter because it
is the only unsigned way into the API, so the app key check, the app_id match
and the per IP budget are the whole door.

The isolation tests at the bottom are the point of the whole handshake and are
the most important tests in this file. Phase 1 trusted whatever the caller put
in X-Device-Id, which meant any client could read, add to or delete from
another device's bookmarks just by supplying its id. Section 4 replaced that
header with a server-issued id the caller proves possession of on every
request. These tests hold that fix in place: they hand device A device B's id
and check that knowing it buys nothing at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db, deps, repo
from app.security import keys, ratelimit, tokens
from tests.conftest import (
    APP_KEYS,
    DeviceCredentials,
    HEADER_APP_KEY,
    HEADER_TEST_UNSIGNED,
    SAMPLE_SUMMARY,
    SignedClient,
    register_device,
)

REGISTER = "/api/auth/device"
REFRESH = "/api/auth/refresh"
BOOKMARKS = "/api/bookmarks"


def unsigned_headers(app_id: str = "web") -> dict[str, str]:
    """The only headers registration takes: an app key, no signature."""
    return {HEADER_APP_KEY: APP_KEYS[app_id], HEADER_TEST_UNSIGNED: "1"}


def device_count() -> int:
    """How many device rows exist, read straight from the table."""
    with db.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()
    return int(row["n"])


def failure(response: Any) -> tuple[int, str]:
    """The status and the contract code of a refused request."""
    body = response.json()
    assert set(body) >= {"detail", "code"}, body
    return response.status_code, body["code"]


def seed_article(slug: str, headline: str) -> int:
    """One article, inserted straight through the repository."""
    return repo.insert_article(
        {
            "story_cluster_id": slug,
            "dedupe_key": slug,
            "headline": headline,
            "summary": SAMPLE_SUMMARY,
            "why_it_matters": "Read-through for Indian equities.",
            "category": "earnings",
            "sentiment": "positive",
            "impact": "medium",
            "impact_direction": "bullish",
            "importance_score": 55,
            "is_breaking": False,
            "symbols": [{"symbol": "RELIANCE", "exchange": "NSE", "kind": "stock"}],
            "topics": ["Q1 Earnings"],
            "sources": [
                {
                    "publisher": "Reuters",
                    "title": headline,
                    "url": f"https://www.reuters.com/markets/{slug}",
                    "published_at": None,
                }
            ],
            "impact_map": [{"name": "NIFTY", "direction": "positive"}],
            "published_at": repo.iso_hours_ago(2),
        }
    )


@pytest.fixture()
def articles(api_client: TestClient) -> list[int]:
    """Two articles, so a bookmark can be told apart from an empty list."""
    return [
        seed_article("devicecluster0001", "Reliance posts a higher quarterly profit"),
        seed_article("devicecluster0002", "TCS wins a large European deal"),
    ]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registration_returns_a_usable_credential_set(api_client: TestClient) -> None:
    """The response carries everything a client needs and nothing it does not."""
    response = api_client.post(
        REGISTER,
        json={"app_id": "mobile", "platform": "ios", "install_id": "opaque-install"},
        headers=unsigned_headers("mobile"),
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "device_id",
        "device_secret",
        "access_token",
        "refresh_token",
        "expires_in",
    }
    assert body["expires_in"] == tokens.DEVICE_ACCESS_TTL_SECONDS
    assert body["device_id"] and body["device_id"] != body["device_secret"]


def test_registration_writes_one_device_row(api_client: TestClient) -> None:
    """The row carries the platform and app id it registered with."""
    assert device_count() == 0
    credentials = register_device(api_client, "mobile", "android")
    assert device_count() == 1

    device = deps.load_device(credentials.device_id)
    assert device is not None
    assert (device.app_id, device.platform) == ("mobile", "android")
    assert device.revoked is False


def test_the_returned_secret_is_the_derived_one(api_client: TestClient) -> None:
    """The server stores nothing: it derives the same secret on every request."""
    credentials = register_device(api_client, "web", "web")
    assert credentials.device_secret == keys.derive_device_secret(
        credentials.device_id
    ).b64


def test_the_returned_credentials_sign_a_real_request(api_client: TestClient) -> None:
    """Registration is only useful if what it hands back actually verifies."""
    credentials = register_device(api_client, "mobile", "ios")
    signed = SignedClient(api_client, credentials)
    assert signed.get("/api/feed").status_code == 200
    assert signed.get("/api/config").status_code == 200


def test_registration_takes_no_signature(api_client: TestClient) -> None:
    """A device with no secret yet cannot sign, so the route must not ask."""
    response = api_client.post(
        REGISTER,
        json={"app_id": "web", "platform": "web"},
        headers=unsigned_headers("web"),
    )
    assert response.status_code == 200


def test_registration_rejects_an_unknown_app_key(api_client: TestClient) -> None:
    """Check 1 of section 3.5, before anything else runs."""
    response = api_client.post(
        REGISTER,
        json={"app_id": "web", "platform": "web"},
        headers={HEADER_APP_KEY: "not-a-configured-key", HEADER_TEST_UNSIGNED: "1"},
    )
    assert failure(response) == (401, deps.CODE_INVALID_APP_KEY)
    assert device_count() == 0


def test_registration_rejects_a_missing_app_key(api_client: TestClient) -> None:
    response = api_client.post(
        REGISTER,
        json={"app_id": "web", "platform": "web"},
        headers={HEADER_TEST_UNSIGNED: "1"},
    )
    assert failure(response) == (401, deps.CODE_INVALID_APP_KEY)
    assert device_count() == 0


@pytest.mark.parametrize(
    ("app_id", "key_for"),
    [("web", "mobile"), ("mobile", "web")],
)
def test_registration_validates_app_id_against_the_app_key(
    api_client: TestClient, app_id: str, key_for: str
) -> None:
    """A body claiming to be one client while holding the other client's key.

    The two are one claim, so the answer is the app key failure rather than a
    code of its own: telling the caller which half it got right would turn the
    route into an oracle for the keys.
    """
    response = api_client.post(
        REGISTER,
        json={"app_id": app_id, "platform": "web" if app_id == "web" else "ios"},
        headers=unsigned_headers(key_for),
    )
    assert failure(response) == (401, deps.CODE_INVALID_APP_KEY)
    assert device_count() == 0


def test_registration_rejects_a_platform_the_client_cannot_have(
    api_client: TestClient,
) -> None:
    """The web bundle asking for an ios device row is a client bug, not an attack."""
    response = api_client.post(
        REGISTER,
        json={"app_id": "web", "platform": "ios"},
        headers=unsigned_headers("web"),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_platform"
    assert device_count() == 0


def test_registration_rejects_an_unknown_platform(api_client: TestClient) -> None:
    """A platform outside the vocabulary never reaches the handler."""
    response = api_client.post(
        REGISTER,
        json={"app_id": "web", "platform": "linux"},
        headers=unsigned_headers("web"),
    )
    assert response.status_code == 422
    assert device_count() == 0


def test_registration_is_rate_limited_per_ip(api_client: TestClient) -> None:
    """Five handshakes per address per hour (section 3.7), then a Retry-After."""
    capacity = int(ratelimit.limit_for(ratelimit.SCOPE_DEVICE_REGISTER).capacity)
    payload = {"app_id": "web", "platform": "web"}
    for attempt in range(capacity):
        response = api_client.post(
            REGISTER, json=payload, headers=unsigned_headers("web")
        )
        assert response.status_code == 200, attempt

    refused = api_client.post(REGISTER, json=payload, headers=unsigned_headers("web"))
    assert failure(refused) == (429, ratelimit.RATE_LIMITED_CODE)
    assert int(refused.headers["Retry-After"]) >= 1
    # The refused attempt created nothing, so the budget cannot be worked
    # around by ignoring the 429 and retrying in a loop.
    assert device_count() == capacity


def test_a_rate_limited_registration_still_checks_the_app_key_first(
    api_client: TestClient,
) -> None:
    """Check 1 runs before check 2, so a bad key never spends the IP budget."""
    for _ in range(int(ratelimit.limit_for(ratelimit.SCOPE_DEVICE_REGISTER).capacity)):
        api_client.post(
            REGISTER,
            json={"app_id": "web", "platform": "web"},
            headers=unsigned_headers("web"),
        )
    response = api_client.post(
        REGISTER,
        json={"app_id": "web", "platform": "web"},
        headers={HEADER_APP_KEY: "not-a-configured-key", HEADER_TEST_UNSIGNED: "1"},
    )
    assert failure(response) == (401, deps.CODE_INVALID_APP_KEY)


def test_the_refresh_route_requires_an_app_key(api_client: TestClient) -> None:
    credentials = register_device(api_client, "web", "web")
    response = api_client.post(
        REFRESH,
        json={"refresh_token": credentials.refresh_token},
        headers={HEADER_TEST_UNSIGNED: "1"},
    )
    assert failure(response) == (401, deps.CODE_INVALID_APP_KEY)


def test_a_revoked_device_cannot_refresh(api_client: TestClient) -> None:
    """Revoking a device closes the refresh route as well as the signed ones."""
    credentials = register_device(api_client, "web", "web")
    with db.get_conn(write=True) as conn:
        conn.execute(
            "UPDATE devices SET revoked = 1 WHERE id = ?", (credentials.device_id,)
        )
    response = api_client.post(
        REFRESH,
        json={"refresh_token": credentials.refresh_token},
        headers=unsigned_headers("web"),
    )
    assert response.status_code == 401
    assert response.json()["code"] in {
        deps.CODE_DEVICE_REVOKED,
        tokens.INVALID_REFRESH_CODE,
    }


def test_a_registered_device_is_stamped_when_it_calls(
    api_client: TestClient,
) -> None:
    """last_seen_at and request_count are what support has on an anonymous user."""
    credentials = register_device(api_client, "web", "web")
    signed = SignedClient(api_client, credentials)
    assert signed.get("/api/feed").status_code == 200
    assert signed.get("/api/trending").status_code == 200

    device = deps.load_device(credentials.device_id)
    assert device is not None
    assert device.last_seen_at is not None
    assert device.request_count >= 2


def test_registration_never_echoes_the_master_key(api_client: TestClient) -> None:
    """The response hands over a derived secret, never the key behind it."""
    from tests.conftest import TEST_DEVICE_MASTER_KEY

    response = api_client.post(
        REGISTER,
        json={"app_id": "web", "platform": "web"},
        headers=unsigned_headers("web"),
    )
    assert TEST_DEVICE_MASTER_KEY not in response.text
    assert APP_KEYS["web"] not in response.text


# ---------------------------------------------------------------------------
# Bookmark isolation. The reason the handshake exists at all (section 4).
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_devices(api_client: TestClient) -> tuple[SignedClient, SignedClient]:
    """Device A and device B, registered through the real handshake."""
    first = SignedClient(api_client, register_device(api_client, "mobile", "ios"))
    second = SignedClient(api_client, register_device(api_client, "web", "web"))
    assert first.device_id != second.device_id
    return first, second


def test_a_device_cannot_read_another_devices_bookmarks(
    two_devices: tuple[SignedClient, SignedClient], articles: list[int]
) -> None:
    """B saves an article. A's list stays empty, whatever A knows about B."""
    device_a, device_b = two_devices
    assert device_b.post(BOOKMARKS, body={"article_id": articles[0]}).status_code == 200

    assert device_b.get(BOOKMARKS).json()["count"] == 1
    assert device_a.get(BOOKMARKS).json() == {"items": [], "count": 0}


def test_knowing_another_device_id_does_not_grant_its_bookmarks(
    two_devices: tuple[SignedClient, SignedClient], articles: list[int]
) -> None:
    """A puts B's id in the header and signs with its own credentials.

    This is the exact phase 1 attack: supply someone else's device id and read
    their saved articles. It now stops at check 6, because the access token's
    subject has to equal the header, and A cannot mint a token for B.
    """
    device_a, device_b = two_devices
    device_b.post(BOOKMARKS, body={"article_id": articles[0]})

    stolen_id = device_b.device_id
    response = device_a.get(BOOKMARKS, device_id=stolen_id)
    assert failure(response) == (401, deps.CODE_INVALID_TOKEN)

    # B's saved article is untouched.
    assert device_b.get(BOOKMARKS).json()["count"] == 1


def test_another_devices_id_with_its_own_secret_still_fails(
    api_client: TestClient,
    two_devices: tuple[SignedClient, SignedClient],
    articles: list[int],
) -> None:
    """Even a caller that somehow signed as B is stopped by the token.

    The signature and the bearer token are separate proofs. This test forges
    the one that can be forged from a leaked secret and shows the other still
    holds, which is what makes a captured token alone useless too.
    """
    device_a, device_b = two_devices
    device_b.post(BOOKMARKS, body={"article_id": articles[1]})

    forged = SignedClient(
        api_client,
        DeviceCredentials(
            device_id=device_b.device_id,
            device_secret=device_b.credentials.device_secret,
            access_token=device_a.credentials.access_token,
            refresh_token="unused",
            app_id="web",
        ),
    )
    assert failure(forged.get(BOOKMARKS)) == (401, deps.CODE_INVALID_TOKEN)


def test_a_device_cannot_add_to_another_devices_bookmarks(
    two_devices: tuple[SignedClient, SignedClient], articles: list[int]
) -> None:
    """A saving an article puts a row under A, never under B."""
    device_a, device_b = two_devices
    assert device_a.post(BOOKMARKS, body={"article_id": articles[0]}).status_code == 200

    assert device_b.get(BOOKMARKS).json() == {"items": [], "count": 0}
    with db.get_conn() as conn:
        rows = conn.execute("SELECT device_id FROM bookmarks").fetchall()
    assert [str(row["device_id"]) for row in rows] == [device_a.device_id]


def test_a_device_cannot_delete_another_devices_bookmarks(
    two_devices: tuple[SignedClient, SignedClient], articles: list[int]
) -> None:
    """A deleting the same article id leaves B's saved copy in place.

    Delete is idempotent by contract, so A still gets a 200. What matters is
    that the row it can reach is only ever its own.
    """
    device_a, device_b = two_devices
    article_id = articles[0]
    device_b.post(BOOKMARKS, body={"article_id": article_id})

    removed = device_a.delete(f"{BOOKMARKS}/{article_id}")
    assert removed.status_code == 200
    assert removed.json() == {"article_id": article_id, "bookmarked": False}

    assert device_b.get(BOOKMARKS).json()["count"] == 1
    assert device_b.get(BOOKMARKS).json()["items"][0]["id"] == article_id


def test_the_bookmarked_flag_is_per_device_everywhere_it_appears(
    two_devices: tuple[SignedClient, SignedClient], articles: list[int]
) -> None:
    """Feed, single article and search all resolve the flag for the caller."""
    device_a, device_b = two_devices
    article_id = articles[0]
    device_a.post(BOOKMARKS, body={"article_id": article_id})

    mine = device_a.get("/api/feed?limit=50").json()["items"]
    theirs = device_b.get("/api/feed?limit=50").json()["items"]
    assert {item["id"]: item["bookmarked"] for item in mine}[article_id] is True
    assert all(item["bookmarked"] is False for item in theirs)

    assert device_a.get(f"/api/articles/{article_id}").json()["bookmarked"] is True
    assert device_b.get(f"/api/articles/{article_id}").json()["bookmarked"] is False

    found_a = device_a.get("/api/search?q=reliance").json()["items"]
    found_b = device_b.get("/api/search?q=reliance").json()["items"]
    assert any(item["id"] == article_id and item["bookmarked"] for item in found_a)
    assert all(not item["bookmarked"] for item in found_b)


def test_a_bookmark_row_carries_a_server_issued_device_id(
    two_devices: tuple[SignedClient, SignedClient], articles: list[int]
) -> None:
    """The stored id is the one the server minted, not anything the client sent."""
    device_a, _device_b = two_devices
    device_a.post(BOOKMARKS, body={"article_id": articles[0]})

    with db.get_conn() as conn:
        row = conn.execute("SELECT device_id FROM bookmarks").fetchone()
    stored = str(row["device_id"])
    assert stored == device_a.device_id
    assert deps.load_device(stored) is not None


def test_a_revoked_device_loses_access_to_its_own_bookmarks(
    two_devices: tuple[SignedClient, SignedClient], articles: list[int]
) -> None:
    """Revoking is the lever that ends a device, and it ends it everywhere."""
    device_a, _device_b = two_devices
    device_a.post(BOOKMARKS, body={"article_id": articles[0]})
    assert device_a.get(BOOKMARKS).json()["count"] == 1

    with db.get_conn(write=True) as conn:
        conn.execute(
            "UPDATE devices SET revoked = 1 WHERE id = ?", (device_a.device_id,)
        )
    assert failure(device_a.get(BOOKMARKS)) == (401, deps.CODE_DEVICE_REVOKED)
    assert failure(device_a.post(BOOKMARKS, body={"article_id": articles[1]})) == (
        401,
        deps.CODE_DEVICE_REVOKED,
    )
