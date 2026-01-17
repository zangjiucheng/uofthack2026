from __future__ import annotations

from typing import Any, Dict, List

from .resolver import resolve_value


def _truthy(x: Any) -> bool:
    return bool(x)


def eval_cond(cond: Dict[str, Any], state: Dict[str, Any]) -> bool:
    """
    Supported:
      {"op":"==","left":..., "right":...}
      {"op":"and","conds":[cond1, cond2, ...]}
      {"op":"or","conds":[...]}
      {"op":"not","cond": cond1}
      {"op":"exists","value": ...}
    Values can be "$vars.x", "$kb.found", etc.
    """
    if not isinstance(cond, dict):
        return False

    op = cond.get("op")
    if not isinstance(op, str):
        return False

    op = op.strip().lower()

    if op == "and":
        conds = cond.get("conds")
        if not isinstance(conds, list):
            # allow legacy: left/right as conditions
            left = cond.get("left")
            right = cond.get("right")
            return _truthy(eval_cond(left, state)) and _truthy(eval_cond(right, state))  # type: ignore
        return all(eval_cond(c, state) for c in conds if isinstance(c, dict))

    if op == "or":
        conds = cond.get("conds")
        if not isinstance(conds, list):
            left = cond.get("left")
            right = cond.get("right")
            return _truthy(eval_cond(left, state)) or _truthy(eval_cond(right, state))  # type: ignore
        return any(eval_cond(c, state) for c in conds if isinstance(c, dict))

    if op == "not":
        inner = cond.get("cond")
        if not isinstance(inner, dict):
            return False
        return not eval_cond(inner, state)

    if op == "exists":
        val = resolve_value(cond.get("value"), state)
        return val is not None

    # comparisons
    left = resolve_value(cond.get("left"), state)
    right = resolve_value(cond.get("right"), state)

    try:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return float(left) > float(right)
        if op == ">=":
            return float(left) >= float(right)
        if op == "<":
            return float(left) < float(right)
        if op == "<=":
            return float(left) <= float(right)
    except Exception:
        return False

    return False
