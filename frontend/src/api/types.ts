/**
 * Wire types for the FinBit REST API, contract sections 3, 4, 5 and 11.
 * Every value vocabulary here is lowercase, exactly as the API sends it.
 */

/** articles.category. The UI-only pseudo category "all" is CategoryKey, not Category. */
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

/** Category plus the UI-only "all" tab. */
export type CategoryKey = 'all' | Category;

/** Market quick filters, which filter by symbol rather than category. */
export type MarketFilterKey = 'NIFTY' | 'BANKNIFTY' | 'SENSEX' | 'USDINR' | 'GOLD' | 'CRUDE';

/** articles.sentiment */
export type Sentiment = 'positive' | 'negative' | 'neutral' | 'mixed';

/** articles.impact */
export type Impact = 'high' | 'medium' | 'low';

/** articles.impact_direction */
export type ImpactDirection = 'bullish' | 'bearish' | 'neutral' | 'mixed';

/** article_symbols.kind */
export type SymbolKind = 'stock' | 'index' | 'commodity' | 'currency' | 'crypto';

/** article_impacts.direction */
export type ImpactEntryDirection = 'positive' | 'negative' | 'mixed' | 'neutral';

/** ingest_runs.status, also reported by /api/health */
export type IngestStatus = 'running' | 'ok' | 'error';

/** Feed ordering: "top" is importance first, "latest" is strictly chronological. */
export type FeedSort = 'top' | 'latest';

export interface SymbolTag {
  symbol: string;
  /** NSE, NASDAQ, NYSE, INDEX, COMMODITY, FX or CRYPTO. */
  exchange: string;
  kind: SymbolKind;
}

export interface SourceRef {
  publisher: string;
  title: string | null;
  url: string;
  published_at: string | null;
}

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
  bookmarked: boolean;
  symbols: SymbolTag[];
  topics: string[];
  sources: SourceRef[];
  impact_map: ImpactEntry[];
}

/** GET /api/feed */
export interface FeedResponse {
  items: ArticleCard[];
  next_cursor: string | null;
  has_more: boolean;
}

/** Query parameters accepted by GET /api/feed. */
export interface FeedParams {
  /** Defaults to "all" on the server. */
  category?: CategoryKey;
  /** A canonical symbol such as NIFTY or RELIANCE. */
  symbol?: string;
  /** Defaults to "top" on the server. */
  sort?: FeedSort;
  cursor?: string;
  /** Default 20, maximum 50. */
  limit?: number;
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

export interface CategoryInfo {
  key: CategoryKey;
  label: string;
  count: number;
}

export interface MarketFilterInfo {
  key: MarketFilterKey;
  label: string;
}

/** GET /api/categories */
export interface CategoriesResponse {
  categories: CategoryInfo[];
  market_filters: MarketFilterInfo[];
}

/** GET /api/health */
export interface HealthResponse {
  status: string;
  articles: number;
  last_ingest_at: string | null;
  last_ingest_status: IngestStatus | null;
}

/** GET /api/bookmarks */
export interface BookmarksResponse {
  items: ArticleCard[];
  count: number;
}

/** POST /api/bookmarks and DELETE /api/bookmarks/{article_id} */
export interface BookmarkToggleResponse {
  article_id: number;
  bookmarked: boolean;
}
