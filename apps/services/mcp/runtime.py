from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class RuntimeLoops:
    stop_event: threading.Event
    kb_ingest_loop: Optional[threading.Thread] = None

    def stop(self):
        self.stop_event.set()
        if self.kb_ingest_loop:
            self.kb_ingest_loop.join(timeout=2.0)


def start_runtime_loops(
    *,
    enable_kb_auto_ingest: bool,
    kb_ingest_interval_s: float,
    ingest_once_fn: Optional[Callable[[], dict]] = None,
) -> RuntimeLoops:
    stop_event = threading.Event()
    loops = RuntimeLoops(stop_event=stop_event)

    if enable_kb_auto_ingest and ingest_once_fn is not None:
        interval = max(0.1, float(kb_ingest_interval_s))

        def _kb_loop():
            while not stop_event.is_set():
                try:
                    ingest_once_fn()
                except Exception:
                    pass
                time.sleep(interval)

        loops.kb_ingest_loop = threading.Thread(target=_kb_loop, daemon=True)
        loops.kb_ingest_loop.start()

    return loops
