/**
 * Every FinBit route as a constant, so no screen ever types a path by hand.
 *
 * Paths live in one object rather than as loose exports because the barrel
 * re-exports this module alongside types.ts, and a flat constant such as
 * CATEGORIES would collide with the category list. Path builders keep their own
 * distinct names for the same reason.
 *
 * buildPath lives here too, and is the only place a query string is assembled.
 * That matters for signing: CONTRACT_MOBILE_ADMIN.md section 3.4 requires the
 * signature to cover the path and query exactly as sent, so the caller must sign
 * the string this function returns and then request that same string.
 */

export const API_PREFIX = '/api';

export const ENDPOINTS = {
  // Public and device authenticated, CONTRACT.md section 5.
  health: '/api/health',
  feed: '/api/feed',
  articles: '/api/articles',
  search: '/api/search',
  trending: '/api/trending',
  categories: '/api/categories',
  bookmarks: '/api/bookmarks',

  // Device handshake, app key only, no signature. Section 6.1.
  authDevice: '/api/auth/device',
  authRefresh: '/api/auth/refresh',

  // Public config, device authenticated. Section 6.2.
  config: '/api/config',

  // Admin auth, section 6.3.
  adminLogin: '/api/admin/auth/login',
  adminRefresh: '/api/admin/auth/refresh',
  adminLogout: '/api/admin/auth/logout',
  adminMe: '/api/admin/auth/me',

  // Admin pipeline and schedule, section 6.4.
  adminPipeline: '/api/admin/pipeline',
  adminPipelineIngest: '/api/admin/pipeline/ingest',
  adminPipelineRescore: '/api/admin/pipeline/rescore',
  adminPipelineImages: '/api/admin/pipeline/images',
  adminPipelineQueries: '/api/admin/pipeline/queries',

  // Admin content moderation, section 6.5.
  adminArticles: '/api/admin/articles',

  // Admin feature flags, section 6.6.
  adminFlags: '/api/admin/flags',

  // Phase 1 admin routes, kept so nothing already built breaks.
  adminIngest: '/api/admin/ingest',
  adminRuns: '/api/admin/runs',
} as const;

/** GET /api/articles/{id} */
export function articlePath(articleId: number | string): string {
  return `${ENDPOINTS.articles}/${articleId}`;
}

/** DELETE /api/bookmarks/{article_id} */
export function bookmarkPath(articleId: number | string): string {
  return `${ENDPOINTS.bookmarks}/${articleId}`;
}

/** PATCH and DELETE /api/admin/articles/{id} */
export function adminArticlePath(articleId: number | string): string {
  return `${ENDPOINTS.adminArticles}/${articleId}`;
}

/** POST /api/admin/articles/{id}/rescore */
export function adminArticleRescorePath(articleId: number | string): string {
  return `${ENDPOINTS.adminArticles}/${articleId}/rescore`;
}

/** POST /api/admin/articles/{id}/refresh-image */
export function adminArticleImagePath(articleId: number | string): string {
  return `${ENDPOINTS.adminArticles}/${articleId}/refresh-image`;
}

/** GET /api/admin/articles/{id}/cluster */
export function adminArticleClusterPath(articleId: number | string): string {
  return `${ENDPOINTS.adminArticles}/${articleId}/cluster`;
}

/** A value that may appear in a query string. */
export type QueryValue = string | number | boolean | undefined | null;

/**
 * Join a path and a query object into the exact string that goes on the wire.
 *
 * Undefined, null and empty values are dropped, insertion order is preserved,
 * and encoding is encodeURIComponent rather than URLSearchParams: the React
 * Native polyfill for URLSearchParams does not encode identically to the browser
 * one, and a one character difference invalidates the signature.
 */
export function buildPath(path: string, query?: Record<string, QueryValue>): string {
  if (!query) {
    return path;
  }
  const parts: string[] = [];
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') {
      continue;
    }
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length === 0 ? path : `${path}?${parts.join('&')}`;
}
