from __future__ import annotations

from typing import Any, Dict


def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except Exception:
                return None
        else:
            return None
    return cur


def resolve_ref(ref: str, state: Dict[str, Any]) -> Any:
    """
    Supports:
      $vars.x
      $last.x
      $kb.found          
      $some_save_key.field
    """
    if not ref.startswith("$"):
        return ref

    token = ref[1:]
    if token.startswith("vars."):
        return _get_path(state.get("vars", {}), token.removeprefix("vars."))
    if token.startswith("last."):
        return _get_path(state.get("last", {}), token.removeprefix("last."))

    # default: "$<save_key>.<path>"
    dot = token.find(".")
    if dot == -1:
        # "$kb" returns the whole saved object if present
        return state.get("save", {}).get(token)
    save_key = token[:dot]
    tail = token[dot + 1 :]
    saved = state.get("save", {}).get(save_key, {})
    return _get_path(saved, tail)


def resolve_value(v: Any, state: Dict[str, Any]) -> Any:
    if isinstance(v, str) and v.startswith("$"):
        return resolve_ref(v, state)
    return v


def resolve_args(args: Any, state: Dict[str, Any]) -> Any:
    if isinstance(args, dict):
        return {k: resolve_args(v, state) for k, v in args.items()}
    if isinstance(args, list):
        return [resolve_args(x, state) for x in args]
    return resolve_value(args, state)
