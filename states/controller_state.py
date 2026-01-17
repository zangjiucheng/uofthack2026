from __future__ import annotations

import time
from dataclasses import dataclass, asdict, field
from typing import Dict, Optional
import threading


@dataclass
class ControllerSnapshot:
    active: bool
    manual_activate: bool
    sticks: Dict[str, int]
    buttons: Dict[str, bool]
    last_ts: float


@dataclass
class ControllerStateStore:
    """Lightweight shared store for controller input."""

    _sticks: Dict[str, int] = field(default_factory=dict)
    _buttons: Dict[str, bool] = field(default_factory=dict)
    _last_ts: float = 0.0
    _ttl: float = 2.0  # seconds before considered inactive
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, sticks: Optional[Dict[str, int]] = None, buttons: Optional[Dict[str, bool]] = None):
        now = time.time()
        with self._lock:
            if sticks:
                self._sticks = dict(sticks)
            if buttons:
                self._buttons.update({k: bool(v) for k, v in buttons.items()})
            self._last_ts = now

    def snapshot(self) -> ControllerSnapshot:
        with self._lock:
            last_ts = self._last_ts
            ttl = self._ttl
            sticks = dict(self._sticks)
            buttons = dict(self._buttons)
        now = time.time()
        active = (now - last_ts) <= ttl
        if not active:
            sticks = {"LX": 0, "LY": 0, "RX": 0, "RY": 0}
        manual_activate = buttons.get("R1", False) or buttons.get("L1", False)
        snapshot = ControllerSnapshot(
            active=active,
            manual_activate=manual_activate,
            sticks=sticks,
            buttons=buttons,
            last_ts=last_ts,
        )
        return snapshot

    def snapshot_dict(self) -> dict:
        snap = self.snapshot()
        data = asdict(snap)
        return data
