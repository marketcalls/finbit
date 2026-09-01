/**
 * The one API client for the app.
 *
 * The transport, the handshake, the signing and the retry rules all live in
 * @finbit/shared so the web app and this app cannot drift. This file supplies the
 * three things that are genuinely platform specific: where the API is, where
 * credentials are stored, and where random bytes come from.
 *
 * Base URL resolution matters more than it looks. Expo Go runs on a physical
 * phone, so "localhost" means the phone itself and a hardcoded IP breaks the
 * moment the developer moves to another network. The dev server already knows
 * the machine's LAN address, so the client reuses that host and swaps in the API
 * port. EXPO_PUBLIC_API_URL overrides everything, which is what makes a dev
 * tunnel and a production build work with no code change.
 *
 * The app key is read from EXPO_PUBLIC_APP_KEY. Expo inlines EXPO_PUBLIC_ values
 * into the bundle at build time, so it is a public value by definition; it raises
 * the cost of calling the API from a script, it does not make the API private.
 * SECURITY.md says so plainly and nothing here should suggest otherwise.
 */

import Constants from 'expo-constants';
import { getRandomBytes } from 'expo-crypto';
import { Platform } from 'react-native';

import {
  ApiError,
  createApiClient,
  isAbortError,
  type ApiClient,
  type DevicePlatform,
} from '@finbit/shared';

import { createCredentialStore } from './storage';

const API_PORT = 8000;

function resolveBaseUrl(): string {
  const configured = process.env.EXPO_PUBLIC_API_URL;
  if (configured) {
    return configured.replace(/\/+$/, '');
  }

  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    // A production web build is served by the API process itself, so the page
    // origin already is the API. In development Metro serves the page on 8081
    // while the API is on 8000.
    if (!__DEV__) {
      return window.location.origin.replace(/\/+$/, '');
    }
    return `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;
  }

  // "192.168.1.20:8081" while connected through Expo Go.
  const hostUri =
    Constants.expoConfig?.hostUri ??
    (Constants as unknown as { expoGoConfig?: { debuggerHost?: string } }).expoGoConfig
      ?.debuggerHost;

  const host = hostUri?.split(':')[0];
  if (host && host !== 'localhost' && host !== '127.0.0.1') {
    return `http://${host}:${API_PORT}`;
  }

  // Android emulators reach the host machine through a dedicated alias.
  if (Platform.OS === 'android') {
    return `http://10.0.2.2:${API_PORT}`;
  }
  return `http://127.0.0.1:${API_PORT}`;
}

/** Where this build talks to. Shown on the Settings screen in development. */
export const API_BASE_URL = resolveBaseUrl();

const APP_KEY = process.env.EXPO_PUBLIC_APP_KEY ?? '';

if (APP_KEY === '' && __DEV__) {
  // Naming the variable is safe; its value is never logged.
  console.warn(
    'FinBit: EXPO_PUBLIC_APP_KEY is not set, so every request will be refused. ' +
      'Copy mobile/.env.example to mobile/.env and set it to APP_KEY_MOBILE from the backend .env.',
  );
}

function devicePlatform(): DevicePlatform {
  if (Platform.OS === 'ios') {
    return 'ios';
  }
  if (Platform.OS === 'android') {
    return 'android';
  }
  return 'web';
}

/**
 * The shared client, wired to this platform. One instance for the app: it holds
 * the access token in memory and single-flights registration, and a second
 * instance would register a second device.
 */
export const api: ApiClient = createApiClient({
  baseUrl: API_BASE_URL,
  appKey: APP_KEY,
  // Always 'mobile', including the web preview, because that is the key this
  // bundle carries and the server checks that the two agree.
  appId: 'mobile',
  platform: devicePlatform(),
  store: createCredentialStore(),
  // expo-crypto reads the platform CSPRNG. Math.random would make nonces
  // predictable, which is the one thing replay protection depends on.
  randomBytes: (length: number) => getRandomBytes(length),
});

export { ApiError, isAbortError };

/**
 * A sentence a user can read, from anything that was thrown.
 *
 * Every list in the app has an error state and none of them may render a raw
 * error object (CONTRACT_MOBILE_ADMIN.md section 8.1). ApiError already carries
 * the server's human sentence; everything else gets a generic line, because an
 * exception message from a library is not written for a reader and can carry
 * request details that do not belong on screen.
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isNetworkError) {
      return 'Cannot reach FinBit. Check your connection and try again.';
    }
    if (error.isRateLimited) {
      return 'Too many requests just now. Wait a moment and try again.';
    }
    return error.detail;
  }
  return 'Something went wrong. Please try again.';
}
