from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


def extract_json_object(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    # Remove fenced code blocks if present (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        text = text.lstrip("`")
        if text.startswith("json"):
            text = text[len("json") :].lstrip()
        fence = text.rfind("```")
        if fence != -1:
            text = text[:fence].rstrip()

    if text.startswith("{") and text.endswith("}"):
        return text

    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        return m.group(0).strip()

    fenced = re.search(r"```(?:json)?\s*({.*?})\s*```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return None


def try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    js = extract_json_object(text)
    if not js:
        return None
    try:
        obj = json.loads(js)
    except Exception:
        cleaned = re.sub(r",\s*}", "}", js)
        cleaned = re.sub(r",\s*]", "]", cleaned)
        try:
            obj = json.loads(cleaned)
        except Exception:
            return None
    if isinstance(obj, dict):
        return obj
    return None
