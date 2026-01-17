from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set

ToolInvoker = Callable[[str, Dict[str, Any]], Dict[str, Any]]

@dataclass(frozen=True)
class ToolSafetyPolicy:

    allow_tools: Optional[Set[str]] = None
    deny_tools: Set[str] = field(default_factory=lambda: {
        "mcp_run", "mcp_execute_plan", "mcp_status", "mcp_cancel",
        "planner_plan", "planner_plan_from_stt",
    })
    deny_prefixes: tuple[str, ...] = ("mcp_", "planner_")

    prevent_same_tool_recursion: bool = True


_thread_local = threading.local()


def _get_callstack() -> list[str]:
    st = getattr(_thread_local, "tool_stack", None)
    if st is None:
        st = []
        _thread_local.tool_stack = st
    return st


def normalize_tool_result(res: Any) -> Dict[str, Any]:
    if not isinstance(res, dict):
        return {"ok": False, "error": "tool returned non-dict"}
    if "ok" in res:
        return res
    if "error" in res:
        return {"ok": False, "error": res.get("error")}
    return {"ok": True, **res}


def make_safe_tool_invoker(
    registry,
    *,
    policy: ToolSafetyPolicy,
) -> ToolInvoker:

    def invoker(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        name = (tool_name or "").strip()
        if not name:
            return {"ok": False, "error": "tool name required"}

        for pfx in policy.deny_prefixes:
            if name.startswith(pfx):
                return {"ok": False, "error": f"tool '{name}' is not allowed"}

        if name in policy.deny_tools:
            return {"ok": False, "error": f"tool '{name}' is not allowed"}

        if policy.allow_tools is not None and name not in policy.allow_tools:
            return {"ok": False, "error": f"tool '{name}' not in allowlist"}

        stack = _get_callstack()
        if policy.prevent_same_tool_recursion and name in stack:
            return {"ok": False, "error": f"tool recursion blocked for '{name}'"}

        stack.append(name)
        try:
            out = registry.dispatch(name, args or {})
            return normalize_tool_result(out)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            stack.pop()

    return invoker


def compute_allow_tools_from_registry(registry) -> Set[str]:
    handlers = getattr(registry, "_handlers", {})
    if isinstance(handlers, dict):
        return set(handlers.keys())
    return set()
