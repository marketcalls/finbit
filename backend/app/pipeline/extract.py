"""Story extraction: schema, prompt, parsing and normalization.

This module owns everything between a query definition and a clean story dict
that repo.insert_article can store:

1. STORY_SCHEMA, the json_schema block sent as response_format. Every field
   the pipeline depends on is in the required array, because an optional field
   can come back as JSON null (contract section 6).
2. build_instructions and build_input, the prompt rules from contract
   section 6.
3. parse_stories_json, a defensive parser that survives code fences and a
   stray prose line before or after the JSON.
4. normalize_story, which enforces the canonical symbol rules of contract
   section 4, coerces the category into the fixed key set, clamps every enum
   to its vocabulary and turns published_at into ISO 8601 UTC with a Z.
5. merge_search_results, which repairs and enriches each story's sources from
   the separate search_results output item so citations are real links.

A story is dropped when it has an empty headline, a summary under 20 words or
no sources at all.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from app.models import (
    CATEGORY_KEYS,
    IMPACT_DIRECTIONS,
    IMPACT_ENTRY_DIRECTIONS,
    IMPACTS,
    SENTIMENTS,
)
from app.pipeline import dedupe
from app.pipeline.perplexity import AgentResult, PerplexityClient
from app.repo import parse_iso, to_iso_z

logger = logging.getLogger(__name__)

# Validation limits.
MIN_SUMMARY_WORDS = 20
MAX_HEADLINE_CHARS = 200
MAX_SUMMARY_CHARS = 900
MAX_WHY_CHARS = 400
MAX_SYMBOLS = 8
MAX_TOPICS = 6
MAX_IMPACT_ENTRIES = 6
MAX_SOURCES = 10
MAX_EXTRA_SOURCES = 6

# Source repair thresholds.
TITLE_MATCH_THRESHOLD = 0.40
EXTRA_SOURCE_RELEVANCE = 0.34

# A published_at further ahead than this is treated as unusable.
FUTURE_SKEW_MINUTES = 10

SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*(.*?)```", re.DOTALL)
_WORD_RE = re.compile(r"\S+")

# ---------------------------------------------------------------------------
# Canonical symbol vocabulary (contract section 4)
# ---------------------------------------------------------------------------

INDEX_TOKENS: frozenset[str] = frozenset(
    {
        "NIFTY",
        "BANKNIFTY",
        "SENSEX",
        "NIFTYIT",
        "NIFTYPHARMA",
        "NIFTYAUTO",
        "NIFTYFMCG",
        "NIFTYMETAL",
    }
)
CURRENCY_TOKENS: frozenset[str] = frozenset({"USDINR", "EURINR", "DXY"})
COMMODITY_TOKENS: frozenset[str] = frozenset({"GOLD", "SILVER", "CRUDE", "NATGAS"})
CRYPTO_TOKENS: frozenset[str] = frozenset({"BTC", "ETH"})

GLOBAL_EXCHANGES: dict[str, str] = {
    "AAPL": "NASDAQ",
    "MSFT": "NASDAQ",
    "NVDA": "NASDAQ",
    "GOOGL": "NASDAQ",
    "GOOG": "NASDAQ",
    "AMZN": "NASDAQ",
    "META": "NASDAQ",
    "TSLA": "NASDAQ",
    "AMD": "NASDAQ",
    "INTC": "NASDAQ",
    "NFLX": "NASDAQ",
    "AVGO": "NASDAQ",
    "JPM": "NYSE",
    "GS": "NYSE",
    "BAC": "NYSE",
    "XOM": "NYSE",
    "WMT": "NYSE",
    "PFE": "NYSE",
    "KO": "NYSE",
    "DIS": "NYSE",
}

# Raw forms the model is known to emit, mapped to the canonical token.
SYMBOL_ALIASES: dict[str, str] = {
    "^NSEI": "NIFTY",
    "NSEI": "NIFTY",
    "NIFTY50": "NIFTY",
    "NIFTY 50": "NIFTY",
    "NIFTY-50": "NIFTY",
    "CNXNIFTY": "NIFTY",
    "^BSESN": "SENSEX",
    "BSESN": "SENSEX",
    "BSE SENSEX": "SENSEX",
    "S&P BSE SENSEX": "SENSEX",
    "SENSEX30": "SENSEX",
    "^NSEBANK": "BANKNIFTY",
    "NSEBANK": "BANKNIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "BANK NIFTY": "BANKNIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTY IT": "NIFTYIT",
    "NIFTY PHARMA": "NIFTYPHARMA",
    "NIFTY AUTO": "NIFTYAUTO",
    "NIFTY FMCG": "NIFTYFMCG",
    "NIFTY METAL": "NIFTYMETAL",
    "USD/INR": "USDINR",
    "USD INR": "USDINR",
    "USDINR": "USDINR",
    "RUPEE": "USDINR",
    "INDIAN RUPEE": "USDINR",
    "EUR/INR": "EURINR",
    "DOLLAR INDEX": "DXY",
    "US DOLLAR INDEX": "DXY",
    "^DXY": "DXY",
    "CRUDE OIL": "CRUDE",
    "BRENT": "CRUDE",
    "BRENT CRUDE": "CRUDE",
    "WTI": "CRUDE",
    "WTI CRUDE": "CRUDE",
    "OIL": "CRUDE",
    "XAUUSD": "GOLD",
    "XAU": "GOLD",
    "GOLD SPOT": "GOLD",
    "XAGUSD": "SILVER",
    "XAG": "SILVER",
    "NATURAL GAS": "NATGAS",
    "BITCOIN": "BTC",
    "BTCUSD": "BTC",
    "BTC-USD": "BTC",
    "ETHEREUM": "ETH",
    "ETHUSD": "ETH",
    "ETH-USD": "ETH",
    # Common company names the model uses instead of the NSE trading symbol.
    "RELIANCE INDUSTRIES": "RELIANCE",
    "RELIANCE INDUSTRIES LTD": "RELIANCE",
    "RIL": "RELIANCE",
    "STATE BANK OF INDIA": "SBIN",
    "SBI": "SBIN",
    "TATA CONSULTANCY SERVICES": "TCS",
    "HDFC BANK": "HDFCBANK",
    "ICICI BANK": "ICICIBANK",
    "AXIS BANK": "AXISBANK",
    "KOTAK MAHINDRA BANK": "KOTAKBANK",
    "INFOSYS": "INFY",
    "BHARTI AIRTEL": "BHARTIARTL",
    "LARSEN & TOUBRO": "LT",
    "L&T": "LT",
    "TATA MOTORS": "TATAMOTORS",
    "TATA STEEL": "TATASTEEL",
    "MARUTI SUZUKI": "MARUTI",
    "BAJAJ FINANCE": "BAJFINANCE",
    "HINDUSTAN UNILEVER": "HINDUNILVR",
    "ADANI ENTERPRISES": "ADANIENT",
    "ADANI PORTS": "ADANIPORTS",
}

_EXCHANGE_PREFIXES = ("NSE:", "BSE:", "NASDAQ:", "NYSE:", "MCX:", "NSEI:", "IN:")
_TICKER_SUFFIXES = (".NS", ".BO", ".NSE", ".BSE", ".NS:", ".BSE:")

# ---------------------------------------------------------------------------
# Category vocabulary (contract section 4)
# ---------------------------------------------------------------------------

CATEGORY_ALIASES: dict[str, str] = {
    "stock": "stocks",
    "equity": "stocks",
    "equities": "stocks",
    "shares": "stocks",
    "corporate": "stocks",
    "company": "stocks",
    "companies": "stocks",
    "deals": "stocks",
    "market": "india",
    "markets": "india",
    "indian markets": "india",
    "india markets": "india",
    "domestic": "india",
    "nse": "india",
    "bse": "india",
    "world": "global",
    "international": "global",
    "us": "global",
    "usa": "global",
    "us markets": "global",
    "global markets": "global",
    "geopolitics": "global",
    "geopolitical": "global",
    "macro": "economy",
    "macroeconomics": "economy",
    "economics": "economy",
    "inflation": "economy",
    "gdp": "economy",
    "fed": "economy",
    "federal reserve": "economy",
    "monetary policy": "rbi",
    "reserve bank": "rbi",
    "reserve bank of india": "rbi",
    "central bank": "rbi",
    "regulation": "sebi",
    "regulatory": "sebi",
    "regulator": "sebi",
    "ipo": "sebi",
    "results": "earnings",
    "result": "earnings",
    "earning": "earnings",
    "quarterly results": "earnings",
    "q1 results": "earnings",
    "commodity": "commodities",
    "metals": "commodities",
    "energy": "commodities",
    "cryptocurrency": "crypto",
    "cryptocurrencies": "crypto",
    "bitcoin": "crypto",
    "digital assets": "crypto",
}

SENTIMENT_TO_DIRECTION: dict[str, str] = {
    "positive": "bullish",
    "negative": "bearish",
    "mixed": "mixed",
    "neutral": "neutral",
}

# ---------------------------------------------------------------------------
# JSON schema sent as response_format (contract section 6)
# ---------------------------------------------------------------------------

SOURCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "publisher": {"type": "string", "description": "Publication name, for example Reuters."},
        "title": {"type": "string", "description": "Headline of the linked article."},
        "url": {"type": "string", "description": "Direct https link to the article."},
        "published_at": {
            "type": "string",
            "description": "Publication timestamp, ISO 8601 UTC ending in Z.",
        },
    },
    "required": ["publisher", "title", "url", "published_at"],
}

IMPACT_ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Market, index or sector affected, for example NIFTY or Banks.",
        },
        "direction": {"type": "string", "enum": list(IMPACT_ENTRY_DIRECTIONS)},
    },
    "required": ["name", "direction"],
}

STORY_PROPERTIES: dict[str, Any] = {
    "headline": {
        "type": "string",
        "description": "Factual headline of at most 90 characters, no clickbait.",
    },
    "summary": {
        "type": "string",
        "description": "50 to 80 words, plain declarative sentences.",
    },
    "why_it_matters": {
        "type": "string",
        "description": "One or two sentences on the read-through for Indian markets.",
    },
    "category": {"type": "string", "enum": list(CATEGORY_KEYS)},
    "sentiment": {"type": "string", "enum": list(SENTIMENTS)},
    "impact": {"type": "string", "enum": list(IMPACTS)},
    "impact_direction": {"type": "string", "enum": list(IMPACT_DIRECTIONS)},
    "is_breaking": {
        "type": "boolean",
        "description": "True only for a major market-moving development of the last few hours.",
    },
    "symbols": {
        "type": "array",
        "items": {"type": "string"},
        "description": "NSE trading symbols in uppercase, for example RELIANCE, TCS.",
    },
    "indices": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Index tokens, for example NIFTY, BANKNIFTY, SENSEX.",
    },
    "topics": {
        "type": "array",
        "items": {"type": "string"},
        "description": "One to three short topic labels, for example Monetary Policy.",
    },
    "published_at": {
        "type": "string",
        "description": "Publication timestamp, ISO 8601 UTC ending in Z.",
    },
    "sources": {"type": "array", "items": SOURCE_SCHEMA},
    "impact_map": {"type": "array", "items": IMPACT_ENTRY_SCHEMA},
}

STORY_REQUIRED: list[str] = list(STORY_PROPERTIES)

STORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": STORY_PROPERTIES,
                "required": STORY_REQUIRED,
            },
        }
    },
    "required": ["stories"],
}


# ---------------------------------------------------------------------------
# Prompt text (contract section 6)
# ---------------------------------------------------------------------------


def build_instructions() -> str:
    """System-style instructions carrying every prompt rule of section 6."""
    categories = ", ".join(CATEGORY_KEYS)
    return (
        "You are the news desk of FinBit, a financial news app for Indian market "
        "traders. Search the web, then return only a JSON object that matches the "
        "supplied schema, with a stories array.\n"
        "\n"
        "Rules for every story:\n"
        "1. Only report stories published in the last 24 hours. Skip anything "
        "older, and skip opinion columns, explainers and promotional posts.\n"
        "2. summary is 50 to 80 words of plain declarative sentences. State the "
        "facts and the numbers. No marketing tone, no hype, no emoji, no em "
        "dashes and no en dashes. Use commas, colons, parentheses or full stops.\n"
        "3. why_it_matters is one or two sentences on the read-through for Indian "
        "markets specifically: what it means for Indian equities, rates, the "
        "rupee or a named sector.\n"
        f"4. category must be exactly one of these lowercase keys: {categories}. "
        "Never use all, never invent a key.\n"
        "5. symbols are canonical NSE trading symbols in uppercase with no "
        "suffix, for example RELIANCE, TCS, HDFCBANK. Do not write RELIANCE.NS, "
        "NSE:TCS or a company's full legal name. Put index tokens in indices, "
        "not in symbols, using exactly NIFTY, BANKNIFTY, SENSEX, NIFTYIT, "
        "NIFTYPHARMA, NIFTYAUTO, NIFTYFMCG or NIFTYMETAL. Global tickers keep "
        "their own ticker, for example AAPL or NVDA. Use USDINR, EURINR or DXY "
        "for currencies, GOLD, SILVER, CRUDE or NATGAS for commodities, and BTC "
        "or ETH for crypto. Leave a list empty rather than guessing.\n"
        "6. sentiment, impact, impact_direction and impact_map are AI "
        "assessments of market relevance, not trading advice and not a "
        "recommendation. Judge impact by how much the story moves Indian "
        "markets: high only for a genuine market mover.\n"
        "7. published_at is the original publication time in ISO 8601 UTC "
        "ending in Z, for example 2026-08-24T09:15:00Z.\n"
        "8. sources must be real articles you actually read, with direct https "
        "links. Prefer wire services, exchange filings and established "
        "financial publications. Never invent a URL. Give at most five sources "
        "per story.\n"
        "9. Each story must be a distinct event. Never return the same event "
        "twice under different wording. Merge duplicate reports into one story "
        "with several sources.\n"
        "10. Every field in the schema is required. When you have nothing for a "
        "list, return an empty list, and never return null.\n"
        "11. Answer with the JSON object only. No prose before it, no prose "
        "after it, no markdown code fence.\n"
    )


def build_input(query: Mapping[str, str], limit: int) -> str:
    """The per-query search task sent as the input field."""
    label = str(query.get("label") or query.get("key") or "market news")
    prompt = str(query.get("prompt") or label)
    count = max(1, int(limit))
    return (
        f"Find the {count} most important {label} stories from the last 24 hours "
        f"for Indian market traders. Search focus: {prompt}. "
        f"Return at most {count} distinct stories as a JSON object with a "
        f"stories array that matches the schema."
    )


# ---------------------------------------------------------------------------
# Defensive JSON parsing
# ---------------------------------------------------------------------------


def strip_code_fences(text: str) -> str:
    """Return the body of the first fenced block, or the text without fences."""
    if not text:
        return ""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.replace("```json", " ").replace("```", " ").strip()


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _loads_embedded(text: str) -> Any:
    """Parse the widest JSON object or array embedded in a block of prose."""
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            parsed = _loads(text[start : end + 1])
            if parsed is not None:
                return parsed
    return None


def recover_story_objects(text: str) -> list[dict[str, Any]]:
    """Pull whole story objects out of a JSON array that was cut off.

    When the model runs into its token budget the payload ends mid object, so
    json.loads fails on the whole document. Every complete object before the
    cut is still perfectly good, and this scanner keeps them.
    """
    start = text.find('"stories"')
    opener = text.find("[", start) if start != -1 else text.find("[")
    if opener == -1:
        return []

    objects: list[dict[str, Any]] = []
    depth = 0
    begin = -1
    in_string = False
    escaped = False
    for index in range(opener + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                begin = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and begin != -1:
                parsed = _loads(text[begin : index + 1])
                if isinstance(parsed, dict):
                    objects.append(parsed)
                begin = -1
        elif char == "]" and depth == 0:
            break
    return objects


def parse_stories_json(text: str) -> list[dict[str, Any]]:
    """Parse the model output into a list of raw story dicts.

    Tolerates a code fence, a leading or trailing prose line, a bare array, a
    single story object and a payload that was cut off by the token budget.
    Never raises: unparsable output yields an empty list, which the caller
    records as a query that produced nothing.
    """
    cleaned = strip_code_fences(text or "")
    if not cleaned:
        return []
    payload = _loads(cleaned)
    if payload is None:
        payload = _loads_embedded(cleaned)

    if isinstance(payload, list):
        stories = [item for item in payload if isinstance(item, dict)]
        if stories:
            return stories
    elif isinstance(payload, dict):
        for key in ("stories", "items", "articles", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                stories = [item for item in value if isinstance(item, dict)]
                if stories:
                    return stories
        if "headline" in payload:
            return [payload]
        # Last resort for an unexpected wrapper key: the first list of objects
        # in the document. Anything that is not a story is dropped later by
        # normalize_story, which needs a headline and a summary.
        for value in payload.values():
            if isinstance(value, list):
                stories = [item for item in value if isinstance(item, dict)]
                if stories:
                    return stories

    recovered = recover_story_objects(cleaned)
    if recovered:
        logger.warning(
            "recovered %d complete story objects from a payload that did not "
            "parse as a whole, the model output was probably cut off",
            len(recovered),
        )
        return recovered
    if payload is None:
        logger.warning(
            "could not parse the model payload, first 300 characters: %s",
            " ".join(cleaned.split())[:300],
        )
    return []


# ---------------------------------------------------------------------------
# Field normalization
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _one_of(value: Any, allowed: Sequence[str], fallback: str) -> str:
    text = _text(value).lower()
    return text if text in allowed else fallback


def word_count(text: str) -> int:
    """Number of whitespace separated words."""
    return len(_WORD_RE.findall(text or ""))


def _strip_market_decoration(text: str) -> str:
    core = text
    for prefix in _EXCHANGE_PREFIXES:
        if core.startswith(prefix):
            core = core[len(prefix) :]
            break
    for suffix in _TICKER_SUFFIXES:
        if core.endswith(suffix):
            core = core[: -len(suffix)]
            break
    return core.lstrip("^").strip()


def classify_symbol(token: str, prefer_index: bool = False) -> tuple[str, str]:
    """Return (kind, exchange) for a canonical token, per contract section 4."""
    if token in INDEX_TOKENS:
        return "index", "INDEX"
    if token in CURRENCY_TOKENS:
        return "currency", "FX"
    if token in COMMODITY_TOKENS:
        return "commodity", "COMMODITY"
    if token in CRYPTO_TOKENS:
        return "crypto", "CRYPTO"
    if prefer_index:
        return "index", "INDEX"
    exchange = GLOBAL_EXCHANGES.get(token)
    if exchange:
        return "stock", exchange
    return "stock", "NSE"


def normalize_symbol(raw: Any, prefer_index: bool = False) -> dict[str, str] | None:
    """Turn one raw ticker into a canonical symbol tag, or None when unusable."""
    text = " ".join(str(raw or "").strip().upper().split())
    if not text:
        return None
    token = SYMBOL_ALIASES.get(text)
    if token is None:
        core = _strip_market_decoration(text)
        token = SYMBOL_ALIASES.get(core)
        if token is None:
            compact = re.sub(r"[^A-Z0-9&-]", "", core)
            token = SYMBOL_ALIASES.get(compact, compact)
    token = token.strip()
    if not SYMBOL_RE.match(token):
        return None
    kind, exchange = classify_symbol(token, prefer_index)
    return {"symbol": token, "exchange": exchange, "kind": kind}


def normalize_symbols(
    symbols: Any, indices: Any = None, limit: int = MAX_SYMBOLS
) -> list[dict[str, str]]:
    """Canonical symbol tags for a story, indices first so they win on ties."""
    tags: list[dict[str, str]] = []
    seen: set[str] = set()
    groups: tuple[tuple[Any, bool], ...] = ((indices, True), (symbols, False))
    for values, prefer_index in groups:
        if isinstance(values, (str, bytes)):
            values = [values]
        for raw in values or []:
            tag = normalize_symbol(raw, prefer_index)
            if tag is None or tag["symbol"] in seen:
                continue
            seen.add(tag["symbol"])
            tags.append(tag)
            if len(tags) >= limit:
                return tags
    return tags


def normalize_category(value: Any, hint: str = "india") -> str:
    """Coerce a model category into the fixed lowercase key set."""
    fallback = hint if hint in CATEGORY_KEYS else "india"
    text = _text(value).lower()
    if not text:
        return fallback
    if text in CATEGORY_KEYS:
        return text
    aliased = CATEGORY_ALIASES.get(text)
    if aliased:
        return aliased
    squashed = re.sub(r"[^a-z]+", "", text)
    if squashed in CATEGORY_KEYS:
        return squashed
    for key in CATEGORY_KEYS:
        if key in squashed:
            return key
    return fallback


def normalize_published_at(value: Any, now: datetime | None = None) -> str:
    """ISO 8601 UTC with a Z. An unparsable or future timestamp becomes now."""
    moment = now or datetime.now(timezone.utc)
    parsed = parse_iso(value) if isinstance(value, str) else None
    if parsed is None and isinstance(value, datetime):
        parsed = (
            value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        ).astimezone(timezone.utc)
    if parsed is None:
        return to_iso_z(moment)
    if parsed > moment + timedelta(minutes=FUTURE_SKEW_MINUTES):
        return to_iso_z(moment)
    return to_iso_z(parsed)


def normalize_topics(value: Any, limit: int = MAX_TOPICS) -> list[str]:
    """Trimmed topic labels without duplicates."""
    if isinstance(value, (str, bytes)):
        value = [value]
    topics: list[str] = []
    seen: set[str] = set()
    for item in value or []:
        name = _text(item, 60)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        topics.append(name)
        if len(topics) >= limit:
            break
    return topics


def normalize_impact_map(value: Any, limit: int = MAX_IMPACT_ENTRIES) -> list[dict[str, str]]:
    """Clean the market impact map, one direction per named market."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value or []:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"), 60)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        entries.append(
            {
                "name": name,
                "direction": _one_of(
                    item.get("direction"), IMPACT_ENTRY_DIRECTIONS, "neutral"
                ),
            }
        )
        if len(entries) >= limit:
            break
    return entries


# ---------------------------------------------------------------------------
# Source repair from the search_results output item
# ---------------------------------------------------------------------------


def _is_web_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _url_key(url: str) -> str:
    """Comparable form of a URL: lowercase host, path without a trailing slash."""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return str(url).strip().lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parts.path or "").rstrip("/").lower()
    return f"{host}{path}"


def _result_publisher(result: Mapping[str, Any]) -> str:
    # Some results put a publication name in source, others a bare hostname.
    source = _text(result.get("source"), 60)
    return source or dedupe.source_domain(result.get("url")) or "Unknown"


def _result_published_at(result: Mapping[str, Any]) -> str | None:
    for key in ("date", "published_at", "last_updated"):
        raw = _text(result.get(key))
        if not raw:
            continue
        parsed = parse_iso(raw)
        if parsed is not None:
            return to_iso_z(parsed)
    return None


def _relevance(headline_tokens: set[str], result: Mapping[str, Any]) -> float:
    """Fraction of headline tokens present in a search result title or snippet."""
    if not headline_tokens:
        return 0.0
    text = f"{result.get('title') or ''} {result.get('snippet') or ''}"
    tokens = dedupe.headline_tokens(text)
    if not tokens:
        return 0.0
    return len(headline_tokens & tokens) / len(headline_tokens)


def merge_search_results(
    sources: Any,
    search_results: Sequence[Mapping[str, Any]] | None,
    headline: str,
    limit: int = MAX_SOURCES,
) -> list[dict[str, Any]]:
    """Repair and enrich a story's sources from the real search results.

    A story source is matched to a search result by URL, or by host plus title
    similarity, in which case the resolvable search result URL replaces the
    model's version. Unmatched search results that are clearly about the same
    story are appended rather than dropped, because the model reliably cites
    fewer sources than it read.
    """
    results = [r for r in (search_results or []) if isinstance(r, Mapping)]
    by_url: dict[str, Mapping[str, Any]] = {}
    by_host: dict[str, list[Mapping[str, Any]]] = {}
    for result in results:
        url = _text(result.get("url"))
        if not _is_web_url(url):
            continue
        by_url.setdefault(_url_key(url), result)
        by_host.setdefault(dedupe.source_domain(url), []).append(result)

    tokens = dedupe.headline_tokens(headline)
    merged: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    used_results: set[str] = set()

    for item in sources or []:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, Mapping):
            continue
        url = _text(item.get("url"))
        if not _is_web_url(url):
            continue
        title = _text(item.get("title"), 200)
        publisher = _text(item.get("publisher"), 60)
        published_at = _text(item.get("published_at")) or None

        match = by_url.get(_url_key(url))
        if match is None:
            host = dedupe.source_domain(url)
            best_score = 0.0
            for candidate in by_host.get(host, []):
                score = dedupe.jaccard(
                    dedupe.headline_tokens(title or headline),
                    dedupe.headline_tokens(_text(candidate.get("title"))),
                )
                if score > best_score:
                    best_score = score
                    match = candidate
            if best_score < TITLE_MATCH_THRESHOLD:
                match = None
        if match is not None:
            # The search result URL is the one that actually resolves.
            url = _text(match.get("url")) or url
            title = title or _text(match.get("title"), 200)
            publisher = publisher or _result_publisher(match)
            published_at = published_at or _result_published_at(match)
            used_results.add(_url_key(_text(match.get("url"))))

        key = _url_key(url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged.append(
            {
                "publisher": publisher or dedupe.source_domain(url) or "Unknown",
                "title": title or None,
                "url": url,
                "published_at": published_at,
            }
        )
        if len(merged) >= limit:
            return merged

    extras = 0
    for result in results:
        if extras >= MAX_EXTRA_SOURCES or len(merged) >= limit:
            break
        url = _text(result.get("url"))
        if not _is_web_url(url):
            continue
        key = _url_key(url)
        if key in seen_keys or key in used_results:
            continue
        if _relevance(tokens, result) < EXTRA_SOURCE_RELEVANCE:
            continue
        seen_keys.add(key)
        extras += 1
        merged.append(
            {
                "publisher": _result_publisher(result),
                "title": _text(result.get("title"), 200) or None,
                "url": url,
                "published_at": _result_published_at(result),
            }
        )
    return merged


# ---------------------------------------------------------------------------
# Story normalization
# ---------------------------------------------------------------------------


def normalize_story(
    raw: Mapping[str, Any],
    query: Mapping[str, str] | None = None,
    search_results: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Validate and normalize one raw story, or return None when unusable.

    Dropped when the headline is empty, the summary is under 20 words or no
    usable source survives.
    """
    if not isinstance(raw, Mapping):
        return None
    query = query or {}
    moment = now or datetime.now(timezone.utc)

    headline = _text(raw.get("headline"), MAX_HEADLINE_CHARS)
    summary = _text(raw.get("summary"), MAX_SUMMARY_CHARS)
    if not headline:
        return None
    if word_count(summary) < MIN_SUMMARY_WORDS:
        return None

    sources = merge_search_results(raw.get("sources"), search_results, headline)
    if not sources:
        return None

    sentiment = _one_of(raw.get("sentiment"), SENTIMENTS, "neutral")
    direction = _one_of(
        raw.get("impact_direction"),
        IMPACT_DIRECTIONS,
        SENTIMENT_TO_DIRECTION.get(sentiment, "neutral"),
    )
    story: dict[str, Any] = {
        "headline": headline,
        "summary": summary,
        "why_it_matters": _text(raw.get("why_it_matters"), MAX_WHY_CHARS) or None,
        "category": normalize_category(
            raw.get("category"), str(query.get("category_hint") or "india")
        ),
        "sentiment": sentiment,
        "impact": _one_of(raw.get("impact"), IMPACTS, "low"),
        "impact_direction": direction,
        "is_breaking": bool(raw.get("is_breaking")),
        "symbols": normalize_symbols(raw.get("symbols"), raw.get("indices")),
        "topics": normalize_topics(raw.get("topics")),
        "sources": sources,
        "impact_map": normalize_impact_map(raw.get("impact_map")),
        "published_at": normalize_published_at(raw.get("published_at"), moment),
        "source_count": len({dedupe.source_domain(s["url"]) for s in sources} - {""}),
        "query_key": str(query.get("key") or ""),
    }
    return story


def build_stories(
    output_text: str,
    search_results: Sequence[Mapping[str, Any]] | None,
    query: Mapping[str, str] | None = None,
    limit: int | None = None,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Parse and normalize a whole batch. Returns (stories, raw_count).

    Pure and offline: this is the function to exercise with a captured
    response body, with no network involved.
    """
    raw_stories = parse_stories_json(output_text)
    stories: list[dict[str, Any]] = []
    seen_headlines: set[str] = set()
    for raw in raw_stories:
        story = normalize_story(raw, query, search_results, now)
        if story is None:
            continue
        key = dedupe.dedupe_key(story["headline"])
        if key in seen_headlines:
            # Two paraphrases of one event inside a single batch.
            continue
        seen_headlines.add(key)
        stories.append(story)
        if limit is not None and len(stories) >= max(1, int(limit)):
            break
    return stories, len(raw_stories)


# ---------------------------------------------------------------------------
# The one call a query makes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExtractionResult:
    """Everything one query produced, including its real cost."""

    query_key: str
    stories: list[dict[str, Any]] = field(default_factory=list)
    raw_count: int = 0
    search_result_count: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0

    @property
    def dropped(self) -> int:
        return max(0, self.raw_count - len(self.stories))


# The Agent API bills tokens actually generated, not the budget, so a generous
# budget costs nothing and only protects against a cut off payload. 8192 is the
# value the Perplexity Agent API documentation uses throughout, and reasoning
# tokens count towards it, which is why the floor sits well above the story
# text itself.
MIN_OUTPUT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 16000
TOKENS_PER_STORY = 1200


def max_output_tokens_for(limit: int) -> int:
    """Token budget for a batch of `limit` stories, never below 8192."""
    return min(
        MAX_OUTPUT_TOKENS,
        max(MIN_OUTPUT_TOKENS, TOKENS_PER_STORY * max(1, int(limit))),
    )


def result_to_stories(
    result: AgentResult,
    query: Mapping[str, str],
    limit: int,
    now: datetime | None = None,
) -> ExtractionResult:
    """Turn a parsed agent response into normalized stories."""
    stories, raw_count = build_stories(
        result.output_text, result.search_results, query, limit, now
    )
    return ExtractionResult(
        query_key=str(query.get("key") or ""),
        stories=stories,
        raw_count=raw_count,
        search_result_count=len(result.search_results),
        cost_usd=result.cost_usd,
        latency_seconds=result.latency_seconds,
    )


async def fetch_stories(
    query: Mapping[str, str],
    limit: int,
    client: PerplexityClient | None = None,
    now: datetime | None = None,
) -> ExtractionResult:
    """Run one query end to end: call the agent, parse, normalize.

    Pass a shared PerplexityClient to reuse one connection pool across a whole
    ingestion cycle.
    """
    key = str(query.get("key") or "")
    instructions = build_instructions()
    input_text = build_input(query, limit)
    budget = max_output_tokens_for(limit)

    if client is None:
        async with PerplexityClient() as owned:
            result = await owned.run_agent(
                input_text,
                instructions,
                STORY_SCHEMA,
                max_output_tokens=budget,
                query_key=key,
            )
    else:
        result = await client.run_agent(
            input_text,
            instructions,
            STORY_SCHEMA,
            max_output_tokens=budget,
            query_key=key,
        )

    extraction = result_to_stories(result, query, limit, now)
    logger.info(
        "extract query=%s raw=%d kept=%d dropped=%d search_results=%d cost=%.5f usd",
        key or "-",
        extraction.raw_count,
        len(extraction.stories),
        extraction.dropped,
        extraction.search_result_count,
        extraction.cost_usd,
    )
    if not extraction.stories:
        logger.warning(
            "query %s produced no usable stories: raw=%d truncated=%s "
            "output_chars=%d. Run with --verbose to log the model payload.",
            key or "-",
            extraction.raw_count,
            result.truncated,
            len(result.output_text),
        )
    return extraction


__all__ = [
    "CATEGORY_ALIASES",
    "COMMODITY_TOKENS",
    "CRYPTO_TOKENS",
    "CURRENCY_TOKENS",
    "EXTRA_SOURCE_RELEVANCE",
    "ExtractionResult",
    "GLOBAL_EXCHANGES",
    "INDEX_TOKENS",
    "MAX_OUTPUT_TOKENS",
    "MAX_SOURCES",
    "MIN_OUTPUT_TOKENS",
    "MIN_SUMMARY_WORDS",
    "SOURCE_SCHEMA",
    "STORY_PROPERTIES",
    "STORY_REQUIRED",
    "STORY_SCHEMA",
    "SYMBOL_ALIASES",
    "SYMBOL_RE",
    "TITLE_MATCH_THRESHOLD",
    "build_input",
    "build_instructions",
    "build_stories",
    "classify_symbol",
    "fetch_stories",
    "max_output_tokens_for",
    "merge_search_results",
    "normalize_category",
    "normalize_impact_map",
    "normalize_published_at",
    "normalize_story",
    "normalize_symbol",
    "normalize_symbols",
    "normalize_topics",
    "parse_stories_json",
    "recover_story_objects",
    "result_to_stories",
    "strip_code_fences",
    "word_count",
]
