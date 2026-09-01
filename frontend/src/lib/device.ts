/**
 * The browser's device identity, CONTRACT_MOBILE_ADMIN.md sections 3.2 and 6.1.
 *
 * Phase 1 minted a UUID in this file and sent it as X-Device-Id, which meant
 * anyone who guessed an id could read that browser's bookmarks. Phase 2 replaces
 * it with the anonymous handshake: the server issues the id, derives a secret
 * for it and returns a rotating refresh token, and every later request carries
 * an HMAC over the method, path, body, timestamp and nonce. There is still no
 * login and no account.
 *
 * The signed client is constructed here rather than in api/client.ts because the
 * two are one unit. The client runs the handshake through the credential store
 * this module owns, and recovering from a device the server has revoked means
 * clearing the client's in-memory copy as well as localStorage, which only the
 * client itself can do. Building it in api/client.ts instead would make these
 * two files import each other, and the store would still be in its temporal dead
 * zone when createApiClient ran. api/client.ts is therefore the layer above: it
 * keeps the phase 1 function names the screens already import and adds the
 * timeout and retry policy the web app wants.
 */

import {
  createApiClient,
  createMemoryCredentialStore,
  DEVICE_ID_KEY,
  type ApiClient,
  type CredentialStore,
} from '@finbit/shared';

/**
 * The localStorage key holding the device id, kept under its phase 1 name for
 * anything that still refers to it. It is now the shared constant, so the web
 * app and the Expo app cannot drift on where a credential lives.
 */
export const DEVICE_ID_STORAGE_KEY = DEVICE_ID_KEY;

const FALLBACK_API_BASE = 'http://127.0.0.1:8000';

/** Base URL of the API, without a trailing slash. */
export const API_BASE = String(import.meta.env.VITE_API_BASE ?? FALLBACK_API_BASE).replace(
  /\/+$/,
  '',
);

/**
 * APP_KEY_WEB, reaching the bundle through VITE_APP_KEY. This is a build-time
 * public value by definition (contract section 3.9): it raises the cost of
 * calling the API from something that is not this app, and it is not a secret.
 */
const APP_KEY = String(import.meta.env.VITE_APP_KEY ?? '');

if (import.meta.env.DEV && APP_KEY === '') {
  // Without it every request comes back 401 invalid_app_key with nothing on the
  // screen to explain why. Name the variable, never the value.
  console.warn('VITE_APP_KEY is not set, so the API will refuse every request.');
}

/** Probe key for the storage test below, removed as soon as it is written. */
const STORAGE_PROBE_KEY = 'finbit.storage_probe';

function availableLocalStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const store = window.localStorage;
    // Safari in private mode has a localStorage object that throws on write,
    // so presence is not enough: it has to be exercised once.
    store.setItem(STORAGE_PROBE_KEY, '1');
    store.removeItem(STORAGE_PROBE_KEY);
    return store;
  } catch {
    return null;
  }
}

const backingStore = availableLocalStorage();

/**
 * The credential store the handshake writes through.
 *
 * A browser that blocks storage falls back to memory, so the app still works:
 * it registers a new device on every load, which costs one request and loses
 * that browser's saved stories. That is a better outcome than refusing to run.
 *
 * A returning phase 1 browser has a UUID under the device id key but no secret
 * and no refresh token, and the client needs all three, so it simply registers
 * and overwrites the stale value. No migration step is needed.
 */
function createBrowserCredentialStore(): CredentialStore {
  if (backingStore === null) {
    return createMemoryCredentialStore();
  }
  return {
    get(key: string): Promise<string | null> {
      try {
        return Promise.resolve(backingStore.getItem(key));
      } catch {
        // A quota or permission failure mid-session reads as "no credentials".
        return Promise.resolve(null);
      }
    },
    set(key: string, value: string): Promise<void> {
      try {
        backingStore.setItem(key, value);
      } catch {
        // The credential stays in the client's memory for this page load.
      }
      return Promise.resolve();
    },
    remove(key: string): Promise<void> {
      try {
        backingStore.removeItem(key);
      } catch {
        // Nothing useful to do: the client has already forgotten it.
      }
      return Promise.resolve();
    },
  };
}

/**
 * Entropy for the per request nonce.
 *
 * getRandomValues works in an insecure context too, unlike crypto.subtle, so
 * this holds on plain http during development. There is no Math.random fallback
 * on purpose: predictable nonces would quietly weaken replay protection, and a
 * clear failure is better than a silent one.
 */
function randomBytes(length: number): Uint8Array {
  const source = typeof globalThis === 'undefined' ? undefined : globalThis.crypto;
  if (!source || typeof source.getRandomValues !== 'function') {
    throw new Error('This browser has no crypto.getRandomValues, so requests cannot be signed.');
  }
  return source.getRandomValues(new Uint8Array(length));
}

/** The one signed transport for the public web app. */
export const apiClient: ApiClient = createApiClient({
  baseUrl: API_BASE,
  appKey: APP_KEY,
  appId: 'web',
  platform: 'web',
  store: createBrowserCredentialStore(),
  randomBytes,
});

function readStoredDeviceId(): string | null {
  if (backingStore === null) {
    return null;
  }
  try {
    return backingStore.getItem(DEVICE_ID_KEY);
  } catch {
    return null;
  }
}

/**
 * Registers this browser if it has no credentials yet and resolves to the
 * device id. Every signed call awaits this internally, so a screen only needs
 * to call it directly when it wants the id before its first request.
 */
export function ensureDevice(): Promise<string> {
  return apiClient.ensureDevice();
}

/**
 * The device id for this browser, synchronously.
 *
 * Unlike phase 1 this cannot invent one: the id is now server issued, so it is
 * an empty string on a first visit until the handshake finishes. Nothing needs
 * it for a header any more, because the signed transport sends X-Device-Id from
 * the credentials it holds.
 */
export function getDeviceId(): string {
  return apiClient.deviceId() ?? readStoredDeviceId() ?? '';
}

/*
  Recovery from a device the server no longer accepts.

  This happens in normal development every time the database is recreated: the
  browser still holds credentials for a devices row that is gone, and every
  signed request comes back 401 device_revoked forever. The generation counter
  turns a burst of parallel failures into a single re-registration, because a
  request that failed under an older generation has already been rescued by the
  one that ran first.
*/
let generation = 0;
let recovery: Promise<void> | null = null;

/** The current identity generation, which increases on every re-registration. */
export function deviceGeneration(): number {
  return generation;
}

/**
 * Forget credentials the server has rejected so the next request registers a
 * new device. `seen` is the generation the failed request ran under: when
 * another request has already recovered since then, this is a no-op.
 */
export function recoverRevokedDevice(seen: number): Promise<void> {
  if (seen !== generation) {
    return Promise.resolve();
  }
  if (recovery === null) {
    recovery = apiClient
      .reset()
      .then(() => {
        generation += 1;
      })
      .finally(() => {
        recovery = null;
      });
  }
  return recovery;
}
