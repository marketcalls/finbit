/**
 * The API types, re-exported from @finbit/shared.
 *
 * Nothing is declared here and nothing may be. The web app and this app share
 * one definition of the wire format (CONTRACT_MOBILE_ADMIN.md section 0), so a
 * local copy of ArticleCard that drifted by one field would be a bug that only
 * shows up as a blank card at runtime. Screens import from '@/src/lib/types' for
 * a short path; that path resolves to exactly the same declarations the backend
 * models mirror.
 */

export type {
  // Vocabularies.
  Category,
  FeedCategory,
  Sentiment,
  Impact,
  ImpactDirection,
  SymbolKind,
  ImpactEntryDirection,
  IngestStatus,
  SortMode,
  MarketFilterKey,
  // Category and filter option shapes.
  CategoryOption,
  MarketFilterOption,
  // Article payloads.
  SymbolTag,
  SourceRef,
  ImpactEntry,
  ArticleCard,
  // Public endpoints.
  FeedParams,
  FeedResponse,
  SearchResponse,
  TrendingResponse,
  CategoryCount,
  MarketFilter,
  CategoriesResponse,
  HealthResponse,
  BookmarksResponse,
  BookmarkRequest,
  BookmarkResponse,
  // Device handshake.
  AppId,
  DevicePlatform,
  DeviceRegisterRequest,
  DeviceRegisterResponse,
  RefreshRequest,
  TokenResponse,
  // Public config and feature flags.
  ConfigCategory,
  ConfigMarketFilter,
  PublicConfig,
  // Errors.
  ApiErrorCode,
  ApiErrorBody,
} from '@finbit/shared';

export {
  CATEGORIES,
  CATEGORY_KEYS,
  MARKET_FILTERS,
  MARKET_FILTER_KEYS,
} from '@finbit/shared';
