/**
 * Typed fetch wrappers for the FinBit REST API, contract section 5.
 * Every request carries the X-Device-Id header and is bounded by a timeout.
 */

import { getDeviceId } from '../lib/device';
import type {
  ArticleCard,
  BookmarkToggleResponse,
  BookmarksResponse,
  CategoriesResponse,
  FeedParams,
  FeedResponse,
  HealthResponse,
  SearchResponse,
  TrendingResponse,
} from './types';

const FALLBACK_API_BASE = 'http://127.0.0.1:8000';

/** Base URL of the API, without a trailing slash. */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? FALLBACK_API_BASE).replace(/\/+$/, '');

/** Default per request timeout in milliseconds. */
export const DEFAULT_TIMEOUT_MS = 15000;

const FEED_LIMIT_MAX = 50;
const SEARCH_LIMIT_MAX = 50;

/** An API call that failed. status is 0 for network failures and timeouts. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    // Keeps instanceof working when the class is transpiled down.
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  /** True when the request never reached the API (offline, DNS, CORS, timeout). */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

export interface RequestOptions {
  /** Caller signal, for example from a React effect cleanup. */
  signal?: AbortSignal;
  /** Overrides DEFAULT_TIMEOUT_MS. */
  timeoutMs?: number;
}

/** True when an error came from an aborted request rather than a real failure. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

type QueryValue = string | number | boolean | undefined | null;

function buildUrl(path: string, query: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') {
      continue;
    }
    search.set(key, String(value));
  }
  const qs = search.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
}

function clampLimit(limit: number | undefined, max: number): number | undefined {
  if (limit === undefined) {
    return undefined;
  }
  const rounded = Math.floor(limit);
  if (!Number.isFinite(rounded) || rounded < 1) {
    return 1;
  }
  return Math.min(rounded, max);
}

function messageFromPayload(payload: unknown, fallback: string): string {
  if (typeof payload === 'string' && payload.trim() !== '') {
    return payload;
  }
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === 'string' && detail.trim() !== '') {
      return detail;
    }
    if (Array.isArray(detail)) {
      // FastAPI validation errors: [{ loc, msg, type }, ...]
      const parts = detail
        .map((entry) =>
          entry && typeof entry === 'object' && typeof (entry as { msg?: unknown }).msg === 'string'
            ? (entry as { msg: string }).msg
            : null,
        )
        .filter((part): part is string => part !== null);
      if (parts.length > 0) {
        return parts.join('. ');
      }
    }
  }
  return fallback;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  query: Record<string, QueryValue> = {},
  options: RequestOptions = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  let timedOut = false;

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const external = options.signal;
  const forwardAbort = () => controller.abort();
  if (external) {
    if (external.aborted) {
      controller.abort();
    } else {
      external.addEventListener('abort', forwardAbort, { once: true });
    }
  }

  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  headers.set('X-Device-Id', getDeviceId());
  if (init.body !== undefined && init.body !== null) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      ...init,
      headers,
      signal: controller.signal,
      mode: 'cors',
      credentials: 'omit',
    });
  } catch (error) {
    if (timedOut) {
      throw new ApiError(0, `The request timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
    }
    if (external?.aborted) {
      // Let the caller's cleanup logic swallow this.
      throw new DOMException('The request was cancelled.', 'AbortError');
    }
    throw new ApiError(0, 'Could not reach the FinBit API. Check that the backend is running.');
  } finally {
    clearTimeout(timer);
    external?.removeEventListener('abort', forwardAbort);
  }

  const raw = await response.text();
  let payload: unknown = null;
  if (raw.trim() !== '') {
    try {
      payload = JSON.parse(raw) as unknown;
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      messageFromPayload(payload, `Request failed with status ${response.status}.`),
    );
  }

  if (payload === null) {
    throw new ApiError(response.status, 'The API returned a response that could not be read.');
  }

  return payload as T;
}

/** GET /api/feed */
export function getFeed(params: FeedParams = {}, options: RequestOptions = {}): Promise<FeedResponse> {
  return request<FeedResponse>(
    '/api/feed',
    { method: 'GET' },
    {
      category: params.category,
      symbol: params.symbol,
      sort: params.sort,
      cursor: params.cursor,
      limit: clampLimit(params.limit, FEED_LIMIT_MAX),
    },
    options,
  );
}

/** GET /api/articles/{id} */
export function getArticle(articleId: number, options: RequestOptions = {}): Promise<ArticleCard> {
  return request<ArticleCard>(`/api/articles/${articleId}`, { method: 'GET' }, {}, options);
}

/** GET /api/search. The API requires a query of at least two characters. */
export function search(
  query: string,
  options: RequestOptions & { limit?: number } = {},
): Promise<SearchResponse> {
  const { limit, ...requestOptions } = options;
  return request<SearchResponse>(
    '/api/search',
    { method: 'GET' },
    { q: query.trim(), limit: clampLimit(limit, SEARCH_LIMIT_MAX) },
    requestOptions,
  );
}

/** GET /api/trending */
export function getTrending(options: RequestOptions = {}): Promise<TrendingResponse> {
  return request<TrendingResponse>('/api/trending', { method: 'GET' }, {}, options);
}

/** GET /api/categories */
export function getCategories(options: RequestOptions = {}): Promise<CategoriesResponse> {
  return request<CategoriesResponse>('/api/categories', { method: 'GET' }, {}, options);
}

/** GET /api/bookmarks, newest saved first. */
export function getBookmarks(options: RequestOptions = {}): Promise<BookmarksResponse> {
  return request<BookmarksResponse>('/api/bookmarks', { method: 'GET' }, {}, options);
}

/** POST /api/bookmarks. Idempotent. */
export function addBookmark(
  articleId: number,
  options: RequestOptions = {},
): Promise<BookmarkToggleResponse> {
  return request<BookmarkToggleResponse>(
    '/api/bookmarks',
    { method: 'POST', body: JSON.stringify({ article_id: articleId }) },
    {},
    options,
  );
}

/** DELETE /api/bookmarks/{article_id}. Idempotent. */
export function removeBookmark(
  articleId: number,
  options: RequestOptions = {},
): Promise<BookmarkToggleResponse> {
  return request<BookmarkToggleResponse>(
    `/api/bookmarks/${articleId}`,
    { method: 'DELETE' },
    {},
    options,
  );
}

/** GET /api/health */
export function getHealth(options: RequestOptions = {}): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health', { method: 'GET' }, {}, options);
}
