"""Story deduplication (contract section 7).

Pure Python, no vector database, no external service, no extra dependency.
Nothing in this module touches SQLite, so every function here is unit-testable
on plain dicts.

The algorithm:

1. Normalize the headline: lowercase, strip punctuation, drop stopwords and
   expand an alias map. Quarter tokens such as q1 survive.
2. dedupe_key is the first 16 hex characters of the sha1 of the sorted
   normalized token set. An exact key match is an immediate merge.
3. Otherwise score against candidates from the last 48 hours:
   score = 0.55 * jaccard(headline_tokens)
         + 0.25 * symbol_overlap
         + 0.20 * domain_overlap
   Symbol and domain overlap are Jaccard over the symbol and source-hostname
   sets, and two empty sets score 0.0, never 1.0.
4. Merge when score >= SIMILARITY_THRESHOLD.
5. story_cluster_id is the dedupe_key of the first article in the cluster.

About the alias map: the four entries the contract names (ril, sbi, rbi, and
pct or the percent sign) are mandatory and are implemented exactly. The
synonym groups below extend that small map with the financial-reporting
vocabulary needed for the case the contract requires to pass, where four
paraphrases of one Reliance earnings story collapse into a single cluster.
Words that name the same reported quantity (profit, earnings, results) or the
same direction of surprise (rises, jumps, beats) fold onto one canonical
token, so a paraphrase does not read as a different story.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from app.repo import parse_iso, to_iso_z

# Contract section 7 constants.
SIMILARITY_THRESHOLD = 0.62
DEDUPE_WINDOW_HOURS = 48

# Score weights, contract section 7 step 3.
HEADLINE_WEIGHT = 0.55
SYMBOL_WEIGHT = 0.25
DOMAIN_WEIGHT = 0.20

DEDUPE_KEY_LENGTH = 16

# A merged cluster keeps at most this many source links and topics so the
# child tables stay bounded after many merges.
MAX_MERGED_SOURCES = 20
MAX_MERGED_TOPICS = 12

STOPWORDS: frozenset[str] = frozenset(
    """the a an of in on for to at by is are as with from its it after amid over
    said says""".split()
)

# The four alias expansions named in contract section 7. The percent sign is
# handled before tokenization because it is punctuation.
CONTRACT_ALIASES: dict[str, str] = {
    "ril": "reliance",
    "sbi": "statebank",
    "rbi": "reservebank",
    "pct": "percent",
}

# Documented extension of the alias map: each group folds onto its first
# member so paraphrases of one story share tokens.
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    (
        "earnings",
        "earning",
        "profit",
        "profits",
        "pat",
        "netprofit",
        "result",
        "results",
        "bottomline",
    ),
    (
        "gain",
        "gains",
        "gained",
        "rise",
        "rises",
        "rising",
        "rose",
        "jump",
        "jumps",
        "jumped",
        "surge",
        "surges",
        "surged",
        "climb",
        "climbs",
        "climbed",
        "grow",
        "grows",
        "grew",
        "growth",
        "beat",
        "beats",
        "tops",
        "higher",
        "advance",
        "advances",
        "rally",
        "rallies",
    ),
    (
        "fall",
        "falls",
        "fell",
        "drop",
        "drops",
        "dropped",
        "slip",
        "slips",
        "slipped",
        "slide",
        "slides",
        "slid",
        "decline",
        "declines",
        "declined",
        "plunge",
        "plunges",
        "plunged",
        "sink",
        "sinks",
        "lower",
        "miss",
        "misses",
        "missed",
    ),
    (
        "estimates",
        "estimate",
        "expectation",
        "expectations",
        "forecast",
        "forecasts",
        "consensus",
    ),
    (
        "report",
        "reports",
        "reported",
        "post",
        "posts",
        "posted",
        "announce",
        "announces",
        "announced",
    ),
    ("percent", "percentage", "pc"),
    ("quarter", "quarterly"),
    ("reservebank", "rbis"),
)

ALIASES: dict[str, str] = dict(CONTRACT_ALIASES)
for _group in SYNONYM_GROUPS:
    _canonical = _group[0]
    for _word in _group:
        ALIASES.setdefault(_word, _canonical)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PERCENT_RE = re.compile(r"%")

IMPACT_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


# ---------------------------------------------------------------------------
# Headline normalization
# ---------------------------------------------------------------------------


def normalize_headline(headline: str | None) -> list[str]:
    """Return the normalized token list for a headline.

    Lowercase, punctuation stripped, stopwords dropped, aliases expanded, and
    single-character tokens dropped because they carry no clustering signal.
    Quarter tokens such as q1 are two characters and survive.
    """
    if not headline:
        return []
    text = _PERCENT_RE.sub(" percent ", str(headline).lower())
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        if raw in STOPWORDS:
            continue
        token = ALIASES.get(raw, raw)
        if token in STOPWORDS or len(token) < 2:
            continue
        tokens.append(token)
    return tokens


def headline_tokens(headline: str | None) -> set[str]:
    """The unique normalized tokens of a headline."""
    return set(normalize_headline(headline))


def dedupe_key(headline: str | None) -> str:
    """First 16 hex characters of the sha1 of the sorted normalized token set."""
    tokens = sorted(headline_tokens(headline))
    digest = hashlib.sha1(" ".join(tokens).encode("utf-8")).hexdigest()
    return digest[:DEDUPE_KEY_LENGTH]


# ---------------------------------------------------------------------------
# Set helpers
# ---------------------------------------------------------------------------


def jaccard(left: Iterable[str] | None, right: Iterable[str] | None) -> float:
    """Jaccard similarity of two sets. Two empty sets score 0.0, not 1.0."""
    a = set(left or ())
    b = set(right or ())
    if not a or not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def source_domain(url: Any) -> str:
    """Lowercase hostname of a URL without the www prefix, or an empty string."""
    if not url:
        return ""
    try:
        host = urlsplit(str(url)).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def symbol_set(article: Mapping[str, Any] | None) -> set[str]:
    """Uppercase symbol tickers tagged on an article."""
    result: set[str] = set()
    for item in (article or {}).get("symbols") or []:
        if isinstance(item, Mapping):
            value = item.get("symbol")
        else:
            value = item
        text = str(value or "").strip().upper()
        if text:
            result.add(text)
    return result


def domain_set(article: Mapping[str, Any] | None) -> set[str]:
    """Distinct source hostnames behind an article."""
    result: set[str] = set()
    for item in (article or {}).get("sources") or []:
        url = item.get("url") if isinstance(item, Mapping) else item
        domain = source_domain(url)
        if domain:
            result.add(domain)
    return result


def article_tokens(article: Mapping[str, Any] | None) -> set[str]:
    """Headline tokens for an article dict, using a cached set when present."""
    if not article:
        return set()
    cached = article.get("headline_tokens")
    if isinstance(cached, (set, frozenset)):
        return set(cached)
    if isinstance(cached, (list, tuple)):
        return set(cached)
    return headline_tokens(article.get("headline"))


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------


def similarity(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> float:
    """Weighted similarity of two article-shaped dicts, 0.0 to 1.0.

    Each dict needs a headline and may carry symbols and sources. Missing
    parts simply contribute nothing.
    """
    headline = jaccard(article_tokens(a), article_tokens(b))
    symbols = jaccard(symbol_set(a), symbol_set(b))
    domains = jaccard(domain_set(a), domain_set(b))
    score = (
        HEADLINE_WEIGHT * headline + SYMBOL_WEIGHT * symbols + DOMAIN_WEIGHT * domains
    )
    return round(min(1.0, max(0.0, score)), 6)


def is_duplicate(
    a: Mapping[str, Any] | None,
    b: Mapping[str, Any] | None,
    threshold: float = SIMILARITY_THRESHOLD,
) -> bool:
    """True when two stories belong in the same cluster."""
    return similarity(a, b) >= threshold


def best_match(
    incoming: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[dict[str, Any] | None, float]:
    """Highest scoring candidate at or above the threshold.

    Returns (None, best_score_seen) when nothing clears the bar, so the caller
    can log how close the near misses were.
    """
    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in candidates or ():
        score = similarity(incoming, candidate)
        if score > best_score:
            best_score = score
            best = dict(candidate)
    if best is None or best_score < threshold:
        return None, best_score
    return best, best_score


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _earliest(left: Any, right: Any) -> str:
    """The earlier of two timestamps, as ISO 8601 UTC with a trailing Z."""
    left_dt = parse_iso(_text(left) or None)
    right_dt = parse_iso(_text(right) or None)
    if left_dt is None and right_dt is None:
        return to_iso_z(left or right)
    if left_dt is None:
        return to_iso_z(right)
    if right_dt is None:
        return to_iso_z(left)
    return to_iso_z(min(left_dt, right_dt))


def merge_sources(
    existing: Iterable[Any] | None, incoming: Iterable[Any] | None
) -> list[dict[str, Any]]:
    """Union of two source lists keyed by URL, existing entries first."""
    merged: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}
    for group in (existing or [], incoming or []):
        for item in group:
            if isinstance(item, str):
                item = {"url": item}
            if not isinstance(item, Mapping):
                continue
            url = _text(item.get("url"))
            if not url:
                continue
            key = url.rstrip("/").lower()
            current = by_url.get(key)
            if current is None:
                if len(merged) >= MAX_MERGED_SOURCES:
                    continue
                entry = {
                    "publisher": _text(item.get("publisher")) or source_domain(url) or "Unknown",
                    "title": _text(item.get("title")) or None,
                    "url": url,
                    "published_at": _text(item.get("published_at")) or None,
                }
                by_url[key] = entry
                merged.append(entry)
                continue
            # Fill in anything the first copy was missing.
            if not current.get("title") and _text(item.get("title")):
                current["title"] = _text(item.get("title"))
            if not current.get("published_at") and _text(item.get("published_at")):
                current["published_at"] = _text(item.get("published_at"))
    return merged


def merge_symbols(
    existing: Iterable[Any] | None, incoming: Iterable[Any] | None
) -> list[dict[str, str]]:
    """Union of two symbol lists keyed by ticker, existing metadata wins."""
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in (existing or [], incoming or []):
        for item in group:
            if isinstance(item, Mapping):
                symbol = _text(item.get("symbol")).upper()
                exchange = _text(item.get("exchange")).upper() or "NSE"
                kind = _text(item.get("kind")).lower() or "stock"
            else:
                symbol = _text(item).upper()
                exchange, kind = "NSE", "stock"
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            merged.append({"symbol": symbol, "exchange": exchange, "kind": kind})
    return merged


def merge_topics(
    existing: Iterable[Any] | None, incoming: Iterable[Any] | None
) -> list[str]:
    """Case-insensitive union of two topic lists, existing spelling wins."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in (existing or [], incoming or []):
        for item in group:
            name = _text(item)
            if not name:
                continue
            key = name.lower()
            if key in seen or len(merged) >= MAX_MERGED_TOPICS:
                continue
            seen.add(key)
            merged.append(name)
    return merged


def merge_impact_map(
    existing: Iterable[Any] | None, incoming: Iterable[Any] | None
) -> list[dict[str, str]]:
    """Union of two impact maps keyed by name, existing direction wins."""
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in (existing or [], incoming or []):
        for item in group:
            if not isinstance(item, Mapping):
                continue
            name = _text(item.get("name"))
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {"name": name, "direction": _text(item.get("direction")).lower() or "neutral"}
            )
    return merged


def merge_articles(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge an incoming story into the stored article it duplicates.

    Contract section 7 step 4: keep the earliest published_at, union sources,
    symbols, topics and the impact map, set source_count to the distinct
    source-domain count, prefer the longer why_it_matters, keep the higher
    impact, and keep the existing id and story_cluster_id. is_breaking
    escalates the same way impact does. Every other stored field keeps the
    value the cluster already had, so the feed does not churn.
    """
    merged: dict[str, Any] = dict(existing)

    sources = merge_sources(existing.get("sources"), incoming.get("sources"))
    merged["sources"] = sources
    merged["symbols"] = merge_symbols(existing.get("symbols"), incoming.get("symbols"))
    merged["topics"] = merge_topics(existing.get("topics"), incoming.get("topics"))
    merged["impact_map"] = merge_impact_map(
        existing.get("impact_map"), incoming.get("impact_map")
    )
    merged["source_count"] = len({source_domain(s.get("url")) for s in sources} - {""})

    merged["published_at"] = _earliest(
        existing.get("published_at"), incoming.get("published_at")
    )

    existing_why = _text(existing.get("why_it_matters"))
    incoming_why = _text(incoming.get("why_it_matters"))
    merged["why_it_matters"] = (
        incoming_why if len(incoming_why) > len(existing_why) else existing_why
    ) or None

    existing_impact = _text(existing.get("impact")).lower() or "low"
    incoming_impact = _text(incoming.get("impact")).lower() or "low"
    merged["impact"] = (
        incoming_impact
        if IMPACT_RANK.get(incoming_impact, 0) > IMPACT_RANK.get(existing_impact, 0)
        else existing_impact
    )

    merged["is_breaking"] = bool(existing.get("is_breaking")) or bool(
        incoming.get("is_breaking")
    )

    # The cluster identity never moves.
    merged["id"] = existing.get("id")
    merged["story_cluster_id"] = existing.get("story_cluster_id")
    merged["dedupe_key"] = existing.get("dedupe_key")
    merged["created_at"] = existing.get("created_at")
    merged.pop("headline_tokens", None)
    return merged


__all__ = [
    "ALIASES",
    "CONTRACT_ALIASES",
    "DEDUPE_KEY_LENGTH",
    "DEDUPE_WINDOW_HOURS",
    "DOMAIN_WEIGHT",
    "HEADLINE_WEIGHT",
    "IMPACT_RANK",
    "MAX_MERGED_SOURCES",
    "MAX_MERGED_TOPICS",
    "SIMILARITY_THRESHOLD",
    "STOPWORDS",
    "SYMBOL_WEIGHT",
    "SYNONYM_GROUPS",
    "article_tokens",
    "best_match",
    "dedupe_key",
    "domain_set",
    "headline_tokens",
    "is_duplicate",
    "jaccard",
    "merge_articles",
    "merge_impact_map",
    "merge_sources",
    "merge_symbols",
    "merge_topics",
    "normalize_headline",
    "similarity",
    "source_domain",
    "symbol_set",
]
