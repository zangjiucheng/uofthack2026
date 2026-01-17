from __future__ import annotations

from typing import Any, Callable, Dict

PostFn = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def register_motion_tools(registry, *, pi_post: PostFn):

    def approach_object(payload: Dict[str, Any]) -> Dict[str, Any]:
        obj = (payload or {}).get("object")
        if not obj or not isinstance(obj, str):
            return {"ok": False, "error": "object (str) required"}
        return pi_post("approach_object", {"object": obj})

    def approach_person(payload: Dict[str, Any]) -> Dict[str, Any]:
        name = (payload or {}).get("name")
        if not name or not isinstance(name, str):
            return {"ok": False, "error": "name (str) required"}
        return pi_post("approach_person", {"name": name})

    registry.register("approach_object", approach_object)
    registry.register("approach_person", approach_person)
