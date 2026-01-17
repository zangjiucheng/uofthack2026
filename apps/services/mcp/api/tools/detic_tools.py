from __future__ import annotations

from typing import Any, Callable, Dict

PostFn = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def register_detic_tools(registry, *, backend_post: PostFn):

    def update_detic_objects(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("update_detic_objects", payload or {})

    def trigger_detic(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("trigger_detic", payload or {})

    registry.register("update_detic_objects", update_detic_objects)
    registry.register("trigger_detic", trigger_detic)
