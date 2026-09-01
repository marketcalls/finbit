"""The security core: signing, replay, tokens and rate limits.

Two kinds of test live here and they have different jobs.

The first half pins the canonical string and the HMAC to fixed vectors
computed by hand from a known device secret. packages/shared/src/signing.ts has
to produce the same bytes for the same input or a request signed by an app
fails here with no useful diagnostic (CONTRACT_MOBILE_ADMIN.md section 3.4), and
a vector is the only thing that can catch a drift between two languages. The
vectors are repeated in a comment block below in a form agent A1 can paste
straight into a TypeScript test.

The second half drives the real application through every row of the failure
table in section 3.5, asserting the status and the code, and then through the
behaviours the table cannot express: that a replay is refused only on the
second use, that the skew window has the exact edges the contract gives it, and
that a refresh token can be spent once.

Nothing here asserts on a secret, a token or a signature appearing in a
message. Several tests assert the opposite: that they do not.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, db, deps
from app.security import keys, ratelimit, signing, tokens
from tests.conftest import (
    APP_KEYS,
    DeviceCredentials,
    HEADER_APP_KEY,
    HEADER_TEST_UNSIGNED,
    SignedClient,
    TEST_DEVICE_MASTER_KEY,
    canonical_string,
    drain_bucket,
    hmac_signature,
    new_nonce,
    provision_device,
    register_device,
)

# ---------------------------------------------------------------------------
# FIXED CROSS-LANGUAGE VECTORS
# ---------------------------------------------------------------------------
#
# Everything below was computed by hand from the inputs in this block, not read
# back from app/security/signing.py. Agent A1: assert these exact strings in a
# TypeScript test against packages/shared/src/signing.ts. If any one of them
# disagrees, the two implementations have drifted and every signed request from
# that client will be rejected as bad_signature.
#
#   DEVICE_MASTER_KEY = "finbit-test-device-master-key-32"
#   device_id         = "0123456789abcdef0123456789abcdef"
#   device_secret     = base64(hmac_sha256(utf8(master_key), utf8(device_id)))
#                     = "kPZmoCZVIKBMErwFDosiViVPYICPlG+XuOQy7TkEj4Y="
#   timestamp         = "1767225600"          unix seconds, 2026-01-01T00:00:00Z
#   nonce             = "9y3rNQ0mF7xKpL2aVbCdEg"    16 bytes, base64url, no pad
#
#   The HMAC key is the DECODED device secret, 32 raw bytes, never the base64
#   text. Getting that wrong is the single most likely cross-language mistake.
#
#   canonical = timestamp + "\n" + nonce + "\n" + METHOD + "\n"
#             + path_with_query + "\n" + lowercase_hex(sha256(body_bytes))
#   signature = base64(hmac_sha256(device_secret_bytes, utf8(canonical)))
#
# 1. empty body, no query string
#    method    GET
#    path      /api/feed
#    body      "" (zero bytes)
#    digest    e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
#    canonical "1767225600\n9y3rNQ0mF7xKpL2aVbCdEg\nGET\n/api/feed\ne3b0c442...b855"
#    signature FVEPPhK1t3xtQiOU72IpKKm6tILJstTmgrvHKZq1qYA=
#
# 2. empty body, with a query string, parameters in the order sent
#    method    GET
#    path      /api/feed?category=rbi&sort=top
#    body      "" (zero bytes)
#    digest    e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
#    signature N8XtP5ZpbkgT52yM81rVH7R0o/zfEDWZGgTnVq3+cH0=
#
# 3. unicode body, digested as utf-8 bytes and sent as those same bytes
#    method    POST
#    path      /api/bookmarks
#    body      {"headline":"RBI holds at 5.50%, \u20b91,20,000, Z\u00fcrich, \u0928\u0940\u0924\u093f"}
#              69 bytes once encoded as utf-8, 58 JavaScript string units
#    digest    c1653087cd9f8586c06764086b3bda5350c9f07431d54976666e8f9c909bd375
#    signature PKl4uZcs/+EM3XLM/eMKlV5hGF8BgmkCO5ahfhsHkwg=
#
# 4. percent encoded query, passed through byte for byte with no re-encoding
#    method    GET
#    path      /api/search?q=RBI%20repo%20rate&limit=5
#    body      "" (zero bytes)
#    digest    e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
#    signature WLgZKxtYqRm3shkiLxbYzk8OW/LznOCTDGh3YGM+tVQ=
#
# ---------------------------------------------------------------------------

VECTOR_MASTER_KEY = "finbit-test-device-master-key-32"
VECTOR_DEVICE_ID = "0123456789abcdef0123456789abcdef"
VECTOR_DEVICE_SECRET = "kPZmoCZVIKBMErwFDosiViVPYICPlG+XuOQy7TkEj4Y="
VECTOR_TIMESTAMP = "1767225600"
VECTOR_NONCE = "9y3rNQ0mF7xKpL2aVbCdEg"

EMPTY_BODY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Written with escapes rather than literal characters so the file stays ascii
# and the bytes under test cannot be changed by an editor normalising them.
# The same escapes are valid in TypeScript, so A1 can paste this line as is.
VECTOR_UNICODE_BODY = (
    '{"headline":"RBI holds at 5.50%, '
    '\u20b91,20,000, Z\u00fcrich, \u0928\u0940\u0924\u093f"}'
)

# (name, method, path_with_query, body bytes, body digest, signature)
VECTORS: tuple[tuple[str, str, str, bytes, str, str], ...] = (
    (
        "empty body and no query string",
        "GET",
        "/api/feed",
        b"",
        EMPTY_BODY_DIGEST,
        "FVEPPhK1t3xtQiOU72IpKKm6tILJstTmgrvHKZq1qYA=",
    ),
    (
        "empty body with a query string",
        "GET",
        "/api/feed?category=rbi&sort=top",
        b"",
        EMPTY_BODY_DIGEST,
        "N8XtP5ZpbkgT52yM81rVH7R0o/zfEDWZGgTnVq3+cH0=",
    ),
    (
        "unicode body",
        "POST",
        "/api/bookmarks",
        VECTOR_UNICODE_BODY.encode("utf-8"),
        "c1653087cd9f8586c06764086b3bda5350c9f07431d54976666e8f9c909bd375",
        "PKl4uZcs/+EM3XLM/eMKlV5hGF8BgmkCO5ahfhsHkwg=",
    ),
    (
        "percent encoded query string",
        "GET",
        "/api/search?q=RBI%20repo%20rate&limit=5",
        b"",
        EMPTY_BODY_DIGEST,
        "WLgZKxtYqRm3shkiLxbYzk8OW/LznOCTDGh3YGM+tVQ=",
    ),
)

VECTOR_SECRET_BYTES = base64.b64decode(VECTOR_DEVICE_SECRET)

FEED = "/api/feed"


# ---------------------------------------------------------------------------
# The vectors themselves
# ---------------------------------------------------------------------------


def test_the_test_environment_uses_the_vector_master_key() -> None:
    """The conftest master key is the one the vectors were computed from."""
    assert TEST_DEVICE_MASTER_KEY == VECTOR_MASTER_KEY


def test_empty_body_digest_constant() -> None:
    """sha256 of zero bytes, the digest line on every GET (section 3.4)."""
    assert hashlib.sha256(b"").hexdigest() == EMPTY_BODY_DIGEST
    assert signing.EMPTY_BODY_DIGEST == EMPTY_BODY_DIGEST
    assert signing.body_digest(b"") == EMPTY_BODY_DIGEST
    assert signing.body_digest(None) == EMPTY_BODY_DIGEST


def test_device_secret_derivation_matches_the_vector() -> None:
    """base64(hmac_sha256(master_key, device_id)) is what the client stores."""
    expected = base64.b64encode(
        hmac.new(
            VECTOR_MASTER_KEY.encode("utf-8"),
            VECTOR_DEVICE_ID.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii")
    assert expected == VECTOR_DEVICE_SECRET

    derived = keys.derive_device_secret(VECTOR_DEVICE_ID)
    assert derived.b64 == VECTOR_DEVICE_SECRET
    assert derived.raw == VECTOR_SECRET_BYTES
    assert len(derived.raw) == 32


def test_derivation_is_deterministic_and_id_specific() -> None:
    """The same id always derives the same secret, a different id never does."""
    again = keys.derive_device_secret(VECTOR_DEVICE_ID)
    assert again.b64 == VECTOR_DEVICE_SECRET
    other = keys.derive_device_secret("fedcba9876543210fedcba9876543210")
    assert other.b64 != VECTOR_DEVICE_SECRET


@pytest.mark.parametrize(
    ("name", "method", "path", "body", "digest", "signature"),
    VECTORS,
    ids=[vector[0] for vector in VECTORS],
)
def test_fixed_vector(
    name: str, method: str, path: str, body: bytes, digest: str, signature: str
) -> None:
    """The Python implementation reproduces a vector computed by hand."""
    assert signing.body_digest(body) == digest

    canonical = signing.canonical_string(
        timestamp=VECTOR_TIMESTAMP,
        nonce=VECTOR_NONCE,
        method=method,
        path_with_query=path,
        digest=digest,
    )
    expected_canonical = "\n".join(
        [VECTOR_TIMESTAMP, VECTOR_NONCE, method, path, digest]
    )
    assert canonical == expected_canonical

    by_hand = base64.b64encode(
        hmac.new(
            VECTOR_SECRET_BYTES, canonical.encode("utf-8"), hashlib.sha256
        ).digest()
    ).decode("ascii")
    assert by_hand == signature

    assert (
        signing.sign_request(
            secret=VECTOR_SECRET_BYTES,
            timestamp=VECTOR_TIMESTAMP,
            nonce=VECTOR_NONCE,
            method=method,
            path_with_query=path,
            body=body,
        )
        == signature
    )
    assert signing.verify_request(
        secret=VECTOR_SECRET_BYTES,
        timestamp=VECTOR_TIMESTAMP,
        nonce=VECTOR_NONCE,
        method=method,
        path_with_query=path,
        body=body,
        signature=signature,
    )


def test_unicode_body_is_digested_as_utf8_bytes() -> None:
    """The digest covers utf-8 bytes, not code units and not a re-encoding."""
    encoded = VECTOR_UNICODE_BODY.encode("utf-8")
    assert len(encoded) == 69
    assert len(VECTOR_UNICODE_BODY) == 58
    assert signing.body_digest(encoded) == VECTORS[2][4]


def test_canonical_string_is_five_lines_and_uppercases_the_method() -> None:
    """The layout is fixed, and a lowercase method still verifies."""
    canonical = signing.canonical_string(
        timestamp=VECTOR_TIMESTAMP,
        nonce=VECTOR_NONCE,
        method="get",
        path_with_query=FEED,
        digest=EMPTY_BODY_DIGEST,
    )
    lines = canonical.split("\n")
    assert len(lines) == 5
    assert lines == [VECTOR_TIMESTAMP, VECTOR_NONCE, "GET", FEED, EMPTY_BODY_DIGEST]


def test_a_signature_over_a_different_input_does_not_verify() -> None:
    """Changing any one line of the canonical string changes the signature."""
    base = dict(
        secret=VECTOR_SECRET_BYTES,
        timestamp=VECTOR_TIMESTAMP,
        nonce=VECTOR_NONCE,
        method="GET",
        path_with_query=FEED,
        body=b"",
    )
    signature = signing.sign_request(**base)
    for field, value in (
        ("timestamp", "1767225601"),
        ("nonce", "AAAAAAAAAAAAAAAAAAAAAA"),
        ("method", "POST"),
        ("path_with_query", "/api/feed?limit=1"),
        ("body", b"{}"),
    ):
        changed = dict(base)
        changed[field] = value
        assert not signing.verify_request(**changed, signature=signature), field


# ---------------------------------------------------------------------------
# Section 3.5, the failure table
# ---------------------------------------------------------------------------


def failure(response: Any) -> tuple[int, str]:
    """The status and the contract code of a refused request."""
    body = response.json()
    assert set(body) >= {"detail", "code"}, body
    assert isinstance(body["detail"], str) and body["detail"]
    return response.status_code, body["code"]


def test_check_1_unknown_app_key(signed: SignedClient) -> None:
    assert failure(signed.get(FEED, app_key="not-a-configured-key")) == (
        401,
        deps.CODE_INVALID_APP_KEY,
    )


def test_check_1_missing_app_key(signed: SignedClient) -> None:
    assert failure(signed.get(FEED, app_key="")) == (401, deps.CODE_INVALID_APP_KEY)


def test_check_1_runs_before_every_other_check(signed: SignedClient) -> None:
    """A request that is wrong in four ways still answers about the app key."""
    response = signed.get(
        FEED,
        app_key="not-a-configured-key",
        timestamp="1",
        access_token="not-a-token",
        signature="bm90LWEtc2lnbmF0dXJl",
    )
    assert failure(response) == (401, deps.CODE_INVALID_APP_KEY)


def test_check_2_ip_rate_limit(signed: SignedClient) -> None:
    drain_bucket(ratelimit.SCOPE_IP, "testclient")
    response = signed.get(FEED)
    assert failure(response) == (429, ratelimit.RATE_LIMITED_CODE)
    assert int(response.headers["Retry-After"]) >= 1


def test_check_3_missing_signature_headers(
    api_client: TestClient, device: DeviceCredentials
) -> None:
    """An app key and a bearer token alone are not enough in signed mode."""
    response = api_client.get(
        FEED,
        headers={
            HEADER_APP_KEY: device.app_key,
            "Authorization": f"Bearer {device.access_token}",
            HEADER_TEST_UNSIGNED: "1",
        },
    )
    assert failure(response) == (401, deps.CODE_MISSING_SIGNATURE_HEADERS)


def test_check_3_missing_bearer_token(signed: SignedClient) -> None:
    assert failure(signed.get(FEED, access_token="")) == (
        401,
        deps.CODE_MISSING_SIGNATURE_HEADERS,
    )


def test_check_3_nonce_that_is_not_a_nonce(signed: SignedClient) -> None:
    """A one character nonce never reaches the nonces table."""
    assert failure(signed.get(FEED, nonce="x")) == (
        401,
        deps.CODE_MISSING_SIGNATURE_HEADERS,
    )


def test_check_4_stale_timestamp(signed: SignedClient) -> None:
    old = str(int(time.time()) - 3600)
    assert failure(signed.get(FEED, timestamp=old)) == (401, deps.CODE_STALE_REQUEST)


def test_check_4_timestamp_from_the_future(signed: SignedClient) -> None:
    """Skew is absolute, so a clock that runs fast is refused the same way."""
    ahead = str(int(time.time()) + 3600)
    assert failure(signed.get(FEED, timestamp=ahead)) == (401, deps.CODE_STALE_REQUEST)


def test_check_4_timestamp_that_is_not_a_number(signed: SignedClient) -> None:
    assert failure(signed.get(FEED, timestamp="yesterday")) == (
        401,
        deps.CODE_STALE_REQUEST,
    )


def test_check_5_replayed_nonce(signed: SignedClient) -> None:
    assert signed.get(FEED, nonce="replay-me-once-abcdefgh").status_code == 200
    assert failure(signed.get(FEED, nonce="replay-me-once-abcdefgh")) == (
        401,
        deps.CODE_REPLAYED_REQUEST,
    )


def test_check_6_invalid_access_token(signed: SignedClient) -> None:
    assert failure(signed.get(FEED, access_token="not.a.jwt")) == (
        401,
        deps.CODE_INVALID_TOKEN,
    )


def test_check_6_admin_token_is_not_a_device_token(signed: SignedClient) -> None:
    """A token minted for the admin audience cannot drive a device route."""
    admin_token, _ttl = tokens.issue_access_token("someone", tokens.AUDIENCE_ADMIN)
    assert failure(signed.get(FEED, access_token=admin_token)) == (
        401,
        deps.CODE_INVALID_TOKEN,
    )


def test_check_6_token_subject_must_equal_the_device_header(
    signed: SignedClient
) -> None:
    """One device's token presented under another device's id is refused."""
    other = provision_device()
    assert failure(signed.get(FEED, access_token=other.access_token)) == (
        401,
        deps.CODE_INVALID_TOKEN,
    )


def test_check_6_expired_access_token(signed: SignedClient) -> None:
    expired, _ttl = tokens.issue_access_token(
        signed.device_id, tokens.AUDIENCE_DEVICE, ttl_seconds=-60
    )
    assert failure(signed.get(FEED, access_token=expired)) == (
        401,
        deps.CODE_INVALID_TOKEN,
    )


def test_check_7_revoked_device(signed: SignedClient) -> None:
    assert signed.get(FEED).status_code == 200
    with db.get_conn(write=True) as conn:
        conn.execute(
            "UPDATE devices SET revoked = 1, revoked_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00Z", signed.device_id),
        )
    assert failure(signed.get(FEED)) == (401, deps.CODE_DEVICE_REVOKED)


def test_check_7_unknown_device_row(api_client: TestClient) -> None:
    """A token for a device that was never inserted reads as revoked."""
    ghost = keys.new_device_id()
    access_token, _ttl = tokens.issue_access_token(ghost, tokens.AUDIENCE_DEVICE)
    credentials = DeviceCredentials(
        device_id=ghost,
        device_secret=keys.derive_device_secret(ghost).b64,
        access_token=access_token,
        refresh_token="unused",
    )
    client = SignedClient(api_client, credentials)
    assert failure(client.get(FEED)) == (401, deps.CODE_DEVICE_REVOKED)


def test_check_8_bad_signature(signed: SignedClient) -> None:
    assert failure(signed.get(FEED, signature="bm90LWEtc2lnbmF0dXJl")) == (
        401,
        deps.CODE_BAD_SIGNATURE,
    )


def test_check_8_signature_made_with_another_device_secret(
    signed: SignedClient,
) -> None:
    """A stolen access token is not enough without the matching secret.

    Everything else about this request is correct: the right app key, the right
    device id, a valid token for that device, a fresh nonce and a current
    timestamp. Only the HMAC key is wrong, so check 8 is the one that fires.
    """
    impostor = provision_device()
    timestamp = str(int(time.time()))
    nonce = new_nonce()
    canonical = canonical_string(timestamp, nonce, "GET", FEED, b"")
    forged = hmac_signature(base64.b64decode(impostor.device_secret), canonical)
    response = signed.get(FEED, timestamp=timestamp, nonce=nonce, signature=forged)
    assert failure(response) == (401, deps.CODE_BAD_SIGNATURE)


def test_check_9_device_rate_limit(signed: SignedClient) -> None:
    drain_bucket(ratelimit.SCOPE_DEVICE, signed.device_id)
    response = signed.get(FEED)
    assert failure(response) == (429, ratelimit.RATE_LIMITED_CODE)
    assert int(response.headers["Retry-After"]) >= 1


# ---------------------------------------------------------------------------
# Order of the checks
# ---------------------------------------------------------------------------


def test_the_timestamp_is_checked_before_the_nonce(signed: SignedClient) -> None:
    """A stale replay answers about the clock, so no nonce row is written."""
    nonce = "stale-and-replayed-aaa"
    old = str(int(time.time()) - 600)
    assert failure(signed.get(FEED, timestamp=old, nonce=nonce)) == (
        401,
        deps.CODE_STALE_REQUEST,
    )
    # The nonce was never claimed, so it is still usable.
    assert signed.get(FEED, nonce=nonce).status_code == 200


def test_the_nonce_is_checked_before_the_token(signed: SignedClient) -> None:
    nonce = "seen-then-reused-abcd"
    assert signed.get(FEED, nonce=nonce).status_code == 200
    assert failure(signed.get(FEED, nonce=nonce, access_token="not.a.jwt")) == (
        401,
        deps.CODE_REPLAYED_REQUEST,
    )


def test_the_token_is_checked_before_the_signature(signed: SignedClient) -> None:
    response = signed.get(FEED, access_token="not.a.jwt", signature="YmFk")
    assert failure(response) == (401, deps.CODE_INVALID_TOKEN)


# ---------------------------------------------------------------------------
# Replay protection and the skew window
# ---------------------------------------------------------------------------


def test_a_replayed_nonce_is_refused_only_on_the_second_use(
    signed: SignedClient,
) -> None:
    """The first call succeeds. The identical call after it does not."""
    nonce = "one-use-only-abcdefgh"
    timestamp = str(int(time.time()))
    first = signed.get(FEED, nonce=nonce, timestamp=timestamp)
    assert first.status_code == 200
    assert first.json() == {"items": [], "next_cursor": None, "has_more": False}

    second = signed.get(FEED, nonce=nonce, timestamp=timestamp)
    assert failure(second) == (401, deps.CODE_REPLAYED_REQUEST)


def test_each_device_owns_its_own_nonce_space(
    api_client: TestClient, signed: SignedClient
) -> None:
    """A nonce is a primary key, so one device can burn another one's value.

    That is deliberate and harmless: a nonce is unpredictable to anyone but the
    device that generated it, and refusing a value someone else already used
    costs that device one retry rather than an account.
    """
    nonce = "shared-nonce-abcdefgh"
    assert signed.get(FEED, nonce=nonce).status_code == 200
    other = SignedClient(api_client, provision_device())
    assert failure(other.get(FEED, nonce=nonce)) == (401, deps.CODE_REPLAYED_REQUEST)


def test_timestamp_119_seconds_old_is_accepted(signed: SignedClient) -> None:
    recent = str(int(time.time()) - 119)
    assert signed.get(FEED, timestamp=recent).status_code == 200


def test_timestamp_121_seconds_old_is_rejected(signed: SignedClient) -> None:
    stale = str(int(time.time()) - 121)
    assert failure(signed.get(FEED, timestamp=stale)) == (401, deps.CODE_STALE_REQUEST)


def test_the_skew_window_edge_is_inclusive(signed: SignedClient) -> None:
    """Exactly the configured skew is still inside the window."""
    assert config.get_settings().signature_skew_seconds == 120
    edge = str(int(time.time()) - 120)
    assert signed.get(FEED, timestamp=edge).status_code == 200


def test_expired_nonces_are_pruned(signed: SignedClient) -> None:
    """A nonce older than the TTL leaves the table, so it cannot grow forever."""
    with db.get_conn(write=True) as conn:
        conn.execute(
            "INSERT INTO nonces (nonce, device_id, seen_at) VALUES (?, ?, ?)",
            ("ancient-nonce-abcdefg", signed.device_id, "2020-01-01T00:00:00Z"),
        )
    assert signed.get(FEED).status_code == 200
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM nonces WHERE nonce = ?",
            ("ancient-nonce-abcdefg",),
        ).fetchone()
    assert int(row["n"]) == 0


# ---------------------------------------------------------------------------
# The body digest covers the bytes actually sent
# ---------------------------------------------------------------------------


def test_a_signature_over_a_different_body_is_rejected(
    signed: SignedClient, seeded_article: int
) -> None:
    """Sign one body, send another, and the request is refused."""
    response = signed.post(
        "/api/bookmarks",
        body={"article_id": seeded_article},
        signed_body={"article_id": seeded_article + 1},
    )
    assert failure(response) == (401, deps.CODE_BAD_SIGNATURE)


def test_the_matching_body_is_accepted(
    signed: SignedClient, seeded_article: int
) -> None:
    """The same call with the body it signed goes through."""
    response = signed.post("/api/bookmarks", body={"article_id": seeded_article})
    assert response.status_code == 200
    assert response.json() == {"article_id": seeded_article, "bookmarked": True}


def test_a_unicode_body_round_trips(signed: SignedClient) -> None:
    """A body with non-ascii characters signs and verifies over its utf-8 bytes.

    /api/search does not take a body, so this asserts the failure the server
    gives a valid signature (422 for the missing query) rather than the
    bad_signature it would give if the digest had been computed over anything
    but the bytes sent.
    """
    body = VECTOR_UNICODE_BODY
    response = signed.post("/api/bookmarks", body=body)
    assert response.status_code == 422
    assert "code" not in response.json()


# ---------------------------------------------------------------------------
# Refresh token rotation (section 3.6)
# ---------------------------------------------------------------------------


def test_refresh_rotation_works_once(api_client: TestClient) -> None:
    """A refresh token buys one new pair, and the new access token works."""
    credentials = register_device(api_client, "mobile", "ios")
    response = api_client.post(
        "/api/auth/refresh",
        json={"refresh_token": credentials.refresh_token},
        headers={HEADER_APP_KEY: APP_KEYS["mobile"], HEADER_TEST_UNSIGNED: "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refresh_token"] != credentials.refresh_token
    assert body["access_token"] != credentials.access_token
    assert body["expires_in"] == tokens.DEVICE_ACCESS_TTL_SECONDS

    rotated = DeviceCredentials(
        device_id=credentials.device_id,
        device_secret=credentials.device_secret,
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        app_id="mobile",
    )
    assert SignedClient(api_client, rotated).get(FEED).status_code == 200


def test_a_reused_refresh_token_revokes_the_family(api_client: TestClient) -> None:
    """The second use of a spent token kills every token of that device."""
    credentials = register_device(api_client, "mobile", "ios")
    headers = {HEADER_APP_KEY: APP_KEYS["mobile"], HEADER_TEST_UNSIGNED: "1"}

    first = api_client.post(
        "/api/auth/refresh",
        json={"refresh_token": credentials.refresh_token},
        headers=headers,
    )
    assert first.status_code == 200
    replacement = first.json()["refresh_token"]

    reused = api_client.post(
        "/api/auth/refresh",
        json={"refresh_token": credentials.refresh_token},
        headers=headers,
    )
    assert failure(reused) == (401, tokens.INVALID_REFRESH_CODE)

    # The replacement issued a moment ago is part of the revoked family, so a
    # stolen token cannot outlive the theft being noticed.
    after = api_client.post(
        "/api/auth/refresh", json={"refresh_token": replacement}, headers=headers
    )
    assert failure(after) == (401, tokens.INVALID_REFRESH_CODE)


def test_rotation_and_reuse_at_the_token_layer(device: DeviceCredentials) -> None:
    """The same rule, asserted on the store rather than through HTTP."""
    rotated = tokens.rotate_refresh_token(
        device.refresh_token, tokens.KIND_DEVICE_REFRESH
    )
    assert rotated.token != device.refresh_token
    assert rotated.subject == device.device_id

    with pytest.raises(tokens.RefreshTokenReuse):
        tokens.rotate_refresh_token(device.refresh_token, tokens.KIND_DEVICE_REFRESH)

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT revoked FROM refresh_tokens WHERE subject = ?",
            (device.device_id,),
        ).fetchall()
    assert rows and all(int(row["revoked"]) == 1 for row in rows)


def test_a_refresh_token_is_stored_only_as_its_hash(device: DeviceCredentials) -> None:
    """A copy of the database cannot be turned back into a session."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT token_hash FROM refresh_tokens").fetchall()
    stored = {str(row["token_hash"]) for row in rows}
    assert device.refresh_token not in stored
    assert tokens.hash_refresh_token(device.refresh_token) in stored


def test_an_unknown_refresh_token_is_refused(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/auth/refresh",
        json={"refresh_token": "there-was-never-such-a-token"},
        headers={HEADER_APP_KEY: APP_KEYS["web"], HEADER_TEST_UNSIGNED: "1"},
    )
    assert failure(response) == (401, tokens.INVALID_REFRESH_CODE)


# ---------------------------------------------------------------------------
# Rate limits (section 3.7)
# ---------------------------------------------------------------------------


def test_registration_is_limited_to_five_per_ip(api_client: TestClient) -> None:
    """The sixth handshake from one address is refused with a Retry-After."""
    capacity = int(ratelimit.limit_for(ratelimit.SCOPE_DEVICE_REGISTER).capacity)
    assert capacity == 5
    headers = {HEADER_APP_KEY: APP_KEYS["web"], HEADER_TEST_UNSIGNED: "1"}
    payload = {"app_id": "web", "platform": "web"}

    for attempt in range(capacity):
        response = api_client.post("/api/auth/device", json=payload, headers=headers)
        assert response.status_code == 200, attempt

    refused = api_client.post("/api/auth/device", json=payload, headers=headers)
    assert failure(refused) == (429, ratelimit.RATE_LIMITED_CODE)
    assert int(refused.headers["Retry-After"]) >= 1


def test_the_bucket_refills_over_time() -> None:
    """A caller that waited gets tokens back, which is what makes bursts work."""
    from datetime import timedelta

    from app.security import utc_now

    scope, identity = ratelimit.SCOPE_DEVICE_REGISTER, "refill-test"
    for _ in range(5):
        assert ratelimit.consume(scope, identity).allowed
    assert not ratelimit.consume(scope, identity).allowed

    later = utc_now() + timedelta(hours=1)
    assert ratelimit.consume(scope, identity, now=later).allowed


def test_the_configured_capacities_match_the_contract() -> None:
    """Section 3.7, verbatim."""
    expected = {
        ratelimit.SCOPE_DEVICE_REGISTER: (5, 60 * 60),
        ratelimit.SCOPE_DEVICE: (120, 60),
        ratelimit.SCOPE_IP: (600, 60),
        ratelimit.SCOPE_ADMIN_LOGIN: (10, 15 * 60),
        ratelimit.SCOPE_ADMIN_INGEST: (6, 60 * 60),
    }
    for scope, (capacity, window) in expected.items():
        limit = ratelimit.limit_for(scope)
        assert (limit.capacity, limit.window_seconds) == (capacity, window), scope


# ---------------------------------------------------------------------------
# The development-only unsigned switch (section 3.9)
# ---------------------------------------------------------------------------


@pytest.fixture()
def unsigned_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn REQUIRE_SIGNED_REQUESTS off for one test.

    The dependency reads the settings on every request, so no restart is
    needed and the running client picks the change up at once.
    """
    monkeypatch.setenv("REQUIRE_SIGNED_REQUESTS", "false")
    config.reset_settings_cache()
    assert config.get_settings().require_signed_requests is False


def test_unsigned_mode_skips_the_signature(
    api_client: TestClient, device: DeviceCredentials, unsigned_mode: None
) -> None:
    """An app key and a bearer token are enough while the switch is off."""
    response = api_client.get(
        FEED,
        headers={
            HEADER_APP_KEY: device.app_key,
            "Authorization": f"Bearer {device.access_token}",
            HEADER_TEST_UNSIGNED: "1",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None, "has_more": False}


def test_unsigned_mode_still_requires_the_app_key(
    api_client: TestClient, device: DeviceCredentials, unsigned_mode: None
) -> None:
    response = api_client.get(
        FEED,
        headers={
            "Authorization": f"Bearer {device.access_token}",
            HEADER_TEST_UNSIGNED: "1",
        },
    )
    assert failure(response) == (401, deps.CODE_INVALID_APP_KEY)


def test_unsigned_mode_still_requires_a_bearer_token(
    api_client: TestClient, device: DeviceCredentials, unsigned_mode: None
) -> None:
    response = api_client.get(
        FEED,
        headers={HEADER_APP_KEY: device.app_key, HEADER_TEST_UNSIGNED: "1"},
    )
    assert failure(response) == (401, deps.CODE_MISSING_SIGNATURE_HEADERS)


def test_unsigned_mode_still_refuses_a_revoked_device(
    api_client: TestClient, device: DeviceCredentials, unsigned_mode: None
) -> None:
    """Dropping the signature does not drop the device checks behind it."""
    with db.get_conn(write=True) as conn:
        conn.execute("UPDATE devices SET revoked = 1 WHERE id = ?", (device.device_id,))
    response = api_client.get(
        FEED,
        headers={
            HEADER_APP_KEY: device.app_key,
            "Authorization": f"Bearer {device.access_token}",
            HEADER_TEST_UNSIGNED: "1",
        },
    )
    assert failure(response) == (401, deps.CODE_DEVICE_REVOKED)


def test_a_signed_request_still_works_in_unsigned_mode(
    signed: SignedClient, unsigned_mode: None
) -> None:
    """The switch relaxes a requirement, it does not reject a correct client."""
    assert signed.get(FEED).status_code == 200


def test_startup_refuses_a_signed_deployment_with_a_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 3.9: a missing secret is a clean refusal, naming the variable."""
    from app.main import enforce_security_configuration

    monkeypatch.setenv("DEVICE_MASTER_KEY", "change-me-32-bytes-of-random")
    config.reset_settings_cache()
    problems = config.get_settings().validate_security()
    assert any("DEVICE_MASTER_KEY" in problem for problem in problems)
    with pytest.raises(RuntimeError):
        enforce_security_configuration()


# ---------------------------------------------------------------------------
# Nothing secret ever reaches a response body
# ---------------------------------------------------------------------------


def test_a_refused_request_never_echoes_the_credentials(
    signed: SignedClient,
) -> None:
    """The failure body carries a sentence and a code, and nothing else."""
    response = signed.get(FEED, signature="bm90LWEtc2lnbmF0dXJl")
    text = response.text
    assert response.status_code == 401
    assert set(response.json()) == {"detail", "code"}
    for secret in (
        signed.credentials.device_secret,
        signed.credentials.access_token,
        signed.credentials.refresh_token,
        signed.credentials.app_key,
        TEST_DEVICE_MASTER_KEY,
    ):
        assert secret not in text


def test_security_headers_are_present_on_every_response(
    api_client: TestClient,
) -> None:
    """The transport hardening applies to a plain public route too."""
    response = api_client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.fixture()
def seeded_article(api_client: TestClient) -> int:
    """One article to bookmark, inserted straight through the repository."""
    from app import repo
    from tests.conftest import SAMPLE_SUMMARY

    return repo.insert_article(
        {
            "story_cluster_id": "securitycluster0001",
            "dedupe_key": "securitycluster0001",
            "headline": "RBI keeps the repo rate unchanged",
            "summary": SAMPLE_SUMMARY,
            "why_it_matters": "Rate sensitive lenders keep their assumptions.",
            "category": "rbi",
            "sentiment": "neutral",
            "impact": "high",
            "impact_direction": "neutral",
            "importance_score": 70,
            "is_breaking": False,
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
