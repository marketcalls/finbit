"""Shared fixtures for the FinBit backend test suite.

Four guarantees apply to every test in this directory:

- the database is a fresh temporary file with the real schema applied, so no
  test can ever read or damage backend/finbit.db,
- live Perplexity calls are disabled, so no test can spend money. Any code
  path that reaches the agent endpoint raises instead,
- the four security secrets hold fixed test values rather than whatever the
  repo root .env happens to carry, so a signature computed here is
  reproducible on any machine (CONTRACT_MOBILE_ADMIN.md section 3.9),
- every TestClient signs its own requests. Phase 2 put the feed, search,
  bookmarks and categories behind a device handshake, so a bare
  client.get("/api/feed") would now be a 401. The transport hook below
  registers a device on demand and signs each call per section 3.4 instead,
  which keeps the phase 1 suite meaningful: it now exercises the whole
  verification chain on the way to every assertion it already made.

The signing helpers here are written from the contract with hashlib and hmac
directly, not by calling app.security.signing. A test that reuses the
implementation it is checking cannot catch a mistake in it, and the fixed
vectors in test_security.py depend on this file being an independent second
opinion.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, db, repo
from app.pipeline import perplexity
from app.security import iso_utc, keys, tokens

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


# ---------------------------------------------------------------------------
# Security configuration (CONTRACT_MOBILE_ADMIN.md sections 3.2, 3.3 and 3.9)
# ---------------------------------------------------------------------------

# Fixed, obviously fake values. They are test inputs, not credentials: none of
# them opens anything outside a temporary database created by pytest, and the
# fixed vectors in test_security.py are computed from them by hand.
TEST_APP_KEY_MOBILE = "finbit-test-app-key-mobile"
TEST_APP_KEY_WEB = "finbit-test-app-key-web"
TEST_DEVICE_MASTER_KEY = "finbit-test-device-master-key-32"
TEST_JWT_SECRET = "finbit-test-jwt-secret-do-not-ship"

APP_KEYS: dict[str, str] = {
    "mobile": TEST_APP_KEY_MOBILE,
    "web": TEST_APP_KEY_WEB,
}

SECURITY_ENV: dict[str, str] = {
    "APP_KEY_MOBILE": TEST_APP_KEY_MOBILE,
    "APP_KEY_WEB": TEST_APP_KEY_WEB,
    "DEVICE_MASTER_KEY": TEST_DEVICE_MASTER_KEY,
    "JWT_SECRET": TEST_JWT_SECRET,
    "REQUIRE_SIGNED_REQUESTS": "true",
    "SIGNATURE_SKEW_SECONDS": "120",
    "NONCE_TTL_SECONDS": "300",
    # Blank on purpose. A bootstrap admin inherited from the developer's .env
    # would make every admin test start from a different table.
    "ADMIN_BOOTSTRAP_USERNAME": "",
    "ADMIN_BOOTSTRAP_PASSWORD": "",
}

# Header names, spelled exactly as section 3.5 spells them.
HEADER_APP_KEY = "X-App-Key"
HEADER_DEVICE_ID = "X-Device-Id"
HEADER_TIMESTAMP = "X-Timestamp"
HEADER_NONCE = "X-Nonce"
HEADER_SIGNATURE = "X-Signature"

# A request carrying this header is sent exactly as the caller built it. It is
# how a test asks for an unauthenticated call now that signing is automatic.
HEADER_TEST_UNSIGNED = "X-Finbit-Test-Unsigned"

# Route prefixes the transport hook never signs: the admin screens carry their
# own bearer token, the handshake routes take an app key and no signature
# (section 3.5), and health is public.
UNSIGNED_PREFIXES: tuple[str, ...] = ("/api/admin", "/api/auth", "/api/health")

# The device a request with no X-Device-Id header is signed as.
DEFAULT_DEVICE_ALIAS = "finbit-default-test-device"


# ---------------------------------------------------------------------------
# Canonical string and signature, written from the contract
# ---------------------------------------------------------------------------


def body_digest(body: bytes | None) -> str:
    """Lowercase hex sha256 of the exact bytes sent (section 3.4)."""
    return hashlib.sha256(body or b"").hexdigest()


def canonical_string(
    timestamp: str, nonce: str, method: str, path_with_query: str, body: bytes | None
) -> str:
    """The five newline separated lines that get signed."""
    return "\n".join(
        [
            str(timestamp),
            nonce,
            method.upper(),
            path_with_query,
            body_digest(body),
        ]
    )


def hmac_signature(secret: bytes, canonical: str) -> str:
    """Standard base64 of hmac sha256 over the utf-8 canonical string."""
    digest = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def derive_device_secret(device_id: str, master_key: str = TEST_DEVICE_MASTER_KEY) -> str:
    """base64(hmac_sha256(master_key, device_id)), the client's copy (section 3.3)."""
    raw = hmac.new(
        master_key.encode("utf-8"), device_id.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(raw).decode("ascii")


def new_nonce() -> str:
    """16 random bytes, base64url, no padding."""
    return base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")


def encode_body(body: Any) -> bytes | None:
    """Serialise a request body once, the way a real client must.

    The digest covers the exact bytes sent, so the body is turned into bytes
    here and those same bytes go on the wire. Passing an already encoded value
    through unchanged is what lets a test sign one body and send another.
    """
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# Device credentials
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceCredentials:
    """Everything a client needs to sign, as registration hands it over."""

    device_id: str
    device_secret: str
    access_token: str
    refresh_token: str
    app_id: str = "web"

    @property
    def secret_bytes(self) -> bytes:
        """The device secret as the bytes the HMAC key is taken from."""
        return base64.b64decode(self.device_secret)

    @property
    def app_key(self) -> str:
        """The app key this device registered with."""
        return APP_KEYS[self.app_id]


def sign_headers(
    credentials: DeviceCredentials,
    method: str,
    path_with_query: str,
    body: bytes | None = None,
    *,
    timestamp: str | None = None,
    nonce: str | None = None,
    app_key: str | None = None,
    device_id: str | None = None,
    access_token: str | None = None,
    signature: str | None = None,
) -> dict[str, str]:
    """The six headers section 3.5 requires on a device-authenticated call.

    Every part can be overridden so a test can present one wrong element and
    nothing else, which is the only way to prove a check fires for its own
    reason rather than by accident.
    """
    stamp = timestamp if timestamp is not None else str(int(time.time()))
    once = nonce if nonce is not None else new_nonce()
    canonical = canonical_string(stamp, once, method, path_with_query, body)
    return {
        HEADER_APP_KEY: app_key if app_key is not None else credentials.app_key,
        HEADER_DEVICE_ID: device_id if device_id is not None else credentials.device_id,
        HEADER_TIMESTAMP: stamp,
        HEADER_NONCE: once,
        HEADER_SIGNATURE: (
            signature
            if signature is not None
            else hmac_signature(credentials.secret_bytes, canonical)
        ),
        "Authorization": (
            f"Bearer {access_token if access_token is not None else credentials.access_token}"
        ),
    }


def provision_device(
    app_id: str = "web", platform: str = "web"
) -> DeviceCredentials:
    """Create a device row and mint its tokens without calling the API.

    The transport hook uses this rather than POST /api/auth/device on purpose:
    the phase 1 tests never called a handshake route, so making them depend on
    one would tie a feed assertion to a registration bug. Tests that are about
    registration call register_device below and exercise the real route.
    """
    device_id = keys.new_device_id()
    with db.get_conn(write=True) as conn:
        conn.execute(
            "INSERT INTO devices (id, platform, app_id, created_at, revoked, "
            "request_count) VALUES (?, ?, ?, ?, 0, 0)",
            (device_id, platform, app_id, iso_utc()),
        )
    access_token, _ttl = tokens.issue_access_token(device_id, tokens.AUDIENCE_DEVICE)
    refresh = tokens.issue_refresh_token(device_id, tokens.KIND_DEVICE_REFRESH)
    return DeviceCredentials(
        device_id=device_id,
        device_secret=derive_device_secret(device_id),
        access_token=access_token,
        refresh_token=refresh.token,
        app_id=app_id,
    )


def register_device(
    client: TestClient, app_id: str = "web", platform: str = "web"
) -> DeviceCredentials:
    """Register a device through POST /api/auth/device, the real handshake.

    Takes the app key and no signature, because the device has no secret yet
    (section 3.5).
    """
    response = client.post(
        "/api/auth/device",
        json={"app_id": app_id, "platform": platform},
        headers={HEADER_APP_KEY: APP_KEYS[app_id], HEADER_TEST_UNSIGNED: "1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return DeviceCredentials(
        device_id=body["device_id"],
        device_secret=body["device_secret"],
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        app_id=app_id,
    )


# ---------------------------------------------------------------------------
# The transport hook that keeps the phase 1 suite honest
# ---------------------------------------------------------------------------

# Keyed by (database file, alias) so a test that switches databases mid-run
# gets a device that exists in the one it is actually talking to. test_api.py
# does exactly that: its client fixture points at a second temporary file.
_device_registry: dict[tuple[str, str], DeviceCredentials] = {}

_httpx_send = httpx.Client.send


def credentials_for_alias(alias: str) -> DeviceCredentials:
    """The registered device standing in for one X-Device-Id value.

    Phase 1 tests picked their own device ids and expected two of them to hold
    separate bookmarks. Mapping each string to its own registered device keeps
    that expectation true, and true for the right reason now: the two callers
    really are two devices the server issued, rather than two headers.
    """
    key = (str(db.get_db_path()), alias)
    existing = _device_registry.get(key)
    if existing is None:
        existing = provision_device()
        _device_registry[key] = existing
    return existing


def _needs_device_auth(path: str) -> bool:
    """True for a route that phase 2 put behind the device handshake."""
    if not path.startswith("/api"):
        return False
    return not path.startswith(UNSIGNED_PREFIXES)


def _autosign(request: httpx.Request) -> None:
    """Add the signature headers to a request that did not bring its own."""
    headers = request.headers
    if HEADER_TEST_UNSIGNED in headers:
        del headers[HEADER_TEST_UNSIGNED]
        return
    if HEADER_SIGNATURE in headers or "Authorization" in headers:
        return
    path_with_query = request.url.raw_path.decode("ascii")
    if not _needs_device_auth(path_with_query.split("?", 1)[0]):
        return
    alias = headers.get(HEADER_DEVICE_ID) or DEFAULT_DEVICE_ALIAS
    credentials = credentials_for_alias(alias)
    signed = sign_headers(
        credentials, request.method, path_with_query, request.read()
    )
    for name, value in signed.items():
        headers[name] = value


@pytest.fixture(autouse=True)
def security_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fixed secrets, a clean device registry and automatic request signing."""
    for name, value in SECURITY_ENV.items():
        monkeypatch.setenv(name, value)
    config.reset_settings_cache()
    _device_registry.clear()

    def send(self: httpx.Client, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        _autosign(request)
        return _httpx_send(self, request, **kwargs)

    monkeypatch.setattr(TestClient, "send", send, raising=False)
    try:
        yield
    finally:
        _device_registry.clear()
        config.reset_settings_cache()


# ---------------------------------------------------------------------------
# Helpers for the phase 2 test files
# ---------------------------------------------------------------------------


class SignedClient:
    """A TestClient that signs with one device and nothing else.

    Every call takes a full path including the query string. Query parameters
    are never assembled here, because the signature covers the path exactly as
    sent and a helper that re-encoded them would be able to disagree with the
    bytes on the wire.
    """

    def __init__(self, client: TestClient, credentials: DeviceCredentials) -> None:
        self.client = client
        self.credentials = credentials

    @property
    def device_id(self) -> str:
        return self.credentials.device_id

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        signed_body: Any = None,
        headers: Mapping[str, str] | None = None,
        sign: bool = True,
        **overrides: Any,
    ) -> httpx.Response:
        """Send one call. signed_body signs different bytes than it sends."""
        payload = encode_body(body)
        covered = payload if signed_body is None else encode_body(signed_body)
        sent: dict[str, str] = {HEADER_TEST_UNSIGNED: "1"}
        if payload is not None:
            sent["Content-Type"] = "application/json"
        if sign:
            sent.update(
                sign_headers(self.credentials, method, path, covered, **overrides)
            )
        sent.update(dict(headers or {}))
        return self.client.request(method, path, content=payload, headers=sent)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)


def drain_bucket(scope: str, identity: str) -> None:
    """Empty one rate limit bucket so the next call is the one that is refused.

    Spending the tokens one call at a time would be six hundred writes for the
    IP scope. Writing the row straight is the same state and costs nothing.
    """
    from app.security import iso_utc_precise, ratelimit

    with db.get_conn(write=True) as conn:
        conn.execute(
            "INSERT INTO rate_buckets (key, tokens, updated_at) VALUES (?, 0.0, ?) "
            "ON CONFLICT(key) DO UPDATE SET tokens = 0.0, updated_at = excluded.updated_at",
            (ratelimit.bucket_key(scope, identity), iso_utc_precise()),
        )


def audit_rows(action: str | None = None) -> list[dict[str, Any]]:
    """Audit log rows, newest first, optionally for one action only."""
    rows = repo.list_audit(limit=200)
    if action is None:
        return rows
    return [row for row in rows if row["action"] == action]


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    """A TestClient over the real application, lifespan included.

    The lifespan is what applies the phase 2 migration and seeds the feature
    flag defaults, so a test that reads /api/config needs this rather than a
    bare application object.
    """
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def device(api_client: TestClient) -> DeviceCredentials:
    """One registered web device."""
    return provision_device()


@pytest.fixture()
def signed(api_client: TestClient, device: DeviceCredentials) -> SignedClient:
    """A signing client bound to one registered device."""
    return SignedClient(api_client, device)


# ---------------------------------------------------------------------------
# Phase 1 expectations that phase 2 deliberately replaced
# ---------------------------------------------------------------------------

# CONTRACT_MOBILE_ADMIN.md section 4 replaced the caller-supplied X-Device-Id
# with a server-issued device id, and calls that fix by name: before it, any
# client could read another device's bookmarks by supplying its id. The phase 1
# test below asserts the old contract, that a write with no X-Device-Id header
# is a 400 naming that header. There is no longer a route that can answer that
# way, and there must not be: an unauthenticated write is a 401 now. The
# expectation is marked as a known failure rather than quietly deleted, and
# strict is on so that a change putting the old behavior back is reported.
SUPERSEDED_BY_DEVICE_AUTH: dict[str, str] = {
    "tests/test_api.py::test_bookmark_write_without_device_header_returns_400": (
        "Phase 2 section 4 replaced the X-Device-Id header with the device "
        "handshake, so an unauthenticated bookmark write is 401 "
        "missing_signature_headers rather than 400."
    ),
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark the phase 1 assertions that phase 2 replaced by design."""
    for item in items:
        for suffix, reason in SUPERSEDED_BY_DEVICE_AUTH.items():
            if item.nodeid.replace("\\", "/").endswith(suffix):
                item.add_marker(pytest.mark.xfail(reason=reason, strict=True))
