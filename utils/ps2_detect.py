from __future__ import annotations

import os
from pathlib import Path
from typing import List


def _list_dev() -> List[str]:
    try:
        return [str(p) for p in Path("/dev").iterdir()]
    except Exception:
        return []


def detect_ps2_device(pattern: str = "usbmodem") -> str | None:
    """
    Best-effort detection of a PS2 serial device on macOS-like paths.
    Scans /dev and returns the first entry containing the pattern.
    """
    candidates = [p for p in _list_dev() if pattern in os.path.basename(p)]
    return sorted(candidates)[0] if candidates else None
