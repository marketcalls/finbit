/**
 * Typed calls into the FinBit REST API, contract section 5.
 *
 * Phase 2 moved the transport itself into packages/shared, so the web app and
 * the Expo app sign requests with one implementation instead of two that drift.
 * Every function below keeps the name and the signature the screens already
 * import: the change is entirely underneath. A request now carries the app key,
 * the device id, a timestamp, a nonce and an HMAC signature rather than a bare
 * X-Device-Id header, and the device handshake happens on the first call.
 *
 * Two policies stay here rather than in the shared client, because they are
 * specific to a browser:
 *
 *   1. A caller signal and the timeout both apply. The shared client drops its
 *      timeout when the caller owns cancellation, since it cannot combine two
 *      signals without lib.dom. A browser has AbortController, and the screens
 *      pass an effect cleanup signal on almost every call, so combining them
 *      here keeps the phase 1 behaviour where a hung request still fails.
 *   2. A revoked device is retried once. See recoverRevokedDevice in lib/device.
 */

import {
  ApiError,
  DEFAULT_TIMEOUT_MS,
  isAbortError,
  type RequestOptions as SignedOptions,
} from '@finbit/shared';
import { apiClient, deviceGeneration, recoverRevokedDevice } from '../lib/device';
import type {
  ArticleCard,
  BookmarksResponse,
  BookmarkToggleResponse,
  CategoriesResponse,
  FeedParams,
  FeedResponse,
  HealthResponse,
  SearchResponse,
  TrendingResponse,
} from './types';

export { API_BASE } from '../lib/device';
export { ApiError, DEFAULT_TIMEOUT_MS, isAbortError };

export interface RequestOptions {
  /** Caller signal, for example from a React effect cleanup. */
  signal?: AbortSignal;
  /** Overrides DEFAULT_TIMEOUT_MS. */
  timeoutMs?: number;
}

/** True for the one failure that a fresh registration can fix. */
function isRevokedDevice(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401 && error.code === 'device_revoked';
}

/**
 * Run one API call with the browser's timeout, cancellation and recovery rules.
 *
 * The retry after a revoked device runs at most once, so a server that keeps
 * rejecting the new device surfaces the error instead of looping. Each attempt
 * gets its own deadline, which is why a recovered call can take up to twice the
 * timeout: the alternative is failing a request that was about to succeed.
 */
async function call<T>(
  run: (options: SignedOptions) => Promise<T>,
  options: RequestOptions,
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const external = options.signal;
  let recovered = false;

  for (;;) {
    const generation = deviceGeneration();
    const controller = new AbortController();
    const forwardAbort = () => controller.abort();
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);

    if (external) {
      if (external.aborted) {
        controller.abort();
      } else {
        external.addEventListener('abort', forwardAbort, { once: true });
      }
    }

    try {
      return await run({ signal: controller.signal });
    } catch (error) {
      if (timedOut && external?.aborted !== true) {
        // The shared client saw a plain abort here, because the timeout was
        // ours. Say what really happened, or the screen swallows it as a
        // cancellation and waits forever.
        throw new ApiError(
          0,
          'timeout',
          `The request timed out after ${Math.round(timeoutMs / 1000)} seconds.`,
        );
      }
      if (!recovered && isRevokedDevice(error)) {
        recovered = true;
        await recoverRevokedDevice(generation);
        continue;
      }
      throw error;
    } finally {
      clearTimeout(timer);
      external?.removeEventListener('abort', forwardAbort);
    }
  }
}

/** GET /api/feed */
export function getFeed(
  params: FeedParams = {},
  options: RequestOptions = {},
): Promise<FeedResponse> {
  return call((signed) => apiClient.getFeed(params, signed), options);
}

/** GET /api/articles/{id} */
export function getArticle(articleId: number, options: RequestOptions = {}): Promise<ArticleCard> {
  return call((signed) => apiClient.getArticle(articleId, signed), options);
}

/** GET /api/search. The API requires a query of at least two characters. */
export function search(
  query: string,
  options: RequestOptions & { limit?: number } = {},
): Promise<SearchResponse> {
  const { limit, ...requestOptions } = options;
  return call((signed) => apiClient.search(query, { ...signed, limit }), requestOptions);
}

/** GET /api/trending */
export function getTrending(options: RequestOptions = {}): Promise<TrendingResponse> {
  return call((signed) => apiClient.trending(signed), options);
}

/** GET /api/categories */
export function getCategories(options: RequestOptions = {}): Promise<CategoriesResponse> {
  return call((signed) => apiClient.categories(signed), options);
}

/** GET /api/bookmarks, newest saved first. Keyed to this device, no login. */
export function getBookmarks(options: RequestOptions = {}): Promise<BookmarksResponse> {
  return call((signed) => apiClient.listBookmarks(signed), options);
}

/** POST /api/bookmarks. Idempotent. */
export function addBookmark(
  articleId: number,
  options: RequestOptions = {},
): Promise<BookmarkToggleResponse> {
  return call((signed) => apiClient.addBookmark(articleId, signed), options);
}

/** DELETE /api/bookmarks/{article_id}. Idempotent. */
export function removeBookmark(
  articleId: number,
  options: RequestOptions = {},
): Promise<BookmarkToggleResponse> {
  return call((signed) => apiClient.removeBookmark(articleId, signed), options);
}

/** GET /api/health */
export function getHealth(options: RequestOptions = {}): Promise<HealthResponse> {
  return call((signed) => apiClient.health(signed), options);
}
