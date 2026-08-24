# FinBit Build Contract

Single source of truth for every build agent. Do not invent names, routes, fields
or colors that are not in this file. If something is missing, follow the nearest
convention already present here.

Product: FinBit, an Inshorts-style financial news app for Indian market traders.
Stack: FastAPI + SQLite (uv-managed) backend, React + Vite + TypeScript +
Tailwind CSS v4 frontend, Perplexity Agent API for news discovery.

Repo root: `D:\AI Bootcamp 2026\Day15\finbit` (git repo, pushed to
`github.com/marketcalls/finbit`, MIT licensed).

---

## 1. Toolchain rules

Backend is a **uv** project. There is no `requirements.txt` and no manual venv.

- Dependencies live in `backend/pyproject.toml`.
- Install with `uv sync` run from `backend/`.
- Run anything with `uv run ...` from `backend/`, never bare `python`.
- `requires-python = ">=3.12"`.

Backend dependencies: `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic>=2`,
`pydantic-settings`, `apscheduler`, `python-dotenv`.
Backend dev dependencies (uv dev group): `pytest`, `pytest-asyncio`.

Frontend is npm + Vite. Run from `frontend/`: `npm install`, `npm run dev`,
`npm run build`.

Windows note: all shell work happens on Windows. Never hardcode POSIX-only paths.
Resolve paths from `Path(__file__).resolve().parents[N]`.

Secrets: `PERPLEXITY_API_KEY` lives in `finbit/.env`, which is git-ignored.
Never print the key, never commit it, never send it to the frontend. Ship a
`.env.example` with placeholder values instead.

---

## 2. Directory layout and file ownership

Each file is written by exactly one agent. Never edit a file you do not own.

```
finbit/
  .env                          # EXISTS, git-ignored. Do not overwrite.
  .env.example                  # agent B1
  .gitignore                    # EXISTS
  LICENSE                       # EXISTS (MIT)
  CONTRACT.md                   # this file, read-only for agents
  README.md                     # agent DOCS
  backend/
    pyproject.toml              # agent B1
    .python-version             # agent B1
    app/
      __init__.py               # agent B1
      config.py                 # agent B1
      db.py                     # agent B1
      schema.sql                # agent B1
      models.py                 # agent B1
      repo.py                   # agent B1
      main.py                   # agent B3
      routers/
        __init__.py             # agent B3
        feed.py                 # agent B3
        search.py               # agent B3
        bookmarks.py            # agent B3
        meta.py                 # agent B3
      pipeline/
        __init__.py             # agent B2
        queries.py              # agent B2
        perplexity.py           # agent B2
        extract.py              # agent B2
        dedupe.py               # agent B2
        score.py                # agent B2
        ingest.py               # agent B2
        scheduler.py            # agent B2
    tests/
      __init__.py               # agent B2
      conftest.py               # agent B2
      test_dedupe.py            # agent B2
      test_score.py             # agent B2
      test_api.py               # agent B3
  frontend/
    package.json                # agent F1
    vite.config.ts              # agent F1
    tsconfig.json               # agent F1
    tsconfig.node.json          # agent F1
    index.html                  # agent F1
    .env.development            # agent F1
    src/
      main.tsx                  # agent F1
      App.tsx                   # agent F1
      index.css                 # agent F1  (design tokens live here)
      vite-env.d.ts             # agent F1
      api/client.ts             # agent F1
      api/types.ts              # agent F1
      lib/device.ts             # agent F1
      lib/format.ts             # agent F1
      lib/useTheme.ts           # agent F1
      lib/bookmarks.tsx         # agent F1  (context + provider + hook)
      components/AppShell.tsx   # agent F1  (header, nav, theme toggle)
      components/Icons.tsx      # agent F1  (all inline SVG icons)
      screens/FeedScreen.tsx    # agent F2
      components/NewsCard.tsx   # agent F2
      components/CategoryTabs.tsx   # agent F2
      components/MarketFilters.tsx  # agent F2
      components/FeedSkeleton.tsx   # agent F2
      screens/SearchScreen.tsx  # agent F3
      screens/SavedScreen.tsx   # agent F3
      components/SourcesSheet.tsx # agent F3
      components/ImpactBadge.tsx  # agent F3
      components/SymbolChips.tsx  # agent F3
      components/EmptyState.tsx   # agent F3
      components/ImpactMap.tsx    # agent F3
      components/ErrorState.tsx   # agent F3
```

`NewsCard.tsx` (F2) imports `ImpactBadge`, `SymbolChips`, `SourcesSheet` and
`ImpactMap` from F3. Those are pure presentational components. Their exact prop
types are frozen in section 11 so F2 and F3 can be built in parallel.

---

## 3. SQLite schema (verbatim DDL, agent B1 copies this into app/schema.sql)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS articles (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  story_cluster_id  TEXT    NOT NULL UNIQUE,
  headline          TEXT    NOT NULL,
  summary           TEXT    NOT NULL,
  why_it_matters    TEXT,
  category          TEXT    NOT NULL,
  sentiment         TEXT    NOT NULL DEFAULT 'neutral',
  impact            TEXT    NOT NULL DEFAULT 'low',
  impact_direction  TEXT    NOT NULL DEFAULT 'neutral',
  importance_score  INTEGER NOT NULL DEFAULT 0,
  is_breaking       INTEGER NOT NULL DEFAULT 0,
  source_count      INTEGER NOT NULL DEFAULT 0,
  published_at      TEXT    NOT NULL,
  created_at        TEXT    NOT NULL,
  updated_at        TEXT    NOT NULL,
  dedupe_key        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_published  ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_category   ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_score      ON articles(importance_score DESC, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_dedupe     ON articles(dedupe_key);

CREATE TABLE IF NOT EXISTS sources (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id   INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  publisher    TEXT    NOT NULL,
  title        TEXT,
  url          TEXT    NOT NULL,
  published_at TEXT,
  UNIQUE(article_id, url)
);
CREATE INDEX IF NOT EXISTS idx_sources_article ON sources(article_id);

CREATE TABLE IF NOT EXISTS article_symbols (
  article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  symbol     TEXT    NOT NULL,
  exchange   TEXT    NOT NULL DEFAULT 'NSE',
  kind       TEXT    NOT NULL DEFAULT 'stock',
  PRIMARY KEY (article_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_symbols_symbol ON article_symbols(symbol);

CREATE TABLE IF NOT EXISTS topics (
  id   INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS article_topics (
  article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  PRIMARY KEY (article_id, topic_id)
);

CREATE TABLE IF NOT EXISTS article_impacts (
  article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  name       TEXT    NOT NULL,
  direction  TEXT    NOT NULL,
  PRIMARY KEY (article_id, name)
);

CREATE TABLE IF NOT EXISTS bookmarks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id  TEXT    NOT NULL,
  article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  created_at TEXT    NOT NULL,
  UNIQUE(device_id, article_id)
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_device ON bookmarks(device_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ingest_runs (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at     TEXT    NOT NULL,
  finished_at    TEXT,
  status         TEXT    NOT NULL DEFAULT 'running',
  queries_run    INTEGER NOT NULL DEFAULT 0,
  stories_seen   INTEGER NOT NULL DEFAULT 0,
  stories_new    INTEGER NOT NULL DEFAULT 0,
  stories_merged INTEGER NOT NULL DEFAULT 0,
  cost_usd       REAL    NOT NULL DEFAULT 0.0,
  error          TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
  headline, summary, why_it_matters, symbols_text, topics_text,
  content='', tokenize='porter unicode61'
);
```

Column value vocabularies, lowercase in both the DB and the JSON API:

- `articles.category`: `india` `global` `stocks` `economy` `rbi` `sebi`
  `earnings` `commodities` `crypto`. Never `all`.
- `articles.sentiment`: `positive` `negative` `neutral` `mixed`
- `articles.impact`: `high` `medium` `low`
- `articles.impact_direction`: `bullish` `bearish` `neutral` `mixed`
- `article_symbols.kind`: `stock` `index` `commodity` `currency` `crypto`
- `article_impacts.direction`: `positive` `negative` `mixed` `neutral`
- `ingest_runs.status`: `running` `ok` `error`

`articles_fts` is a contentless FTS5 table. `repo.py` owns keeping it in sync:
on insert, write a row with `rowid = articles.id`; on update, delete the row by
rowid then reinsert. Wrap FTS queries so a malformed user query falls back to a
`LIKE` scan instead of raising.

Timestamps are ISO 8601 UTC with a trailing `Z`, for example
`2026-08-24T14:32:00Z`. Always store UTC. The frontend does relative-time
formatting.

DB file path: `backend/finbit.db`, git-ignored, resolved in `config.py`.

---

## 4. Categories, filters and symbol normalization

Category keys in display order. `all` is a UI-only pseudo-category:

```
all | india | global | stocks | economy | rbi | sebi | earnings | commodities | crypto
```

Display labels: All, India, Global, Stocks, Economy, RBI, SEBI, Earnings,
Commodities, Crypto.

Market quick filters, which filter by symbol rather than category:

```
NIFTY | BANKNIFTY | SENSEX | USDINR | GOLD | CRUDE
```

Display labels: Nifty, Bank Nifty, Sensex, USDINR, Gold, Crude.

Canonical symbol rules, enforced in `extract.py`, not left to the model:

- Indian stocks use the NSE trading symbol, uppercase, no suffix: `RELIANCE`,
  `TCS`, `HDFCBANK`. Strip `.NS`, `.BO`, a leading `^`, and `NSE:` / `BSE:`
  prefixes.
- Indices use exactly these tokens: `NIFTY`, `BANKNIFTY`, `SENSEX`, `NIFTYIT`,
  `NIFTYPHARMA`, `NIFTYAUTO`, `NIFTYFMCG`, `NIFTYMETAL`.
  Map `^NSEI`, `NIFTY50`, `NIFTY 50` to `NIFTY`; `^BSESN`, `BSE SENSEX` to
  `SENSEX`; `^NSEBANK`, `NIFTY BANK` to `BANKNIFTY`.
- Currencies: `USDINR`, `EURINR`, `DXY`. Commodities: `GOLD`, `SILVER`,
  `CRUDE`, `NATGAS`. Crypto: `BTC`, `ETH`.
- Global tickers keep their exchange: `exchange` is `NASDAQ` or `NYSE` for
  `AAPL`, `NVDA`. Indian equities use `NSE`. Indices use `INDEX`. Commodities
  use `COMMODITY`. Currencies use `FX`. Crypto uses `CRYPTO`.
- Drop any symbol that is not `^[A-Z0-9&-]{1,20}$` after normalization.

---

## 5. REST API contract

Dev base URL: `http://127.0.0.1:8000`. All app routes live under `/api`.
CORS allows `http://localhost:5173` and `http://127.0.0.1:5173`.

Device identity: the frontend generates a UUIDv4 once, stores it in
`localStorage` under `finbit.device_id`, and sends it as `X-Device-Id` on every
request. A missing header means anonymous with no bookmarks.

### GET /api/health
```json
{ "status": "ok", "articles": 42, "last_ingest_at": "2026-08-24T14:30:00Z", "last_ingest_status": "ok" }
```

### GET /api/feed
Params: `category` (default `all`), `symbol` (optional), `sort` (`top` default,
or `latest`), `cursor` (optional), `limit` (default 20, max 50).

`sort=top` orders by `importance_score DESC, published_at DESC, id DESC`.
`sort=latest` orders by `published_at DESC, id DESC`.
`cursor` is base64 of `"<primary>|<published_at>|<id>"`. An unparsable cursor is
treated as absent, never a 500.

```json
{ "items": [], "next_cursor": "eyJ...", "has_more": true }
```

### GET /api/articles/{id}
A single ArticleCard. Missing id returns 404 `{"detail": "Article not found"}`.

### GET /api/search
Params: `q` (required, min length 2), `limit` (default 30, max 50).
```json
{ "query": "reliance", "items": [], "count": 7 }
```
A `q` shorter than 2 characters returns 422.

### GET /api/trending
```json
{ "symbols": ["RELIANCE", "NIFTY"], "topics": ["RBI Policy", "Q1 Earnings"] }
```
Most frequent symbols and topics over the last 48 hours, max 12 each.

### GET /api/categories
```json
{
  "categories": [{ "key": "all", "label": "All", "count": 120 }],
  "market_filters": [{ "key": "NIFTY", "label": "Nifty" }]
}
```

### GET /api/bookmarks
Requires `X-Device-Id`. Newest saved first.
```json
{ "items": [], "count": 3 }
```

### POST /api/bookmarks
Body `{ "article_id": 12 }`. Requires `X-Device-Id`. Idempotent.
```json
{ "article_id": 12, "bookmarked": true }
```
404 for an unknown article, 400 when `X-Device-Id` is missing.

### DELETE /api/bookmarks/{article_id}
Requires `X-Device-Id`. Idempotent.
```json
{ "article_id": 12, "bookmarked": false }
```

### POST /api/admin/ingest
Dev trigger. Body `{ "queries": ["india_markets"], "limit": 2 }`, both optional.
Starts one pipeline cycle in the background and returns immediately.
```json
{ "started": true, "run_id": 4 }
```

### GET /api/admin/runs
The last 20 ingest runs, newest first, each with cost and counts.

### ArticleCard, the exact JSON returned by every article-bearing endpoint

```json
{
  "id": 12,
  "story_cluster_id": "a3f1c9e2b7d40156",
  "headline": "RBI keeps repo rate unchanged at 5.50%",
  "summary": "A 50 to 80 word summary.",
  "why_it_matters": "One or two sentences on the Indian market read-through.",
  "category": "rbi",
  "sentiment": "neutral",
  "impact": "high",
  "impact_direction": "neutral",
  "importance_score": 78,
  "is_breaking": true,
  "source_count": 5,
  "published_at": "2026-08-24T09:15:00Z",
  "created_at": "2026-08-24T09:22:11Z",
  "bookmarked": false,
  "symbols": [{ "symbol": "HDFCBANK", "exchange": "NSE", "kind": "stock" }],
  "topics": ["Monetary Policy", "Banking"],
  "sources": [
    { "publisher": "Reuters", "title": "RBI holds rates", "url": "https://example.com/a", "published_at": "2026-08-24T09:15:00Z" }
  ],
  "impact_map": [
    { "name": "NIFTY", "direction": "neutral" },
    { "name": "Banks", "direction": "positive" }
  ]
}
```

`why_it_matters` may be null. `sources[].title` and `sources[].published_at` may
be null. Arrays are always present and never null.

---

## 6. Perplexity Agent API contract (verified live against the real key)

Endpoint: `POST https://api.perplexity.ai/v1/agent`
Headers: `Authorization: Bearer <PERPLEXITY_API_KEY>`, `Content-Type: application/json`

Verified request body:

```json
{
  "model": "perplexity/sonar",
  "input": "the search task",
  "instructions": "system-style instructions",
  "tools": [{ "type": "web_search" }],
  "max_output_tokens": 4000,
  "response_format": {
    "type": "json_schema",
    "json_schema": { "name": "finbit_stories", "schema": {} }
  }
}
```

Verified HTTP 200 response shape:

```json
{
  "id": "...",
  "status": "completed",
  "output": [
    { "type": "search_results",
      "results": [
        { "id": 1, "title": "...", "url": "https://...", "snippet": "...",
          "source": "...", "date": "2026-08-24", "last_updated": "2026-08-24" }
      ] },
    { "type": "message",
      "content": [{ "type": "output_text", "text": "{\"stories\": []}" }] }
  ],
  "usage": {
    "input_tokens": 5669, "output_tokens": 805, "total_tokens": 6474,
    "cost": { "total_cost": 0.00593, "currency": "USD" }
  }
}
```

Facts established by the live smoke test. Treat them as requirements:

- The JSON payload is in the `message` output item at `content[i].text` where
  `content[i].type == "output_text"`. Concatenate every such text before parsing.
- `search_results` is a separate output item and carries the real, resolvable
  source URLs. Use it to enrich and repair the per-story `sources` array,
  because the model returns fewer sources than it actually read.
- `usage.cost.total_cost` is the real USD cost of the call. Record it.
- Always send `max_output_tokens`. Anthropic models reject requests without it.
- The first call with a new JSON schema can take 10 to 30 seconds. Use a 180
  second httpx timeout. Retry twice with exponential backoff on timeout, 429 and
  5xx. Never retry a 400.
- Optional schema fields can come back as JSON null, so every field the pipeline
  depends on must appear in the schema `required` array.
- The model emits raw ticker forms such as `^NSEI` and `RELIANCE.NS`. Symbol
  normalization is the pipeline's job, per section 4.

Model id lives in config as `PERPLEXITY_MODEL`, default `perplexity/sonar`.

### Story extraction schema (agent B2)

Each story object requires exactly these keys: `headline`, `summary`,
`why_it_matters`, `category`, `sentiment`, `impact`, `impact_direction`,
`is_breaking`, `symbols`, `indices`, `topics`, `published_at`, `sources`
(array of `{publisher, title, url, published_at}`) and `impact_map`
(array of `{name, direction}`).

The instructions text must state:

- Summary is 50 to 80 words, plain declarative sentences, no marketing tone,
  no emoji, no em dashes or en dashes.
- `why_it_matters` is one or two sentences on the read-through for Indian
  markets specifically.
- Only stories published in the last 24 hours.
- `category` must be one of the fixed lowercase keys, never `all`.
- Symbols follow the canonical rules in section 4.
- Impact fields are AI assessments, not trading advice.

---

## 7. Deduplication (agent B2, `dedupe.py`)

Pure Python. No vector database, no external service, no extra dependency.

1. Normalize the headline: lowercase, strip punctuation, drop stopwords
   (`the a an of in on for to at by is are as with from its it after amid over
   said says`), and expand a small alias map (`ril` to `reliance`, `sbi` to
   `statebank`, `rbi` to `reservebank`, `pct` and `%` to `percent`). Keep
   quarter tokens such as `q1`.
2. `dedupe_key` is the sha1 of the sorted normalized token set, first 16 hex
   characters. An exact key match is an immediate merge.
3. Otherwise score against candidates from the last 48 hours:
   `score = 0.55 * jaccard(headline_tokens) + 0.25 * symbol_overlap + 0.20 * domain_overlap`
   `symbol_overlap` is Jaccard over symbol sets, and two empty sets score 0.0,
   not 1.0. `domain_overlap` is Jaccard over source hostnames, same rule.
4. Merge when `score >= 0.62`. On merge: keep the earliest `published_at`, union
   sources, symbols, topics and impact map, set `source_count` to the distinct
   source-domain count, prefer the longer `why_it_matters`, keep the higher
   `impact`, and keep the existing `id` and `story_cluster_id`.
5. `story_cluster_id` is the `dedupe_key` of the first article in the cluster.

`SIMILARITY_THRESHOLD` and `DEDUPE_WINDOW_HOURS` are module-level constants.

`test_dedupe.py` must cover: an exact duplicate merging, the four Reliance
earnings paraphrases from the MVP spec collapsing to one cluster, and two
genuinely different stories staying separate.

## 8. Importance score (agent B2, `score.py`)

Deterministic, 0 to 100, computed in Python. Never trust a score from the model.

```
base           = impact weight: high 40, medium 25, low 12
+ sources      = min(distinct_source_domains, 6) * 3
+ credibility  = best publisher tier: tier1 12, tier2 8, tier3 4
+ breaking     = 12 when is_breaking
+ index_rel    = 10 when NIFTY, BANKNIFTY or SENSEX is tagged
+ category     = rbi 8, sebi 6, earnings 6, economy 5, stocks 4, else 0
- decay        = age_hours * 1.5, capped at 30
```

Clamp to 0 to 100 and round to an int.

Tier 1 publisher hosts contain: `reuters`, `bloomberg`, `rbi.org.in`,
`sebi.gov.in`, `nseindia`, `bseindia`, `ft.com`, `wsj.com`.
Tier 2 contain: `economictimes`, `moneycontrol`, `business-standard`,
`livemint`, `mint`, `cnbctv18`, `thehindubusinessline`, `financialexpress`,
`cnbc`, `ndtvprofit`. Everything else is tier 3.

The score is recomputed on merge and by a periodic rescore pass so the feed
decays. `test_score.py` must assert that adding sources never lowers the score
and that an older article scores below an otherwise identical newer one.

## 9. Scheduler and query set (agent B2)

`queries.py` exposes a list of `{key, label, prompt, category_hint}`:

```
india_markets   Indian stock market breaking news today NSE BSE Sensex Nifty
corporate       NSE BSE Indian corporate announcements board meetings deals
rbi             RBI monetary policy repo rate liquidity banking regulation India
sebi            SEBI regulation enforcement IPO approval market rules India
earnings        Indian company quarterly results earnings today profit revenue
global          global markets news US Europe Asia equities today
fed             US Federal Reserve interest rates inflation data
commodities     crude oil gold silver commodity prices today
geopolitics     geopolitical events affecting global markets today
```

Config defaults, all overridable from env:

- `INGEST_INTERVAL_MINUTES` default 15
- `INGEST_QUERIES_PER_CYCLE` default 4, rotating so all nine are covered in
  roughly 35 minutes
- `INGEST_ENABLED` default true
- `INGEST_MAX_STORIES_PER_QUERY` default 6
- `INGEST_CONCURRENCY` default 3
- `RESCORE_INTERVAL_MINUTES` default 30

One query costs roughly 0.006 USD. Write the per-run cost from
`usage.cost.total_cost` into `ingest_runs.cost_usd` and expose it on
`/api/admin/runs`. The scheduler starts and stops inside the FastAPI lifespan
and must shut down cleanly.

`uv run python -m app.pipeline.ingest --once` runs a single full cycle from the
command line for seeding, printing a per-query summary and the total cost.
It must accept `--queries india_markets,rbi` and `--limit N`.

---

## 10. Design system (agents F1, F2, F3)

Dark-first, editorial, Swiss minimal. Direction taken from the local
`ui-ux-pro-max` design intelligence for a news and finance product.

Fonts, loaded from Google Fonts in `index.html` with `preconnect`:

- Headlines: **Newsreader**, weights 400 500 600 700
- UI and body: **Roboto**, weights 300 400 500 700
- Numbers and tickers: `font-variant-numeric: tabular-nums`

Tokens are CSS custom properties in `index.css`. Dark is the default. Light
applies under `[data-theme="light"]`, and the initial value follows
`prefers-color-scheme` unless the user has chosen one, stored in `localStorage`
under `finbit.theme`.

Dark:
```
--bg #0F172A   --card #111827   --fg #F8FAFC   --muted #1E293B
--muted-fg #CBD5E1   --border #334155   --accent #1E40AF   --on-accent #FFFFFF
--breaking #DC2626   --on-breaking #FFFFFF
--bull #22C55E   --bear #EF4444   --flat #94A3B8
```
Light:
```
--bg #FFFFFF   --card #FFFFFF   --fg #0F172A   --muted #F1F5F9
--muted-fg #475569   --border #E2E8F0   --accent #1D4ED8   --on-accent #FFFFFF
--breaking #DC2626   --on-breaking #FFFFFF
--bull #16A34A   --bear #DC2626   --flat #64748B
```

Semantic mapping: `bull` for positive and bullish, `bear` for negative and
bearish, `flat` for neutral. `mixed` renders as a split bull/bear chip, never a
new hue.

Tailwind CSS v4: `@import "tailwindcss";` plus an `@theme` block mapping the
custom properties to Tailwind color names, so components use `bg-card`,
`text-muted-fg`, `border-border`, `text-bull` and so on. No raw hex in any
component file.

Layout is mobile-first. The feed column is capped at 480px and centered on
desktop while the app chrome is full bleed. Verify at 375, 768, 1024 and 1440.

Non-negotiable interface rules, which the review agent will enforce against the
Vercel Web Interface Guidelines:

- Every interactive element is a real `<button>` or `<a>`, never `<div onClick>`.
- Icon-only buttons carry `aria-label`. Decorative SVGs carry `aria-hidden="true"`.
- Visible `:focus-visible` ring on everything focusable. Never bare `outline: none`.
- Minimum 44 by 44 px touch targets.
- Honor `prefers-reduced-motion`. Animate only `transform` and `opacity`.
  Never `transition: all`.
- Async state changes announce through `aria-live="polite"`.
- Body text contrast is at least 4.5:1 in both themes.
- Inline SVG icons only. No icon library dependency, no emoji.
- Never call `alert`, `confirm` or `prompt`.

Copy rules, which apply to code, comments and UI text alike: no emoji, and no em
dashes or en dashes. Use commas, colons, parentheses or full stops instead.
Plain hyphens inside compound words are fine.

The impact section is always labelled **Market Impact** and carries the line
"AI assessment, not investment advice" in the sources sheet. Never present it as
a trading signal.

---

## 11. Frontend behavior and frozen component props

Three screens plus a shell: Feed, Search, Saved. Bottom nav on mobile, header nav
on desktop. Routing is a `useState` screen switch in `App.tsx` mirrored to
`location.hash` (`#/feed`, `#/search`, `#/saved`) so refresh and browser back
work. No router dependency.

State: no Redux, no react-query. `useState` and `useEffect` plus small hooks in
`src/lib`. Bookmarked ids live in one `BookmarksProvider` context so Feed,
Search and Saved stay in sync.

Feed:
- Vertical one-card-per-viewport snap feed, `scroll-snap-type: y mandatory`.
- Category tabs are a horizontally scrollable tablist with proper roles and
  arrow-key navigation.
- Market quick filter chips sit under the tabs and are toggles.
- Infinite scroll through an `IntersectionObserver` sentinel using `next_cursor`.
- A refresh button in the header, not pull-to-refresh.
- Keyboard navigation: ArrowUp, ArrowDown, PageUp, PageDown, Home, plus `j` and
  `k`. Show a small key hint on desktop only.
- Card contents: breaking flag, headline, summary, Why it matters, symbol chips,
  Market Impact badge, relative time, `Sources (n)` button, bookmark button.

Search:
- Input debounced 300 ms, `type="search"`, `autocomplete="off"`,
  `spellCheck={false}`, placeholder ending in a single ellipsis character.
- Trending symbol and topic chips from `/api/trending` while the box is empty.
- Results reuse `NewsCard` in compact mode, in a normal scrolling list.

Saved:
- Reads `/api/bookmarks`. Unsave is optimistic with rollback on failure.
- Empty state explains bookmarks are per device with no login needed.

Loading uses skeleton cards, never a bare spinner on first paint. Errors render
inline with a retry button.

Frozen prop types, so F2 and F3 can build in parallel:

```ts
// components/ImpactBadge.tsx  (F3)
export function ImpactBadge(props: {
  impact: Impact;                 // 'high' | 'medium' | 'low'
  direction: ImpactDirection;     // 'bullish' | 'bearish' | 'neutral' | 'mixed'
  className?: string;
}): JSX.Element

// components/SymbolChips.tsx  (F3)
export function SymbolChips(props: {
  symbols: SymbolTag[];
  onSelect?: (symbol: string) => void;
  max?: number;                   // default 6
}): JSX.Element

// components/SourcesSheet.tsx  (F3)
export function SourcesSheet(props: {
  open: boolean;
  onClose: () => void;
  headline: string;
  sources: SourceRef[];
}): JSX.Element

// components/ImpactMap.tsx  (F3)
export function ImpactMap(props: { entries: ImpactEntry[] }): JSX.Element

// components/EmptyState.tsx  (F3)
export function EmptyState(props: {
  title: string;
  body: string;
  action?: { label: string; onClick: () => void };
}): JSX.Element

// components/ErrorState.tsx  (F3)
export function ErrorState(props: { message: string; onRetry: () => void }): JSX.Element

// components/NewsCard.tsx  (F2)
export function NewsCard(props: {
  article: ArticleCard;
  compact?: boolean;              // Search and Saved use compact
  onSelectSymbol?: (symbol: string) => void;
}): JSX.Element
```

Icons come from `components/Icons.tsx` (F1), which exports inline SVG function
components: `IconFeed`, `IconSearch`, `IconBookmark`, `IconBookmarkFilled`,
`IconRefresh`, `IconClose`, `IconExternal`, `IconSun`, `IconMoon`,
`IconChevronRight`, `IconAlert`, `IconTrendUp`, `IconTrendDown`, `IconTrendFlat`.
Each accepts `{ className?: string }` and renders with
`aria-hidden="true" focusable="false"`.

`api/types.ts` (F1) exports: `Category`, `Sentiment`, `Impact`,
`ImpactDirection`, `SymbolKind`, `SymbolTag`, `SourceRef`, `ImpactEntry`,
`ArticleCard`, `FeedResponse`, `SearchResponse`, `TrendingResponse`,
`CategoriesResponse`, `HealthResponse`.

`api/client.ts` (F1) exports: `getFeed`, `getArticle`, `search`, `getTrending`,
`getCategories`, `getBookmarks`, `addBookmark`, `removeBookmark`, `getHealth`,
plus an `ApiError` class carrying `status` and `message`. The base URL comes
from `import.meta.env.VITE_API_BASE` with a fallback of
`http://127.0.0.1:8000`.

---

## 12. Definition of done

- `cd backend` then `uv sync` succeeds.
- `cd backend` then `uv run pytest` passes.
- `cd backend` then `uv run uvicorn app.main:app` serves `/api/health` 200 and
  renders `/docs`.
- `cd frontend` then `npm install` and `npm run build` succeed with zero
  TypeScript errors.
- The app runs against an empty database and shows a real empty state.
- `POST /api/admin/ingest` populates the feed from the live Perplexity API.
- `README.md` covers setup, env vars, run commands, architecture, cost
  expectations and the AI-assessment disclaimer.
