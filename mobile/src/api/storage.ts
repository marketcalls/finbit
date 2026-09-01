/**
 * The device credential store for React Native.
 *
 * @finbit/shared defines the CredentialStore interface and the key names but
 * deliberately knows nothing about expo-secure-store, so this file is the
 * adapter. CONTRACT_MOBILE_ADMIN.md section 8.3 is exact about where each value
 * lives: the device id, the device secret and the refresh token go in
 * SecureStore, which is the Keychain on iOS and an encrypted SharedPreferences
 * entry on Android. AsyncStorage is plain text on disk and is reserved for the
 * theme preference and cached feed.
 *
 * Two things go wrong in practice and both are handled here rather than at every
 * call site:
 *
 *   - SecureStore does not exist on web. Expo Go can serve this app in a browser
 *     and the web build has no keychain, so there the store falls back to
 *     AsyncStorage, which is localStorage. That is exactly what the contract
 *     prescribes for the web client anyway.
 *   - SecureStore can fail on a device with no screen lock, a corrupted keystore
 *     or a restored backup. A throw there would leave the app permanently unable
 *     to register, so a failure degrades to memory for the session. The device
 *     re-registers on next launch, which costs one request and that device's
 *     saved articles.
 *
 * Nothing in this file logs a value it stores.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import { createMemoryCredentialStore, type CredentialStore } from '@finbit/shared';

/** True where expo-secure-store has a real keystore behind it. */
const HAS_SECURE_STORE = Platform.OS === 'ios' || Platform.OS === 'android';

/**
 * AsyncStorage backed store, used for the web build only. On web AsyncStorage is
 * localStorage, which is the storage the contract names for the web client.
 */
function createAsyncStorageCredentialStore(): CredentialStore {
  return {
    async get(key: string): Promise<string | null> {
      try {
        return await AsyncStorage.getItem(key);
      } catch {
        return null;
      }
    },
    async set(key: string, value: string): Promise<void> {
      await AsyncStorage.setItem(key, value);
    },
    async remove(key: string): Promise<void> {
      try {
        await AsyncStorage.removeItem(key);
      } catch {
        // Removing a key that cannot be read is not a failure worth surfacing.
      }
    },
  };
}

function createSecureCredentialStore(): CredentialStore {
  // Holds the credentials for this session when the keystore refuses to write.
  const fallback = createMemoryCredentialStore();
  let degraded = false;

  function degrade(): void {
    if (!degraded) {
      degraded = true;
      console.warn(
        'FinBit: secure storage is unavailable, so device credentials are kept in memory ' +
          'for this session only. The app will register again on the next launch.',
      );
    }
  }

  return {
    async get(key: string): Promise<string | null> {
      if (degraded) {
        return fallback.get(key);
      }
      try {
        const stored = await SecureStore.getItemAsync(key);
        return stored ?? (await fallback.get(key));
      } catch {
        // A read failure is a normal condition (locked keystore, restored
        // backup). Answering null makes the client register a new device.
        degrade();
        return fallback.get(key);
      }
    },

    async set(key: string, value: string): Promise<void> {
      await fallback.set(key, value);
      if (degraded) {
        return;
      }
      try {
        await SecureStore.setItemAsync(key, value, {
          // Available after the first unlock and not synced to another device:
          // a device secret identifies this install, so copying it to an iCloud
          // restored phone would hand two devices the same identity.
          keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
        });
      } catch {
        degrade();
      }
    },

    async remove(key: string): Promise<void> {
      await fallback.remove(key);
      if (degraded) {
        return;
      }
      try {
        await SecureStore.deleteItemAsync(key);
      } catch {
        degrade();
      }
    },
  };
}

/**
 * The credential store for this platform. One instance is created by
 * src/api/client.ts and shared by the whole app; there is no reason for a screen
 * to build another.
 */
export function createCredentialStore(): CredentialStore {
  return HAS_SECURE_STORE ? createSecureCredentialStore() : createAsyncStorageCredentialStore();
}
