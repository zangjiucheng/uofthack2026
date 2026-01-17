from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .sqlite_cache import SqliteEmbeddingCache

@dataclass(frozen=True)
class GeminiEmbedderConfig:
    api_key: str
    base_url: str
    model: str
    timeout_s: float = 10.0


class GeminiEmbedder:
    """
      POST {base_url}/models/{model}:embedContent?key=...
    """

    def __init__(self, cache: SqliteEmbeddingCache, cfg: Optional[GeminiEmbedderConfig] = None):
        if cfg is None:
            api_key = os.environ.get("APP_GEMINI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY required for embeddings")
            base_url = os.environ.get("APP_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1").rstrip("/")
            model = os.environ.get("APP_GEMINI_EMBED_MODEL", "text-embedding-004")
            timeout_s = float(os.environ.get("GEMINI_EMBED_TIMEOUT_S", "10.0"))
            cfg = GeminiEmbedderConfig(api_key=api_key, base_url=base_url, model=model, timeout_s=timeout_s)

        self.cfg = cfg
        self.cache = cache

    def embed(self, text: str) -> List[float]:
        text = (text or "").strip()
        if not text:
            return []

        cached = self.cache.get(self.cfg.model, text)
        if cached is not None:
            return cached

        vec = self._embed_remote(text)
        self.cache.put(self.cfg.model, text, vec)
        return vec

    def _embed_remote(self, text: str) -> List[float]:
        url = f"{self.cfg.base_url}/models/{self.cfg.model}:embedContent?key={self.cfg.api_key}"
        payload: Dict[str, Any] = {
            "content": {"parts": [{"text": text}]}
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                body = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Gemini embed HTTP {exc.code}: {detail or exc.reason}") from exc
        except Exception as exc:
            raise RuntimeError(f"Gemini embed request failed: {exc}") from exc

        obj = json.loads(body or "{}")
        # Expected: { "embedding": { "values": [...] } }
        emb = obj.get("embedding") or {}
        values = emb.get("values")
        if not isinstance(values, list):
            raise RuntimeError(f"Unexpected embed response: {obj}")
        return [float(x) for x in values]
