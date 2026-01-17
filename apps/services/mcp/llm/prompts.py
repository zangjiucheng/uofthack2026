from __future__ import annotations

import json
from typing import Any, Dict, List


SYSTEM_PROMPT = """You map a transcript to a single robot action.
Return ONLY one JSON object and nothing else (no Markdown or code fences).
If the request is not about finding/approaching an object or person or enrolling a face, ignore the JSON rules and reply conversationally like a normal assistant.

Format:
{
  "version": "mcp.plan.v1",
  "goal_type": "FIND_OBJECT" | "FIND_PERSON" | "ENROLL_PERSON",
  "tool": "approach_object" | "approach_person" | "start_face_record",
  "payload": { ... }
}

Rules:
- payload must always be an object.
- If the user is just chatting or asking something unrelated to the robot goals above, answer naturally in plain text (no JSON at all).
- If the user introduces their name ("my name is X", "call me X", "I am X", "I'm X"), use goal_type ENROLL_PERSON, tool start_face_record, payload {"name": "<X>"}.
- If the user wants the robot to find/approach a person, use goal_type FIND_PERSON, tool approach_person, payload {"name": "<person_name>"}.
- Otherwise treat it as FIND_OBJECT with tool approach_object and payload {"object": "<object_label>"}.
- Use context hints when available (e.g., context.known_people, context.hint) to choose the target string, but keep payload minimal.
- Do not include steps, vars, policy, or any extra keys. Keep JSON concise with version exactly "mcp.plan.v1".
"""


def build_user_prompt(transcript: str, context: Dict[str, Any], tools: List[Dict[str, Any]]) -> str:
    ctx = json.dumps(context or {}, ensure_ascii=False)
    tools_json = json.dumps(tools or [], ensure_ascii=False, indent=2)

    return (
        f"Transcript:\n{transcript.strip()}\n\n"
        f"Context JSON:\n{ctx}\n\n"
        f"Available tools (name/description/args_schema/example):\n{tools_json}\n\n"
        "If the request is unrelated to the robot goals (find object/person or enroll face), respond normally in natural language.\n"
        "Otherwise, output one JSON object with version/goal_type/tool/payload only."
    )
