from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..embeddings.gemini_embedder import GeminiEmbedder
from ..embeddings.similarity import cosine_similarity
from .kb_store import KbStore


@dataclass
class KbQueryResult:
    found: bool
    label: Optional[str] = None
    entity_id: Optional[int] = None
    score: float = 0.0
    last_seen_ts: Optional[float] = None
    last_seen: Optional[Dict[str, float]] = None
    matched_text: Optional[str] = None  


class KbService:
    """
    High-level KB functions:
    - ingest_detection(kind,label,score,bbox,pose[,aliases])
    - query(kind, q) via embeddings
    - last_seen(kind,label)
    """

    def __init__(self, store: KbStore, embedder: GeminiEmbedder):
        self.store = store
        self.embedder = embedder

    def ingest_detection(
        self,
        *,
        kind: str,
        label: str,
        ts: Optional[float] = None,
        score: Optional[float] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        pose: Optional[Dict[str, float]] = None,
        aliases: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
        dedup_window_s: float = 1.0,
    ) -> int:
        ts = float(ts) if ts is not None else time.time()
        kind = (kind or "").strip()
        label = (label or "").strip()
        if not kind or not label:
            return -1

        # Look up existing entity first
        existing = self.store.get_entity(kind, label)
        recent_seen = False
        if existing and existing.get("last_seen_ts") is not None:
            try:
                last_ts = float(existing["last_seen_ts"])
                recent_seen = (ts - last_ts) < float(dedup_window_s)
            except Exception:
                recent_seen = False

        entity_id = self.store.upsert_entity(kind, label)

        # Store aliases
        if aliases:
            for a in aliases:
                a = (a or "").strip()
                if a:
                    self.store.add_alias(entity_id, a)

        # Only compute / upsert embeddings if not recently seen
        if not recent_seen:
            vec = self.embedder.embed(f"{kind}:{label}")
            if vec:
                self.store.put_embedding(entity_id, f"{kind}:{label}", vec)

            if aliases:
                for a in aliases:
                    a = (a or "").strip()
                    if not a:
                        continue
                    avec = self.embedder.embed(f"{kind}:{a}")
                    if avec:
                        self.store.put_embedding(entity_id, f"{kind}:{a}", avec)

        self.store.update_last_seen(entity_id, ts, pose)
        self.store.add_observation(entity_id, ts, score, bbox, pose, extra=extra)
        return entity_id

    def last_seen(self, *, kind: str, label: str) -> Dict[str, Any]:
        kind = (kind or "").strip()
        label = (label or "").strip()
        if not kind or not label:
            return {"ok": False, "error": "kind and label required"}

        ent = self.store.get_entity(kind, label)
        if not ent:
            return {"ok": True, "found": False}
        return {"ok": True, "found": True, **ent}

    def query(self, *, kind: str, q: str, top_k: int = 1, min_score: float = 0.55) -> Dict[str, Any]:
        kind = (kind or "").strip()
        q = (q or "").strip()
        if not kind:
            return {"ok": False, "error": "kind required"}
        if not q:
            return {"ok": False, "error": "q required"}

        qvec = self.embedder.embed(f"{kind}:{q}")
        if not qvec:
            return {"ok": False, "error": "embedding failed"}

        raw_candidates = self.store.get_embeddings_by_kind(kind)
        scored: List[KbQueryResult] = []

        for c in raw_candidates:
            sim = cosine_similarity(qvec, c["vec"])
            scored.append(
                KbQueryResult(
                    found=True,
                    label=c["label"],
                    entity_id=c["entity_id"],
                    score=float(sim),
                    last_seen_ts=c.get("last_seen_ts"),
                    last_seen=c.get("last_seen"),
                    matched_text=c.get("embed_text"),
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        top_items = scored[: max(1, int(top_k))]

        best = top_items[0] if top_items else None
        if not best or best.score < float(min_score):
            return {
                "ok": True,
                "found": False,
                "best_score": float(best.score) if best else 0.0,
                "candidates": [
                    {
                        "label": c.label,
                        "entity_id": c.entity_id,
                        "score": c.score,
                        "last_seen_ts": c.last_seen_ts,
                        "last_seen": c.last_seen,
                        "matched_text": c.matched_text,
                    }
                    for c in top_items
                ],
            }

        return {
            "ok": True,
            "found": True,
            "label": best.label,
            "entity_id": best.entity_id,
            "score": best.score,
            "last_seen_ts": best.last_seen_ts,
            "last_seen": best.last_seen,
            "matched_text": best.matched_text,
            "candidates": [
                {
                    "label": c.label,
                    "entity_id": c.entity_id,
                    "score": c.score,
                    "last_seen_ts": c.last_seen_ts,
                    "last_seen": c.last_seen,
                    "matched_text": c.matched_text,
                }
                for c in top_items
            ],
        }
