from __future__ import annotations
from typing import Any, Dict, List

DEFAULT_PLANNER_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "approach_object",
        "description": "Move toward an object label.",
        "args_schema": {"object": "string"},
        "example": {"object": "bottle"},
    },
    {
        "name": "approach_person",
        "description": "Move toward a known person name.",
        "args_schema": {"name": "string"},
        "example": {"name": "Alex"},
    },
    {
        "name": "start_face_record",
        "description": "Begin face enrollment for a person name.",
        "args_schema": {"name": "string"},
        "example": {"name": "Alex"},
    },
]
