from __future__ import annotations

import threading
import time
from typing import Optional, Dict, Any
import dataclasses

from states.visual_states import VisualStateStore


class VisualStateLiveStore:
    """Shared latest visual snapshot for WS/router consumption."""

    _lock = threading.Lock()
    _latest: Dict[str, Any] = {}

    @staticmethod
    def _serialize(obj):
        if obj is None:
            return None
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, (list, tuple)):
            return [VisualStateLiveStore._serialize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: VisualStateLiveStore._serialize(v) for k, v in obj.items()}
        return obj

    @classmethod
    def refresh(cls):
        snap = VisualStateStore.snapshot()
        snap = cls._serialize(snap)
        with cls._lock:
            cls._latest = snap

    @classmethod
    def get(cls) -> Dict[str, Any]:
        with cls._lock:
            return dict(cls._latest)


class VisualStateService:
    def __init__(self, interval: float = 0.2):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        def loop():
            while not self._stop.is_set():
                VisualStateLiveStore.refresh()
                time.sleep(self.interval)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
