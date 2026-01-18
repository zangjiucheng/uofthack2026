from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, Optional

from .tools.detic_tools import register_detic_tools
from .tools.face_tools import register_face_tools
from .tools.tracking_tools import register_tracking_tools
from .tools.motion_tools import register_motion_tools

PostFn = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def _make_post(base_url_env: str, *, timeout_s: float = 2.0) -> PostFn:
    base = (os.environ.get(base_url_env, "") or "").rstrip("/")
    if not base:
        def _missing(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            return {"ok": False, "error": f"{base_url_env} not set"}
        return _missing

    def post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{base}/{path.lstrip('/')}"
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                body = resp.read().decode("utf-8", errors="replace") or "{}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"HTTP {exc.code}", "detail": detail}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        try:
            obj = json.loads(body)
            # normalize ok/error a bit
            if isinstance(obj, dict):
                if "ok" in obj:
                    return obj
                if "error" in obj:
                    return {"ok": False, "error": obj.get("error")}
                return {"ok": True, **obj}
            return {"ok": True, "result": obj}
        except Exception:
            return {"ok": False, "error": "invalid json response", "raw": body}

    return post


def register_tool_handlers(registry) -> None:
    backend_post = _make_post("APP_BACKEND_REST_URL", timeout_s=2.0)
    pi_post = _make_post("APP_PI_REST_URL", timeout_s=2.0)

    # Use backend REST for motion tools so planner-triggered tools hit the backend service.
    register_motion_tools(registry, pi_post=backend_post)

    register_detic_tools(registry, backend_post=backend_post)
    register_face_tools(registry, backend_post=backend_post)
    register_tracking_tools(registry, backend_post=backend_post)
