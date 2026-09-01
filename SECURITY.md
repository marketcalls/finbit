# FinBit security

This document describes what the FinBit API actually protects against, how each
control works, and where the limits are. It is written for whoever has to deploy
this, rotate a key, or write a third client against the API.

Read the summary honestly: FinBit raises the cost of calling its API from
anything that is not the FinBit app. It does not, and cannot, prove that a
caller is the FinBit app.

---

## 1. Threat model

### What this build does stop

| Threat | What stops it |
| --- | --- |
| Casual scraping of the feed | An unauthenticated caller has no app key, no device, no token and no signature. Getting all four means reverse engineering the client rather than running `curl` in a loop |
| A stolen access token replayed from somewhere else | The token alone is not enough. Every request is also signed with the device secret, which never travels on the wire after registration |
| A captured request replayed later | The timestamp must be within 120 seconds and the nonce must never have been seen. A recorded request works exactly once, at the time it was recorded |
| A captured request with the body or the path edited | The signature covers the method, the path with its query string and the exact body bytes. Any edit invalidates it |
| One device reading another device's bookmarks | The device id is issued by the server and has to be proven with a signature and a matching token subject. Phase 1 accepted any id in a header, which meant anyone who guessed one could read those saved articles |
| A leaked copy of the database | It holds no device secrets (they are derived on demand), no raw refresh tokens (only sha256), and no plaintext passwords (argon2id) |
| An anonymous caller reaching the admin console | Every admin route requires a bearer token in the `admin` JWT audience. A device token on an admin route is refused |
| Brute forcing an admin password | argon2id hashing, a 12 character minimum, lockout after 5 consecutive failures for 15 minutes, and 10 login attempts per IP per 15 minutes |
| Learning whether a username exists | A wrong username and a wrong password return a byte identical body, and the unknown-username path burns one argon2 verification so the two take comparable time |
| A rogue browser origin calling the API | An explicit CORS allowlist, never a wildcard, with `allow_credentials` off |
| A request designed to make the server do work | A 256 KB body cap, refused from the `Content-Length` header before a byte is read |
| Silent misconfiguration | Startup refuses to run when any of the four secrets is empty or still holds its `change-me` placeholder |

### What this build does not stop

- **A determined attacker extracting the app key and the device secret from a
  device.** The app key is compiled into the bundle. The device secret is handed
  to the client at registration and stored on the device. On a rooted or
  jailbroken phone, in an emulator, or with a patched build, both are readable.
  Once someone has them, they can sign requests that are indistinguishable from
  the real app's.
- **Anyone who can run the registration handshake.** `POST /api/auth/device` is
  open to anything holding a valid app key. It is rate limited to 5 devices per
  IP per hour, which slows a farm down; it does not stop one.
- **Traffic interception without TLS.** Every control here assumes HTTPS.
  Over plain HTTP, the registration response hands the device secret to anyone
  on the path, and everything downstream falls with it.
- **A compromised server.** `DEVICE_MASTER_KEY` and `JWT_SECRET` live in the
  process environment. Anyone who can read them can mint device secrets and
  tokens at will.
- **Denial of service.** The rate limits are token buckets in SQLite, sized for
  correctness and not for volume. A real flood needs something in front.

### App attestation is not possible in this build

The only controls that genuinely prove a request came from an unmodified,
store-installed app are **Play Integrity** on Android and **App Attest** on iOS.
Both require native modules and a custom development build. This app runs in
**Expo Go**, deliberately (see the SDK 54 section of the README), and Expo Go
cannot load either one.

So this build has no app attestation, and nothing here should be read as if it
did. Adding it would mean:

1. Leaving Expo Go for a custom development build (`expo-dev-client`) and EAS
   Build, so every tester installs a build instead of scanning a QR code.
2. Adding the native attestation modules and wiring the platform APIs.
3. Adding a server-side verification step: the client obtains an attestation
   token from Google or Apple, sends it during the handshake, and the server
   verifies it against the vendor's API before issuing a device secret.
4. Handling the failure modes: attestation is unavailable on emulators, on
   devices with no Play Services, and intermittently in the field.

That is a real project, not a flag. Until it is done, the honest description of
this API is: layered controls that make casual abuse expensive, over an
anonymous identity that a capable attacker can forge.

---

## 2. The seven layers

Each layer is worth something on its own, and none of them is sufficient alone.

**1. App key.** Every request carries `X-App-Key`. There are two configured
keys, `APP_KEY_MOBILE` and `APP_KEY_WEB`, so either client can be rotated
without touching the other. An unknown key is rejected with 401
`invalid_app_key` before anything else runs, including any database read.
*Stops:* a caller who found the URL but has never looked at a client bundle.
*Does not stop:* anyone who has, because the key is in the bundle.

**2. Anonymous device handshake.** The client registers once and receives an
opaque `device_id`, a `device_secret`, an access token and a refresh token.
There is no account and no login.
*Stops:* a caller from acting without an identity the server issued and can
revoke. It is also what makes bookmarks per device rather than per header.

**3. Per-request HMAC signature.** Every device-authenticated call is signed
over the method, the path with its query, the body digest, a timestamp and a
nonce, with the device secret as the key.
*Stops:* a stolen bearer token being used on its own, and any tampering with the
path, the query or the body of a captured request.

**4. Replay protection.** A timestamp more than `SIGNATURE_SKEW_SECONDS` (120)
from the server clock is refused. A nonce that has been seen before is refused.
Nonces are pruned after `NONCE_TTL_SECONDS` (300), which is longer than the skew
window, so nothing can age out of the nonce table while it is still inside the
timestamp window.
*Stops:* replaying a captured request, even one captured a second ago.

**5. Rate limits.** Token buckets persisted in `rate_buckets`, per device and
per IP, refilled continuously rather than resetting on a window boundary.
*Stops:* one device or one address consuming the API at machine speed, and caps
how fast a device farm can be built.

**6. Strict CORS.** An explicit origin allowlist from `CORS_ORIGINS`, never a
wildcard. `allow_credentials` stays false because this API authenticates with a
bearer header and not a cookie, so there is nothing for a credentialed
cross-origin request to gain.
*Stops:* another site's JavaScript reading FinBit responses in a browser.
*Does not stop:* anything outside a browser, which does not enforce CORS.

**7. Admin login.** argon2id password hashing, account lockout, a separate JWT
audience so a device token can never reach an admin route, and an `audit_log`
row for every mutation.
*Stops:* unauthenticated access to the pipeline and moderation controls, and
makes every change attributable.

Two more protections sit underneath all seven, in
`backend/app/security/middleware.py`:

- **A 256 KB request body cap**, answered with 413 `payload_too_large`. A
  declared `Content-Length` over the cap is refused before a byte is read.
- **Security headers on every response**: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and a
  `Permissions-Policy` that denies every browser capability the API has no use
  for.

---

## 3. The canonical string and the signature

This is the part a future client has to reproduce byte for byte.
`backend/app/security/signing.py` and `packages/shared/src/signing.ts` are two
implementations of exactly this, and the fixed vectors below are asserted
against both.

### Device secret derivation

The server stores no device secret. It derives one whenever it needs to verify:

```
device_secret_bytes = hmac_sha256(key = utf8(DEVICE_MASTER_KEY),
                                  msg = utf8(device_id))
device_secret       = base64_standard(device_secret_bytes)
```

`DEVICE_MASTER_KEY` is taken **verbatim as UTF-8 bytes**, never hex decoded and
never base64 decoded. One unambiguous rule matters more than a compact key here,
and the master key never leaves the server, so nothing else has to agree with
that interpretation.

`device_secret` is the base64 text the handshake returns to the client. The
client stores that text and decodes it back to the 32 raw bytes before signing.
**Signing with the base64 text instead of the bytes it represents is the single
most common cross-language mistake**, and it fails identically on every request.

### The canonical string

```
body_digest = lowercase_hex( sha256( raw_request_body_bytes ) )
              # empty body, the sha256 of zero bytes:
              # e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

canonical   = timestamp          + "\n"
            + nonce              + "\n"
            + METHOD_UPPERCASE   + "\n"
            + path_with_query    + "\n"
            + body_digest

signature   = base64_standard( hmac_sha256( key = device_secret_bytes,
                                            msg = utf8(canonical) ) )
```

Five lines, newline separated, no trailing newline.

Rules that both sides must follow, or signatures mismatch silently:

- `timestamp` is unix **seconds**, as a decimal string, with no fractional part.
- `nonce` is 16 random bytes from a cryptographic source, base64url, unpadded.
  `Math.random` is not acceptable: predictable nonces are the one thing replay
  protection depends on.
- `path_with_query` starts with `/` and carries the query string exactly as
  sent, for example `/api/feed?category=rbi&sort=top`. No origin, no fragment.
  Neither side reorders parameters and neither side re-encodes them. The client
  must sign the string it is about to request, character for character. The
  server rebuilds it from the raw ASGI path and query, so a percent encoded
  segment survives intact.
- The body digest is over the **exact bytes sent**. Serialize the body once,
  digest that string, and send that same string. Re-serializing an object later
  will eventually produce different key order and a signature that cannot be
  reproduced.
- An absent body is zero bytes, not `"null"` and not `"{}"`.
- The server compares with `hmac.compare_digest`, in constant time.

### Request headers

Every call to a device-authenticated route:

```
X-App-Key:      <APP_KEY_MOBILE or APP_KEY_WEB>
X-Device-Id:    <device_id>
X-Timestamp:    <unix seconds>
X-Nonce:        <base64url, 16 bytes, unpadded>
X-Signature:    <base64 standard of the HMAC>
Authorization:  Bearer <access_token>
Content-Type:   application/json      (only when there is a body)
```

`POST /api/auth/device` and `POST /api/auth/refresh` take `X-App-Key` and
nothing else, because the caller has no device secret yet or is proving
possession through the refresh token instead.

Admin routes take `Authorization: Bearer <admin access token>` and no app key
and no signature. Adding a signature there would mean putting a shared secret in
a browser bundle for no gain.

### Fixed vectors

Computed by hand, asserted in `backend/tests/test_security.py`, and verified
against the TypeScript implementation. A new client that reproduces all four is
signing correctly.

```
DEVICE_MASTER_KEY = "finbit-test-device-master-key-32"
device_id         = "0123456789abcdef0123456789abcdef"
device_secret     = "kPZmoCZVIKBMErwFDosiViVPYICPlG+XuOQy7TkEj4Y="
timestamp         = "1767225600"
nonce             = "9y3rNQ0mF7xKpL2aVbCdEg"
```

1. Empty body, no query string.

```
method     GET
path       /api/feed
body       "" (zero bytes)
digest     e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
signature  FVEPPhK1t3xtQiOU72IpKKm6tILJstTmgrvHKZq1qYA=
```

2. Empty body, with a query string, parameters in the order sent.

```
method     GET
path       /api/feed?category=rbi&sort=top
digest     e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
signature  N8XtP5ZpbkgT52yM81rVH7R0o/zfEDWZGgTnVq3+cH0=
```

3. Unicode body, digested as UTF-8 bytes and sent as those same bytes.

```
method     POST
path       /api/bookmarks
body       {"headline":"RBI holds at 5.50%, ₹1,20,000, Zürich, नीति"}
           69 bytes as UTF-8, 58 JavaScript string units
digest     c1653087cd9f8586c06764086b3bda5350c9f07431d54976666e8f9c909bd375
signature  PKl4uZcs/+EM3XLM/eMKlV5hGF8BgmkCO5ahfhsHkwg=
```

4. Percent encoded query, passed through byte for byte with no re-encoding.

```
method     GET
path       /api/search?q=RBI%20repo%20rate&limit=5
digest     e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
signature  WLgZKxtYqRm3shkiLxbYzk8OW/LznOCTDGh3YGM+tVQ=
```

---

## 4. Verification order

Each check short-circuits. The order is a security decision, not a style one:
the cheap checks run first so an unauthenticated flood is rejected before it can
cost a JWT decode or a database read.

| Order | Check | Status | `code` |
| --- | --- | --- | --- |
| 1 | `X-App-Key` matches a configured key | 401 | `invalid_app_key` |
| 2 | IP rate limit | 429 | `rate_limited` |
| 3 | Required headers present and the nonce is a plausible shape | 401 | `missing_signature_headers` |
| 4 | Timestamp within `SIGNATURE_SKEW_SECONDS` of now | 401 | `stale_request` |
| 5 | Nonce has not been seen | 401 | `replayed_request` |
| 6 | Access token valid, audience `device`, subject equals `X-Device-Id` | 401 | `invalid_token` |
| 7 | Device row exists and is not revoked | 401 | `device_revoked` |
| 8 | Signature matches | 401 | `bad_signature` |
| 9 | Device rate limit | 429 | `rate_limited` |

Other codes the API returns:

| Status | `code` | When |
| --- | --- | --- |
| 401 | `invalid_refresh_token` | Any refresh failure: unknown, expired, revoked, or already used. One code for all of them, because a distinct code per cause would tell an attacker whether a guessed token ever existed |
| 413 | `payload_too_large` | The request body is over 256 KB |
| 503 | `maintenance` | Maintenance mode is on. Every content route answers this; `/api/config` and the admin routes keep working |

Every coded failure body is `{"detail": "<human sentence>", "code": "<code>"}`.
The detail never says which check failed beyond the code, and no refusal body,
log line or exception message anywhere carries a secret, a token, a signature or
a password. There are tests that assert exactly that.

The skew window is inclusive at both edges: 119 seconds is accepted, 120 is
accepted, 121 is refused.

---

## 5. Tokens

| Token | Kind | Audience | Lifetime | Where the client keeps it |
| --- | --- | --- | --- | --- |
| Device access | HS256 JWT | `device` | 15 minutes | Memory only, refetched on demand |
| Device refresh | Opaque, 32 random bytes | `device-refresh` | 30 days, rotating, single use | SecureStore on the phone, `localStorage` in the browser |
| Admin access | HS256 JWT | `admin` | 30 minutes | Memory only |
| Admin refresh | Opaque, 32 random bytes | `admin-refresh` | 12 hours, rotating, single use | `sessionStorage`, so closing the tab ends the session |

Access tokens are JWTs signed with `JWT_SECRET`, carrying `sub`, `aud`, `iat`,
`exp`, `jti` and `typ`. The audience is enforced on decode, so a device token
presented to an admin route fails as `invalid_token` and never gets as far as
looking up an account.

Refresh tokens are **not** JWTs. They are 32 bytes of `secrets.token_urlsafe`
and they are stored server-side only as `sha256(token)`. A leaked database gives
an attacker hashes, not sessions.

### Rotation and reuse detection

Spending a refresh token marks it used and issues a replacement, inside one
write transaction so two parallel refreshes cannot both succeed.

Presenting an **already used** refresh token is treated as a theft signal: every
refresh token for that subject and kind is revoked, and the caller gets 401
`invalid_refresh_token`. The whole family goes, not just the reused token,
because at that point either the client or the attacker holds a valid one and
there is no way to tell which.

What the clients do next:

- **Device, on `invalid_token`:** refresh once with a fresh timestamp and a
  fresh nonce, then retry the request exactly once.
- **Device, on a rejected refresh:** forget the credentials and register as a
  new anonymous device. There is no login screen to fall back to, so the
  alternative would be an app that is permanently dead. The cost is that
  device's server-side bookmarks.
- **Admin, on a rejected refresh:** back to the sign-in form.

---

## 6. Rate limits

Token buckets in the `rate_buckets` table, refilled continuously at
`capacity / window` per second. A caller that has been quiet for half the window
gets half its bucket back, rather than everyone resetting together on a
boundary. State is in SQLite so it survives a restart and stays correct across
the FastAPI threadpool and the scheduler threads.

| Scope | Capacity | Refill | Applied to |
| --- | --- | --- | --- |
| `device_register` | 5 | 5 per hour, per IP | `POST /api/auth/device` |
| `device` | 120 | 120 per minute, per device | Every device-authenticated route |
| `ip` | 600 | 600 per minute, per IP | Every device route, every admin route, both auth routes |
| `admin_login` | 10 | 10 per 15 minutes, per IP | `POST /api/admin/auth/login` |
| `admin_ingest` | 6 | 6 per hour, per IP | `POST /api/admin/pipeline/ingest` |

A refusal is 429 with `code: rate_limited` and a `Retry-After` header in whole
seconds.

**The IP is the socket address and never `X-Forwarded-For`.** With no trusted
proxy configured, honouring that header would let any caller pick its own rate
limit bucket by sending a different value each time. Behind a real proxy,
terminate TLS in front of the app and run uvicorn with `--proxy-headers` so the
socket address is the client's.

Separately from the buckets, an admin account locks for 15 minutes after 5
consecutive failed logins. During the lockout, even the correct password is
refused, with the same body as a wrong one.

---

## 7. Secrets: what lives where

### Real secrets, server side only

| Secret | Lives in | Used for |
| --- | --- | --- |
| `DEVICE_MASTER_KEY` | The repo root `.env`, git-ignored | Deriving every device secret |
| `JWT_SECRET` | The same | Signing and verifying access tokens |
| `PERPLEXITY_API_KEY` | The same | The news pipeline. Never sent to any client |
| `ADMIN_BOOTSTRAP_PASSWORD` | The same, optional | Creating the first admin at startup. Clear it once the account exists |

None of these ever reaches a client, a response body or a log line. The startup
validation messages name the missing variable and never quote its value.

### Public by definition

**`EXPO_PUBLIC_APP_KEY` and `VITE_APP_KEY` are compiled into the client bundles
and are readable by anyone who downloads them.** That is not a leak, it is what
those prefixes mean: Expo inlines every `EXPO_PUBLIC_` variable at build time,
and Vite exposes every `VITE_` variable to the browser bundle. The same is true
of `EXPO_PUBLIC_API_URL` and `VITE_API_BASE`.

Treat an app key as a client identifier with a rotation lever attached, not as a
credential. It tells the API which client is calling and lets you cut one of
them off. It proves nothing.

Never put a real secret behind either prefix.

### Stored on the device

| Value | Phone | Browser |
| --- | --- | --- |
| `device_id` | SecureStore | `localStorage` |
| `device_secret` | SecureStore | `localStorage` |
| Device refresh token | SecureStore | `localStorage` |
| Device access token | Memory | Memory |
| Admin refresh token | Not applicable | `sessionStorage` |
| Admin access token | Not applicable | Memory |

SecureStore is the iOS Keychain and an encrypted SharedPreferences entry on
Android. AsyncStorage is plaintext on disk and holds only the theme preference
and the cached feed, never a credential.

In the browser, `localStorage` is readable by any script running on that origin.
That is the accepted position for an anonymous device identity with no account
behind it, and it is why the admin session lives in `sessionStorage` and memory
instead.

### Stored in the database

| Value | Form |
| --- | --- |
| Device secrets | Not stored. Derived on demand from `DEVICE_MASTER_KEY` |
| Refresh tokens | `sha256(token)` only |
| Admin passwords | argon2id, with the parameters inside the hash string |
| Nonces | The nonce and the time it was seen, pruned after 300 seconds |
| Admin actions | An `audit_log` row per mutation: actor, action, target, detail, IP, timestamp. Reads write nothing |

---

## 8. Key rotation

All four keys live in the repo root `.env`. Generate a replacement the same way
you generated the original, from `backend/`:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

There is exactly one configured value per key, so every rotation is a hard
cutover. This build has no overlap window where an old and a new key are both
accepted. Plan accordingly.

### `APP_KEY_MOBILE`

*What breaks:* every installed copy of the app, immediately. Requests come back
401 `invalid_app_key` and the app shows its retry screen.
*How to do it:* set the new value, rebuild the app with the matching
`EXPO_PUBLIC_APP_KEY`, ship it, and only then restart the API. Users on the old
build stay broken until they update. In practice, rotate this only in response
to something that justifies that.

### `APP_KEY_WEB`

*What breaks:* every open browser tab, until it reloads.
*How to do it:* set the new value in `.env` and in `frontend/.env.local`,
rebuild and deploy the web app, restart the API. Cheap, because a browser picks
up the new bundle on the next load.

### `DEVICE_MASTER_KEY`

This is the emergency lever. Rotating it changes the derived secret of every
device at once, so every signature stops verifying.

*What breaks:* every registered device, on both clients. Requests come back 401
`bad_signature`.

*The catch:* neither client automatically recovers from `bad_signature`. The web
app re-registers on `device_revoked` and both clients re-register when a refresh
token is rejected, but a device whose stored secret no longer derives correctly
just fails every request. So do not rotate the master key on its own.

*How to do it:*

1. Set the new `DEVICE_MASTER_KEY`.
2. Clear the device rows in the same maintenance window, so clients get
   `device_revoked` (which the web app recovers from) rather than
   `bad_signature`:
   `DELETE FROM devices;` or `UPDATE devices SET revoked = 1, revoked_at = ...`.
3. Restart the API.
4. Expect every device to re-register, and every device's server-side bookmarks
   to be gone with the old ids.

Mobile users may still need to clear app data or reinstall, because the app
shows a retry screen rather than discarding its credentials. That is a known gap
in this build.

### `JWT_SECRET`

*What breaks:* less than you would expect. Access tokens stop verifying and come
back 401 `invalid_token`, but refresh tokens are opaque random strings and are
unaffected, so both clients simply refresh and carry on. Admin sessions survive
the same way.
*How to do it:* set the new value and restart. There is no client-side work.
Every in-flight request at the moment of the restart fails once and retries.

### The admin password

Use the CLI, from `backend/`:

```powershell
uv run python -m app.admin_cli reset-password --username alice
```

This does not revoke existing admin refresh tokens. If the password was
compromised, also clear that account's admin refresh rows:
`DELETE FROM refresh_tokens WHERE subject = 'alice' AND kind = 'admin-refresh';`

---

## 9. `REQUIRE_SIGNED_REQUESTS=false` is development only

Setting it false degrades every device-authenticated route to an app key plus a
bearer token. Specifically, it removes:

- The signature check (step 8). Nothing binds a request to a device secret.
- The timestamp check (step 4). A captured request never goes stale.
- The nonce check (step 5). A captured request can be replayed forever.
- The requirement to send `X-Device-Id`, `X-Timestamp`, `X-Nonce` and
  `X-Signature` at all.

What survives: the app key, the bearer token with its audience and subject, the
device row and revocation check, the rate limits, CORS, the body cap and the
maintenance gate.

It exists for one reason: so a developer can drive the API from `/docs`, where
there is no way to compute a signature. It defaults to true, and when it is
false the server logs a loud warning at startup naming exactly what has been
turned off.

It also disables the startup check on the four secrets, because that check is
only meaningful in signed mode. So a process running with
`REQUIRE_SIGNED_REQUESTS=false` may well be running with no real
`DEVICE_MASTER_KEY` at all, deriving every device secret from an empty key. That
is the second reason it must never reach a deployment.

---

## 10. Known gaps in this build

Listed here rather than buried, because a gap you know about is manageable.

- **No app attestation.** See section 1.
- **`POST /api/admin/ingest` and `GET /api/admin/runs` are unauthenticated.**
  They are phase 1 development routes kept so nothing already built breaks. The
  ingest trigger spends real money on the Perplexity API. Set
  `ALLOW_ADMIN_INGEST_FROM_UI=false` before exposing the API anywhere, which
  turns it into a 403. The authenticated replacements are
  `POST /api/admin/pipeline/ingest` and the `recent_runs` field of
  `GET /api/admin/pipeline`.
- **No client recovery from `bad_signature`.** See the `DEVICE_MASTER_KEY`
  rotation notes. The mobile app also has no recovery from `device_revoked`: it
  shows a retry screen rather than discarding its credentials.
- **Device registration is open to anything holding an app key**, limited only
  by 5 per IP per hour.
- **`X-Forwarded-For` is deliberately ignored**, so behind a proxy that is not
  configured with `--proxy-headers`, every caller shares one rate limit bucket.
- **The admin console has one flat role.** Any admin can do anything, including
  deleting articles and turning maintenance mode on. There are no roles and no
  second factor.
- **Rate limits are correctness-sized, not volume-sized.** They are SQLite
  writes on the request path.
- **Images are hotlinked from publisher CDNs.** That is a deliberate MVP choice
  and it means those publishers see a request per card render.

---

## 11. Deployment checklist

Work through this before the API is reachable from the internet.

**Secrets**

- [ ] All four of `APP_KEY_MOBILE`, `APP_KEY_WEB`, `DEVICE_MASTER_KEY` and
      `JWT_SECRET` hold real random values. Startup refuses otherwise, so a
      successful start is the proof.
- [ ] `DEVICE_MASTER_KEY` and `JWT_SECRET` are different values, and neither one
      is reused from another environment.
- [ ] `ADMIN_BOOTSTRAP_USERNAME` and `ADMIN_BOOTSTRAP_PASSWORD` are empty, and
      the admin account exists.
- [ ] `.env` is not in the image, the repository or the build log. The
      `.gitignore` covers it; confirm your deployment path does too.

**Transport**

- [ ] TLS terminates in front of the app. Nothing here is safe over plain HTTP.
- [ ] Uvicorn runs with `--proxy-headers` behind that terminator, so the rate
      limits see real client addresses.
- [ ] `CORS_ORIGINS` lists exactly the origins that need it, with no wildcard
      and no leftover tunnel or localhost entry.

**Configuration**

- [ ] `REQUIRE_SIGNED_REQUESTS=true`. Check the startup log for the unsigned
      mode warning; its absence is the confirmation.
- [ ] `ALLOW_ADMIN_INGEST_FROM_UI=false`, so the unauthenticated legacy ingest
      trigger cannot spend money.
- [ ] `SIGNATURE_SKEW_SECONDS` is still 120 and `NONCE_TTL_SECONDS` is still
      300, or if changed, the TTL is comfortably larger than the skew.
- [ ] The server clock is synchronised. A drifted clock rejects every real
      client with `stale_request`.

**Clients**

- [ ] The web bundle was built with `VITE_APP_KEY` set to the deployed
      `APP_KEY_WEB`, from `.env.local` or the build environment. `npm run build`
      never reads `.env.development`.
- [ ] The mobile build carries the deployed `APP_KEY_MOBILE` in
      `EXPO_PUBLIC_APP_KEY` and a real `EXPO_PUBLIC_API_URL`. Check `eas.json`:
      it ships with `replace-with-your-api-host` and `change-me-mobile`
      placeholders.

**Accounts and operations**

- [ ] The admin account was created with the CLI and has a password that is not
      shared with anything else.
- [ ] The database file and its `-wal` and `-shm` siblings are backed up and are
      not served by any web root.
- [ ] Something in front of the API handles volume, because the token buckets do
      not.
- [ ] You know how to reach the `audit_log` table, which is the only record of
      who changed what.

**Verify, after the first deploy**

- [ ] An unsigned request to `/api/feed` returns 401.
- [ ] A signed request replayed a second time returns 401 `replayed_request`.
- [ ] A device token presented to an admin route returns 401.
- [ ] A wrong admin username and a wrong admin password return identical bodies.
- [ ] No secret, token, signature or password appears anywhere in the startup
      log or the request log.

---

## Reporting a problem

Open an issue describing the class of problem and how to reproduce it. Do not
include a working exploit, a real key or a captured token in a public issue.
