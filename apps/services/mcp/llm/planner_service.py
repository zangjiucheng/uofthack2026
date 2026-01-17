from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import threading
from typing import Any, Dict, List, Set, Tuple

from .agent import Agent
from .json_utils import try_parse_json
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .validate import validate_plan
from ..planner.mcp_tools import DEFAULT_PLANNER_TOOLS


def _normalize_tools(tools: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Returns (tool_defs, tool_names).
    Accepts:
      - ["toolA","toolB"]
      - [{"name":"toolA", "description":..., "args_schema":...}, ...]
    """
    if tools is None:
        return [], []
    if not isinstance(tools, list):
        return [], []

    out_defs: List[Dict[str, Any]] = []
    out_names: List[str] = []

    for t in tools:
        if isinstance(t, str) and t.strip():
            name = t.strip()
            out_names.append(name)
            out_defs.append({"name": name})
        elif isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip():
            name = t["name"].strip()
            out_names.append(name)
            out_defs.append({k: t[k] for k in t.keys()})
    return out_defs, out_names


def start_planner_service(host: str = "0.0.0.0", port: int = 8091) -> HTTPServer:
    token = (os.environ.get("PLANNER_TOKEN") or os.environ.get("APP_PLANNER_TOKEN") or "").strip()
    agent = Agent()  
    temperature = float(os.environ.get("PLANNER_TEMPERATURE", "0.0"))

    class Handler(BaseHTTPRequestHandler):
        def _set_cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Planner-Token")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def do_OPTIONS(self): 
            self.send_response(200)
            self._set_cors()
            self.end_headers()

        def _json(self, code: int, obj: Dict[str, Any]):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._set_cors()
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  
            if self.path.rstrip("/") != "/plan":
                return self._json(404, {"ok": False, "error": "not found"})

            if token:
                got = (self.headers.get("X-Planner-Token") or "").strip()
                if got != token:
                    return self._json(401, {"ok": False, "error": "unauthorized"})

            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                payload = {}

            transcript = (payload.get("transcript") or "").strip()
            context = payload.get("context") or {}

            tools_raw = payload.get("tools")
            if tools_raw is None:
                tools_raw = DEFAULT_PLANNER_TOOLS

            tool_defs, tool_names = _normalize_tools(tools_raw)

            if not transcript:
                return self._json(400, {"ok": False, "error": "transcript required"})

            allowed_tools: Set[str] = set(tool_names)

            user_prompt = build_user_prompt(
                transcript,
                context if isinstance(context, dict) else {},
                tool_defs, 
            )

            # 1) call LLM
            llm_resp = agent.respond(user_prompt, system_prompt=SYSTEM_PROMPT, temperature=temperature)
            if llm_resp.text.startswith("[llm:") and "error]" in llm_resp.text:
                return self._json(502, {"ok": False, "error": "llm error", "detail": llm_resp.text})

            # 2) parse JSON
            plan_obj = try_parse_json(llm_resp.text)
            if plan_obj is None:
                strict_prompt = (
                    f"{user_prompt}\n\n"
                    "Return ONLY valid MCP Plan JSON v1. No code fences, no Markdown, no commentary. "
                    "Keep it single JSON object, at least one step. "
                    "Example format:\n"
                    "{\"version\":\"mcp.plan.v1\",\"goal_type\":\"FIND_OBJECT\",\"entities\":{},\"policy\":{},\"vars\":{},"
                    "\"steps\":[{\"type\":\"tool\",\"name\":\"kb_query\",\"args\":{\"kind\":\"object\",\"q\":\"bottle\"}}]}"
                )
                llm_resp = agent.respond(strict_prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0)
                plan_obj = try_parse_json(llm_resp.text)
                if plan_obj is None:
                    return self._json(
                        200,
                        {
                            "ok": False,
                            "error": "planner returned non-json",
                            "raw": llm_resp.text[:800],
                        },
                    )

            # 3) validate plan
            ok, err = validate_plan(plan_obj, allowed_tools)
            if not ok:
                repair_prompt = (
                    "Your previous output failed validation.\n"
                    f"Error: {err}\n\n"
                    "Return ONLY corrected MCP Plan JSON v1 that passes validation. No extra text.\n\n"
                    f"Previous JSON:\n{json.dumps(plan_obj)}"
                )
                llm2 = agent.respond(repair_prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0)
                plan2 = try_parse_json(llm2.text) or plan_obj
                ok2, err2 = validate_plan(plan2, allowed_tools)
                if not ok2:
                    return self._json(200, {"ok": False, "error": f"invalid plan: {err2}", "plan": plan2})

                return self._json(200, {"ok": True, "plan": plan2})

            return self._json(200, {"ok": True, "plan": plan_obj})

        def log_message(self, fmt, *args):  # noqa: ANN001
            return  # silence

    server = HTTPServer((host, port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[planner] HTTP POST on http://{host}:{port}/plan")
    return server
