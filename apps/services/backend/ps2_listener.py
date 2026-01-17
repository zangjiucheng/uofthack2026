import os
import threading

from core.services import Service
from utils.ps2_detect import detect_ps2_device
from input.ps2_lib import PS2Reader


class PS2ListenerService(Service):
    name = "ps2_listener"

    def __init__(self, event_state, controller_state):
        self.event_state = event_state
        self.controller_state = controller_state
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        if os.environ.get("APP_PS2_FAKE_INPUT", "0") == "1":
            print("[ps2_listener] WARNING: APP_PS2_FAKE_INPUT=1; PS2 listener disabled. (Conflicts with teleop service)")
            return
        port = os.environ.get("APP_PS2_PORT") or detect_ps2_device()
        if not port:
            print("[ps2_listener] No PS2 device detected; listener disabled.")
            return
        baud = int(os.environ.get("APP_PS2_BAUD", "115200"))
        log_events = os.environ.get("APP_PS2_LOG_EVENTS", "0") == "1"
        print(f"[ps2_listener] Starting on {port} @ {baud}")

        def loop():
            try:
                with PS2Reader(port, baud, timeout=0.2, dedupe=True, dedupe_payload=True) as reader:
                    for kind, payload, line in reader:
                        if self._stop.is_set():
                            break
                        if kind == "sticks":
                            self.controller_state.update(sticks=payload)
                        elif kind == "kv":
                            self.controller_state.update(buttons=payload)
                        if log_events:
                            self.event_state.log_event("ps2", raw=line)
            except Exception as exc:  # pragma: no cover - hardware path
                print(f"[ps2_listener] stopped: {exc}")

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
