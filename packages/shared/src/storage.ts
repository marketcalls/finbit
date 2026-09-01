/**
 * The credential store contract, CONTRACT_MOBILE_ADMIN.md section 8.3.
 *
 * The device secret and the refresh token belong in the most private store each
 * platform offers: expo-secure-store on a device, localStorage in a browser.
 * Those two APIs share no shape and one of them is async, so this package
 * defines the smallest common interface and each app supplies the adapter. That
 * keeps @finbit/shared free of expo-secure-store and of the DOM, which is what
 * lets the same client run in both places.
 *
 * Nothing here writes anything: it only names the keys, so the web app and the
 * mobile app cannot drift apart on where a credential lives.
 */

/**
 * A tiny async key value store for credentials.
 *
 * Every method returns a promise even where the platform is synchronous, so the
 * caller has one code path. An adapter should swallow storage failures on read
 * and resolve to null instead of throwing: a browser in private mode is a
 * normal condition, not an error, and the client will simply register again.
 */
export interface CredentialStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

/** The opaque server-issued device id, sent as X-Device-Id. */
export const DEVICE_ID_KEY = 'finbit.device_id';

/** The base64 device secret. Signing key material, never sent as a header. */
export const DEVICE_SECRET_KEY = 'finbit.device_secret';

/** The rotating device refresh token. Single use, replaced on every refresh. */
export const REFRESH_TOKEN_KEY = 'finbit.refresh_token';

/**
 * The admin refresh token, which the web admin keeps in sessionStorage so
 * closing the tab ends the session. Named here only so there is one spelling.
 */
export const ADMIN_REFRESH_TOKEN_KEY = 'finbit.admin_refresh_token';

/** The three keys the device handshake owns, for a clean logout or reset. */
export const CREDENTIAL_KEYS: readonly string[] = [
  DEVICE_ID_KEY,
  DEVICE_SECRET_KEY,
  REFRESH_TOKEN_KEY,
];

/**
 * A store that keeps credentials for the lifetime of the process only.
 *
 * Useful as a fallback when the real store throws (private browsing, a device
 * with no keychain) and in tests. The device simply registers again next
 * launch, which costs one request and loses that device's bookmarks.
 */
export function createMemoryCredentialStore(): CredentialStore {
  const values = new Map<string, string>();
  return {
    get(key: string): Promise<string | null> {
      return Promise.resolve(values.has(key) ? (values.get(key) as string) : null);
    },
    set(key: string, value: string): Promise<void> {
      values.set(key, value);
      return Promise.resolve();
    },
    remove(key: string): Promise<void> {
      values.delete(key);
      return Promise.resolve();
    },
  };
}
