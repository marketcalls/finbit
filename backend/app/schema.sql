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
  dedupe_key        TEXT    NOT NULL,
  image_url         TEXT,
  image_source_url  TEXT,
  image_checked_at  TEXT
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
