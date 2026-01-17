# planner_service/validate.py
from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple


VALID_GOALS = {"FIND_OBJECT", "FIND_PERSON", "ENROLL_PERSON"}
VALID_ON_FAIL = {"stop", "continue"}


def validate_plan(plan: Dict[str, Any], allowed_tools: Set[str]) -> Tuple[bool, str]:
    if not isinstance(plan, dict):
        return False, "plan must be an object"

    if plan.get("version") != "mcp.plan.v1":
        return False, "missing or invalid version (expected 'mcp.plan.v1')"

    if plan.get("goal_type") not in VALID_GOALS:
        return False, "invalid or missing goal_type"

    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) < 1:
        return False, "steps must be a non-empty array"

    ok, err = _validate_steps(steps, allowed_tools, path="steps")
    if not ok:
        return False, err

    return True, ""


def _validate_steps(steps: List[Any], allowed_tools: Set[str], path: str) -> Tuple[bool, str]:
    for i, step in enumerate(steps):
        p = f"{path}[{i}]"
        if not isinstance(step, dict):
            return False, f"{p} must be an object"

        stype = (step.get("type") or "").strip().lower()
        if stype == "tool":
            ok, err = _validate_tool_step(step, allowed_tools, p)
            if not ok:
                return False, err

        elif stype == "set":
            var = step.get("var")
            if not isinstance(var, str) or not var.strip():
                return False, f"{p}: set step missing var"
            # value can be anything, including "$vars.x"
            # no further validation needed

        elif stype == "if":
            cond = step.get("cond")
            if not isinstance(cond, dict):
                return False, f"{p}: if step missing cond"
            then_steps = step.get("then")
            else_steps = step.get("else")
            if not isinstance(then_steps, list) or not isinstance(else_steps, list):
                return False, f"{p}: if then/else must be arrays"
            ok, err = _validate_steps(then_steps, allowed_tools, f"{p}.then")
            if not ok:
                return False, err
            ok, err = _validate_steps(else_steps, allowed_tools, f"{p}.else")
            if not ok:
                return False, err

        elif stype == "wait":
            cond = step.get("cond")
            if not isinstance(cond, dict):
                return False, f"{p}: wait step missing cond"
            tick = step.get("tick", [])
            refresh = step.get("refresh", [])
            if tick is not None and not isinstance(tick, list):
                return False, f"{p}: wait.tick must be an array"
            if refresh is not None and not isinstance(refresh, list):
                return False, f"{p}: wait.refresh must be an array"
            if isinstance(tick, list):
                ok, err = _validate_steps(tick, allowed_tools, f"{p}.tick")
                if not ok:
                    return False, err
            if isinstance(refresh, list):
                ok, err = _validate_steps(refresh, allowed_tools, f"{p}.refresh")
                if not ok:
                    return False, err

        else:
            return False, f"{p}: unknown step type '{stype}'"

    return True, ""


def _validate_tool_step(step: Dict[str, Any], allowed_tools: Set[str], path: str) -> Tuple[bool, str]:
    name = step.get("name")
    if not isinstance(name, str) or not name.strip():
        return False, f"{path}: tool step missing name"
    name = name.strip()
    if name not in allowed_tools:
        return False, f"{path}: tool '{name}' not in allowed tools"

    args = step.get("args", {})
    if args is None:
        step["args"] = {}
    elif not isinstance(args, dict):
        return False, f"{path}: tool args must be an object"

    on_fail = step.get("on_fail")
    if on_fail is not None:
        if not isinstance(on_fail, str) or on_fail.strip().lower() not in VALID_ON_FAIL:
            return False, f"{path}: on_fail must be 'stop' or 'continue'"

    fb = step.get("fallback")
    if fb is not None and not isinstance(fb, list):
        return False, f"{path}: fallback must be an array"
    
    if isinstance(fb, list):
        ok, err = _validate_steps(fb, allowed_tools, f"{path}.fallback")
        if not ok:
            return False, err

    return True, ""
