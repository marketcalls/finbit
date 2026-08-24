/**
 * Anonymous per device identity, contract section 5.
 * A UUIDv4 is generated once, kept in localStorage under finbit.device_id and
 * sent as the X-Device-Id header on every API request. There is no login.
 */

export const DEVICE_ID_STORAGE_KEY = 'finbit.device_id';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

let cachedDeviceId: string | null = null;

function randomHexBytes(count: number): number[] {
  const bytes = new Uint8Array(count);
  const cryptoObj = typeof globalThis !== 'undefined' ? globalThis.crypto : undefined;
  if (cryptoObj && typeof cryptoObj.getRandomValues === 'function') {
    cryptoObj.getRandomValues(bytes);
  } else {
    for (let i = 0; i < count; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  return Array.from(bytes);
}

/** UUIDv4, using crypto.randomUUID when available and a manual build otherwise. */
export function createUuidV4(): string {
  const cryptoObj = typeof globalThis !== 'undefined' ? globalThis.crypto : undefined;
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    try {
      return cryptoObj.randomUUID();
    } catch {
      // Fall through to the manual build below.
    }
  }

  const bytes = randomHexBytes(16);
  // Version 4 and the RFC 4122 variant bits.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.map((b) => b.toString(16).padStart(2, '0'));
  return [
    hex.slice(0, 4).join(''),
    hex.slice(4, 6).join(''),
    hex.slice(6, 8).join(''),
    hex.slice(8, 10).join(''),
    hex.slice(10, 16).join(''),
  ].join('-');
}

function readStored(): string | null {
  try {
    const value = window.localStorage.getItem(DEVICE_ID_STORAGE_KEY);
    return value && UUID_PATTERN.test(value) ? value : null;
  } catch {
    // Private mode or blocked storage: treat as no stored id.
    return null;
  }
}

function writeStored(value: string): void {
  try {
    window.localStorage.setItem(DEVICE_ID_STORAGE_KEY, value);
  } catch {
    // Storage is unavailable, so this device stays anonymous for the session only.
  }
}

/**
 * The device id for this browser. Creates and persists one on first call.
 * Never throws: a browser that blocks storage still gets a usable in-memory id.
 */
export function getDeviceId(): string {
  if (cachedDeviceId) {
    return cachedDeviceId;
  }
  const stored = readStored();
  if (stored) {
    cachedDeviceId = stored;
    return stored;
  }
  const created = createUuidV4();
  cachedDeviceId = created;
  writeStored(created);
  return created;
}

/** Drops the in-memory cache. Used by tests and by manual resets. */
export function resetDeviceIdCache(): void {
  cachedDeviceId = null;
}
