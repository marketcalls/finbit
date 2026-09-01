# FinBit

An Inshorts-style financial news app for Indian market traders. Every card is a
headline, a sixty word summary, the tickers it touches, an impact call and the
real sources behind it.

Stack: FastAPI plus SQLite on the backend (uv managed), React plus Vite plus
TypeScript plus Tailwind CSS v4 on the frontend, and the Perplexity Agent API
for news discovery.

Impact and sentiment on every card are AI assessments, not investment advice.

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

The API is read only apart from bookmarks and the admin ingest trigger. The
frontend is three screens over plain hash routing with no router dependency, and
there is no login: the browser generates one UUID, keeps it in `localStorage`
and sends it as `X-Device-Id`, which is the only thing that owns saved stories.

A picture walkthrough of the same architecture is published as an artifact:
<https://claude.ai/code/artifact/8df6818a-4272-4a52-a31b-568da0b515f9>

---

## Requirements

- Python 3.12 or newer, driven by [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer
- A Perplexity API key, optional for browsing cached articles

---

## Setup

Copy the environment template and add your key. The `.env` file lives at the
repo root and is git-ignored.

```
cp .env.example .env
```

Backend, run from `backend/`:

```
uv sync
```

Frontend, run from `frontend/`:

```
npm install
```

---

## Running

Two terminals.

Backend, from `backend/`:

```
uv run uvicorn app.main:app --reload
```

The API serves on <http://127.0.0.1:8000> with interactive documentation at
`/docs`. Startup creates the schema if needed, starts the background scheduler
and, when the database is empty or stale, fires one seeding cycle.

Frontend, from `frontend/`:

```
npm run dev
```

The app serves on <http://localhost:5173> and reads the API base from
`frontend/.env.development`.

---

## Ingesting on demand

The pipeline has a command line, run from `backend/`:

```
uv run python -m app.pipeline.ingest --once
uv run python -m app.pipeline.ingest --queries india_markets,rbi --limit 3
uv run python -m app.pipeline.ingest --rescore
uv run python -m app.pipeline.ingest --images
```

`--rescore` and `--images` never call Perplexity, so they cost nothing.

---

## Tests

From `backend/`:

```
uv run pytest
```

The suite covers the API surface, the dedupe scoring, the importance formula and
Open Graph extraction over saved HTML. Nothing in it hits the network.

---

## Configuration

Every value is read from the repo root `.env`, or from real environment
variables, which win over the file. See `.env.example` for the annotated list.
The ones worth knowing:

| Variable | Default | What it does |
| --- | --- | --- |
| `PERPLEXITY_API_KEY` | empty | Required for ingestion only. The API starts and serves cached articles without it. |
| `PERPLEXITY_MODEL` | `perplexity/sonar` | Model id used for story discovery. |
| `DB_PATH` | `finbit.db` | SQLite file. A relative path resolves against `backend/`. |
| `CORS_ORIGINS` | the two Vite dev origins | Comma separated list of allowed browser origins. |
| `INGEST_ENABLED` | `true` | Set false to run the API on cached articles only. |
| `INGEST_INTERVAL_MINUTES` | `15` | How often a fetch cycle runs. |
| `INGEST_QUERIES_PER_CYCLE` | `4` | How many of the nine queries each cycle asks. |
| `INGEST_CONCURRENCY` | `1` | Keep at 1. The live account answers `x-ratelimit-limit: 1`. |
| `RESCORE_INTERVAL_MINUTES` | `30` | How often stored articles are rescored so the feed decays. |

Cost note: one query is roughly 0.006 USD. The defaults are about sixteen
queries an hour, close to 0.10 USD an hour. Lower `INGEST_QUERIES_PER_CYCLE` or
raise `INGEST_INTERVAL_MINUTES` to spend less. The real cost of every call is
recorded on the `ingest_runs` row and is visible at `GET /api/admin/runs`.

---

## API

All routes are prefixed with `/api`.

| Route | Purpose |
| --- | --- |
| `GET /health` | Article count, last ingest time and status, and why ingestion is unavailable if it is. |
| `GET /feed` | Cursor paginated cards, sorted by `top` or `latest`, filterable by category and market. |
| `GET /articles/{id}` | One card in full. |
| `GET /search` | Full text search across headlines, summaries, tickers and topics. |
| `GET /trending` | Recurring tickers and topics. |
| `GET /categories` | The ten category tabs with counts, plus the six market filters. |
| `GET /bookmarks` | Saved articles for the calling device. |
| `POST /bookmarks` | Save an article. |
| `DELETE /bookmarks/{article_id}` | Remove a saved article. |
| `POST /admin/ingest` | Trigger one cycle without waiting for the timer. |
| `GET /admin/runs` | Recent ingest runs with counts and cost. |

Every request carries an `X-Device-Id` header. Responses carry an
`X-Response-Time-Ms` header.

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

---

## Layout

```
finbit/
  .env.example                  environment template
  CONTRACT.md                   the build contract, single source of truth
  backend/
    pyproject.toml              uv project, no requirements.txt
    app/
      main.py                   FastAPI app, lifespan, middleware
      config.py                 settings, never raises on a missing key
      models.py                 Pydantic models and the fixed vocabularies
      db.py, repo.py            connection handling and every SQL statement
      schema.sql                tables, indexes and the FTS5 index
      routers/                  feed, search, bookmarks, meta
      pipeline/                 queries, perplexity, extract, dedupe, score,
                                images, ingest, scheduler
    tests/                      pytest suite, no network
  frontend/
    src/
      api/                      typed fetch client and response types
      components/               app shell, cards, tabs, filters, states
      screens/                  feed, search, saved
      lib/                      device id, bookmarks, formatting, theme
```

---

## License

MIT. See [LICENSE](LICENSE).
