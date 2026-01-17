import os
import json
import time
import asyncio
import threading

from core.services import Service
from states.raspi_states import RaspiStateStore

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    websockets = None
try:
    from routes.ws_common import start_state_ws
except Exception:  # pragma: no cover - optional dependency
    start_state_ws = None


class PiStateWSService(Service):
    name = "pi_state_ws"

    def __init__(self, raspi_state: RaspiStateStore):
        # Subscribe to backend state websocket (8765 for subscribe)
        self._sub_host = os.environ.get("PI_SUB_STATE_WS_HOST", "127.0.0.1")
        self._sub_port = int(os.environ.get("PI_SUB_STATE_WS_PORT", "8765"))
        self._sub_url = os.environ.get("PI_SUB_STATE_WS_URL", f"ws://{self._sub_host}:{self._sub_port}")
        sub_max_size_env = os.environ.get("PI_SUB_STATE_WS_MAX_SIZE")
        if sub_max_size_env in (None, "", "none", "None"):
            self._sub_max_size = None
        else:
            try:
                self._sub_max_size = int(sub_max_size_env)
            except Exception:
                self._sub_max_size = None
        # Publish Pi RaspiState for local consumers (8766 for publish)
        self._pub_host = os.environ.get("PI_PUB_STATE_WS_HOST", "0.0.0.0")
        self._pub_port = int(os.environ.get("PI_PUB_STATE_WS_PORT", "8766"))
        self._pub_interval = float(os.environ.get("PI_PUB_WS_INTERVAL", "0.3"))
        self._stop = threading.Event()
        self._raspi_state = raspi_state
    def start(self):
        if os.environ.get("PI_STATE_WS", "1") != "1":
            return
        self._stop.clear()

        self._maybe_start_subscriber()
        self._maybe_start_publisher()

    def stop(self):
        self._stop.set()
        self.threads.join("state_ws_client", timeout=1.0)
        self.threads.join("state_ws_server", timeout=1.0)

    def _maybe_start_subscriber(self):
        if websockets is None:
            print("[pi_robot] websockets not available; state WS subscribe disabled.")
            return
        if self.threads.is_running("state_ws_client"):
            return

        def runner():
            async def consume():
                while not self._stop.is_set():
                    try:
                        async with websockets.connect(self._sub_url, max_size=self._sub_max_size) as ws:  # type: ignore[arg-type]
                            print(f"[pi_robot] Subscribed to backend state WS at {self._sub_url}")
                            async for message in ws:
                                try:
                                    payload = json.loads(message)
                                except Exception:
                                    payload = {"raw": message}
                                # Update local visual state if available.
                                visual = None
                                if isinstance(payload, dict):
                                    visual = payload.get("visual")
                                    if visual is None and isinstance(payload.get("state"), dict):
                                        visual = payload["state"].get("visual")
                                if visual is None:
                                    visual = {}
                                if isinstance(visual, dict):
                                    try:
                                        self._raspi_state.set_visual_state(visual)
                                    except Exception:
                                        pass
                                controller = None
                                if isinstance(payload, dict):
                                    controller = payload.get("controller")
                                    if controller is None and isinstance(payload.get("state"), dict):
                                        controller = payload["state"].get("controller")
                                if isinstance(controller, dict):
                                    try:
                                        self._raspi_state.set_controller_state(controller)
                                    except Exception:
                                        pass
                    except Exception as exc:  # pragma: no cover - background path
                        print(f"[pi_robot] State WS subscribe failed: {exc}")
                        try:
                            await asyncio.sleep(2.0)
                        except Exception:
                            break

            asyncio.run(consume())

        self.threads.start("state_ws_client", runner)

    def _maybe_start_publisher(self):
        if start_state_ws is None:
            print("[pi_robot] websockets not available; state WS publish disabled.")
            return
        if self.threads.is_running("state_ws_server"):
            return

        def runner():
            def build_payload():
                state = self._raspi_state.snapshot_dict()
                # Remove visual/controller to reduce payload size.
                state.pop("visual", None)
                state.pop("controller", None)
                return {"ts": time.time(), "state": state}

            try:
                asyncio.run(
                    start_state_ws(
                        build_payload,
                        host=self._pub_host,
                        port=self._pub_port,
                        interval=self._pub_interval,
                    )
                )
            except Exception as exc:  # pragma: no cover - background path
                print(f"[pi_robot] State WS publish failed: {exc}")

        self.threads.start("state_ws_server", runner)
        print(f"[pi_robot] State WS publish enabled at ws://{self._pub_host}:{self._pub_port}")
