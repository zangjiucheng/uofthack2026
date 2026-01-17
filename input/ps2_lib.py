"""
Lightweight PS2 controller reader/parsers for reuse.

Example:
    from input.ps2_lib import PS2Reader
    with PS2Reader(port="/dev/cu.usbmodem1201", baud=115200) as reader:
        for kind, payload, line in reader:
            print(kind, payload)
"""

from __future__ import annotations

from typing import Dict, Iterator, Tuple

import serial
from serial import SerialException

Event = Tuple[str, Dict, str]


def _decode_line(raw: bytes) -> str:
    """Robustly decode controller bytes, keeping only printable ASCII."""
    filtered = bytes(b for b in raw if 32 <= b <= 126)
    return filtered.decode("ascii", errors="ignore").strip()


def _parse_kv_line(line: str) -> Dict:
    data = {}
    for part in line.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        key = k.strip()
        val = v.strip()
        lower_val = val.lower()
        try:
            num = int(val)
            data[key] = bool(num) if num in (0, 1) else num
        except ValueError:
            if lower_val in {"true", "false"}:
                data[key] = lower_val == "true"
            else:
                data[key] = val
    return data


def parse_line(line: str) -> tuple[str, Dict]:
    """
    Parse a decoded line from the controller.
    Returns (kind, payload):
      - kind="sticks": payload with LX/LY/RX/RY ints if stick values present
      - kind="kv": payload dict of parsed key/values (buttons become bools; numbers stay ints/strings)
      - kind="text": payload {"text": line} for unparsed lines
    """
    normalized = line.strip()
    lowered = normalized.lower()

    # Normalize prefixed lines like "sticks LX=..." or "buttons L1=0,..."
    if lowered.startswith("sticks "):
        normalized = normalized.split(" ", 1)[1]
    elif lowered.startswith("buttons "):
        normalized = normalized.split(" ", 1)[1]
    elif "stick values:" in lowered:
        # Legacy format from the library examples
        try:
            nums = normalized.split(":", 1)[1].split(",")
            lx, ly, rx, ry = [int(n.strip()) for n in nums[:4]]
            return "sticks", {"LX": lx, "LY": ly, "RX": rx, "RY": ry}
        except Exception:
            return "text", {"text": line}

    data = _parse_kv_line(normalized)
    if data:
        if all(k in data for k in ("LX", "LY", "RX", "RY")):
            return "sticks", {k: int(data[k]) for k in ("LX", "LY", "RX", "RY")}
        return "kv", data
    return "text", {"text": line}


class PS2Reader:
    def __init__(
        self,
        port: str,
        baud: int = 115200,
        timeout: float = 1.0,
        dedupe: bool = True,
        dedupe_payload: bool = True,
    ):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.dedupe = dedupe
        self.dedupe_payload = dedupe_payload
        self._last_line: str | None = None
        self._last_payload: Dict[str, Dict] = {}
        self.ser = serial.Serial(port, baud, timeout=timeout)

    def __iter__(self) -> Iterator[Event]:
        return self.iter_events()

    def iter_events(self) -> Iterator[Event]:
        """Yield (kind, payload, raw_line) tuples indefinitely."""
        while True:
            try:
                raw = self.ser.readline()
            except SerialException:
                continue  # transient USB hiccup

            if not raw:
                continue
            line = _decode_line(raw)
            if not line:
                continue
            kind, payload = parse_line(line)
            if self.dedupe and line == self._last_line:
                continue
            if self.dedupe_payload:
                prev = self._last_payload.get(kind)
                if prev is not None and prev == payload:
                    self._last_line = line
                    continue
                self._last_payload[kind] = payload
            self._last_line = line
            yield kind, payload, line

    def close(self):
        self.ser.close()

    def __enter__(self) -> "PS2Reader":
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
