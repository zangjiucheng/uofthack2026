import asyncio
import os
import threading
import time
import json

from core.services import Service
from states.video_stream import VideoFrameStore
from states.visual_state_service import VisualStateLiveStore
from states.raspi_states import RaspiStateStore
from states.controller_state import ControllerStateStore
from states.event_states import EventState

try:  # optional deps
    from routes.ws_common import start_state_ws, start_video_ws
except Exception:  # pragma: no cover - optional dependency
    start_state_ws = None
    start_video_ws = None
try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    websockets = None


class WebsocketService(Service):
    name = "websocket_service"

    def __init__(self, event_state: EventState, controller_state: ControllerStateStore, raspi_state: RaspiStateStore):
        self.event_state = event_state
        self.controller_state = controller_state
        self.raspi_state = raspi_state
        self._state_thread: threading.Thread | None = None
        self._visual_thread: threading.Thread | None = None
        self._video_started = False
        self._pi_state_thread: threading.Thread | None = None
        self._pi_stop = threading.Event()

    def start(self):
        self._maybe_start_state_ws()
        self._maybe_start_video_stream()
        self._pi_stop.clear()
        self._maybe_start_pi_state_subscriber()

    def stop(self):
        # Threads are daemonized; nothing explicit to stop.
        self._state_thread = None
        self._visual_thread = None
        self._video_started = False
        self._pi_state_thread = None
        self._pi_stop.set()

    def _maybe_start_state_ws(self):
        if self._state_thread is not None:
            return
        if start_state_ws is None:
            print("[websocket] websockets not available; state WS disabled.")
            return
        if os.environ.get("APP_STATE_WS", "1") != "1":
            return

        host = os.environ.get("APP_PUB_WS_HOST", "0.0.0.0")
        port = int(os.environ.get("APP_STATE_WS_PORT", "8765"))
        interval = float(os.environ.get("APP_WS_INTERVAL", "0.2"))

        def runner():
            try:
                asyncio.run(
                    start_state_ws(
                        lambda: {
                            "ts": time.time(),
                            "state": self.event_state.snapshot_dict() if hasattr(self.event_state, "snapshot_dict") else {},
                            "controller": self.controller_state.snapshot_dict() if self.controller_state else {"active": False},
                            "visual": VisualStateLiveStore.get(),
                            "pi": self.raspi_state.snapshot_dict() if hasattr(self.raspi_state, "snapshot_dict") else {},
                        },
                        host=host,
                        port=port,
                        interval=interval,
                    )
                )
            except Exception as exc:  # pragma: no cover - background path
                print(f"[websocket] State WS failed: {exc}")

        self._state_thread = threading.Thread(target=runner, daemon=True)
        self._state_thread.start()
        print(f"[websocket] State WS enabled at ws://{host}:{port}")

    def _maybe_start_video_stream(self):
        if self._video_started:
            return
        if start_video_ws is None:
            return
        if os.environ.get("APP_VIDEO_STREAM", "1") != "1":
            return

        host = os.environ.get("APP_VIDEO_HOST", "0.0.0.0")
        ws_port = int(os.environ.get("APP_VIDEO_WS_PORT", "8890"))
        interval = float(os.environ.get("APP_VIDEO_INTERVAL", "0.1"))
        send_timeout = float(os.environ.get("APP_VIDEO_SEND_TIMEOUT", "0.2"))
        try:
            t = threading.Thread(
                target=lambda: asyncio.run(
                    start_video_ws(
                        VideoFrameStore.get_jpeg,
                        host=host,
                        port=ws_port,
                        interval=interval,
                        send_timeout=send_timeout,
                    )
                ),
                daemon=True,
            )
            t.start()
            print(f"[websocket] Video WS at ws://{host}:{ws_port}")
            self._video_started = True
        except Exception as exc:  # pragma: no cover
            print(f"[websocket] Video WS failed: {exc}")

    def _maybe_start_pi_state_subscriber(self):
        if websockets is None:
            return
        if self._pi_state_thread is not None:
            return

        host = os.environ.get("APP_PI_STATE_HOST") or "127.0.0.1"
        port = int(os.environ.get("APP_PI_STATE_WS_PORT", "8766"))
        url =  f"ws://{host}:{port}"

        async def consume():
            while not self._pi_stop.is_set():
                try:
                    async with websockets.connect(url) as ws:  # type: ignore[arg-type]
                        print(f"[websocket] Subscribed to Pi state WS at {url}")
                        async for message in ws:
                            try:
                                payload = json.loads(message)
                            except Exception:
                                continue
                            if isinstance(payload, dict):
                                state = payload.get("state") if "state" in payload else payload
                                if isinstance(state, dict):
                                    try:
                                        self.raspi_state.load_snapshot(state)
                                    except Exception as e:
                                        print(f"[websocket] Pi state WS load snapshot error: {e}")
                                        pass
                except Exception as exc:  # pragma: no cover - background path
                    print(f"[websocket] Pi state WS subscribe failed: {exc}")
                    try:
                        await asyncio.sleep(2.0)
                    except Exception:
                        break

        def runner():
            asyncio.run(consume())

        self._pi_state_thread = threading.Thread(target=runner, daemon=True)
        self._pi_state_thread.start()
        print(f"[websocket] Pi state subscriber enabled -> {url}")
