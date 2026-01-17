from __future__ import annotations

from typing import Any, Callable, Dict

PostFn = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def register_face_tools(registry, *, backend_post: PostFn):

    def start_face_record(payload: Dict[str, Any]) -> Dict[str, Any]:
        name = (payload or {}).get("name")
        if not name or not isinstance(name, str):
            return {"ok": False, "error": "name required"}
        return backend_post("start_face_record", {"name": name})

    def update_face_record(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("update_face_record", payload or {})

    def delete_face(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("delete_face", payload or {})

    def list_faces(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("list_faces", payload or {})

    def set_face_only(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("set_face_only", payload or {})

    def reset_face_db(payload: Dict[str, Any]) -> Dict[str, Any]:
        return backend_post("reset_face_db", payload or {})

    registry.register("start_face_record", start_face_record)
    registry.register("update_face_record", update_face_record)
    registry.register("delete_face", delete_face)
    registry.register("list_faces", list_faces)
    registry.register("set_face_only", set_face_only)
    registry.register("reset_face_db", reset_face_db)
