"""Card image resolution from Open Graph tags (contract section 14.2).

The Agent API never returns images, so the lead image on a card is resolved
from the source URLs the pipeline already holds. This is the same mechanism a
link-preview unfurler uses, it costs nothing and it hits publisher websites
rather than Perplexity.

How one article is resolved:

1. Order the article's sources by publisher tier from score.py, tier 1 first,
   so the image comes from the most credible publisher that has one. Obvious
   non-pages (a PDF, an image file, an archive) are dropped before they can
   waste a slot.
2. Take at most three candidates. For each, issue one GET with redirects
   followed, an 8 second timeout and a descriptive User-Agent, because a
   default client User-Agent collects 403s from several publishers.
3. Stream the response and stop reading at `</head>` or 200 KB, whichever
   comes first, so an article page is never downloaded whole.
4. Read the meta tags in priority order: og:image:secure_url, og:image,
   twitter:image, twitter:image:src. Publishers use `property` on some tags
   and `name` on others, so both attributes are matched.
5. Accept only an absolute http or https value. A protocol-relative
   `//host/path` resolves against https, a relative path resolves against the
   page URL, and a data: URI is rejected.

Nothing here ever raises at the caller: a 403, a redirect loop, a non-HTML
content type, a page with no tags at all and a connection timeout all end as
None, logged at debug level.

`extract_og_image` is pure and network-free, which is what test_images.py
exercises over saved HTML.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.pipeline.score import publisher_tier

logger = logging.getLogger(__name__)

# Contract section 14.2 budgets.
TIMEOUT_SECONDS = 8.0
MAX_HEAD_BYTES = 200 * 1024
MAX_CANDIDATES = 3
DEFAULT_CONCURRENCY = 1

# A default client User-Agent is refused by several Indian publishers, so the
# request identifies itself as a normal browser and names the app in a
# trailing product token. Measured against the live sites: this string is
# served by business-standard.com, moneycontrol.com, livemint.com and
# economictimes.indiatimes.com, while the same string carrying a
# parenthesised comment after the product token is answered with a 403.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 FinBit/1.0"
)

REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

# Meta tag keys in the order the contract fixes.
META_KEYS: tuple[str, ...] = (
    "og:image:secure_url",
    "og:image",
    "twitter:image",
    "twitter:image:src",
)

# Only a markup response can carry meta tags.
HTML_CONTENT_HINTS: tuple[str, ...] = ("html", "xml")

# Paths that are certainly not an HTML page. Skipping them keeps the three
# candidate slots for pages that can actually carry an Open Graph tag.
NON_PAGE_SUFFIXES: tuple[str, ...] = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".zip",
    ".rar",
    ".mp3",
    ".mp4",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
)

_ALLOWED_SCHEMES = ("http", "https")

_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE | re.DOTALL)

_ATTR_RE = re.compile(
    r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))"""
)

_HEAD_END_RE = re.compile(rb"</head\s*>", re.IGNORECASE)

_HEAD_END_MARKER = re.compile(r"</head\s*>", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pure parsing, no network
# ---------------------------------------------------------------------------


def _unescape(value: str) -> str:
    """Decode the handful of entities that appear inside a content attribute.

    html.unescape is deliberately not used: it also rewrites bare ampersands
    followed by a known entity name, which mangles query strings on CDN image
    URLs such as `?w=1200&h=630`.
    """
    return (
        value.replace("&amp;", "&")
        .replace("&#38;", "&")
        .replace("&quot;", '"')
        .replace("&#34;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def meta_tags(html: str) -> list[dict[str, str]]:
    """Every meta tag in the markup as a dict of lowercase attribute names."""
    tags: list[dict[str, str]] = []
    for raw in _META_TAG_RE.findall(html or ""):
        attrs: dict[str, str] = {}
        for match in _ATTR_RE.finditer(raw):
            name = match.group(1).lower()
            value = match.group(2)
            if value is None:
                value = match.group(3)
            if value is None:
                value = match.group(4) or ""
            attrs[name] = _unescape(value.strip())
        if attrs:
            tags.append(attrs)
    return tags


def meta_image_values(html: str) -> dict[str, str]:
    """The first value seen for each supported meta key.

    Publishers put the key on `property` for Open Graph and on `name` for the
    Twitter tags, and plenty of them mix the two, so both are accepted.
    """
    found: dict[str, str] = {}
    for attrs in meta_tags(html):
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        if key not in META_KEYS:
            continue
        content = attrs.get("content") or attrs.get("value") or ""
        if content and key not in found:
            found[key] = content
    return found


def normalize_image_url(value: Any, base_url: str = "") -> str | None:
    """Absolute http or https image URL, or None when the value is unusable.

    A protocol-relative `//host/path` resolves against https, a relative path
    resolves against the page it was found on, and a data: URI is rejected.
    """
    text = str(value or "").strip().strip('"').strip("'")
    if not text or "\n" in text or "\r" in text:
        return None
    if text.lower().startswith("data:"):
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if not parts.scheme and base_url:
        try:
            text = urljoin(base_url, text)
            parts = urlsplit(text)
        except ValueError:
            return None
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        return None
    if not parts.hostname:
        return None
    return text


def extract_og_image(html: str, base_url: str = "") -> str | None:
    """The card image declared by a page, or None. Pure and network-free.

    Keys are tried in the contract order, and a key holding an unusable value
    (a data: URI, an empty string) falls through to the next key rather than
    failing the page.
    """
    if not html:
        return None
    values = meta_image_values(html)
    if not values:
        return None
    for key in META_KEYS:
        candidate = normalize_image_url(values.get(key), base_url)
        if candidate:
            return candidate
    return None


def truncate_at_head_end(html: str) -> str:
    """Drop everything after `</head>`, which no meta tag can live in."""
    match = _HEAD_END_MARKER.search(html or "")
    return html[: match.end()] if match else html


def is_page_url(url: Any) -> bool:
    """True when a URL could plausibly serve an HTML page."""
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    if parts.scheme.lower() not in _ALLOWED_SCHEMES or not parts.hostname:
        return False
    path = parts.path.lower()
    return not path.endswith(NON_PAGE_SUFFIXES)


def _source_url(source: Any) -> str:
    if isinstance(source, Mapping):
        return str(source.get("url") or "").strip()
    return str(source or "").strip()


def candidate_urls(
    sources: Iterable[Any] | None, limit: int = MAX_CANDIDATES
) -> list[str]:
    """Fetchable source URLs, best publisher tier first, capped at `limit`.

    The sort is stable, so inside one tier the article's own source order
    decides. Duplicate URLs are collapsed.
    """
    seen: set[str] = set()
    ranked: list[tuple[int, int, str]] = []
    for index, source in enumerate(sources or ()):
        url = _source_url(source)
        if not url or url in seen or not is_page_url(url):
            continue
        seen.add(url)
        ranked.append((publisher_tier(url), index, url))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [url for _, _, url in ranked[: max(0, int(limit))]]


def _is_html_response(content_type: str) -> bool:
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    if not kind:
        # A publisher that declares nothing still gets parsed: the worst case
        # is that no meta tag is found.
        return True
    return any(hint in kind for hint in HTML_CONTENT_HINTS)


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def build_client() -> httpx.AsyncClient:
    """An AsyncClient configured the way section 14.2 requires."""
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
        headers=REQUEST_HEADERS,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
    )


@asynccontextmanager
async def _client_scope(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield the caller's client, or own one for the duration of the call."""
    if client is not None:
        yield client
        return
    owned = build_client()
    try:
        yield owned
    finally:
        await owned.aclose()


async def fetch_head_html(url: str, client: httpx.AsyncClient) -> str | None:
    """The head of one page as text, or None when it cannot be read.

    Reading stops at `</head>` or 200 KB, whichever comes first. Every
    transport failure, non-200 status and non-markup content type returns None
    instead of raising.
    """
    buffer = bytearray()
    try:
        async with client.stream(
            "GET",
            url,
            headers=REQUEST_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
        ) as response:
            if response.status_code != 200:
                logger.debug(
                    "image fetch %s returned HTTP %d", url, response.status_code
                )
                return None
            if not _is_html_response(response.headers.get("content-type", "")):
                logger.debug(
                    "image fetch %s is not markup: %s",
                    url,
                    response.headers.get("content-type", ""),
                )
                return None
            encoding = response.charset_encoding or "utf-8"
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                tail_start = max(0, len(buffer) - 8)
                buffer.extend(chunk)
                if _HEAD_END_RE.search(bytes(buffer[tail_start:])):
                    break
                if len(buffer) >= MAX_HEAD_BYTES:
                    break
    except asyncio.CancelledError:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.debug("image fetch %s failed: %s: %s", url, type(exc).__name__, exc)
        return None

    if not buffer:
        return None
    try:
        text = bytes(buffer[:MAX_HEAD_BYTES]).decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = bytes(buffer[:MAX_HEAD_BYTES]).decode("utf-8", errors="replace")
    return truncate_at_head_end(text)


async def resolve_image(
    sources: Iterable[Any] | None,
    client: httpx.AsyncClient | None = None,
) -> tuple[str | None, str | None]:
    """Resolve one article's card image.

    Returns (image_url, image_source_url), or (None, None) when no candidate
    page carries a usable tag. Never raises.
    """
    candidates = candidate_urls(sources)
    if not candidates:
        return None, None
    async with _client_scope(client) as active:
        for url in candidates:
            html = await fetch_head_html(url, active)
            if not html:
                continue
            image_url = extract_og_image(html, url)
            if image_url:
                logger.debug("image resolved from %s: %s", url, image_url)
                return image_url, url
            logger.debug("no card image tag on %s", url)
    return None, None


async def resolve_images(
    source_lists: Sequence[Iterable[Any] | None],
    concurrency: int = DEFAULT_CONCURRENCY,
    client: httpx.AsyncClient | None = None,
) -> list[tuple[str | None, str | None]]:
    """Resolve many articles at once, in input order, bounded by `concurrency`.

    One article failing never affects the others: its slot simply comes back
    as (None, None).
    """
    if not source_lists:
        return []
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(sources: Iterable[Any] | None, active: httpx.AsyncClient):
        async with semaphore:
            try:
                return await resolve_image(sources, active)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a miss is never fatal
                logger.debug("image resolution failed: %s: %s", type(exc).__name__, exc)
                return None, None

    async with _client_scope(client) as active:
        return list(
            await asyncio.gather(*(one(sources, active) for sources in source_lists))
        )


__all__ = [
    "DEFAULT_CONCURRENCY",
    "HTML_CONTENT_HINTS",
    "MAX_CANDIDATES",
    "MAX_HEAD_BYTES",
    "META_KEYS",
    "NON_PAGE_SUFFIXES",
    "REQUEST_HEADERS",
    "TIMEOUT_SECONDS",
    "USER_AGENT",
    "build_client",
    "candidate_urls",
    "extract_og_image",
    "fetch_head_html",
    "is_page_url",
    "meta_image_values",
    "meta_tags",
    "normalize_image_url",
    "resolve_image",
    "resolve_images",
    "truncate_at_head_end",
]
