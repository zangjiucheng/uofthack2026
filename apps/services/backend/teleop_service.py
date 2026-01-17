import os
import threading
import time
from typing import Dict, Optional

from core.services import Service
from input.fake_input import start_fake_ps2_input
from states.controller_state import ControllerStateStore
from states.event_states import EventState
from states.raspi_states import RaspiStateStore


class BackendTeleopService(Service):
    """
    Keyboard-driven PS2 simulator for host/backend use.
    Updates controller/event stores so downstream consumers see a PS2-like feed.
    """

    name = "backend_teleop"

    def __init__(
        self,
        controller_state: ControllerStateStore | None = None,
        event_state: EventState | None = None,
        raspi_state: Optional[RaspiStateStore] = None,
    ):
        self.controller_state = controller_state
        self.event_state = event_state
        self._stop = threading.Event()
        self._enabled = os.environ.get("APP_PS2_FAKE_INPUT", "0") == "1"
        self._raspi_state = raspi_state
        self._sticks: Dict[str, int] = {"LX": 0, "LY": 0, "RX": 0, "RY": 0}
        self._buttons: Dict[str, bool] = {}

    def _push_controller_state(self):
        controller = {
            "active": True,
            "manual_activate": bool(self._buttons.get("L1") or self._buttons.get("R1")),
            "sticks": dict(self._sticks),
            "buttons": dict(self._buttons),
            "last_ts": time.time(),
        }
        if self.controller_state:
            try:
                self.controller_state.update(sticks=controller["sticks"], buttons=controller["buttons"])
            except Exception:
                pass
        if self._raspi_state:
            try:
                self._raspi_state.set_controller_state(controller)
            except Exception:
                pass
        if self.event_state:
            try:
                self.event_state.log_event("ps2_fake", raw=controller)
            except Exception:
                pass

    def start(self):
        if not self._enabled:
            return
        if self.threads.is_running("teleop"):
            return

        self._stop.clear()
        self._sticks = {"LX": 0, "LY": 0, "RX": 0, "RY": 0}
        self._buttons = {}

        def on_event(kind: str, payload: Dict, raw: str):
            if kind == "sticks":
                self._sticks.update({k: int(v) for k, v in payload.items()})
            elif kind == "kv":
                self._buttons.update({k.upper(): bool(v) for k, v in payload.items()})
            self._push_controller_state()
            if self.event_state:
                try:
                    self.event_state.log_event("ps2_fake_raw", raw=raw)
                except Exception:
                    pass

        teleop_thread = start_fake_ps2_input(on_event, self._stop)
        if teleop_thread:
            self.threads.register("teleop", teleop_thread)
            print("[backend] Keyboard PS2 teleop enabled (see console for key map).")
        else:
            print("[backend] Keyboard teleop requested but stdin is not a TTY.")

    def stop(self):
        self._stop.set()
        self.threads.join("teleop", timeout=1.0)
