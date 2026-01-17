from __future__ import annotations

from typing import Any, Callable, Dict

PostFn = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def register_tracking_tools(registry, *, backend_post: PostFn):

    def start_tracking(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("start_tracking", payload or {})

    def set_tracking_roi(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("set_tracking_roi", payload or {})

    def stop_tracking(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("stop_tracking", payload or {})

    registry.register("start_tracking", start_tracking)
    registry.register("set_tracking_roi", set_tracking_roi)
    registry.register("stop_tracking", stop_tracking)
