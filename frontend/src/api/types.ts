/**
 * Wire types for the FinBit REST API, contract sections 3, 4, 5 and 11.
 *
 * The definitions moved to packages/shared in phase 2, so the web app and the
 * Expo app describe the same API with one set of types and a field that drifts
 * on the server breaks one file instead of two. This module stays because every
 * screen and component imports from '../api/types', and because five phase 1
 * names differ from the shared ones. Those are aliased here rather than renamed
 * across files that belong to other agents.
 *
 * Import the phase 2 types (PublicConfig, the admin payloads, the device
 * handshake) straight from '@finbit/shared'. They are deliberately not
 * re-exported here: this module is the phase 1 surface.
 */

export type {
  ArticleCard,
  BookmarksResponse,
  CategoriesResponse,
  Category,
  FeedParams,
  FeedResponse,
  HealthResponse,
  Impact,
  ImpactDirection,
  ImpactEntry,
  ImpactEntryDirection,
  IngestStatus,
  MarketFilterKey,
  SearchResponse,
  Sentiment,
  SourceRef,
  SymbolKind,
  SymbolTag,
  TrendingResponse,
} from '@finbit/shared';

/*
  The five renames. Left is the phase 1 spelling the screens use, right is the
  shared one. Same shapes, so nothing about the wire format changed.
*/
export type {
  /** Category plus the UI-only "all" tab. */
  FeedCategory as CategoryKey,
  /** Feed ordering: "top" is importance first, "latest" is chronological. */
  SortMode as FeedSort,
  /** One entry of GET /api/categories, including its article count. */
  CategoryCount as CategoryInfo,
  /** One market quick filter chip. */
  MarketFilter as MarketFilterInfo,
  /** POST /api/bookmarks and DELETE /api/bookmarks/{article_id}. */
  BookmarkResponse as BookmarkToggleResponse,
} from '@finbit/shared';
