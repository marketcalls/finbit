# FinBit

An Inshorts-style financial news app for Indian market traders. Every card is a
headline, a sixty word summary, the tickers it touches, an impact call and the
real sources behind it.

Impact and sentiment on every card are AI assessments, not investment advice.

## Three clients, one API

| Client | Path | Sign in | What it is |
| --- | --- | --- | --- |
| Mobile | `mobile/` | None. Anonymous device handshake | Expo SDK 54 native newsfeed, full-screen swipe pager |
| Web, public | `frontend/` | None. Anonymous device handshake | The same feed in a browser, three screens |
| Web, admin | `frontend/src/admin/` | Username and password | Pipeline controls, content moderation, feature flags |

One shared TypeScript package, `packages/shared/`, holds the wire types, the
route constants and the request-signing implementation, so the two web bundles
and the app cannot drift from each other or from the server.

Stack: FastAPI plus SQLite on the backend (uv managed), React plus Vite plus
TypeScript plus Tailwind CSS v4 on the web, Expo plus React Native plus
gluestack-ui on mobile, and the Perplexity Agent API for news discovery.

---

## How it works

FinBit never browses. It holds nine standing questions and asks four of them
every fifteen minutes, rotating so all nine come round in about thirty five
minutes. A cycle runs end to end like this:

1. **Ask.** `pipeline/queries.py` picks the next slice of the nine query set:
   India markets, corporates, RBI, SEBI, earnings, global, the Fed, commodities
   and geopolitics.
2. **Read.** `pipeline/perplexity.py` posts each query to the Agent API, which
   searches the live web and returns finished stories against a strict JSON
   schema, plus the resolvable URLs it actually read. Requests go out one at a
   time because the account rate limit is one in flight. Retries are two, with
   exponential backoff on timeouts, 429s and 5xx.
3. **Clean.** `pipeline/extract.py` parses the payload, repairs the citations
   from the separate search results item, forces every enum into its fixed
   vocabulary, canonicalizes symbols and normalizes timestamps to ISO 8601 UTC.
   A story with no sources, an empty headline or a summary under twenty words is
   dropped.
4. **Merge.** `pipeline/dedupe.py` collapses the many reports of one event into
   one cluster. Headlines are reduced to a normalized token set and hashed into
   a `dedupe_key`; an exact key match merges immediately, otherwise candidates
   from the last forty eight hours are scored as
   `0.55 * headline jaccard + 0.25 * symbol overlap + 0.20 * domain overlap`
   and merged above 0.62. No vector database and no second model call.
5. **Rank.** `pipeline/score.py` computes importance in Python, never from the
   model. The model supplies only high, medium or low impact; the code adds
   points for distinct sources, publisher tier, breaking, index exposure and
   category, then subtracts 1.5 points per hour of age up to 30, clamped to
   0 to 100.
6. **Illustrate.** The Agent API returns no images, so `pipeline/images.py`
   fetches the Open Graph tag from the story's most credible source. It streams
   the response and stops at `</head>` or 200 KB, tries at most three
   candidates with an eight second timeout each, and gives up quietly. This hits
   publisher sites rather than Perplexity, so it adds no API cost.

Everything is written through `repo.py`, the only module that touches SQL, into
a single SQLite file. A separate rescore pass runs every thirty minutes so the
feed decays without any new spending.

### What phase 2 added

The API is no longer open. Every feed, article, search, trending, category,
bookmark and config route now requires an anonymous device identity plus a
per-request HMAC signature, so a captured bearer token on its own is not enough
to call it. The full design is in [SECURITY.md](SECURITY.md); the short version:

- **Device handshake.** A client registers once at `POST /api/auth/device` with
  its app key and gets back an opaque `device_id`, a `device_secret`, a fifteen
  minute access token and a rotating refresh token. There is no login screen and
  never was one.
- **Signed requests.** Every call carries `X-App-Key`, `X-Device-Id`,
  `X-Timestamp`, `X-Nonce`, `X-Signature` and a bearer token. The signature
  covers the method, the path with its query, the exact body bytes, the
  timestamp and the nonce.
- **Derived secrets.** The server stores no device secret. It derives one on
  demand from `DEVICE_MASTER_KEY` and the device id, so a stolen database copy
  cannot sign anything.
- **Bookmarks became private.** `bookmarks.device_id` now holds a server-issued
  id that the caller has to prove it owns. Before this, anyone who knew another
  device's id could read its saved articles.
- **Admin console.** A username and password sign-in with argon2id hashing, a
  separate JWT audience, account lockout, and an `audit_log` row for every
  mutation. Reachable at `#/admin`, lazy loaded so the public bundle never
  carries it.
- **Runtime settings.** `app_settings` rows override the `.env` values for the
  ingestion schedule, so the admin can retune the pipeline without a restart.
  `feature_flags` rows drive `/api/config`, which is what lets the admin switch
  a category off or put every client into maintenance mode.
- **Mobile app.** An Expo SDK 54 build sharing the design tokens, the wire types
  and the signing code with the web app.

---

## Requirements

- Python 3.12 or newer, driven by [uv](https://docs.astral.sh/uv/)
- Node.js 20.19 or newer (Vite 8 requires it)
- A Perplexity API key, optional for browsing cached articles
- For the phone: the Expo Go app from the App Store or Play Store, on the same
  Wi-Fi as your machine

Everything below is written for Windows, in PowerShell. Git Bash works too;
where the two differ, both forms are given.

---

## First-time setup

Do these in order. The shared package has to be installed before the web app or
the mobile app can resolve `@finbit/shared`.

### 1. Environment file and the four secrets

```powershell
Copy-Item .env.example .env
```

The API refuses to start until `APP_KEY_MOBILE`, `APP_KEY_WEB`,
`DEVICE_MASTER_KEY` and `JWT_SECRET` all hold real values. A value that is empty
or still begins with `change-me` counts as unset. Generate one value per key,
run from `backend/`:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run it four times and paste each result into `.env`:

```
APP_KEY_MOBILE=<first value>
APP_KEY_WEB=<second value>
DEVICE_MASTER_KEY=<third value>
JWT_SECRET=<fourth value>
```

The two app keys are copied into the client bundles later, so they are public by
definition. `DEVICE_MASTER_KEY` and `JWT_SECRET` are real secrets and never
leave the server. `.env` is git-ignored; the only file that gets committed is
`.env.example`.

### 2. Shared package

```powershell
Set-Location packages\shared
npm install
```

It ships TypeScript source with no build step, so there is nothing to compile.
The install exists to fetch its one dependency, `@noble/hashes`.

### 3. Backend

```powershell
Set-Location backend
uv sync
```

There is no `requirements.txt` and no manual venv. Run everything with
`uv run ...` from `backend/`, never bare `python`.

### 4. Frontend

```powershell
Set-Location frontend
npm install
```

`npm run dev` reads `frontend/.env.development`, which already points at
`http://127.0.0.1:8000`. Set `VITE_APP_KEY` there to the same value you put in
`APP_KEY_WEB`, or every request comes back `401 invalid_app_key`. For a
production build, copy `frontend/.env.example` to `frontend/.env.local` and set
both values there: `npm run build` runs in production mode and never reads
`.env.development`.

### 5. Mobile

```powershell
Set-Location mobile
npm install
Copy-Item .env.example .env
```

Install from the committed `package-lock.json`. Do not delete it: a fresh
unlocked resolve of the gluestack dependency tree currently produces an app that
type checks but does not bundle. `mobile/AGENTS.md` explains exactly why.

Set `EXPO_PUBLIC_APP_KEY` in `mobile/.env` to the same value you put in
`APP_KEY_MOBILE`.

Add packages with `npx expo install <pkg>`, never `npm install <pkg>`, so Expo
resolves the SDK 54 compatible version.

### 6. The first admin account

There is no HTTP route that creates an administrator, on purpose: an endpoint
that can mint one is an endpoint someone can find. Run the CLI from `backend/`:

```powershell
uv run python -m app.admin_cli create-admin --username alice
```

It prompts for the password twice on stdin. The password is never echoed, never
lands in shell history and never reaches a log line. Minimum length is 12
characters.

The other two subcommands:

```powershell
uv run python -m app.admin_cli list-admins
uv run python -m app.admin_cli reset-password --username alice
```

Alternatively, set `ADMIN_BOOTSTRAP_USERNAME` and `ADMIN_BOOTSTRAP_PASSWORD` in
`.env`. When both are set and no admin exists yet, startup creates that one
account and logs the username only. Clear both variables afterwards so the
password is not sitting in a file.

---

## Running

Three terminals, or as many as you need.

### Backend

From `backend/`:

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Binding `0.0.0.0` rather than `127.0.0.1` is what lets a phone on the same Wi-Fi
reach the API. Startup creates the schema, applies the phase 2 migration, checks
that the four secrets are real, seeds the feature flag defaults, starts the
scheduler and, when the database is empty or stale, fires one seeding cycle.
Interactive documentation is at <http://127.0.0.1:8000/docs>.

### Frontend

From `frontend/`:

```powershell
npm run dev
```

The app serves on <http://localhost:5173>. The public feed is at `#/feed`, and
the admin console is at `#/admin`.

### Mobile

From `mobile/`:

```powershell
npx expo start
```

Scan the QR code with Expo Go on Android, or with the Camera app on iOS. Press
`w` to open the same app in a browser, `a` for an Android emulator, `i` for an
iOS simulator.

### Ingesting on demand

The pipeline has a command line, run from `backend/`:

```powershell
uv run python -m app.pipeline.ingest --once
uv run python -m app.pipeline.ingest --queries india_markets,rbi --limit 3
uv run python -m app.pipeline.ingest --rescore
uv run python -m app.pipeline.ingest --images
```

`--rescore` and `--images` never call Perplexity, so they cost nothing. A full
`--once` cycle across all nine queries costs roughly 0.05 USD and takes one to
two minutes.

---

## Expo SDK 54, deliberately

The mobile app is pinned to Expo SDK 54 and must stay there.

Expo Go installed from the App Store or Play Store can only open projects on the
SDK version it tracks. Check which one that is:

```powershell
(Invoke-RestMethod https://api.expo.dev/v2/versions/latest).data.expoGoSdkVersion
```

Git Bash:

```bash
curl -s https://api.expo.dev/v2/versions/latest | grep -o '"expoGoSdkVersion":"[^"]*"'
```

That currently answers `54.0.0`. A project on SDK 55 or newer cannot be opened
by a store-installed Expo Go at all: newer runtimes ship only as sideloadable
GitHub releases or inside a custom development build, so bumping the SDK trades
"scan a QR code and it runs" for "everyone testing this needs a custom build
first". Every version in `mobile/package.json` is pinned to the set in
`CONTRACT_MOBILE_ADMIN.md` section 2.1 for that reason.

If `npx expo-doctor` reports a version mismatch, fix it with
`npx expo install --check`. Never hand-edit a version to silence it.

---

## Testing on a phone

The phone and the machine running the API have to be able to reach each other.

### 1. Same Wi-Fi

Put both on the same network, and make sure it is not a guest network. Many
guest and hotel networks enable client isolation, which blocks phone-to-laptop
traffic entirely. If that is your only option, skip to the dev tunnel below.

### 2. Two Windows Firewall rules

Windows blocks inbound connections to both ports by default, which shows up as
Expo Go hanging on "Downloading JavaScript bundle" or the app registering
forever. Run these once from an **elevated** PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Expo dev server 8081" -Direction Inbound -Protocol TCP -LocalPort 8081 -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "FinBit API 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

Port 8081 is Metro, which serves the JavaScript bundle. Port 8000 is the API.
The rules are scoped to the Private profile, so they do not open those ports on
a public network.

### 3. The API base URL

`mobile/src/api/client.ts` works this out without any hardcoded IP:

1. `EXPO_PUBLIC_API_URL` when it is set, which wins over everything.
2. Otherwise the host from `Constants.expoConfig.hostUri`, which is the machine
   Metro is serving from, with port 8000 swapped in. This is the normal LAN path
   and needs no configuration.
3. `10.0.2.2:8000` on an Android emulator, `127.0.0.1:8000` otherwise.

So on the same Wi-Fi you set nothing. Set `EXPO_PUBLIC_API_URL` in `mobile/.env`
only when the phone cannot reach your machine directly. Expo inlines
`EXPO_PUBLIC_` variables at bundle time, so restart `npx expo start` after
changing one.

### 4. When the network isolates clients

Tunnel Metro:

```powershell
npx expo start --tunnel
```

That publishes the bundle through ngrok, so Expo Go can load the app from
anywhere. It does **not** tunnel the API: the auto-detection in step 3 would
then point at the ngrok host on port 8000, which does not exist. So expose port
8000 separately, with ngrok, cloudflared or whatever you already use, and set
the result in `mobile/.env`:

```
EXPO_PUBLIC_API_URL=https://your-api-tunnel-host
```

Then restart `npx expo start --tunnel`.

**Add that tunnel origin to `CORS_ORIGINS` in the repo root `.env`.** CORS does
not apply to the native app, which is not a browser, but it does apply the
moment a browser is involved: the Expo web build (`press w`), the Vite app
pointed at a tunneled API, or anything you open from a phone browser. A missing
origin there is a silent failure that looks like a network error.

```
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://your-api-tunnel-host
```

The list is explicit and never a wildcard. Restart the API after changing it.

---

## The admin console

Open <http://localhost:5173/#/admin> and sign in with the account you created
with the CLI. The console is loaded with `React.lazy`, so a reader of the public
feed never downloads it. The session lives in memory plus `sessionStorage`,
which means closing the tab ends it.

| Screen | Hash | What it controls |
| --- | --- | --- |
| Dashboard | `#/admin` | Landing view: article counts, recent runs, quick links into the other three |
| Pipeline | `#/admin/pipeline` | Ingestion on or off, interval, queries per cycle, max stories per query, rescore interval, the nine-query editor with per-query enable, and three action buttons: Fetch now, Rescore now, Refresh images |
| Content | `#/admin/content` | The article table with search, category filter and hidden or pinned filters. Row actions: hide, pin, edit, re-score, refresh image, delete, view cluster |
| Flags | `#/admin/flags` | A switch per category and per market filter, the default sort, maintenance mode with its message, and a minimum mobile version |

Two things worth knowing:

- **Buttons that spend money say so.** Fetch now states the cost estimate next
  to it and asks for confirmation before it runs. Deleting an article asks too.
- **Pipeline changes take effect without a restart.** The settings written here
  land in `app_settings`, which overrides `.env` at runtime, and the scheduler
  re-reads the interval on every tick.
- **Maintenance mode is global.** Turning it on makes every content route answer
  503 with your message, on the web and in the app alike. `/api/config` keeps
  answering so the clients can render the message rather than an error, and the
  admin screens keep working so you can turn it back off.

---

## Tests

Backend, from `backend/`:

```powershell
uv run pytest
```

284 tests: 283 pass and 1 is an expected failure. They cover the API surface,
dedupe scoring, the importance formula, Open Graph extraction over saved HTML,
the whole signing and replay layer with fixed cross-language vectors, the device
handshake and bookmark isolation, and every admin route including lockout, the
audit log and the maintenance gate. Nothing in the suite hits the network.

Shared package and web, from `packages/shared/` and `frontend/`:

```powershell
npx tsc --noEmit
npm run build
```

Mobile, from `mobile/`:

```powershell
npx tsc --noEmit
npx expo-doctor
```

`expo-doctor` runs 18 checks, including whether any installed package has
drifted from the version SDK 54 expects.

---

## API

All routes are prefixed with `/api`.

**Device** means the route needs the full signed request: app key, device id,
timestamp, nonce, signature and a device bearer token. **Admin** means an admin
bearer token. **App key** means the key header only, because the caller has no
device secret yet. See [SECURITY.md](SECURITY.md) for the exact rules.

### Public and device authenticated

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /health` | none | Article count, last ingest time and status, and why ingestion is unavailable if it is |
| `POST /auth/device` | app key | Register an anonymous device, returns the id, the secret and a token pair |
| `POST /auth/refresh` | app key | Rotate a device refresh token |
| `GET /config` | device | Categories, market filters, default sort, maintenance mode and message, minimum mobile version |
| `GET /feed` | device | Cursor paginated cards, sorted by `top` or `latest`, filterable by category and market |
| `GET /articles/{id}` | device | One card in full |
| `GET /search` | device | Full text search across headlines, summaries, tickers and topics |
| `GET /trending` | device | Recurring tickers and topics |
| `GET /categories` | device | The ten category tabs with counts, plus the six market filters |
| `GET /bookmarks` | device | Saved articles for the calling device |
| `POST /bookmarks` | device | Save an article |
| `DELETE /bookmarks/{article_id}` | device | Remove a saved article |

### Admin

| Route | Purpose |
| --- | --- |
| `POST /admin/auth/login` | Sign in, returns an access token and a rotating refresh token |
| `POST /admin/auth/refresh` | Rotate an admin refresh token |
| `POST /admin/auth/logout` | 204, revokes the refresh token |
| `GET /admin/auth/me` | The signed in username and last login time |
| `GET /admin/pipeline` | Settings, scheduler state, whether ingest can run, and the last five runs |
| `PATCH /admin/pipeline` | Change any subset of the overridable pipeline settings |
| `POST /admin/pipeline/ingest` | Run one ingestion cycle now |
| `POST /admin/pipeline/rescore` | Recompute importance scores |
| `POST /admin/pipeline/images` | Resolve missing card images |
| `GET /admin/pipeline/queries` | The nine discovery queries with their enable flags |
| `PUT /admin/pipeline/queries` | Replace the query set |
| `GET /admin/articles` | The moderation table, with `q`, `category`, `hidden`, `pinned`, `sort`, `cursor`, `limit` |
| `PATCH /admin/articles/{id}` | Hide, pin, recategorize or edit the text of one article |
| `DELETE /admin/articles/{id}` | 204, cascades to sources, symbols, topics and bookmarks |
| `POST /admin/articles/{id}/rescore` | Recompute one importance score |
| `POST /admin/articles/{id}/refresh-image` | Resolve that card image again |
| `GET /admin/articles/{id}/cluster` | What deduplication decided: the sources, the dedupe key and the sibling stories |
| `GET /admin/flags` | The `/api/config` shape plus a last-changed time per key |
| `PUT /admin/flags` | Update the categories, market filters, default sort, maintenance mode and message, and minimum mobile version |

### Phase 1 development routes

| Route | Purpose |
| --- | --- |
| `POST /admin/ingest` | Trigger one cycle without waiting for the timer |
| `GET /admin/runs` | The last twenty ingest runs with counts and cost |

These two predate the admin console and are **not authenticated**. They are kept
so nothing already built breaks. Set `ALLOW_ADMIN_INGEST_FROM_UI=false` before
exposing the API anywhere, which turns `POST /admin/ingest` into a 403. The
authenticated equivalents are `POST /admin/pipeline/ingest` and the
`recent_runs` field of `GET /admin/pipeline`.

Every response carries an `X-Response-Time-Ms` header. Every coded failure body
is `{"detail": "<human sentence>", "code": "<machine code>"}`.

---

## Failure behavior

The expensive and fragile parts are wrapped so they cannot take the app down.

- **No API key.** The app boots, serves whatever it already collected, and the
  empty state explains the real reason instead of blaming the network.
- **One query fails.** Its error is recorded on the run outcome and the other
  queries in the cycle still persist their stories.
- **The scheduler fails.** It is imported lazily, so a pipeline problem never
  stops the API from serving cached articles.
- **A development restart.** The startup cycle is conditional on the last run
  being older than the ingest interval, so saving a file under `--reload` does
  not re-buy news that was just fetched.
- **A missing secret.** Startup refuses, naming the variable. It never starts
  half configured and derives device secrets from an empty key.
- **A device that cannot store its credentials.** SecureStore failures on the
  phone degrade to memory for the session; the app re-registers on next launch
  and loses only that device's saved articles.

---

## Configuration

Every value is read from the repo root `.env`, or from real environment
variables, which win over the file. See `.env.example` for the annotated list.

### Pipeline and transport

| Variable | Default | What it does |
| --- | --- | --- |
| `PERPLEXITY_API_KEY` | empty | Required for ingestion only. The API starts and serves cached articles without it |
| `PERPLEXITY_MODEL` | `perplexity/sonar` | Model id used for story discovery |
| `DB_PATH` | `finbit.db` | SQLite file. A relative path resolves against `backend/` |
| `CORS_ORIGINS` | the two Vite dev origins | Comma separated list of allowed browser origins. Never a wildcard |
| `INGEST_ENABLED` | `true` | Set false to run the API on cached articles only |
| `INGEST_INTERVAL_MINUTES` | `15` | How often a fetch cycle runs |
| `INGEST_QUERIES_PER_CYCLE` | `4` | How many of the nine queries each cycle asks |
| `INGEST_MAX_STORIES_PER_QUERY` | `6` | Cap on stories kept per query |
| `INGEST_CONCURRENCY` | `1` | Keep at 1. The live account answers `x-ratelimit-limit: 1` |
| `RESCORE_INTERVAL_MINUTES` | `30` | How often stored articles are rescored so the feed decays |
| `INGEST_ON_STARTUP` | `true` | Seed an empty or stale database on boot |
| `ALLOW_ADMIN_INGEST_FROM_UI` | `true` | Gates the unauthenticated `POST /api/admin/ingest`. Set false outside local development |

The six pipeline keys in the middle of that table can be overridden at runtime
from the admin Pipeline screen. Those overrides live in `app_settings` and win
over the `.env` value until they are cleared. Secrets are never overridable from
the database.

### Security

| Variable | Default | What it does |
| --- | --- | --- |
| `APP_KEY_MOBILE` | placeholder | The app key the mobile bundle carries. Public by definition |
| `APP_KEY_WEB` | placeholder | The app key the web bundle carries. Public by definition |
| `DEVICE_MASTER_KEY` | placeholder | Every device secret is derived from this. A real secret. Rotating it invalidates every device |
| `JWT_SECRET` | placeholder | Signs access tokens. A real secret. Rotating it signs everyone out |
| `ADMIN_BOOTSTRAP_USERNAME` | empty | Optional. With the password below, creates the first admin at startup when none exists |
| `ADMIN_BOOTSTRAP_PASSWORD` | empty | Optional. Only the username is ever logged |
| `SIGNATURE_SKEW_SECONDS` | `120` | How far a signed timestamp may be from the server clock |
| `NONCE_TTL_SECONDS` | `300` | How long a nonce is remembered before it is pruned |
| `REQUIRE_SIGNED_REQUESTS` | `true` | Development-only switch. False drops the signature and the replay check. See SECURITY.md |

The four keys with a `change-me` placeholder are checked at startup. With
`REQUIRE_SIGNED_REQUESTS=true`, a placeholder or an empty value is a clean
startup failure naming the variable.

### Client environment

| File | Variable | Notes |
| --- | --- | --- |
| `frontend/.env.development` | `VITE_API_BASE`, `VITE_APP_KEY` | Loaded by `npm run dev` only |
| `frontend/.env.local` | the same two | Needed for `npm run build`, which never reads `.env.development` |
| `mobile/.env` | `EXPO_PUBLIC_API_URL`, `EXPO_PUBLIC_APP_KEY` | Both are inlined into the bundle at build time |

Everything with a `VITE_` or `EXPO_PUBLIC_` prefix is compiled into the
JavaScript every user downloads. Never put a real secret in one.

### Cost

One query is roughly 0.006 USD. The defaults are about sixteen queries an hour,
close to 0.10 USD an hour. Lower `INGEST_QUERIES_PER_CYCLE` or raise
`INGEST_INTERVAL_MINUTES` to spend less. The real cost of every call is recorded
on the `ingest_runs` row and is visible on the admin Pipeline screen and at
`GET /api/admin/runs`.

---

## Layout

```
finbit/
  .env.example                  environment template, all keys annotated
  CONTRACT.md                   phase 1 build contract
  CONTRACT_MOBILE_ADMIN.md      phase 2 build contract, mobile and admin
  SECURITY.md                   threat model, signing, rotation, deployment
  packages/shared/              one API contract for both web and mobile
    src/types.ts                every request and response type
    src/endpoints.ts            every route path, plus buildPath
    src/signing.ts              canonical string and HMAC, isomorphic
    src/storage.ts              the CredentialStore interface
    src/client.ts               transport-agnostic signed fetch client
  backend/
    pyproject.toml              uv project, no requirements.txt
    app/
      main.py                   FastAPI app, lifespan, middleware, routers
      config.py                 settings, and the startup security check
      deps.py                   the signed-request verification chain
      admin_cli.py              create-admin, list-admins, reset-password
      migrate.py                idempotent ALTER TABLE additions
      models.py                 Pydantic models and the fixed vocabularies
      db.py, repo.py            connection handling and every SQL statement
      schema.sql                tables, indexes and the FTS5 index
      security/                 app keys, signing, tokens, passwords,
                                rate limits, transport middleware
      routers/                  feed, search, bookmarks, meta, config,
                                device auth, admin auth, admin pipeline,
                                admin content, admin flags
      pipeline/                 queries, perplexity, extract, dedupe, score,
                                images, ingest, scheduler, settings bridge
    tests/                      pytest suite, no network
  frontend/                     the web app
    src/
      api/                      signed client and re-exported wire types
      components/               shell, cards, tabs, filters, states
      components/ui/            shadcn primitives on the phase 1 tokens
      screens/                  feed, search, saved
      admin/                    login, shell, auth, api
      admin/screens/            dashboard, pipeline, content, flags
      lib/                      device handshake, bookmarks, format, theme
  mobile/                       the Expo SDK 54 app
    app/                        expo-router: tabs and the article route
    src/api/                    client, base URL resolution, SecureStore
    src/store/                  device auth, config and bookmarks providers
    src/theme/                  gluestack config and the shared color tokens
    src/components/             cards, chips, filters, states
    AGENTS.md                   why the SDK and the lockfile are pinned
```

---

## License

MIT. See [LICENSE](LICENSE).
