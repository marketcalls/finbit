"""Pydantic v2 models and shared vocabularies.

These mirror contract section 5 exactly. Routers, the pipeline and the
repository all import the enum aliases and the CATEGORIES / MARKET_FILTERS
constants from here so there is exactly one list in the codebase.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Vocabularies (contract section 3). Lowercase in the DB and in the JSON API.
# ---------------------------------------------------------------------------

Category = Literal[
    "india",
    "global",
    "stocks",
    "economy",
    "rbi",
    "sebi",
    "earnings",
    "commodities",
    "crypto",
]
"""A stored article category. Never 'all'."""

FeedCategory = Literal[
    "all",
    "india",
    "global",
    "stocks",
    "economy",
    "rbi",
    "sebi",
    "earnings",
    "commodities",
    "crypto",
]
"""A category as used by the feed filter and the categories response."""

Sentiment = Literal["positive", "negative", "neutral", "mixed"]
Impact = Literal["high", "medium", "low"]
ImpactDirection = Literal["bullish", "bearish", "neutral", "mixed"]
SymbolKind = Literal["stock", "index", "commodity", "currency", "crypto"]
ImpactEntryDirection = Literal["positive", "negative", "mixed", "neutral"]
IngestStatus = Literal["running", "ok", "error"]
SortMode = Literal["top", "latest"]
MarketFilterKey = Literal["NIFTY", "BANKNIFTY", "SENSEX", "USDINR", "GOLD", "CRUDE"]

# ---------------------------------------------------------------------------
# Categories and market filters (contract section 4), in display order.
# ---------------------------------------------------------------------------

CATEGORIES: list[dict[str, str]] = [
    {"key": "all", "label": "All"},
    {"key": "india", "label": "India"},
    {"key": "global", "label": "Global"},
    {"key": "stocks", "label": "Stocks"},
    {"key": "economy", "label": "Economy"},
    {"key": "rbi", "label": "RBI"},
    {"key": "sebi", "label": "SEBI"},
    {"key": "earnings", "label": "Earnings"},
    {"key": "commodities", "label": "Commodities"},
    {"key": "crypto", "label": "Crypto"},
]

MARKET_FILTERS: list[dict[str, str]] = [
    {"key": "NIFTY", "label": "Nifty"},
    {"key": "BANKNIFTY", "label": "Bank Nifty"},
    {"key": "SENSEX", "label": "Sensex"},
    {"key": "USDINR", "label": "USDINR"},
    {"key": "GOLD", "label": "Gold"},
    {"key": "CRUDE", "label": "Crude"},
]

CATEGORY_KEYS: tuple[str, ...] = tuple(c["key"] for c in CATEGORIES if c["key"] != "all")
"""Storable category keys, without the UI-only 'all' pseudo-category."""

FEED_CATEGORY_KEYS: tuple[str, ...] = tuple(c["key"] for c in CATEGORIES)

CATEGORY_LABELS: dict[str, str] = {c["key"]: c["label"] for c in CATEGORIES}

MARKET_FILTER_KEYS: tuple[str, ...] = tuple(f["key"] for f in MARKET_FILTERS)

MARKET_FILTER_LABELS: dict[str, str] = {f["key"]: f["label"] for f in MARKET_FILTERS}

SENTIMENTS: tuple[str, ...] = ("positive", "negative", "neutral", "mixed")
IMPACTS: tuple[str, ...] = ("high", "medium", "low")
IMPACT_DIRECTIONS: tuple[str, ...] = ("bullish", "bearish", "neutral", "mixed")
SYMBOL_KINDS: tuple[str, ...] = ("stock", "index", "commodity", "currency", "crypto")
IMPACT_ENTRY_DIRECTIONS: tuple[str, ...] = ("positive", "negative", "mixed", "neutral")

# ---------------------------------------------------------------------------
# Article payload models.
# ---------------------------------------------------------------------------


class SymbolTag(BaseModel):
    """One ticker tagged on an article."""

    model_config = ConfigDict(extra="ignore")

    symbol: str
    exchange: str = "NSE"
    kind: SymbolKind = "stock"


class SourceRef(BaseModel):
    """One publisher link behind a story."""

    model_config = ConfigDict(extra="ignore")

    publisher: str
    title: str | None = None
    url: str
    published_at: str | None = None


class ImpactEntry(BaseModel):
    """One line of the market impact map, for example NIFTY: neutral."""

    model_config = ConfigDict(extra="ignore")

    name: str
    direction: ImpactEntryDirection


class ArticleCard(BaseModel):
    """The exact JSON returned by every article-bearing endpoint."""

    model_config = ConfigDict(extra="ignore")

    id: int
    story_cluster_id: str
    headline: str
    summary: str
    why_it_matters: str | None = None
    category: Category
    sentiment: Sentiment = "neutral"
    impact: Impact = "low"
    impact_direction: ImpactDirection = "neutral"
    importance_score: int = 0
    is_breaking: bool = False
    source_count: int = 0
    published_at: str
    created_at: str
    image_url: str | None = None
    """Card image resolved from a source page (contract section 14.4).

    image_source_url and image_checked_at stay internal and are deliberately
    absent here, so the extra='ignore' config drops them on validation.
    """
    bookmarked: bool = False
    symbols: list[SymbolTag] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    impact_map: list[ImpactEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoint response models.
# ---------------------------------------------------------------------------


class FeedResponse(BaseModel):
    """GET /api/feed"""

    items: list[ArticleCard] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class SearchResponse(BaseModel):
    """GET /api/search"""

    query: str
    items: list[ArticleCard] = Field(default_factory=list)
    count: int = 0


class TrendingResponse(BaseModel):
    """GET /api/trending"""

    symbols: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class CategoryCount(BaseModel):
    """One entry of the categories list, including the 'all' pseudo-category."""

    key: FeedCategory
    label: str
    count: int = 0


class MarketFilter(BaseModel):
    """One market quick filter chip."""

    key: MarketFilterKey
    label: str


class CategoriesResponse(BaseModel):
    """GET /api/categories"""

    categories: list[CategoryCount] = Field(default_factory=list)
    market_filters: list[MarketFilter] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """GET /api/health, including the cold start fields of contract 13.5."""

    status: str = "ok"
    articles: int = 0
    last_ingest_at: str | None = None
    last_ingest_status: IngestStatus | None = None
    ingest_running: bool = False
    ingest_enabled: bool = True
    reason: str | None = None


# ---------------------------------------------------------------------------
# Bookmark models.
# ---------------------------------------------------------------------------


class BookmarkRequest(BaseModel):
    """POST /api/bookmarks body."""

    article_id: int


class BookmarkResponse(BaseModel):
    """POST and DELETE /api/bookmarks response."""

    article_id: int
    bookmarked: bool


# ---------------------------------------------------------------------------
# Admin and ingestion models.
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    """POST /api/admin/ingest body, both fields optional."""

    queries: list[str] | None = None
    limit: int | None = None


class IngestResponse(BaseModel):
    """POST /api/admin/ingest response."""

    started: bool
    run_id: int


class IngestRun(BaseModel):
    """One row of GET /api/admin/runs."""

    id: int
    started_at: str
    finished_at: str | None = None
    status: IngestStatus = "running"
    queries_run: int = 0
    stories_seen: int = 0
    stories_new: int = 0
    stories_merged: int = 0
    cost_usd: float = 0.0
    error: str | None = None


__all__ = [
    "ArticleCard",
    "BookmarkRequest",
    "BookmarkResponse",
    "CATEGORIES",
    "CATEGORY_KEYS",
    "CATEGORY_LABELS",
    "Category",
    "CategoriesResponse",
    "CategoryCount",
    "FEED_CATEGORY_KEYS",
    "FeedCategory",
    "FeedResponse",
    "HealthResponse",
    "IMPACTS",
    "IMPACT_DIRECTIONS",
    "IMPACT_ENTRY_DIRECTIONS",
    "Impact",
    "ImpactDirection",
    "ImpactEntry",
    "ImpactEntryDirection",
    "IngestRequest",
    "IngestResponse",
    "IngestRun",
    "IngestStatus",
    "MARKET_FILTERS",
    "MARKET_FILTER_KEYS",
    "MARKET_FILTER_LABELS",
    "MarketFilter",
    "MarketFilterKey",
    "SENTIMENTS",
    "SYMBOL_KINDS",
    "SearchResponse",
    "Sentiment",
    "SortMode",
    "SourceRef",
    "SymbolKind",
    "SymbolTag",
    "TrendingResponse",
]
