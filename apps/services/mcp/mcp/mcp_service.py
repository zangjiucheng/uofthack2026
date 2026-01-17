from __future__ import annotations

from typing import Dict, Optional

from .executor import McpExecutor
from .run_store import McpRunStore
from ..planner.planner_client import PlannerClient


class McpService:
    def __init__(self, *, store: McpRunStore, executor: McpExecutor, planner: PlannerClient):
        self.store = store
        self.executor = executor
        self.planner = planner

    def plan_and_execute(self, *, transcript: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp = self.planner.plan(transcript=transcript, context=context or {})
        if not resp.get("ok"):
            return resp

        if resp.get("mode") == "chat" or ("plan" not in resp and resp.get("reply")):
            return {"ok": True, "mode": "chat", "reply": resp.get("reply", "")}

        plan = resp.get("plan")
        if not isinstance(plan, dict):
            return {"ok": False, "error": "planner returned invalid plan"}

        initial_state = {"vars": {}, "save": {}, "last": {}, "planner_context": context or {}, "planner_plan": plan}
        run_id = self.executor.execute_plan(plan, initial_state=initial_state)
        return {"ok": True, "mode": resp.get("mode", "plan"), "run_id": run_id, "plan": plan}
