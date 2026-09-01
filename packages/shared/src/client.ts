/**
 * The signed FinBit API client, shared by the web app and the mobile app.
 *
 * One implementation of the handshake, the header set and the retry rules from
 * CONTRACT_MOBILE_ADMIN.md sections 3.5 and 6.1, so a change to the protocol is
 * a change to one file instead of two clients that drift.
 *
 * It deliberately imports nothing from react, react-native or the DOM. Even the
 * fetch, timer and AbortController types are declared locally rather than pulled
 * from lib.dom, because Metro bundles this file for Hermes where lib.dom is a
 * fiction. The two platform specific pieces, credential storage and randomness,
 * arrive through the config instead.
 *
 * What the client does on every call:
 *   1. registers the device once, then reuses the stored credentials
 *   2. signs method, path, query, body digest, timestamp and nonce
 *   3. refreshes the access token exactly once on a 401 invalid_token and
 *      retries the original request with a fresh nonce
 *   4. throws ApiError carrying status, code and detail, never a raw Response
 */

import {
  ENDPOINTS,
  articlePath,
  bookmarkPath,
  buildPath,
  type QueryValue,
} from './endpoints';
import {
  NONCE_BYTES,
  createNonce,
  currentTimestamp,
  signRequest,
} from './signing';
import {
  DEVICE_ID_KEY,
  DEVICE_SECRET_KEY,
  REFRESH_TOKEN_KEY,
  type CredentialStore,
} from './storage';
import type {
  ApiErrorBody,
  AppId,
  ArticleCard,
  BookmarkRequest,
  BookmarkResponse,
  BookmarksResponse,
  CategoriesResponse,
  DevicePlatform,
  DeviceRegisterRequest,
  DeviceRegisterResponse,
  FeedParams,
  FeedResponse,
  HealthResponse,
  PublicConfig,
  RefreshRequest,
  SearchResponse,
  TokenResponse,
  TrendingResponse,
} from './types';

/*
 * Timers are declared here rather than taken from lib.dom or @types/node. Both
 * runtimes provide them, but this package pulls in neither type library, and an
 * ambient declaration inside a module shadows the global only within this file.
 */
declare function setTimeout(handler: () => void, timeoutMs: number): unknown;
declare function clearTimeout(handle: unknown): void;

/** Default per request timeout in milliseconds. */
export const DEFAULT_TIMEOUT_MS = 15000;

/** Refresh this long before the access token actually expires. */
const TOKEN_LEEWAY_MS = 30000;

const FEED_LIMIT_MAX = 50;
const SEARCH_LIMIT_MAX = 50;

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

/** The subset of the fetch Response this client reads. */
export interface HttpResponse {
  readonly ok: boolean;
  readonly status: number;
  text(): Promise<string>;
}

/** The subset of RequestInit this client writes. */
export interface HttpRequestInit {
  method: string;
  headers: Record<string, string>;
  body?: string;
  /** An AbortSignal, kept opaque so this file never references lib.dom. */
  signal?: unknown;
}

export type FetchLike = (url: string, init: HttpRequestInit) => Promise<HttpResponse>;

export interface RequestOptions {
  /** Overrides the client timeout for this call. */
  timeoutMs?: number;
  /**
   * A caller-owned AbortSignal, for example from an effect cleanup. Passing one
   * replaces the internal timeout controller, so the caller owns cancellation.
   */
  signal?: unknown;
}

export interface SendOptions extends RequestOptions {
  query?: Record<string, QueryValue>;
  /** Serialized once by the client, digested and sent as the same string. */
  body?: unknown;
}

export interface ApiClientConfig {
  /** Origin of the API, with or without a trailing slash. */
  baseUrl: string;
  /** APP_KEY_MOBILE or APP_KEY_WEB. A build-time public value by definition. */
  appKey: string;
  /** Must match the app key presented, or registration is refused. */
  appId: AppId;
  /** Reported once at registration and stored on the device row. */
  platform: DevicePlatform;
  /** SecureStore on native, localStorage on web. See storage.ts. */
  store: CredentialStore;
  /** crypto.getRandomValues in a browser, expo-crypto on a device. */
  randomBytes: (length: number) => Uint8Array;
  /** Optional opaque value that survives a reinstall on some platforms. */
  installId?: string;
  timeoutMs?: number;
  /** Overrides the global fetch, mainly for tests. */
  fetchImpl?: FetchLike;
}

/**
 * An API call that failed.
 *
 * status is 0 when the request never reached the API. code is the machine
 * readable value from the error body, for example invalid_token or
 * maintenance, and is null when the server sent none.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: string;

  constructor(status: number, code: string | null, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    // Keeps instanceof working when the class is transpiled down.
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  /** True when the request never reached the API (offline, DNS, CORS, timeout). */
  get isNetworkError(): boolean {
    return this.status === 0;
  }

  /** True while the admin has switched maintenance mode on. */
  get isMaintenance(): boolean {
    return this.code === 'maintenance';
  }

  /** True when a rate limit bucket is empty and the caller should back off. */
  get isRateLimited(): boolean {
    return this.status === 429;
  }
}

/** True when an error came from an aborted request rather than a real failure. */
export function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as { name?: unknown }).name === 'AbortError'
  );
}

export interface ApiClient {
  /** Registers the device if needed and resolves to the device id. */
  ensureDevice(): Promise<string>;
  /** The cached device id, or null before the first call completes. */
  deviceId(): string | null;
  /** Forgets the stored credentials. The next call registers a new device. */
  reset(): Promise<void>;
  /** Escape hatch for a route that has no typed method yet. */
  request<T>(method: HttpMethod, path: string, options?: SendOptions): Promise<T>;

  getFeed(params?: FeedParams, options?: RequestOptions): Promise<FeedResponse>;
  getArticle(articleId: number, options?: RequestOptions): Promise<ArticleCard>;
  search(query: string, options?: RequestOptions & { limit?: number }): Promise<SearchResponse>;
  trending(options?: RequestOptions): Promise<TrendingResponse>;
  categories(options?: RequestOptions): Promise<CategoriesResponse>;
  config(options?: RequestOptions): Promise<PublicConfig>;
  listBookmarks(options?: RequestOptions): Promise<BookmarksResponse>;
  addBookmark(articleId: number, options?: RequestOptions): Promise<BookmarkResponse>;
  removeBookmark(articleId: number, options?: RequestOptions): Promise<BookmarkResponse>;
  health(options?: RequestOptions): Promise<HealthResponse>;
}

interface DeviceCredentials {
  deviceId: string;
  deviceSecret: string;
  refreshToken: string;
}

interface Handshake {
  credentials: DeviceCredentials;
  accessToken: string;
}

interface AbortControllerLike {
  readonly signal: unknown;
  abort(): void;
}

type AbortControllerCtor = new () => AbortControllerLike;

function resolveFetch(): FetchLike {
  const candidate = (globalThis as unknown as { fetch?: FetchLike }).fetch;
  if (typeof candidate !== 'function') {
    throw new Error('No global fetch is available. Pass fetchImpl in the client config.');
  }
  // Browsers reject a fetch called with the wrong receiver, so bind it once.
  return candidate.bind(globalThis) as FetchLike;
}

function createAbortController(): AbortControllerLike | null {
  const ctor = (globalThis as unknown as { AbortController?: AbortControllerCtor }).AbortController;
  return typeof ctor === 'function' ? new ctor() : null;
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

function detailFromPayload(payload: unknown, fallback: string): string {
  if (payload === null || typeof payload !== 'object') {
    return fallback;
  }
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string' && detail.trim() !== '') {
    return detail;
  }
  if (Array.isArray(detail)) {
    // FastAPI validation errors arrive as [{ loc, msg, type }, ...].
    const parts: string[] = [];
    for (const entry of detail) {
      const message = (entry as { msg?: unknown } | null)?.msg;
      if (typeof message === 'string' && message.trim() !== '') {
        parts.push(message);
      }
    }
    if (parts.length > 0) {
      return parts.join('. ');
    }
  }
  return fallback;
}

function toApiError(status: number, payload: unknown): ApiError {
  const detail = detailFromPayload(payload, `Request failed with status ${status}.`);
  let code: string | null = null;
  if (payload !== null && typeof payload === 'object') {
    const raw = (payload as ApiErrorBody).code;
    if (typeof raw === 'string' && raw !== '') {
      code = raw;
    }
  }
  return new ApiError(status, code, detail);
}

export function createApiClient(config: ApiClientConfig): ApiClient {
  const baseUrl = config.baseUrl.replace(/\/+$/, '');
  const defaultTimeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const doFetch = config.fetchImpl ?? resolveFetch();

  let credentials: DeviceCredentials | null = null;
  let accessToken: string | null = null;
  let accessExpiresAt = 0;
  let credentialsPromise: Promise<DeviceCredentials> | null = null;
  let tokenPromise: Promise<string> | null = null;

  function rememberToken(token: string, expiresInSeconds: number): void {
    accessToken = token;
    const lifetimeMs = Math.max(0, Math.floor(expiresInSeconds)) * 1000;
    accessExpiresAt = Date.now() + lifetimeMs;
  }

  async function callFetch(
    pathWithQuery: string,
    init: HttpRequestInit,
    options: RequestOptions,
  ): Promise<HttpResponse> {
    const limitMs = options.timeoutMs ?? defaultTimeoutMs;
    // A caller supplied signal replaces the timeout: two signals cannot be
    // combined without lib.dom, and the caller's intent wins.
    const controller = options.signal === undefined ? createAbortController() : null;
    let timedOut = false;
    let timer: unknown = null;

    if (controller !== null) {
      timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, limitMs);
    }

    try {
      return await doFetch(`${baseUrl}${pathWithQuery}`, {
        ...init,
        signal: options.signal ?? controller?.signal,
      });
    } catch (error) {
      if (timedOut) {
        throw new ApiError(
          0,
          'timeout',
          `The request timed out after ${Math.round(limitMs / 1000)} seconds.`,
        );
      }
      if (isAbortError(error)) {
        // The caller cancelled. Let their cleanup swallow it.
        throw error;
      }
      throw new ApiError(
        0,
        'network_error',
        'Could not reach the FinBit API. Check your connection and try again.',
      );
    } finally {
      if (timer !== null) {
        clearTimeout(timer);
      }
    }
  }

  async function readPayload(response: HttpResponse): Promise<unknown> {
    const raw = await response.text();
    if (raw.trim() === '') {
      return null;
    }
    try {
      return JSON.parse(raw) as unknown;
    } catch {
      return null;
    }
  }

  /**
   * The registration and refresh routes carry the app key but no signature:
   * the device has no secret yet, or is proving possession with the refresh
   * token itself.
   */
  async function unsignedPost<T>(path: string, body: unknown): Promise<T> {
    const raw = JSON.stringify(body);
    const response = await callFetch(
      path,
      {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-App-Key': config.appKey,
        },
        body: raw,
      },
      {},
    );
    const payload = await readPayload(response);
    if (!response.ok) {
      throw toApiError(response.status, payload);
    }
    return payload as T;
  }

  async function persist(next: DeviceCredentials): Promise<void> {
    await config.store.set(DEVICE_ID_KEY, next.deviceId);
    await config.store.set(DEVICE_SECRET_KEY, next.deviceSecret);
    await config.store.set(REFRESH_TOKEN_KEY, next.refreshToken);
  }

  async function forget(): Promise<void> {
    credentials = null;
    accessToken = null;
    accessExpiresAt = 0;
    await config.store.remove(DEVICE_ID_KEY);
    await config.store.remove(DEVICE_SECRET_KEY);
    await config.store.remove(REFRESH_TOKEN_KEY);
  }

  async function register(): Promise<Handshake> {
    const body: DeviceRegisterRequest = {
      app_id: config.appId,
      platform: config.platform,
    };
    if (config.installId !== undefined && config.installId !== '') {
      body.install_id = config.installId;
    }
    const response = await unsignedPost<DeviceRegisterResponse>(ENDPOINTS.authDevice, body);
    const next: DeviceCredentials = {
      deviceId: response.device_id,
      deviceSecret: response.device_secret,
      refreshToken: response.refresh_token,
    };
    await persist(next);
    credentials = next;
    rememberToken(response.access_token, response.expires_in);
    return { credentials: next, accessToken: response.access_token };
  }

  async function loadStored(): Promise<DeviceCredentials | null> {
    const [deviceId, deviceSecret, refreshToken] = await Promise.all([
      config.store.get(DEVICE_ID_KEY),
      config.store.get(DEVICE_SECRET_KEY),
      config.store.get(REFRESH_TOKEN_KEY),
    ]);
    if (!deviceId || !deviceSecret || !refreshToken) {
      return null;
    }
    return { deviceId, deviceSecret, refreshToken };
  }

  function ensureCredentials(): Promise<DeviceCredentials> {
    if (credentials !== null) {
      return Promise.resolve(credentials);
    }
    if (credentialsPromise === null) {
      // Single flight: a cold start fires several screens at once and must not
      // register several devices.
      credentialsPromise = (async () => {
        const stored = await loadStored();
        if (stored !== null) {
          credentials = stored;
          return stored;
        }
        const handshake = await register();
        return handshake.credentials;
      })().finally(() => {
        credentialsPromise = null;
      });
    }
    return credentialsPromise;
  }

  async function refreshAccessToken(current: DeviceCredentials): Promise<string> {
    const body: RefreshRequest = { refresh_token: current.refreshToken };
    try {
      const response = await unsignedPost<TokenResponse>(ENDPOINTS.authRefresh, body);
      const next: DeviceCredentials = { ...current, refreshToken: response.refresh_token };
      credentials = next;
      await config.store.set(REFRESH_TOKEN_KEY, response.refresh_token);
      rememberToken(response.access_token, response.expires_in);
      return response.access_token;
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        // The refresh token was rejected: reused, expired, or the device was
        // revoked. There is no login screen to fall back to, so start over as
        // a new anonymous device rather than leaving the app permanently dead.
        // That device's server-side bookmarks are gone, which is the accepted
        // cost of an app with no accounts.
        await forget();
        const handshake = await register();
        return handshake.accessToken;
      }
      throw error;
    }
  }

  function ensureAccessToken(
    current: DeviceCredentials,
    staleToken?: string | null,
  ): Promise<string> {
    const usable =
      accessToken !== null &&
      accessToken !== staleToken &&
      Date.now() < accessExpiresAt - TOKEN_LEEWAY_MS;
    if (usable) {
      return Promise.resolve(accessToken as string);
    }
    if (tokenPromise === null) {
      tokenPromise = refreshAccessToken(current).finally(() => {
        tokenPromise = null;
      });
    }
    return tokenPromise;
  }

  async function sendSigned<T>(
    method: HttpMethod,
    path: string,
    options: SendOptions,
    current: DeviceCredentials,
    token: string,
  ): Promise<T> {
    const pathWithQuery = buildPath(path, options.query);
    // Serialized once. This exact string is digested and this exact string is
    // sent, which is the whole reason signing agrees with the server.
    const rawBody = options.body === undefined ? undefined : JSON.stringify(options.body);
    const timestamp = currentTimestamp();
    const nonce = createNonce(config.randomBytes(NONCE_BYTES));
    const signature = signRequest(current.deviceSecret, {
      timestamp,
      nonce,
      method,
      pathWithQuery,
      body: rawBody,
    });

    const headers: Record<string, string> = {
      Accept: 'application/json',
      'X-App-Key': config.appKey,
      'X-Device-Id': current.deviceId,
      'X-Timestamp': timestamp,
      'X-Nonce': nonce,
      'X-Signature': signature,
      Authorization: `Bearer ${token}`,
    };
    const init: HttpRequestInit = { method, headers };
    if (rawBody !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = rawBody;
    }

    const response = await callFetch(pathWithQuery, init, options);
    const payload = await readPayload(response);
    if (!response.ok) {
      throw toApiError(response.status, payload);
    }
    return payload as T;
  }

  async function request<T>(
    method: HttpMethod,
    path: string,
    options: SendOptions = {},
  ): Promise<T> {
    const current = await ensureCredentials();
    const token = await ensureAccessToken(current);
    try {
      return await sendSigned<T>(method, path, options, current, token);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401 && error.code === 'invalid_token') {
        // Exactly one retry, with a fresh token, a fresh timestamp and a fresh
        // nonce. The old nonce is burned on the server and cannot be replayed.
        const refreshed = await ensureAccessToken(credentials ?? current, token);
        return await sendSigned<T>(method, path, options, credentials ?? current, refreshed);
      }
      throw error;
    }
  }

  return {
    async ensureDevice(): Promise<string> {
      const current = await ensureCredentials();
      return current.deviceId;
    },

    deviceId(): string | null {
      return credentials === null ? null : credentials.deviceId;
    },

    reset(): Promise<void> {
      return forget();
    },

    request,

    getFeed(params: FeedParams = {}, options: RequestOptions = {}): Promise<FeedResponse> {
      return request<FeedResponse>('GET', ENDPOINTS.feed, {
        ...options,
        query: {
          category: params.category,
          symbol: params.symbol,
          sort: params.sort,
          cursor: params.cursor,
          limit: clampLimit(params.limit, FEED_LIMIT_MAX),
        },
      });
    },

    getArticle(articleId: number, options: RequestOptions = {}): Promise<ArticleCard> {
      return request<ArticleCard>('GET', articlePath(articleId), options);
    },

    search(
      query: string,
      options: RequestOptions & { limit?: number } = {},
    ): Promise<SearchResponse> {
      const { limit, ...rest } = options;
      return request<SearchResponse>('GET', ENDPOINTS.search, {
        ...rest,
        query: { q: query.trim(), limit: clampLimit(limit, SEARCH_LIMIT_MAX) },
      });
    },

    trending(options: RequestOptions = {}): Promise<TrendingResponse> {
      return request<TrendingResponse>('GET', ENDPOINTS.trending, options);
    },

    categories(options: RequestOptions = {}): Promise<CategoriesResponse> {
      return request<CategoriesResponse>('GET', ENDPOINTS.categories, options);
    },

    config(options: RequestOptions = {}): Promise<PublicConfig> {
      return request<PublicConfig>('GET', ENDPOINTS.config, options);
    },

    listBookmarks(options: RequestOptions = {}): Promise<BookmarksResponse> {
      return request<BookmarksResponse>('GET', ENDPOINTS.bookmarks, options);
    },

    addBookmark(articleId: number, options: RequestOptions = {}): Promise<BookmarkResponse> {
      const body: BookmarkRequest = { article_id: articleId };
      return request<BookmarkResponse>('POST', ENDPOINTS.bookmarks, { ...options, body });
    },

    removeBookmark(articleId: number, options: RequestOptions = {}): Promise<BookmarkResponse> {
      return request<BookmarkResponse>('DELETE', bookmarkPath(articleId), options);
    },

    health(options: RequestOptions = {}): Promise<HealthResponse> {
      return request<HealthResponse>('GET', ENDPOINTS.health, options);
    },
  };
}
