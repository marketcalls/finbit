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


# ---------------------------------------------------------------------------
# Phase 2 vocabularies (CONTRACT_MOBILE_ADMIN.md sections 3 and 6).
# ---------------------------------------------------------------------------

AppId = Literal["mobile", "web"]
"""Which client is calling. Must match the app key presented."""

DevicePlatform = Literal["ios", "android", "web"]

ADMIN_ARTICLE_SORTS: tuple[str, ...] = ("top", "latest", "oldest")

PIPELINE_SETTING_KEYS: tuple[str, ...] = (
    "ingest_enabled",
    "ingest_interval_minutes",
    "ingest_queries_per_cycle",
    "ingest_max_stories_per_query",
    "rescore_interval_minutes",
    "query_set",
)
"""The only settings an admin may override from the database (section 5).

Secrets are deliberately absent and must never be added here.
"""


class ErrorBody(BaseModel):
    """Every failure body in phase 2: a human sentence plus a stable code."""

    detail: str
    code: str


# ---------------------------------------------------------------------------
# Device authentication (section 6.1).
# ---------------------------------------------------------------------------


class DeviceRegisterRequest(BaseModel):
    """POST /api/auth/device body."""

    model_config = ConfigDict(extra="ignore")

    app_id: AppId
    platform: DevicePlatform
    install_id: str | None = None
    """Opaque and optional. Only ever used to spot a reinstall loop."""


class DeviceRegisterResponse(BaseModel):
    """POST /api/auth/device response.

    device_secret is handed over exactly once, at registration. The server
    derives it again on every request and stores nothing.
    """

    device_id: str
    device_secret: str
    access_token: str
    refresh_token: str
    expires_in: int


class RefreshRequest(BaseModel):
    """POST /api/auth/refresh and the admin refresh and logout bodies."""

    refresh_token: str


class TokenPairResponse(BaseModel):
    """POST /api/auth/refresh response. The refresh token always rotates."""

    access_token: str
    refresh_token: str
    expires_in: int


# ---------------------------------------------------------------------------
# Public config (section 6.2).
# ---------------------------------------------------------------------------


class ConfigCategory(BaseModel):
    """One category as the apps see it, including whether it is switched on."""

    key: FeedCategory
    label: str
    enabled: bool = True


class ConfigMarketFilter(BaseModel):
    """One market quick filter as the apps see it."""

    key: MarketFilterKey
    label: str
    enabled: bool = True


class PublicConfigResponse(BaseModel):
    """GET /api/config, the payload both clients boot from."""

    categories: list[ConfigCategory] = Field(default_factory=list)
    market_filters: list[ConfigMarketFilter] = Field(default_factory=list)
    default_sort: SortMode = "top"
    maintenance_mode: bool = False
    maintenance_message: str | None = None
    min_mobile_version: str | None = None


# ---------------------------------------------------------------------------
# Admin authentication (section 6.3).
# ---------------------------------------------------------------------------


class AdminLoginRequest(BaseModel):
    """POST /api/admin/auth/login body. Never log either field."""

    username: str
    password: str


class AdminTokenResponse(BaseModel):
    """The login and refresh response for an admin session."""

    access_token: str
    refresh_token: str
    expires_in: int
    username: str


class AdminMeResponse(BaseModel):
    """GET /api/admin/auth/me"""

    username: str
    last_login_at: str | None = None


# ---------------------------------------------------------------------------
# Admin pipeline and schedule (section 6.4).
# ---------------------------------------------------------------------------


class PipelineSettings(BaseModel):
    """The overridable settings of section 5, with their effective values."""

    ingest_enabled: bool = True
    ingest_interval_minutes: int = 15
    ingest_queries_per_cycle: int = 4
    ingest_max_stories_per_query: int = 6
    rescore_interval_minutes: int = 30
    query_set: list[str] = Field(default_factory=list)


class PipelineSettingsPatch(BaseModel):
    """PATCH /api/admin/pipeline body: any subset of the overridable keys."""

    model_config = ConfigDict(extra="forbid")

    ingest_enabled: bool | None = None
    ingest_interval_minutes: int | None = None
    ingest_queries_per_cycle: int | None = None
    ingest_max_stories_per_query: int | None = None
    rescore_interval_minutes: int | None = None
    query_set: list[str] | None = None


class SchedulerStatus(BaseModel):
    """What the background scheduler is doing right now."""

    running: bool = False
    next_ingest_at: str | None = None
    next_rescore_at: str | None = None


class PipelineStatusResponse(BaseModel):
    """GET /api/admin/pipeline"""

    settings: PipelineSettings
    scheduler: SchedulerStatus
    ingest_available: bool = False
    reason: str | None = None
    recent_runs: list[IngestRun] = Field(default_factory=list)


class RescoreResponse(BaseModel):
    """POST /api/admin/pipeline/rescore"""

    updated: int = 0


class ImagesResponse(BaseModel):
    """POST /api/admin/pipeline/images, which runs in the background."""

    started: bool = True


class QueryDefinition(BaseModel):
    """One entry of the nine-query set, with its per-query switch."""

    key: str
    label: str
    prompt: str
    category_hint: Category | None = None
    enabled: bool = True


class QuerySetResponse(BaseModel):
    """GET and PUT /api/admin/pipeline/queries"""

    queries: list[QueryDefinition] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Admin content moderation (section 6.5).
# ---------------------------------------------------------------------------


class AdminArticle(ArticleCard):
    """An ArticleCard plus the moderation fields the admin screens need.

    The public feed never returns these, which is why they hang off a subclass
    rather than getting added to ArticleCard.
    """

    hidden: bool = False
    pinned: bool = False
    moderated_at: str | None = None
    moderated_by: str | None = None
    dedupe_key: str = ""


class AdminArticleList(BaseModel):
    """GET /api/admin/articles"""

    items: list[AdminArticle] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class AdminArticlePatch(BaseModel):
    """PATCH /api/admin/articles/{id} body, every field optional."""

    model_config = ConfigDict(extra="forbid")

    hidden: bool | None = None
    pinned: bool | None = None
    category: Category | None = None
    headline: str | None = None
    summary: str | None = None
    why_it_matters: str | None = None


class ArticleScoreResponse(BaseModel):
    """POST /api/admin/articles/{id}/rescore"""

    importance_score: int = 0


class ArticleImageResponse(BaseModel):
    """POST /api/admin/articles/{id}/refresh-image"""

    image_url: str | None = None


class ArticleClusterResponse(BaseModel):
    """GET /api/admin/articles/{id}/cluster"""

    article: AdminArticle
    sources: list[SourceRef] = Field(default_factory=list)
    dedupe_key: str = ""
    story_cluster_id: str = ""
    siblings: list[AdminArticle] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Admin feature flags (section 6.6).
# ---------------------------------------------------------------------------


class FlagState(BaseModel):
    """One switchable key, with when it was last changed."""

    key: str
    label: str
    enabled: bool = True
    updated_at: str | None = None


class AdminFlagsResponse(BaseModel):
    """GET /api/admin/flags: the /api/config shape plus updated_at per key."""

    categories: list[FlagState] = Field(default_factory=list)
    market_filters: list[FlagState] = Field(default_factory=list)
    default_sort: SortMode = "top"
    maintenance_mode: bool = False
    maintenance_message: str | None = None
    min_mobile_version: str | None = None
    updated_at: str | None = None


class AdminFlagsUpdate(BaseModel):
    """PUT /api/admin/flags body. Absent keys are left as they are."""

    model_config = ConfigDict(extra="forbid")

    categories: dict[str, bool] | None = None
    market_filters: dict[str, bool] | None = None
    default_sort: SortMode | None = None
    maintenance_mode: bool | None = None
    maintenance_message: str | None = None
    min_mobile_version: str | None = None


__all__ = [
    "ADMIN_ARTICLE_SORTS",
    "AdminArticle",
    "AdminArticleList",
    "AdminArticlePatch",
    "AdminFlagsResponse",
    "AdminFlagsUpdate",
    "AdminLoginRequest",
    "AdminMeResponse",
    "AdminTokenResponse",
    "AppId",
    "ArticleClusterResponse",
    "ArticleImageResponse",
    "ArticleScoreResponse",
    "ConfigCategory",
    "ConfigMarketFilter",
    "DevicePlatform",
    "DeviceRegisterRequest",
    "DeviceRegisterResponse",
    "ErrorBody",
    "FlagState",
    "ImagesResponse",
    "PIPELINE_SETTING_KEYS",
    "PipelineSettings",
    "PipelineSettingsPatch",
    "PipelineStatusResponse",
    "PublicConfigResponse",
    "QueryDefinition",
    "QuerySetResponse",
    "RefreshRequest",
    "RescoreResponse",
    "SchedulerStatus",
    "TokenPairResponse",
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
