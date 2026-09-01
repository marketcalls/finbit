/**
 * Wire types for the FinBit REST API.
 *
 * This file is the single TypeScript mirror of `backend/app/models.py` plus the
 * phase 2 additions in CONTRACT_MOBILE_ADMIN.md sections 6.1 to 6.6. The web app
 * and the mobile app both import from here, so a field that drifts on the server
 * breaks exactly one file instead of two independent copies.
 *
 * Every value vocabulary is lowercase, exactly as the API sends it, and every
 * union below is a string literal union so a typo is a compile error rather than
 * a runtime 422.
 */

// ---------------------------------------------------------------------------
// Vocabularies (CONTRACT.md section 3, mirroring models.py).
// ---------------------------------------------------------------------------

/** A stored article category. Never 'all'. */
export type Category =
  | 'india'
  | 'global'
  | 'stocks'
  | 'economy'
  | 'rbi'
  | 'sebi'
  | 'earnings'
  | 'commodities'
  | 'crypto';

/** A category as used by the feed filter and the categories response. */
export type FeedCategory = 'all' | Category;

/** articles.sentiment */
export type Sentiment = 'positive' | 'negative' | 'neutral' | 'mixed';

/** articles.impact */
export type Impact = 'high' | 'medium' | 'low';

/** articles.impact_direction */
export type ImpactDirection = 'bullish' | 'bearish' | 'neutral' | 'mixed';

/** article_symbols.kind */
export type SymbolKind = 'stock' | 'index' | 'commodity' | 'currency' | 'crypto';

/** article_impacts.direction, a different vocabulary from ImpactDirection. */
export type ImpactEntryDirection = 'positive' | 'negative' | 'mixed' | 'neutral';

/** ingest_runs.status, also reported by /api/health. */
export type IngestStatus = 'running' | 'ok' | 'error';

/** Feed ordering: 'top' is importance first, 'latest' is strictly chronological. */
export type SortMode = 'top' | 'latest';

/** Market quick filters, which filter by symbol rather than by category. */
export type MarketFilterKey = 'NIFTY' | 'BANKNIFTY' | 'SENSEX' | 'USDINR' | 'GOLD' | 'CRUDE';

// ---------------------------------------------------------------------------
// Categories and market filters (CONTRACT.md section 4), in display order.
// These match models.py CATEGORIES and MARKET_FILTERS one for one, so the apps
// can render tabs and chips before the first /api/categories call returns.
// ---------------------------------------------------------------------------

export interface CategoryOption {
  key: FeedCategory;
  label: string;
}

export interface MarketFilterOption {
  key: MarketFilterKey;
  label: string;
}

export const CATEGORIES: readonly CategoryOption[] = [
  { key: 'all', label: 'All' },
  { key: 'india', label: 'India' },
  { key: 'global', label: 'Global' },
  { key: 'stocks', label: 'Stocks' },
  { key: 'economy', label: 'Economy' },
  { key: 'rbi', label: 'RBI' },
  { key: 'sebi', label: 'SEBI' },
  { key: 'earnings', label: 'Earnings' },
  { key: 'commodities', label: 'Commodities' },
  { key: 'crypto', label: 'Crypto' },
];

export const MARKET_FILTERS: readonly MarketFilterOption[] = [
  { key: 'NIFTY', label: 'Nifty' },
  { key: 'BANKNIFTY', label: 'Bank Nifty' },
  { key: 'SENSEX', label: 'Sensex' },
  { key: 'USDINR', label: 'USDINR' },
  { key: 'GOLD', label: 'Gold' },
  { key: 'CRUDE', label: 'Crude' },
];

/** Storable category keys, without the UI-only 'all' pseudo-category. */
export const CATEGORY_KEYS: readonly Category[] = CATEGORIES.filter(
  (entry): entry is CategoryOption & { key: Category } => entry.key !== 'all',
).map((entry) => entry.key);

export const MARKET_FILTER_KEYS: readonly MarketFilterKey[] = MARKET_FILTERS.map(
  (entry) => entry.key,
);

// ---------------------------------------------------------------------------
// Article payload models.
// ---------------------------------------------------------------------------

/** One ticker tagged on an article. */
export interface SymbolTag {
  symbol: string;
  /** NSE, NASDAQ, NYSE, INDEX, COMMODITY, FX or CRYPTO. */
  exchange: string;
  kind: SymbolKind;
}

/** One publisher link behind a story. */
export interface SourceRef {
  publisher: string;
  title: string | null;
  url: string;
  published_at: string | null;
}

/** One line of the market impact map, for example NIFTY: neutral. */
export interface ImpactEntry {
  /** A symbol or a sector label, for example NIFTY or Banks. */
  name: string;
  direction: ImpactEntryDirection;
}

/** The exact JSON returned by every article-bearing endpoint. */
export interface ArticleCard {
  id: number;
  story_cluster_id: string;
  headline: string;
  summary: string;
  why_it_matters: string | null;
  category: Category;
  sentiment: Sentiment;
  impact: Impact;
  impact_direction: ImpactDirection;
  importance_score: number;
  is_breaking: boolean;
  source_count: number;
  /** ISO 8601 UTC with a trailing Z. */
  published_at: string;
  /** ISO 8601 UTC with a trailing Z. */
  created_at: string;
  /**
   * CONTRACT.md section 14: the Open Graph image resolved from the story's
   * source pages, hotlinked from the publisher. Null when no source carried
   * one, in which case the card renders a typographic plate instead.
   * image_source_url and image_checked_at stay internal and are not sent.
   */
  image_url: string | null;
  bookmarked: boolean;
  symbols: SymbolTag[];
  topics: string[];
  sources: SourceRef[];
  impact_map: ImpactEntry[];
}

// ---------------------------------------------------------------------------
// Public endpoint responses (CONTRACT.md section 5).
// ---------------------------------------------------------------------------

/** Query parameters accepted by GET /api/feed. */
export interface FeedParams {
  /** Defaults to 'all' on the server. */
  category?: FeedCategory;
  /** A canonical symbol such as NIFTY or RELIANCE. */
  symbol?: string;
  /** Defaults to 'top' on the server. */
  sort?: SortMode;
  cursor?: string;
  /** Default 20, maximum 50. */
  limit?: number;
}

/** GET /api/feed */
export interface FeedResponse {
  items: ArticleCard[];
  next_cursor: string | null;
  has_more: boolean;
}

/** GET /api/search */
export interface SearchResponse {
  query: string;
  items: ArticleCard[];
  count: number;
}

/** GET /api/trending */
export interface TrendingResponse {
  symbols: string[];
  topics: string[];
}

/** One entry of the categories list, including the 'all' pseudo-category. */
export interface CategoryCount {
  key: FeedCategory;
  label: string;
  count: number;
}

/** One market quick filter chip. */
export interface MarketFilter {
  key: MarketFilterKey;
  label: string;
}

/** GET /api/categories */
export interface CategoriesResponse {
  categories: CategoryCount[];
  market_filters: MarketFilter[];
}

/** GET /api/health, including the cold start fields of CONTRACT.md 13.5. */
export interface HealthResponse {
  status: string;
  articles: number;
  last_ingest_at: string | null;
  last_ingest_status: IngestStatus | null;
  ingest_running: boolean;
  ingest_enabled: boolean;
  reason: string | null;
}

/** GET /api/bookmarks, newest saved first. */
export interface BookmarksResponse {
  items: ArticleCard[];
  count: number;
}

/** POST /api/bookmarks body. */
export interface BookmarkRequest {
  article_id: number;
}

/** POST and DELETE /api/bookmarks response. */
export interface BookmarkResponse {
  article_id: number;
  bookmarked: boolean;
}

// ---------------------------------------------------------------------------
// Ingestion (CONTRACT.md section 5, kept for the legacy admin routes).
// ---------------------------------------------------------------------------

/** POST /api/admin/ingest and POST /api/admin/pipeline/ingest body. */
export interface IngestRequest {
  queries?: string[];
  limit?: number;
}

/** POST /api/admin/ingest and POST /api/admin/pipeline/ingest response. */
export interface IngestResponse {
  started: boolean;
  run_id: number;
}

/** One row of GET /api/admin/runs and of PipelineState.recent_runs. */
export interface IngestRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: IngestStatus;
  queries_run: number;
  stories_seen: number;
  stories_new: number;
  stories_merged: number;
  cost_usd: number;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Device auth (CONTRACT_MOBILE_ADMIN.md section 6.1). There is no login: the
// app registers itself once and keeps the returned credentials.
// ---------------------------------------------------------------------------

/** Which of the two app keys the caller presented. */
export type AppId = 'mobile' | 'web';

/** The device platform reported at registration. */
export type DevicePlatform = 'ios' | 'android' | 'web';

/** POST /api/auth/device body. app_id must match the app key presented. */
export interface DeviceRegisterRequest {
  app_id: AppId;
  platform: DevicePlatform;
  /** Optional opaque value the client may reuse across reinstalls. */
  install_id?: string;
}

/** POST /api/auth/device response. The secret is returned exactly once. */
export interface DeviceRegisterResponse {
  device_id: string;
  /** Standard base64. Signing keys off the decoded bytes, never off this text. */
  device_secret: string;
  access_token: string;
  refresh_token: string;
  /** Access token lifetime in seconds. */
  expires_in: number;
}

/** POST /api/auth/refresh and POST /api/admin/auth/refresh body. */
export interface RefreshRequest {
  refresh_token: string;
}

/** POST /api/auth/refresh response. Refresh tokens rotate on every use. */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

// ---------------------------------------------------------------------------
// Public config (CONTRACT_MOBILE_ADMIN.md section 6.2).
// ---------------------------------------------------------------------------

export interface ConfigCategory {
  key: FeedCategory;
  label: string;
  enabled: boolean;
}

export interface ConfigMarketFilter {
  key: MarketFilterKey;
  label: string;
  enabled: boolean;
}

/**
 * GET /api/config. Fetched before the first feed call so a disabled category
 * never shows as a tab. When maintenance_mode is true every other device route
 * answers 503 with code 'maintenance', so the apps render the message from here.
 */
export interface PublicConfig {
  categories: ConfigCategory[];
  market_filters: ConfigMarketFilter[];
  default_sort: SortMode;
  maintenance_mode: boolean;
  maintenance_message: string | null;
  /** A semver string the mobile app compares against its own build. */
  min_mobile_version: string | null;
}

// ---------------------------------------------------------------------------
// Admin auth (CONTRACT_MOBILE_ADMIN.md section 6.3).
// ---------------------------------------------------------------------------

/** POST /api/admin/auth/login body. */
export interface AdminLoginRequest {
  username: string;
  password: string;
}

/** POST /api/admin/auth/login and /refresh response. */
export interface AdminTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  username: string;
}

/** GET /api/admin/auth/me */
export interface AdminMeResponse {
  username: string;
  last_login_at: string | null;
}

// ---------------------------------------------------------------------------
// Admin pipeline and schedule (CONTRACT_MOBILE_ADMIN.md section 6.4).
// ---------------------------------------------------------------------------

/**
 * The six keys an admin may override from the database, and nothing else.
 * Secrets are deliberately absent: they are never settable over HTTP.
 */
export interface PipelineSettings {
  ingest_enabled: boolean;
  ingest_interval_minutes: number;
  ingest_queries_per_cycle: number;
  ingest_max_stories_per_query: number;
  rescore_interval_minutes: number;
  /** The query keys in rotation, a subset of the nine defined query keys. */
  query_set: string[];
}

/** PATCH /api/admin/pipeline body: any subset of the overridable keys. */
export type PipelineSettingsPatch = Partial<PipelineSettings>;

export interface SchedulerState {
  running: boolean;
  next_ingest_at: string | null;
  next_rescore_at: string | null;
}

/** GET /api/admin/pipeline */
export interface PipelineState {
  settings: PipelineSettings;
  scheduler: SchedulerState;
  /** False when the Perplexity key is missing or the UI trigger is disabled. */
  ingest_available: boolean;
  /** Why ingestion is unavailable, for display next to a disabled button. */
  reason: string | null;
  /** The five most recent runs, newest first. */
  recent_runs: IngestRun[];
}

/** One entry of the nine-query discovery set. */
export interface QueryDef {
  key: string;
  label: string;
  prompt: string;
  category_hint: Category;
  enabled: boolean;
}

/** GET and PUT /api/admin/pipeline/queries */
export interface QuerySetResponse {
  queries: QueryDef[];
}

/** POST /api/admin/pipeline/rescore */
export interface RescoreAllResponse {
  updated: number;
}

/** POST /api/admin/pipeline/images */
export interface ImagesStartedResponse {
  started: boolean;
}

// ---------------------------------------------------------------------------
// Admin content moderation (CONTRACT_MOBILE_ADMIN.md section 6.5).
// ---------------------------------------------------------------------------

/** An ArticleCard plus the moderation columns, admin only. */
export interface AdminArticle extends ArticleCard {
  hidden: boolean;
  pinned: boolean;
  moderated_at: string | null;
  moderated_by: string | null;
  dedupe_key: string;
}

/** Query parameters accepted by GET /api/admin/articles. */
export interface AdminArticleParams {
  q?: string;
  category?: FeedCategory;
  hidden?: boolean;
  pinned?: boolean;
  sort?: SortMode;
  cursor?: string;
  limit?: number;
}

/** GET /api/admin/articles */
export interface AdminArticlesResponse {
  items: AdminArticle[];
  next_cursor: string | null;
  has_more: boolean;
}

/** PATCH /api/admin/articles/{id} body: any subset of the editable fields. */
export interface AdminArticlePatch {
  hidden?: boolean;
  pinned?: boolean;
  category?: Category;
  headline?: string;
  summary?: string;
  why_it_matters?: string | null;
}

/** POST /api/admin/articles/{id}/rescore */
export interface ArticleRescoreResponse {
  importance_score: number;
}

/** POST /api/admin/articles/{id}/refresh-image */
export interface ArticleImageResponse {
  image_url: string | null;
}

/** GET /api/admin/articles/{id}/cluster */
export interface ArticleClusterResponse {
  article: AdminArticle;
  sources: SourceRef[];
  dedupe_key: string;
  story_cluster_id: string;
  /** Other articles that merged into, or share, this cluster. */
  siblings: AdminArticle[];
}

// ---------------------------------------------------------------------------
// Admin feature flags (CONTRACT_MOBILE_ADMIN.md section 6.6).
// ---------------------------------------------------------------------------

export interface AdminFlagCategory extends ConfigCategory {
  updated_at: string | null;
}

export interface AdminFlagMarketFilter extends ConfigMarketFilter {
  updated_at: string | null;
}

/** GET /api/admin/flags: the /api/config shape plus updated_at per key. */
export interface AdminFlagsResponse {
  categories: AdminFlagCategory[];
  market_filters: AdminFlagMarketFilter[];
  default_sort: SortMode;
  maintenance_mode: boolean;
  maintenance_message: string | null;
  min_mobile_version: string | null;
}

/**
 * PUT /api/admin/flags body. Categories and market filters are keyed maps of
 * enabled state rather than arrays, so a partial write cannot reorder the list
 * or silently drop a key the server knows about.
 */
export interface FlagsPayload {
  categories: Record<string, boolean>;
  market_filters: Record<string, boolean>;
  default_sort: SortMode;
  maintenance_mode: boolean;
  maintenance_message: string | null;
  min_mobile_version: string | null;
}

// ---------------------------------------------------------------------------
// Errors (CONTRACT_MOBILE_ADMIN.md section 3.5).
// ---------------------------------------------------------------------------

/**
 * The codes the security layer returns. The client switches on these, so they
 * are a union rather than a bare string. Any other code the server adds later
 * still arrives intact on ApiErrorBody.code.
 */
export type ApiErrorCode =
  | 'invalid_app_key'
  | 'rate_limited'
  | 'missing_signature_headers'
  | 'stale_request'
  | 'replayed_request'
  | 'invalid_token'
  | 'device_revoked'
  | 'bad_signature'
  | 'maintenance';

/** Every failure body: a human sentence plus a stable machine code. */
export interface ApiErrorBody {
  detail: string;
  code?: string | null;
}
