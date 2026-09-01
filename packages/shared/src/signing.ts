/**
 * Canonical string and HMAC request signature, CONTRACT_MOBILE_ADMIN.md 3.4.
 *
 * This file and `backend/app/security/signing.py` must produce identical bytes
 * for identical input, so everything here is written to be boringly explicit:
 * no locale-dependent formatting, no JSON round trips, no implicit encoding.
 *
 * It has to run unchanged in a browser and in React Native under Hermes, so it
 * uses no Node API, no Buffer, no crypto.subtle and not even TextEncoder, which
 * is absent on older Hermes builds. UTF-8 encoding and base64 are implemented
 * here in a few lines rather than depending on a host object that may or may not
 * exist. The only dependency is @noble/hashes, which is pure JavaScript.
 *
 * The one rule that causes almost every silent signature mismatch: the caller
 * must serialize the request body ONCE, digest that exact string, and send that
 * same string. JSON.stringify is not guaranteed to be stable across two calls
 * for objects built at different times (key order follows insertion order), so
 * digesting a re-serialized body will eventually disagree with what was sent and
 * the server will answer 401 bad_signature with nothing in the logs to explain
 * it. signRequest therefore takes the serialized body text, never an object.
 */

import { hmac } from '@noble/hashes/hmac';
import { sha256 } from '@noble/hashes/sha256';

/** sha256 of zero bytes, the body digest for a request with no body. */
export const EMPTY_BODY_SHA256 =
  'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';

/** The nonce is exactly 16 random bytes, base64url, unpadded. */
export const NONCE_BYTES = 16;

const BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const BASE64URL_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
const HEX_DIGITS = '0123456789abcdef';

/** Reverse lookup that accepts both the standard and the URL-safe alphabet. */
const BASE64_VALUES: Record<string, number> = (() => {
  const table: Record<string, number> = {};
  for (let index = 0; index < BASE64_ALPHABET.length; index += 1) {
    table[BASE64_ALPHABET.charAt(index)] = index;
    table[BASE64URL_ALPHABET.charAt(index)] = index;
  }
  return table;
})();

/**
 * UTF-8 encode a string the way Python's str.encode('utf-8') does.
 *
 * Surrogate pairs are combined into one code point and a lone surrogate becomes
 * U+FFFD, matching TextEncoder. A lone surrogate cannot appear in a JSON body
 * the client built itself, but silently emitting WTF-8 for one would produce a
 * digest the server can never reproduce.
 */
export function utf8ToBytes(text: string): Uint8Array {
  const out: number[] = [];
  for (let index = 0; index < text.length; index += 1) {
    let code = text.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = index + 1 < text.length ? text.charCodeAt(index + 1) : 0;
      if (next >= 0xdc00 && next <= 0xdfff) {
        code = 0x10000 + ((code - 0xd800) << 10) + (next - 0xdc00);
        index += 1;
      } else {
        code = 0xfffd;
      }
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      code = 0xfffd;
    }

    if (code < 0x80) {
      out.push(code);
    } else if (code < 0x800) {
      out.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code < 0x10000) {
      out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    } else {
      out.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f),
      );
    }
  }
  return Uint8Array.from(out);
}

/** Lowercase hex, which is what the canonical string requires. */
export function bytesToHex(bytes: Uint8Array): string {
  let out = '';
  for (let index = 0; index < bytes.length; index += 1) {
    const byte = bytes[index] as number;
    out += HEX_DIGITS.charAt(byte >> 4) + HEX_DIGITS.charAt(byte & 0x0f);
  }
  return out;
}

function encodeWithAlphabet(bytes: Uint8Array, alphabet: string, pad: boolean): string {
  let out = '';
  for (let index = 0; index < bytes.length; index += 3) {
    const hasSecond = index + 1 < bytes.length;
    const hasThird = index + 2 < bytes.length;
    const first = bytes[index] as number;
    const second = hasSecond ? (bytes[index + 1] as number) : 0;
    const third = hasThird ? (bytes[index + 2] as number) : 0;

    out += alphabet.charAt(first >> 2);
    out += alphabet.charAt(((first & 0x03) << 4) | (second >> 4));
    out += hasSecond ? alphabet.charAt(((second & 0x0f) << 2) | (third >> 6)) : pad ? '=' : '';
    out += hasThird ? alphabet.charAt(third & 0x3f) : pad ? '=' : '';
  }
  return out;
}

/** Standard base64 with padding, the encoding the signature header uses. */
export function base64Encode(bytes: Uint8Array): string {
  return encodeWithAlphabet(bytes, BASE64_ALPHABET, true);
}

/** base64url without padding, the encoding the nonce uses. */
export function base64UrlEncode(bytes: Uint8Array): string {
  return encodeWithAlphabet(bytes, BASE64URL_ALPHABET, false);
}

/**
 * Decode standard or URL-safe base64, with or without padding.
 *
 * The error message deliberately never quotes the input, because the only value
 * this decodes in practice is the device secret.
 */
export function base64Decode(text: string): Uint8Array {
  let clean = '';
  for (let index = 0; index < text.length; index += 1) {
    const char = text.charAt(index);
    if (char === '=' || char === '\n' || char === '\r' || char === ' ' || char === '\t') {
      continue;
    }
    if (!(char in BASE64_VALUES)) {
      throw new Error('base64Decode received a value that is not valid base64.');
    }
    clean += char;
  }

  const remainder = clean.length % 4;
  if (remainder === 1) {
    throw new Error('base64Decode received a value of an impossible length.');
  }

  const outLength = Math.floor((clean.length * 3) / 4);
  const out = new Uint8Array(outLength);
  let outIndex = 0;
  let buffer = 0;
  let bits = 0;
  for (let index = 0; index < clean.length; index += 1) {
    buffer = (buffer << 6) | (BASE64_VALUES[clean.charAt(index)] as number);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[outIndex] = (buffer >> bits) & 0xff;
      outIndex += 1;
    }
  }
  return out;
}

/** Lowercase hex sha256 of a UTF-8 string. */
export function sha256Hex(input: string): string {
  return bytesToHex(sha256(utf8ToBytes(input)));
}

/**
 * The body digest for a request: sha256 of the exact bytes sent.
 * An absent body is zero bytes, not the string "null" and not "{}".
 */
export function bodyDigest(body?: string | null): string {
  if (body === undefined || body === null || body === '') {
    return EMPTY_BODY_SHA256;
  }
  return sha256Hex(body);
}

/**
 * The exact string that gets signed. Five fields, newline separated, no
 * trailing newline. Keep this function dumb: any normalisation belongs in the
 * caller, because the server normalises nothing either.
 */
export function canonicalString(
  timestamp: string | number,
  nonce: string,
  method: string,
  pathWithQuery: string,
  bodyDigestHex: string,
): string {
  return [
    String(timestamp),
    nonce,
    method.toUpperCase(),
    pathWithQuery,
    bodyDigestHex,
  ].join('\n');
}

export interface SignatureInput {
  /** Unix seconds as a decimal string, or a number that is whole seconds. */
  timestamp: string | number;
  /** base64url, 16 bytes, unpadded. See createNonce. */
  nonce: string;
  method: string;
  /** Starts with '/', carries the query exactly as sent, no origin, no fragment. */
  pathWithQuery: string;
  /**
   * The serialized body, exactly as it will be written to the socket, or
   * undefined when there is no body. Never pass an object: re-serializing it
   * later is the classic cause of a silent signature mismatch.
   */
  body?: string | null;
}

/**
 * base64 standard of hmac_sha256(device_secret_bytes, utf8(canonical)).
 *
 * deviceSecretBase64 is the value the handshake returned. It is decoded to
 * bytes first: signing over the base64 text instead of the bytes it represents
 * is the second classic mismatch, and it fails identically on every request.
 */
export function signRequest(deviceSecretBase64: string, input: SignatureInput): string {
  const key = base64Decode(deviceSecretBase64);
  const canonical = canonicalString(
    input.timestamp,
    input.nonce,
    input.method,
    input.pathWithQuery,
    bodyDigest(input.body),
  );
  return base64Encode(hmac(sha256, key, utf8ToBytes(canonical)));
}

/**
 * Turn 16 caller-supplied random bytes into the nonce header value.
 *
 * Entropy comes from the caller because the two runtimes get it from different
 * places: crypto.getRandomValues in the browser, expo-crypto on the device.
 * This package stays free of both.
 */
export function createNonce(randomBytes: Uint8Array): string {
  if (randomBytes.length !== NONCE_BYTES) {
    throw new Error(`createNonce expects exactly ${NONCE_BYTES} random bytes.`);
  }
  return base64UrlEncode(randomBytes);
}

/** Unix seconds as a decimal string, with no fractional part. */
export function currentTimestamp(nowMs: number = Date.now()): string {
  return String(Math.floor(nowMs / 1000));
}
