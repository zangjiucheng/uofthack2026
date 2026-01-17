from __future__ import annotations

KB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entities (
  entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,             -- 'object' | 'person' | 'spot'
  label TEXT NOT NULL,            -- canonical name
  created_ts REAL NOT NULL,
  last_seen_ts REAL,
  last_seen_x REAL,
  last_seen_y REAL,
  last_seen_heading REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_kind_label ON entities(kind, label);

CREATE TABLE IF NOT EXISTS entity_aliases (
  alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id INTEGER NOT NULL,
  alias TEXT NOT NULL,
  FOREIGN KEY(entity_id) REFERENCES entities(entity_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alias_unique ON entity_aliases(entity_id, alias);

-- Embeddings (stored as json list[float] to keep deps minimal)
CREATE TABLE IF NOT EXISTS entity_embeddings (
  embed_id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id INTEGER NOT NULL,
  text TEXT NOT NULL,             -- label or alias
  vec_json TEXT NOT NULL,
  ts REAL NOT NULL,
  FOREIGN KEY(entity_id) REFERENCES entities(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_embeddings_entity ON entity_embeddings(entity_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_embeddings_unique
ON entity_embeddings(entity_id, text);

CREATE TABLE IF NOT EXISTS observations (
  obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id INTEGER NOT NULL,
  ts REAL NOT NULL,
  score REAL,
  bbox_json TEXT,                 -- optional
  x REAL, y REAL, heading REAL,   -- optional pose
  extra_json TEXT,
  FOREIGN KEY(entity_id) REFERENCES entities(entity_id)
);

CREATE INDEX IF NOT EXISTS idx_observations_entity_ts ON observations(entity_id, ts);
"""
