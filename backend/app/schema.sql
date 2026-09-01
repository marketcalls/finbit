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

-- ---------------------------------------------------------------------------
-- Phase 2 additions (CONTRACT_MOBILE_ADMIN.md section 4).
--
-- The ALTER TABLE additions to articles and the idx_articles_visible index are
-- not here on purpose: ALTER TABLE has no IF NOT EXISTS form and this file is
-- executed on every start. app/migrate.py reads PRAGMA table_info(articles)
-- and applies them only when they are missing.
-- ---------------------------------------------------------------------------

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
