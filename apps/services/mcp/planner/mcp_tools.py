from __future__ import annotations
from typing import Any, Dict, List

DEFAULT_PLANNER_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "kb_query",
        "description": "Semantic search the local KB for objects/people by query text. Returns best match and candidates list (top_k).",
        "args_schema": {"kind": "object|person", "q": "string", "top_k": "int?", "min_score": "float?"},
        "example": {"kind": "object", "q": "bottle", "top_k": 3, "min_score": 0.55},
    },
    {
        "name": "kb_last_seen",
        "description": "Get last-known observation for an entity label (object/person). Returns pose if available.",
        "args_schema": {"kind": "object|person", "label": "string"},
        "example": {"kind": "object", "label": "bottle"},
    },
    {
        "name": "update_detic_objects",
        "description": "Update Detic detection target list and thresholds.",
        "args_schema": {"object_list": "list[str]|comma_string", "vocabulary": "string?", "score_threshold": "float?"},
        "example": {"object_list": "bottle,chair", "vocabulary": "lvis", "score_threshold": 0.3},
    },
    {
        "name": "trigger_detic",
        "description": "Queue one Detic inference immediately (best-effort).",
        "args_schema": {},
        "example": {},
    },
    {
        "name": "approach_object",
        "description": "Command robot to move toward an object label (pi-side). Use after KB hit or detection.",
        "args_schema": {"object": "string"},
        "example": {"object": "bottle"},
    },
    {
        "name": "approach_person",
        "description": "Command robot to move toward a known person name (pi-side).",
        "args_schema": {"name": "string"},
        "example": {"name": "Tim"},
    },
    {
        "name": "start_face_record",
        "description": "Begin face enrollment for a person name. Use for ENROLL_PERSON goal_type.",
        "args_schema": {"name": "string"},
        "example": {"name": "Tim"},
    },
    {
        "name": "set_face_only",
        "description": "Enable/disable face-only mode if supported by backend pipeline.",
        "args_schema": {"enabled": "bool"},
        "example": {"enabled": True},
    },
    {
        "name": "notify",
        "description": "Send a user-facing message (best-effort).",
        "args_schema": {"text": "string"},
        "example": {"text": "Starting face enrollment for Tim."},
    },
]
