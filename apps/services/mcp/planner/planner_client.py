from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class PlannerClientConfig:
    base_url: str
    token: str = ""
    timeout_s: float = 5.0


class PlannerClient:
    def __init__(self, cfg: Optional[PlannerClientConfig] = None):
        if cfg is None:
            base_url = (
                os.environ.get("APP_PLANNER_URL")
            ).rstrip("/")

            # Allow host+port config too
            if not base_url:
                host = os.environ.get("APP_PLANNER_HOST", "http://127.0.0.1").rstrip("/")
                port = os.environ.get("APP_PLANNER_PORT", "").strip()
                if port:
                    base_url = f"{host}:{port}".rstrip("/")

            token = (
                os.environ.get("APP_PLANNER_TOKEN")
            ).strip()

            timeout_s = float(os.environ.get("APP_PLANNER_TIMEOUT_S", "5.0"))
            cfg = PlannerClientConfig(base_url=base_url, token=token, timeout_s=timeout_s)

        self.cfg = cfg

    def plan(
        self,
        *,
        transcript: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.cfg.base_url:
            return {"ok": False, "error": "Planner URL not set (APP_PLANNER_URL / PLANNER_URL / PLANNER_HOST+PLANNER_PORT)"}

        transcript = (transcript or "").strip()
        if not transcript:
            return {"ok": False, "error": "transcript required"}

        payload: Dict[str, Any] = {"transcript": transcript, "context": context or {}}

        url = f"{self.cfg.base_url}/plan"
        data = json.dumps(payload).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.cfg.token:
            headers["X-Planner-Token"] = self.cfg.token

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                body = resp.read().decode(charset, errors="replace") or "{}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"planner HTTP {exc.code}", "detail": detail}
        except Exception as exc:
            return {"ok": False, "error": f"planner request failed: {exc}"}

        try:
            return json.loads(body)
        except Exception:
            return {"ok": False, "error": "invalid planner response json", "raw": body}
