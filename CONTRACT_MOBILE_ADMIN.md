# FinBit Contract, phase 2: mobile app, admin controls, secured common API

Single source of truth for every agent in this build. `CONTRACT.md` still governs
everything it already describes and is read-only. This file only adds. Where the
two disagree, this file wins.

Do not invent names, routes, fields, colors or package versions that are not in
this file. If something is missing, follow the nearest convention already present
in the repo.

Writing style for every file you produce, including code comments, log messages,
commit messages and docs: **no emoji, no em dashes, no en dashes.** Plain hyphens
in compound words are fine.

---

## 0. What is being built

Three clients over one API.

| Client | Path | Auth | Purpose |
| --- | --- | --- | --- |
| Mobile | `mobile/` | Anonymous device handshake, no login | Inshorts-style native newsfeed |
| Web public | `frontend/` (existing screens) | Anonymous device handshake, no login | Same feed in a browser |
| Web admin | `frontend/src/admin/` | Username and password | Control the pipeline, content and feature flags |

One shared TypeScript package (`packages/shared/`) holds the API types, the route
constants and the request-signing implementation, so web and mobile speak to the
API through exactly one contract.

---

## 1. Repository layout and file ownership

Each file below is written by exactly one agent. **Never edit a file you do not
own.** If you need a change in someone else's file, it is already specified here;
build to this document, not to their output.

```
finbit/
  CONTRACT.md                       read-only, phase 1
  CONTRACT_MOBILE_ADMIN.md          read-only, this file
  README.md                         agent D3
  SECURITY.md                       agent D3

  packages/shared/                  AGENT A1
    package.json
    tsconfig.json
    src/index.ts
    src/types.ts                    every API request and response type
    src/endpoints.ts                every route path as a constant
    src/signing.ts                  canonical string + HMAC, isomorphic
    src/storage.ts                  the CredentialStore interface
    src/client.ts                   transport-agnostic signed fetch client

  backend/
    pyproject.toml                  AGENT A2 (adds deps only, keeps existing)
    app/
      config.py                     AGENT A2 (extends, keeps every existing field)
      schema.sql                    AGENT A2 (appends new tables only)
      migrate.py                    AGENT A2 (new)
      models.py                     AGENT A2 (appends new models only)
      repo.py                       AGENT B1 (appends new functions only)
      main.py                       AGENT B1 (wires middleware and new routers)
      security/                     AGENT A2 (new package)
        __init__.py
        keys.py                     app keys, device secret derivation
        signing.py                  canonical string + HMAC verify
        tokens.py                   JWT encode and decode, two audiences
        passwords.py                argon2 hashing
        ratelimit.py                token bucket over SQLite
        middleware.py               security headers, body size cap
      deps.py                       AGENT A2 (new) shared FastAPI dependencies
      routers/
        auth_device.py              AGENT A2 (new)
        admin_auth.py               AGENT A2 (new)
        admin_pipeline.py           AGENT B1 (new)
        admin_content.py            AGENT B1 (new)
        admin_flags.py              AGENT B1 (new)
        config_public.py            AGENT B1 (new)
        feed.py, search.py,         AGENT B1 (edits: device auth + hidden filter)
        bookmarks.py, meta.py
      pipeline/settings_bridge.py   AGENT B1 (new) DB settings override .env
    tests/
      test_security.py              AGENT C1 (new)
      test_admin.py                 AGENT C1 (new)
      test_device_auth.py           AGENT C1 (new)
      conftest.py                   AGENT C1 (extends)

  frontend/                         web
    package.json                    AGENT B4 (adds shadcn deps)
    components.json                 AGENT B4 (shadcn config)
    src/
      lib/utils.ts                  AGENT B4 (cn helper)
      components/ui/*               AGENT B4 (shadcn primitives)
      admin/                        AGENT B5
        AdminApp.tsx
        AdminLogin.tsx
        AdminShell.tsx
        useAdminAuth.tsx
        api.ts
        screens/PipelineScreen.tsx
        screens/ContentScreen.tsx
        screens/FlagsScreen.tsx
      api/client.ts                 AGENT B6 (rewired to signed transport)
      api/types.ts                  AGENT B6 (re-exports packages/shared)
      lib/device.ts                 AGENT B6 (device handshake, replaces UUID)
      App.tsx                       AGENT B6 (adds the /admin route branch)

  mobile/                           AGENT A3 scaffold, B2 and B3 screens
    package.json                    AGENT A3
    app.json                        AGENT A3
    metro.config.js                 AGENT A3
    babel.config.js                 AGENT A3
    tsconfig.json                   AGENT A3
    eas.json                        AGENT A3
    .env.example                    AGENT A3
    AGENTS.md                       AGENT A3
    app/
      _layout.tsx                   AGENT A3
      (tabs)/_layout.tsx            AGENT B2
      (tabs)/index.tsx              AGENT B2   feed
      (tabs)/search.tsx             AGENT B3
      (tabs)/saved.tsx              AGENT B3
      (tabs)/settings.tsx           AGENT B3
      article/[id].tsx              AGENT B2
    src/
      theme/                        AGENT A3   gluestack config + tokens
      api/                          AGENT A3   client, device auth bootstrap
      store/                        AGENT A3   providers
      components/NewsCard.tsx       AGENT B2
      components/*                  AGENT B2 (feed related), B3 (the rest)
      lib/                          AGENT A3
```

---

## 2. Toolchain, pinned

### 2.1 Mobile, Expo SDK 54, non-negotiable

Store-installed Expo Go tracks `expoGoSdkVersion`, which is 54. A project on 55 or
newer cannot be opened by Expo Go from the App Store or Play Store. **Copy these
versions verbatim from the working prototype at
`D:\AI Bootcamp 2026\Dy21\todo mobile app\mobile\package.json`:**

```json
"expo": "~54.0.37",
"react": "19.1.0",
"react-dom": "19.1.0",
"react-native": "0.81.5",
"expo-router": "~6.0.24",
"expo-constants": "~18.0.14",
"expo-linking": "~8.0.12",
"expo-status-bar": "~3.0.9",
"@expo/metro-runtime": "~6.1.2",
"@gluestack-style/react": "^1.0.57",
"@gluestack-ui/config": "^1.1.20",
"@gluestack-ui/themed": "^1.1.73",
"@legendapp/motion": "^2.5.3",
"@react-native-async-storage/async-storage": "2.2.0",
"react-native-gesture-handler": "~2.28.0",
"react-native-reanimated": "~4.1.1",
"react-native-safe-area-context": "~5.6.0",
"react-native-screens": "~4.16.0",
"react-native-svg": "15.12.1",
"react-native-web": "^0.21.2",
"react-native-worklets": "0.5.1"
```

devDependencies: `@expo/ngrok ^4.1.3`, `@types/react ~19.1.10`,
`babel-preset-expo ~54.0.10`, `typescript ~5.9.2`.

**Any package beyond that list must be added with `npx expo install <pkg>`, never
`npm install`,** so Expo resolves the SDK 54 compatible version. The additions
this build needs, and nothing else:

- `expo-secure-store` (the device secret must not sit in AsyncStorage)
- `expo-haptics` (swipe feedback)
- `expo-image` (cached card images)
- `@noble/hashes` (plain npm, it is not an Expo module)

Do not add `expo-dev-client`, do not enable the new architecture flags beyond what
`app.json` already carries in the prototype, and do not bump the SDK.

### 2.2 Backend

Still a uv project. Run everything with `uv run ...` from `backend/`. New
dependencies to add to `backend/pyproject.toml`:

```
"pyjwt", "argon2-cffi"
```

Nothing else. `httpx` and `pydantic` are already there.

### 2.3 Web

npm plus Vite, Tailwind CSS v4, React 19, as today. shadcn/ui is added in Tailwind
v4 mode. New dependencies: `class-variance-authority`, `clsx`, `tailwind-merge`,
`lucide-react`, `@radix-ui/*` as pulled in by the components used, `sonner`,
`recharts` only if a chart is genuinely needed.

### 2.4 Shared package wiring

`packages/shared` ships TypeScript source, not a build step.

- `frontend/tsconfig.json` gets `"paths": { "@finbit/shared": ["../packages/shared/src/index.ts"] }`
  and `vite.config.ts` gets a matching `resolve.alias`.
- `mobile/metro.config.js` must add the monorepo root to `watchFolders` and add
  both `mobile/node_modules` and the repo root `node_modules` to
  `resolver.nodeModulesPaths`, plus a `resolver.extraNodeModules` entry mapping
  `@finbit/shared` to `../packages/shared`. Without this Metro will not resolve
  files outside `mobile/`.
- `mobile/tsconfig.json` gets the same `paths` entry.

---

## 3. Security design

### 3.1 What this achieves, and what it does not

Layered controls raise the cost of calling the API from anything but the two real
apps. They are not proof of app identity. Anything shipped to a device can be
extracted by a determined attacker. Real attestation needs Play Integrity or App
Attest, which require a custom dev build and therefore cannot run in Expo Go.
**Agent D3 must state this plainly in `SECURITY.md`. Do not claim the API is
unbreakable anywhere in the docs, the UI or code comments.**

### 3.2 Layers

1. **App key.** Every request carries `X-App-Key`. Two distinct keys, one for
   mobile and one for web, so either can be rotated alone. Configured as
   `APP_KEY_MOBILE` and `APP_KEY_WEB`. A request with an unknown key gets 401
   before anything else runs.
2. **Anonymous device handshake.** The client registers once and receives an
   opaque `device_id`, a `device_secret`, a short-lived `access_token` and a
   rotating `refresh_token`.
3. **Per-request HMAC signature** over method, path, body digest, timestamp and
   nonce. A captured access token alone is not enough to call the API.
4. **Replay protection.** Timestamp skew over 120 seconds is rejected. A nonce
   seen before is rejected. Nonces older than 300 seconds are pruned.
5. **Rate limits** per device and per IP, token bucket, enforced in SQLite.
6. **Strict CORS.** An explicit origin allowlist, never `*`, and
   `allow_credentials` stays false because auth is a bearer header.
7. **Admin login** with argon2 password hashing, lockout after failures, a
   separate JWT audience, and an audit log row for every mutation.

### 3.3 Device secret derivation

The server stores no secrets. The device secret is derived on demand:

```
device_secret_bytes = hmac_sha256(key = DEVICE_MASTER_KEY_bytes, msg = utf8(device_id))
device_secret       = base64_standard(device_secret_bytes)      # what the client stores
```

`DEVICE_MASTER_KEY` is a 32 byte random value from the environment. Rotating it
invalidates every device, which is the intended emergency lever. A device row
carries only `id`, `platform`, `app_id`, timestamps and a `revoked` flag.

### 3.4 Canonical string and signature, byte exact

Both `packages/shared/src/signing.ts` and `backend/app/security/signing.py` must
produce identical bytes for the same input. Agent C1 must test this with fixed
vectors.

```
body_digest = lowercase_hex( sha256( raw_request_body_bytes ) )
              # for an empty body, the sha256 of zero bytes:
              # e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

canonical   = timestamp + "\n"
            + nonce     + "\n"
            + METHOD_UPPERCASE + "\n"
            + path_with_query  + "\n"
            + body_digest

signature   = base64_standard( hmac_sha256( key = device_secret_bytes,
                                            msg = utf8(canonical) ) )
```

Rules that both sides must follow, or signatures will silently mismatch:

- `timestamp` is unix **seconds**, as a decimal string, no fraction.
- `nonce` is 16 random bytes, base64url, no padding.
- `path_with_query` starts with `/` and includes the query string exactly as sent,
  for example `/api/feed?category=rbi&sort=top`. No origin, no fragment.
  Do not re-encode or reorder query parameters on either side.
- The body digest is over the **exact bytes sent**. The client must serialize the
  body once, digest that string, and send that same string.
- Comparison on the server is constant time (`hmac.compare_digest`).

### 3.5 Request headers

Every call to a device-authenticated route:

```
X-App-Key:      <APP_KEY_MOBILE or APP_KEY_WEB>
X-Device-Id:    <device_id>
X-Timestamp:    <unix seconds>
X-Nonce:        <base64url, 16 bytes>
X-Signature:    <base64 hmac>
Authorization:  Bearer <access_token>
Content-Type:   application/json      (only when there is a body)
```

The registration and refresh routes take `X-App-Key` but no signature, because the
device has no secret yet or is proving possession through the refresh token.

Server verification order, each failure short-circuiting:

| Order | Check | Failure |
| --- | --- | --- |
| 1 | `X-App-Key` known and enabled | 401 `invalid_app_key` |
| 2 | IP rate limit | 429 `rate_limited` |
| 3 | Required headers present | 401 `missing_signature_headers` |
| 4 | Timestamp within 120s of now | 401 `stale_request` |
| 5 | Nonce unseen | 401 `replayed_request` |
| 6 | Access token valid, audience `device`, subject equals `X-Device-Id` | 401 `invalid_token` |
| 7 | Device row exists and is not revoked | 401 `device_revoked` |
| 8 | Signature matches | 401 `bad_signature` |
| 9 | Device rate limit | 429 `rate_limited` |

Every failure body is `{"detail": "<human sentence>", "code": "<code above>"}`.
Never leak which check failed beyond that code, and never log a secret, a token or
a signature.

### 3.6 Tokens

| Token | Audience | Lifetime | Storage |
| --- | --- | --- | --- |
| Device access | `device` | 15 minutes | memory, refetched on demand |
| Device refresh | `device-refresh` | 30 days, rotating, single use | SecureStore on native, localStorage on web |
| Admin access | `admin` | 30 minutes | memory only |
| Admin refresh | `admin-refresh` | 12 hours, rotating, single use | `sessionStorage` |

Refresh rotation: using a refresh token marks it used and issues a new one. A
second use of an already-used token revokes the whole device or admin session and
returns 401. Refresh tokens are stored server-side as `sha256(token)`, never raw.

### 3.7 Rate limits

Token bucket, refilled continuously, persisted in `rate_buckets`.

| Scope | Capacity | Refill |
| --- | --- | --- |
| Device registration per IP | 5 | 5 per hour |
| Any device route per device | 120 | 120 per minute |
| Any route per IP | 600 | 600 per minute |
| Admin login per IP | 10 | 10 per 15 minutes |
| Admin ingest trigger | 6 | 6 per hour |

### 3.8 Admin login

- Passwords hashed with argon2id via `argon2-cffi`, default parameters.
- 5 consecutive failures lock the account for 15 minutes (`locked_until`).
- A wrong username and a wrong password return the identical 401 body and take a
  comparable amount of time. Do not reveal which was wrong.
- The first admin is created by a CLI, never by an HTTP route:
  `uv run python -m app.admin_cli create-admin --username <name>`
  which prompts for the password twice on stdin and never echoes or logs it.
  If `ADMIN_BOOTSTRAP_USERNAME` and `ADMIN_BOOTSTRAP_PASSWORD` are both set in the
  environment and no admin exists, startup creates that one account and logs the
  username only.
- Every admin mutation writes an `audit_log` row: actor, action, target, detail,
  ip, timestamp.

### 3.9 Secrets and configuration

New `.env` keys, all added to `.env.example` with placeholder values by agent A2:

```
APP_KEY_MOBILE=change-me-mobile
APP_KEY_WEB=change-me-web
DEVICE_MASTER_KEY=change-me-32-bytes-of-random
JWT_SECRET=change-me-long-random
ADMIN_BOOTSTRAP_USERNAME=
ADMIN_BOOTSTRAP_PASSWORD=
SIGNATURE_SKEW_SECONDS=120
NONCE_TTL_SECONDS=300
REQUIRE_SIGNED_REQUESTS=true
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

`REQUIRE_SIGNED_REQUESTS=false` degrades to app key plus bearer only. It exists so
a developer can drive the API from `/docs` while debugging. **It must default to
true, log a loud warning at startup when false, and be documented as a
development-only switch.**

Startup must refuse to run when `REQUIRE_SIGNED_REQUESTS` is true and any of
`APP_KEY_MOBILE`, `APP_KEY_WEB`, `DEVICE_MASTER_KEY` or `JWT_SECRET` is empty or
still equal to its `change-me` placeholder. Fail with a clear message naming the
missing key.

The mobile app key reaches the bundle through `EXPO_PUBLIC_APP_KEY`. The web app
key reaches the bundle through `VITE_APP_KEY`. Both are build-time public values
by definition. Say so in `SECURITY.md` rather than pretending otherwise.

---

## 4. Database additions

Appended to `backend/app/schema.sql`. Every statement is `IF NOT EXISTS`.
`backend/app/migrate.py` handles the `ALTER TABLE` additions to `articles` by
reading `PRAGMA table_info(articles)` first, so it is safe to run repeatedly and
safe against an existing populated database.

```sql
ALTER TABLE articles ADD COLUMN hidden       INTEGER NOT NULL DEFAULT 0;
ALTER TABLE articles ADD COLUMN pinned       INTEGER NOT NULL DEFAULT 0;
ALTER TABLE articles ADD COLUMN moderated_at TEXT;
ALTER TABLE articles ADD COLUMN moderated_by TEXT;
CREATE INDEX IF NOT EXISTS idx_articles_visible ON articles(hidden, pinned DESC, importance_score DESC);

CREATE TABLE IF NOT EXISTS devices (
  id            TEXT PRIMARY KEY,
  platform      TEXT NOT NULL,
  app_id        TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  last_seen_at  TEXT,
  revoked       INTEGER NOT NULL DEFAULT 0,
  revoked_at    TEXT,
  request_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_devices_seen ON devices(last_seen_at DESC);

CREATE TABLE IF NOT EXISTS nonces (
  nonce     TEXT PRIMARY KEY,
  device_id TEXT NOT NULL,
  seen_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nonces_seen ON nonces(seen_at);

CREATE TABLE IF NOT EXISTS refresh_tokens (
  token_hash  TEXT PRIMARY KEY,
  subject     TEXT NOT NULL,
  kind        TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  used_at     TEXT,
  revoked     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_refresh_subject ON refresh_tokens(subject, kind);

CREATE TABLE IF NOT EXISTS admin_users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  last_login_at TEXT,
  failed_count  INTEGER NOT NULL DEFAULT 0,
  locked_until  TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT
);

CREATE TABLE IF NOT EXISTS feature_flags (
  key        TEXT PRIMARY KEY,
  enabled    INTEGER NOT NULL DEFAULT 1,
  value      TEXT,
  updated_at TEXT NOT NULL,
  updated_by TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  at     TEXT NOT NULL,
  actor  TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  detail TEXT,
  ip     TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at DESC);

CREATE TABLE IF NOT EXISTS rate_buckets (
  key        TEXT PRIMARY KEY,
  tokens     REAL NOT NULL,
  updated_at TEXT NOT NULL
);
```

`bookmarks.device_id` now holds a server-issued device id. This is a real fix:
before this change any client could read another device's bookmarks by supplying
its id. Existing rows keep working; they simply belong to devices that will never
authenticate again.

---

## 5. Settings precedence

`app_settings` overrides `.env` at runtime, so the admin can change the schedule
without a restart. `backend/app/pipeline/settings_bridge.py` exposes:

```python
def effective(name: str, default):  ...        # app_settings row, else settings, else default
def set_setting(name, value, actor): ...       # writes and invalidates the cache
```

Overridable keys, and nothing else:
`ingest_enabled`, `ingest_interval_minutes`, `ingest_queries_per_cycle`,
`ingest_max_stories_per_query`, `rescore_interval_minutes`, `query_set`.

Secrets are never overridable from the database. The scheduler re-reads the
interval on every tick and reschedules itself when it changed.

---

## 6. New API surface

All paths keep the `/api` prefix. Existing phase 1 routes keep their paths,
request shapes and response shapes exactly, and only gain device authentication
plus a `hidden = 0` filter.

### 6.1 Device auth, app key only, no signature

**`POST /api/auth/device`**
```json
request  { "app_id": "mobile", "platform": "ios", "install_id": "optional-opaque" }
response { "device_id": "…", "device_secret": "base64…", "access_token": "jwt…",
           "refresh_token": "…", "expires_in": 900 }
```
`app_id` is `mobile` or `web` and must match the app key presented.
`platform` is `ios`, `android` or `web`.

**`POST /api/auth/refresh`**
```json
request  { "refresh_token": "…" }
response { "access_token": "jwt…", "refresh_token": "…", "expires_in": 900 }
```

### 6.2 Public config, device authenticated

**`GET /api/config`**
```json
{ "categories": [{"key":"india","label":"India","enabled":true}, …],
  "market_filters": [{"key":"NIFTY","label":"Nifty","enabled":true}, …],
  "default_sort": "top",
  "maintenance_mode": false,
  "maintenance_message": null,
  "min_mobile_version": null }
```
When `maintenance_mode` is true, every device-authenticated content route returns
503 with `{"detail": "<maintenance_message>", "code": "maintenance"}`. `/api/config`
itself keeps answering, so the apps can render the maintenance screen.

### 6.3 Admin auth

- `POST /api/admin/auth/login` → `{username, password}` → `{access_token, refresh_token, expires_in, username}`
- `POST /api/admin/auth/refresh` → `{refresh_token}` → same shape
- `POST /api/admin/auth/logout` → 204, revokes the refresh token
- `GET  /api/admin/auth/me` → `{username, last_login_at}`

### 6.4 Admin pipeline and schedule

- `GET /api/admin/pipeline` → `{settings: {...}, scheduler: {running, next_ingest_at, next_rescore_at}, ingest_available, reason, recent_runs: IngestRun[5]}`
- `PATCH /api/admin/pipeline` → any subset of the overridable keys in section 5
- `POST /api/admin/pipeline/ingest` → `{queries?: string[], limit?: number}` → `{started, run_id}`
- `POST /api/admin/pipeline/rescore` → `{updated: number}`
- `POST /api/admin/pipeline/images` → `{started: true}`
- `GET  /api/admin/pipeline/queries` → `{queries: [{key,label,prompt,category_hint,enabled}]}`
- `PUT  /api/admin/pipeline/queries` → same shape, replaces the set

The existing `POST /api/admin/ingest` and `GET /api/admin/runs` stay as they are so
nothing already built breaks. `recent_runs` in the pipeline payload is the only run
history this build ships. A dedicated cost and analytics screen is out of scope.

### 6.5 Admin content moderation

- `GET /api/admin/articles` with `q`, `category`, `hidden`, `pinned`, `sort`, `cursor`, `limit`
  → `{items: AdminArticle[], next_cursor, has_more}` where `AdminArticle` is
  `ArticleCard` plus `hidden`, `pinned`, `moderated_at`, `moderated_by`, `dedupe_key`
- `PATCH /api/admin/articles/{id}` → any of `{hidden, pinned, category, headline, summary, why_it_matters}`
- `DELETE /api/admin/articles/{id}` → 204, cascades
- `POST /api/admin/articles/{id}/rescore` → `{importance_score}`
- `POST /api/admin/articles/{id}/refresh-image` → `{image_url}`
- `GET  /api/admin/articles/{id}/cluster` → `{article, sources, dedupe_key, story_cluster_id, siblings}`

### 6.6 Admin feature flags

- `GET /api/admin/flags` → the `/api/config` shape plus `updated_at` per key
- `PUT /api/admin/flags` → `{categories: {...}, market_filters: {...}, default_sort, maintenance_mode, maintenance_message, min_mobile_version}`

---

## 7. Design system, shared by web and mobile

Mobile reuses the phase 1 palette from `frontend/src/index.css` exactly. Every
color in the mobile app comes from `mobile/src/theme/tokens.ts`, and no component
file may contain a raw hex value.

```
dark   bg #0f172a  card #111827  fg #f8fafc  muted #1e293b  mutedFg #cbd5e1
       border #334155  accent #1e40af  onAccent #ffffff  breaking #dc2626
       bull #22c55e  bear #ef4444  flat #94a3b8
light  bg #ffffff  card #ffffff  fg #0f172a  muted #f1f5f9  mutedFg #475569
       border #e2e8f0  accent #1d4ed8  onAccent #ffffff  breaking #dc2626
       bull #16a34a  bear #dc2626  flat #64748b
```

Type: headlines in a serif, body in a sans. On mobile, load nothing custom in this
build; use the platform serif (`Georgia` on iOS, `serif` on Android) for headlines
and the system sans for body, exposed as `theme.fonts.headline` and
`theme.fonts.body`. The theme follows the system setting and can be overridden in
Settings.

---

## 8. Mobile app specification

### 8.1 Behavior

- **No login, ever.** On first launch the app registers a device in the
  background behind a splash. A failed handshake shows a retry screen, not a
  login screen.
- **Feed** is a vertical, full-screen, one-card-per-viewport pager. Use a
  `FlatList` with `pagingEnabled`, `snapToInterval` set to the card height,
  `decelerationRate="fast"` and `getItemLayout`, not a third-party pager.
- A light haptic fires on each card change (`expo-haptics`,
  `impactAsync(ImpactFeedbackStyle.Light)`).
- Card layout, top to bottom: image (16:9, `expo-image`, with a token-colored
  placeholder), category and time row, headline in the serif face, the 60-word
  summary, impact badge and sentiment, symbol chips, source count with a tap
  target that opens the sources sheet, and a bookmark toggle.
- Category tabs scroll horizontally above the feed. Market filter chips sit under
  them and are collapsible.
- Pull to refresh at the top of the feed. Infinite paging through `next_cursor`.
- **Search** screen: input, trending symbol and topic chips, results as compact
  rows, tapping a row opens `article/[id]`.
- **Saved** screen: bookmarks for this device, swipe to remove.
- **Settings** screen: theme (system, light, dark), a partial device id for
  support, the API base URL in development builds only, and an about section
  carrying the line "Impact and sentiment are AI assessments, not investment
  advice." There is no admin anything in the mobile app.
- Maintenance mode renders a full-screen message from `/api/config` on every tab.
- Every list has a skeleton, an empty state and an error state with retry. Never
  show a raw error object.

### 8.2 API base URL resolution

Copy the prototype's strategy in `mobile/src/api/client.ts`: prefer
`EXPO_PUBLIC_API_URL`; otherwise read `Constants.expoConfig.hostUri`, take the
host and swap in port 8000; fall back to `10.0.2.2:8000` on Android emulators and
`127.0.0.1:8000` otherwise. This is what makes both LAN mode and a dev tunnel work
without hardcoding an IP.

### 8.3 Credential storage

`device_id` and `refresh_token` go in `expo-secure-store`. `device_secret` goes in
`expo-secure-store`. The access token stays in memory only. Nothing sensitive goes
in AsyncStorage; AsyncStorage is for the theme preference and cached feed only.

---

## 9. Web admin specification

- Route branch: the existing hash router in `App.tsx` gains an `admin` branch.
  `#/admin/...` renders `AdminApp`, everything else renders the public shell.
  `AdminApp` is loaded with `React.lazy`, so the public bundle does not carry it.
- Unauthenticated access to any `#/admin` route renders `AdminLogin`.
- shadcn/ui provides the primitives. Match the existing token names: components
  must resolve to `bg-card`, `text-fg`, `border-border`, `bg-accent` and the rest
  of the phase 1 Tailwind theme, not shadcn's default `--background` scale.
- Three screens plus a dashboard landing:
  - **Pipeline**: ingestion on/off switch, interval, queries per cycle, max
    stories per query, rescore interval, the nine-query editor with per-query
    enable, and three action buttons (Fetch now, Rescore now, Refresh images).
    Show the last five runs as a compact strip with status and time. Any button
    that spends money states the cost estimate next to it and asks for
    confirmation in an `AlertDialog`.
  - **Content**: a table of articles with search, category filter and
    hidden/pinned filters. Row actions: hide, pin, edit, re-score, refresh image,
    delete, view cluster. Deleting asks for confirmation.
  - **Flags**: switches for each category and market filter, a default sort
    selector, maintenance mode with a message field, and a minimum mobile version
    field. A banner warns while maintenance mode is on.
- Every mutation shows a toast on success and on failure, and rolls back optimistic
  state on failure.
- The admin session lives in memory plus `sessionStorage`, so closing the tab ends
  it.

---

## 10. Definition of done

An agent's work is done when all of these hold for the files it owns.

1. `cd backend && uv run pytest` passes, including the 122 phase 1 tests.
2. `cd frontend && npm run build` completes with no TypeScript errors.
3. `cd mobile && npx tsc --noEmit` completes with no errors.
4. `cd mobile && npx expo-doctor` reports no version mismatches against SDK 54.
5. No file contains an emoji, an em dash or an en dash.
6. No secret, token, signature or password appears in any log line.
7. No component file contains a raw hex color.
8. Every new endpoint appears in the FastAPI OpenAPI schema with a summary.
9. `packages/shared` and `backend/app/security/signing.py` agree on the fixed test
   vectors in `backend/tests/test_security.py`.
10. Nothing in phase 1 changed shape: the feed, search, bookmarks and meta
    responses still validate against the phase 1 models.
