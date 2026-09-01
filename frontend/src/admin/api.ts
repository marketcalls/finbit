/**
 * Typed client for the admin endpoints, CONTRACT_MOBILE_ADMIN.md sections 6.3
 * to 6.6.
 *
 * Admin traffic is deliberately not routed through the signed device transport.
 * The device handshake exists because the public apps have no login and must
 * prove something about themselves; an admin has a real password, so a bearer
 * token is the whole story and adding an HMAC on top would only mean the admin
 * console has to carry a device secret it has no other use for.
 *
 * Session shape, contract section 3.6 and section 9: the access token lives in
 * a module variable and dies with the tab, the refresh token lives in
 * sessionStorage so closing the tab ends the session, and neither is ever
 * written to localStorage where it would survive a browser restart. A 401 on a
 * normal call triggers exactly one refresh and one retry; a second failure ends
 * the session, because at that point the refresh token is spent or revoked and
 * retrying again would only spin.
 *
 * The route constants and wire types come from @finbit/shared, which is the
 * single definition of the API surface, so a field that moves on the server
 * breaks this file at compile time rather than at runtime. Even the storage key
 * is named there, so the console and the apps cannot drift on where a
 * credential lives.
 */

import {
  ADMIN_REFRESH_TOKEN_KEY,
  ENDPOINTS,
  adminArticleClusterPath,
  adminArticleImagePath,
  adminArticlePath,
  adminArticleRescorePath,
  buildPath,
} from '@finbit/shared';
import type {
  AdminArticle,
  AdminArticleParams,
  AdminArticlePatch,
  AdminArticlesResponse,
  AdminFlagsResponse,
  AdminMeResponse,
  AdminTokenResponse,
  ArticleClusterResponse,
  ArticleImageResponse,
  ArticleRescoreResponse,
  FlagsPayload,
  HealthResponse,
  ImagesStartedResponse,
  IngestRequest,
  IngestResponse,
  PipelineSettingsPatch,
  PipelineState,
  QueryDef,
  QuerySetResponse,
  QueryValue,
  RescoreAllResponse,
} from '@finbit/shared';

const FALLBACK_API_BASE = 'http://127.0.0.1:8000';

/**
 * Base URL of the API, without a trailing slash.
 *
 * Resolved here rather than imported from the public client, because that
 * module is the device handshake and the admin console performs no handshake.
 * It reads the same VITE_API_BASE with the same fallback, so the two cannot
 * point at different servers.
 */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? FALLBACK_API_BASE).replace(/\/+$/, '');

/** Default per request timeout in milliseconds. */
export const DEFAULT_TIMEOUT_MS = 20000;

/**
 * A longer budget for the two routes that do real work before answering.
 * A rescore pass walks every article and an image refresh fetches source pages.
 */
export const LONG_TIMEOUT_MS = 120000;

/** Roughly what one discovery query costs, CONTRACT.md section 9. */
export const COST_PER_QUERY_USD = 0.006;

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/**
 * An admin API call that failed.
 *
 * status is 0 when the request never reached the API, which is a different
 * problem from any HTTP status and gets its own copy in the UI. code carries
 * the machine string from the contract's `{"detail", "code"}` body when the
 * server sent one, so a caller can branch without matching on prose.
 */
export class AdminApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: string;

  constructor(status: number, detail: string, code: string | null = null) {
    super(detail);
    this.name = 'AdminApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
    // Keeps instanceof working when the class is transpiled down.
    Object.setPrototypeOf(this, AdminApiError.prototype);
  }

  /** True when the request never reached the API (offline, DNS, CORS, timeout). */
  get isNetworkError(): boolean {
    return this.status === 0;
  }

  /** True when the session is gone and the console has to show the login form. */
  get isUnauthorized(): boolean {
    return this.status === 401 || this.status === 403;
  }

  /**
   * True when the account is locked out, contract section 3.8.
   *
   * The lock is a distinct condition from a wrong password and the user needs
   * to be told to wait rather than to try again, so it is matched on both the
   * conventional status for a locked resource and on the coded body.
   */
  get isLocked(): boolean {
    return this.status === 423 || this.code === 'account_locked' || this.code === 'locked';
  }

  /** True when a rate limit bucket is empty, contract section 3.7. */
  get isRateLimited(): boolean {
    return this.status === 429 || this.code === 'rate_limited';
  }

  /** True when the API is in maintenance mode, contract section 6.2. */
  get isMaintenance(): boolean {
    return this.status === 503 || this.code === 'maintenance';
  }
}

/** True when an error came from an aborted request rather than a real failure. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

/**
 * The sentence to put in front of the user for any caught value.
 *
 * Screens render this and never the caught value itself, so a stack trace or a
 * raw Response can never reach the page.
 */
export function describeAdminError(error: unknown): string {
  if (error instanceof AdminApiError) {
    if (error.isNetworkError) {
      return 'Could not reach the FinBit API. Check that the backend is running, then try again.';
    }
    if (error.detail !== '') {
      return error.detail;
    }
    return `The API answered ${error.status}.`;
  }
  if (error instanceof Error && error.message !== '') {
    return error.message;
  }
  return 'Something went wrong. Please try again.';
}

// ---------------------------------------------------------------------------
// Session storage
// ---------------------------------------------------------------------------

let accessToken: string | null = null;
let sessionUsername: string | null = null;
let refreshInFlight: Promise<void> | null = null;

const sessionListeners = new Set<() => void>();

function emitSessionChange(): void {
  for (const listener of sessionListeners) {
    listener();
  }
}

function readStoredRefreshToken(): string | null {
  try {
    const stored = window.sessionStorage.getItem(ADMIN_REFRESH_TOKEN_KEY);
    return stored !== null && stored !== '' ? stored : null;
  } catch {
    // Storage is blocked. The session then lives in memory for this page only.
    return null;
  }
}

function writeStoredRefreshToken(token: string): void {
  try {
    window.sessionStorage.setItem(ADMIN_REFRESH_TOKEN_KEY, token);
  } catch {
    // Private browsing. The session survives until the next full page load.
  }
}

function clearStoredRefreshToken(): void {
  try {
    window.sessionStorage.removeItem(ADMIN_REFRESH_TOKEN_KEY);
  } catch {
    // Nothing to do: there was nothing to clear.
  }
}

function adoptTokens(response: AdminTokenResponse): void {
  accessToken = response.access_token;
  sessionUsername = response.username;
  writeStoredRefreshToken(response.refresh_token);
  emitSessionChange();
}

function dropSession(): void {
  const had = accessToken !== null || sessionUsername !== null || readStoredRefreshToken() !== null;
  accessToken = null;
  sessionUsername = null;
  refreshInFlight = null;
  clearStoredRefreshToken();
  if (had) {
    emitSessionChange();
  }
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

interface SendOptions {
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Omitted on login and on refresh, which authenticate with their own body. */
  token?: string | null;
}

/**
 * One HTTP call, with a timeout that also honours a caller supplied signal.
 *
 * AbortSignal.any would express this in one line but is too new to rely on in
 * every browser this console has to open in, so the two signals are joined by
 * hand. The timer is always cleared, including on the error path.
 */
async function send<T>(method: string, path: string, options: SendOptions = {}): Promise<T> {
  const url = `${API_BASE}${buildPath(path, options.query)}`;
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timer = window.setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  const caller = options.signal;
  const forwardAbort = () => {
    controller.abort();
  };
  if (caller) {
    if (caller.aborted) {
      forwardAbort();
    } else {
      caller.addEventListener('abort', forwardAbort);
    }
  }

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }
  let payload: string | undefined;
  if (options.body !== undefined) {
    payload = JSON.stringify(options.body);
    headers['Content-Type'] = 'application/json';
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: payload,
      signal: controller.signal,
      credentials: 'omit',
      mode: 'cors',
    });
  } catch (cause) {
    // A caller abort is the caller's business and is rethrown untouched.
    if (caller?.aborted) {
      throw cause;
    }
    throw new AdminApiError(0, 'The request did not reach the API.', 'network_error');
  } finally {
    window.clearTimeout(timer);
    caller?.removeEventListener('abort', forwardAbort);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let parsed: unknown = null;
  if (text !== '') {
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    throw new AdminApiError(response.status, errorDetail(parsed, response.status), errorCode(parsed));
  }

  return parsed as T;
}

/** Pull the human sentence out of a `{"detail", "code"}` body, or invent one. */
function errorDetail(parsed: unknown, status: number): string {
  if (parsed !== null && typeof parsed === 'object') {
    const detail = (parsed as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail !== '') {
      return detail;
    }
    // FastAPI validation errors arrive as a list of objects, which is not copy.
    if (Array.isArray(detail) && detail.length > 0) {
      return 'The API rejected that request as invalid.';
    }
  }
  if (status === 401) {
    return 'Not signed in.';
  }
  return `The API answered ${status}.`;
}

function errorCode(parsed: unknown): string | null {
  if (parsed !== null && typeof parsed === 'object') {
    const code = (parsed as { code?: unknown }).code;
    if (typeof code === 'string' && code !== '') {
      return code;
    }
  }
  return null;
}

/**
 * Exchange the stored refresh token for a fresh pair.
 *
 * Single flight: several screens can fire calls at once and all of them can see
 * the same expiry, so concurrent callers wait on one exchange instead of racing
 * to spend a single-use token and revoking the session between themselves.
 */
function refreshSession(): Promise<void> {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  const stored = readStoredRefreshToken();
  if (stored === null) {
    dropSession();
    return Promise.reject(new AdminApiError(401, 'Not signed in.', 'no_session'));
  }

  refreshInFlight = send<AdminTokenResponse>('POST', ENDPOINTS.adminRefresh, {
    body: { refresh_token: stored },
  })
    .then((tokens) => {
      adoptTokens(tokens);
    })
    .catch((cause: unknown) => {
      // A network blip must not sign the admin out: only the API saying no does.
      if (cause instanceof AdminApiError && cause.isNetworkError) {
        throw cause;
      }
      dropSession();
      throw cause;
    })
    .finally(() => {
      refreshInFlight = null;
    });

  return refreshInFlight;
}

/** One authenticated call, refreshing once on a 401 and then retrying once. */
async function authorized<T>(method: string, path: string, options: SendOptions = {}): Promise<T> {
  if (accessToken === null) {
    await refreshSession();
  }

  try {
    return await send<T>(method, path, { ...options, token: accessToken });
  } catch (cause) {
    if (!(cause instanceof AdminApiError) || cause.status !== 401) {
      throw cause;
    }
    // One refresh, one retry. A second 401 means the session is genuinely gone.
    await refreshSession();
    try {
      return await send<T>(method, path, { ...options, token: accessToken });
    } catch (second) {
      if (second instanceof AdminApiError && second.status === 401) {
        dropSession();
      }
      throw second;
    }
  }
}

// ---------------------------------------------------------------------------
// Public surface
// ---------------------------------------------------------------------------

/** Watch for a sign in, a sign out or a session the API refused to renew. */
export function subscribeToSession(listener: () => void): () => void {
  sessionListeners.add(listener);
  return () => {
    sessionListeners.delete(listener);
  };
}

/** The signed in username, or null when there is no live session. */
export function currentUsername(): string | null {
  return sessionUsername;
}

/** True when a refresh token is on hand, so a restore is worth attempting. */
export function hasStoredSession(): boolean {
  return readStoredRefreshToken() !== null;
}

export const adminApi = {
  // -- auth, section 6.3 ---------------------------------------------------

  /** Sign in. Throws AdminApiError on a wrong password, a lockout or a limit. */
  async login(username: string, password: string): Promise<string> {
    const tokens = await send<AdminTokenResponse>('POST', ENDPOINTS.adminLogin, {
      body: { username, password },
    });
    adoptTokens(tokens);
    return tokens.username;
  },

  /**
   * Restore a session left behind by a page reload.
   *
   * Resolves to the username, or throws when there is nothing to restore.
   */
  async restore(): Promise<string> {
    await refreshSession();
    if (sessionUsername === null) {
      throw new AdminApiError(401, 'Not signed in.', 'no_session');
    }
    return sessionUsername;
  },

  /**
   * Sign out. The local session is dropped whatever the server says, because a
   * failed revoke must never leave the console showing an admin who cannot act.
   */
  async logout(): Promise<void> {
    const stored = readStoredRefreshToken();
    try {
      if (accessToken !== null) {
        await send<void>('POST', ENDPOINTS.adminLogout, {
          token: accessToken,
          body: stored === null ? undefined : { refresh_token: stored },
        });
      }
    } catch {
      // The token expires by itself. Nothing here is worth blocking a sign out.
    } finally {
      dropSession();
    }
  },

  me(signal?: AbortSignal): Promise<AdminMeResponse> {
    return authorized<AdminMeResponse>('GET', ENDPOINTS.adminMe, { signal });
  },

  // -- pipeline, section 6.4 -----------------------------------------------

  getPipeline(signal?: AbortSignal): Promise<PipelineState> {
    return authorized<PipelineState>('GET', ENDPOINTS.adminPipeline, { signal });
  },

  patchPipeline(patch: PipelineSettingsPatch): Promise<PipelineState> {
    return authorized<PipelineState>('PATCH', ENDPOINTS.adminPipeline, { body: patch });
  },

  triggerIngest(body: IngestRequest = {}): Promise<IngestResponse> {
    return authorized<IngestResponse>('POST', ENDPOINTS.adminPipelineIngest, { body });
  },

  rescoreAll(): Promise<RescoreAllResponse> {
    return authorized<RescoreAllResponse>('POST', ENDPOINTS.adminPipelineRescore, {
      timeoutMs: LONG_TIMEOUT_MS,
    });
  },

  refreshImages(): Promise<ImagesStartedResponse> {
    return authorized<ImagesStartedResponse>('POST', ENDPOINTS.adminPipelineImages, {
      timeoutMs: LONG_TIMEOUT_MS,
    });
  },

  getQueries(signal?: AbortSignal): Promise<QuerySetResponse> {
    return authorized<QuerySetResponse>('GET', ENDPOINTS.adminPipelineQueries, { signal });
  },

  putQueries(queries: QueryDef[]): Promise<QuerySetResponse> {
    return authorized<QuerySetResponse>('PUT', ENDPOINTS.adminPipelineQueries, {
      body: { queries },
    });
  },

  // -- content, section 6.5 ------------------------------------------------

  listArticles(params: AdminArticleParams, signal?: AbortSignal): Promise<AdminArticlesResponse> {
    return authorized<AdminArticlesResponse>('GET', ENDPOINTS.adminArticles, {
      query: {
        q: params.q,
        category: params.category,
        hidden: params.hidden,
        pinned: params.pinned,
        sort: params.sort,
        cursor: params.cursor,
        limit: params.limit,
      },
      signal,
    });
  },

  patchArticle(articleId: number, patch: AdminArticlePatch): Promise<AdminArticle> {
    return authorized<AdminArticle>('PATCH', adminArticlePath(articleId), { body: patch });
  },

  deleteArticle(articleId: number): Promise<void> {
    return authorized<void>('DELETE', adminArticlePath(articleId));
  },

  rescoreArticle(articleId: number): Promise<ArticleRescoreResponse> {
    return authorized<ArticleRescoreResponse>('POST', adminArticleRescorePath(articleId));
  },

  refreshArticleImage(articleId: number): Promise<ArticleImageResponse> {
    return authorized<ArticleImageResponse>('POST', adminArticleImagePath(articleId), {
      timeoutMs: LONG_TIMEOUT_MS,
    });
  },

  getCluster(articleId: number, signal?: AbortSignal): Promise<ArticleClusterResponse> {
    return authorized<ArticleClusterResponse>('GET', adminArticleClusterPath(articleId), { signal });
  },

  // -- flags, section 6.6 --------------------------------------------------

  getFlags(signal?: AbortSignal): Promise<AdminFlagsResponse> {
    return authorized<AdminFlagsResponse>('GET', ENDPOINTS.adminFlags, { signal });
  },

  putFlags(payload: FlagsPayload): Promise<AdminFlagsResponse> {
    return authorized<AdminFlagsResponse>('PUT', ENDPOINTS.adminFlags, { body: payload });
  },

  // -- health --------------------------------------------------------------

  /**
   * GET /api/health, sent with the admin bearer.
   *
   * Phase 2 moves the public routes behind the device handshake, which the
   * admin console does not perform, so this call can legitimately be refused.
   * The dashboard treats that as "not available here" rather than an error,
   * which is why it is a separate call and not folded into the pipeline load.
   */
  health(signal?: AbortSignal): Promise<HealthResponse> {
    return authorized<HealthResponse>('GET', ENDPOINTS.health, { signal });
  },
};
