from __future__ import annotations

import json
import sqlite3
import threading
import time
import os
from typing import List, Optional


class SqliteEmbeddingCache:
    """
    Persistent on-disk cache:
      key = f"{model}:{text}"
      value = embedding vector (json list[float])
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        if self.db_path:
            parent = os.path.dirname(os.path.abspath(self.db_path))
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS embedding_cache (
                        key TEXT PRIMARY KEY,
                        model TEXT NOT NULL,
                        text TEXT NOT NULL,
                        vec_json TEXT NOT NULL,
                        ts REAL NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_embedding_model ON embedding_cache(model)")
                conn.commit()
            finally:
                conn.close()

    def get(self, model: str, text: str) -> Optional[List[float]]:
        key = f"{model}:{text}"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT vec_json FROM embedding_cache WHERE key=?",
                    (key,),
                ).fetchone()
                if not row:
                    return None
                return json.loads(row[0])
            finally:
                conn.close()

    def put(self, model: str, text: str, vec: List[float]) -> None:
        key = f"{model}:{text}"
        vec_json = json.dumps(vec)
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO embedding_cache(key, model, text, vec_json, ts)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET
                      vec_json=excluded.vec_json,
                      ts=excluded.ts
                    """,
                    (key, model, text, vec_json, now),
                )
                conn.commit()
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM embedding_cache")
                conn.commit()
            finally:
                conn.close()
