from __future__ import annotations

import json
import sqlite3
import threading
import time
import os
from typing import Any, Dict, List, Optional, Tuple

from .kb_schema import KB_SCHEMA_SQL


class KbStore:

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        if self.db_path:
            parent = os.path.dirname(os.path.abspath(self.db_path))
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                # Base schema
                conn.executescript(KB_SCHEMA_SQL)

                # Ensure uniqueness for embedding upserts
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_embeddings_unique
                    ON entity_embeddings(entity_id, text)
                    """
                )

                # Helpful index for query/list
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_entities_kind_last_seen
                    ON entities(kind, last_seen_ts)
                    """
                )

                conn.commit()
            finally:
                conn.close()

    def upsert_entity(self, kind: str, label: str) -> int:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO entities(kind, label, created_ts)
                    VALUES(?,?,?)
                    ON CONFLICT(kind, label) DO NOTHING
                    """,
                    (kind, label, now),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT entity_id FROM entities WHERE kind=? AND label=?",
                    (kind, label),
                ).fetchone()
                return int(row[0])
            finally:
                conn.close()

    def add_alias(self, entity_id: int, alias: str) -> None:
        alias = (alias or "").strip()
        if not alias:
            return
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO entity_aliases(entity_id, alias) VALUES(?,?)",
                    (entity_id, alias),
                )
                conn.commit()
            finally:
                conn.close()

    def put_embedding(self, entity_id: int, text: str, vec: List[float]) -> None:
        """
        Upsert embedding for (entity_id, text).
        Requires unique index on (entity_id, text) which _init_db ensures.
        """
        now = time.time()
        vec_json = json.dumps(vec)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO entity_embeddings(entity_id, text, vec_json, ts)
                    VALUES(?,?,?,?)
                    ON CONFLICT(entity_id, text) DO UPDATE SET
                      vec_json=excluded.vec_json,
                      ts=excluded.ts
                    """,
                    (entity_id, text, vec_json, now),
                )
                conn.commit()
            finally:
                conn.close()

    def get_embeddings_by_kind(self, kind: str) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT e.entity_id,
                           e.label,
                           e.last_seen_ts,
                           e.last_seen_x, e.last_seen_y, e.last_seen_heading,
                           em.text, em.vec_json
                    FROM entities e
                    JOIN entity_embeddings em ON em.entity_id = e.entity_id
                    WHERE e.kind = ?
                    """,
                    (kind,),
                ).fetchall()

                out: List[Dict[str, Any]] = []
                for r in rows:
                    out.append(
                        {
                            "entity_id": int(r[0]),
                            "label": r[1],
                            "last_seen_ts": r[2],
                            "last_seen": {"x": r[3], "y": r[4], "heading": r[5]},
                            "embed_text": r[6],
                            "vec": json.loads(r[7]),
                        }
                    )
                return out
            finally:
                conn.close()

    def update_last_seen(self, entity_id: int, ts: float, pose: Optional[Dict[str, float]]) -> None:
        x = y = h = None
        if pose:
            x = pose.get("x")
            y = pose.get("y")
            h = pose.get("heading")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE entities
                    SET last_seen_ts=?, last_seen_x=?, last_seen_y=?, last_seen_heading=?
                    WHERE entity_id=?
                    """,
                    (ts, x, y, h, entity_id),
                )
                conn.commit()
            finally:
                conn.close()

    def add_observation(
        self,
        entity_id: int,
        ts: float,
        score: Optional[float],
        bbox: Optional[Tuple[float, float, float, float]],
        pose: Optional[Dict[str, float]],
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        bbox_json = json.dumps(bbox) if bbox is not None else None
        extra_json = json.dumps(extra or {})
        x = y = h = None
        if pose:
            x = pose.get("x")
            y = pose.get("y")
            h = pose.get("heading")

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO observations(entity_id, ts, score, bbox_json, x, y, heading, extra_json)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (entity_id, ts, score, bbox_json, x, y, h, extra_json),
                )
                conn.commit()
            finally:
                conn.close()

    def get_entity(self, kind: str, label: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT entity_id, label, last_seen_ts, last_seen_x, last_seen_y, last_seen_heading
                    FROM entities
                    WHERE kind=? AND label=?
                    """,
                    (kind, label),
                ).fetchone()
                if not row:
                    return None
                return {
                    "entity_id": int(row[0]),
                    "label": row[1],
                    "last_seen_ts": row[2],
                    "last_seen": {"x": row[3], "y": row[4], "heading": row[5]},
                }
            finally:
                conn.close()

    def list_entities(self, kind: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Uses a SQLite-friendly ordering to emulate "NULLS LAST":
          ORDER BY (last_seen_ts IS NULL), last_seen_ts DESC
        """
        with self._lock:
            conn = self._connect()
            try:
                if kind:
                    rows = conn.execute(
                        """
                        SELECT entity_id, kind, label, last_seen_ts, last_seen_x, last_seen_y, last_seen_heading
                        FROM entities
                        WHERE kind=?
                        ORDER BY (last_seen_ts IS NULL) ASC, last_seen_ts DESC
                        LIMIT ?
                        """,
                        (kind, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT entity_id, kind, label, last_seen_ts, last_seen_x, last_seen_y, last_seen_heading
                        FROM entities
                        ORDER BY (last_seen_ts IS NULL) ASC, last_seen_ts DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()

                out: List[Dict[str, Any]] = []
                for r in rows:
                    out.append(
                        {
                            "entity_id": int(r[0]),
                            "kind": r[1],
                            "label": r[2],
                            "last_seen_ts": r[3],
                            "last_seen": {"x": r[4], "y": r[5], "heading": r[6]},
                        }
                    )
                return out
            finally:
                conn.close()
