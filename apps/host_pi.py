import os
import time
import pathlib
import threading

from core.services import Service, ServiceContext
from states.raspi_states import RaspiStateStore
from states.robot_fsm import (
    PiRobotState,
    run_state_handler,
)
from apps.services.pi import PiStateWSService, CamStreamingService, PiDebugDisplayService
from apps.services.pi.pi_rest_api_service import PiRestApiService
from pi_hardware.cmd_handler import make_cmd_handler

# Prefer real hardware API but fall back to the fake implementation on platforms
# where adafruit/board can't initialize (e.g., local dev on macOS).
try:
    from pi_hardware.robot.robot_api import Bot  # type: ignore
except Exception as exc:  # pragma: no cover - platform guard
    print(f"[pi_robot] real Bot unavailable ({exc}); using FakeBot")
    from pi_hardware.robot.fake_robot_api import FakeBot as Bot  # type: ignore


DEBUG_TRACE = os.environ.get("PI_DEBUG_TRACE", "0") == "1"
ROOT_DIR = pathlib.Path(os.getcwd()).resolve()
try:
    from viztracer import VizTracer  # optional dependency
except Exception:  # pragma: no cover
    VizTracer = None


class PiRobotService(Service):
    """
    Raspberry Pi side robot service:
    - Streams camera via cam_streaming_service (MJPEG).
    - Runs minimal loop; all planning comes from backend guidance/commands.
    - Sends velocity commands to Bot (differential placeholder).
    """

    name = "pi_robot"

    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.cfg = ctx.config
        self.raspi_state = RaspiStateStore()
        self.robot = Bot()
        self._stop = threading.Event()
        self._handler = make_cmd_handler(
            robot=self.robot,
            set_state=self._set_state,
            raspi_state=self.raspi_state,
        )
        self.state_ws_service = PiStateWSService(raspi_state=self.raspi_state)
        self.cam_stream_service = CamStreamingService()
        self.debug_display_service = PiDebugDisplayService(raspi_state=self.raspi_state)
        self._last_unimplemented_state: PiRobotState | None = None
        self._last_status_ts: float = 0.0
        self._stopped = False
        self.pi_rest_service = PiRestApiService(self.raspi_state.task_manager)
        self._tracer = None

    def start(self) -> None:  # pragma: no cover - interactive/long-running
        self._start_tracer_if_enabled()
        self._maybe_start_streaming()
        self._maybe_start_state_ws()
        self.pi_rest_service.start()
        self.debug_display_service.start()
        self._status_payload()

        try:
            while not self._stop.is_set():
                self._tick()
                self._status_heartbeat()
                time.sleep(0.05)
        except KeyboardInterrupt:
            self._stop.set()
        finally:
            self.stop()
            self._stop_tracer()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        self._handler({"cmd": "stop"})
        self.state_ws_service.stop()
        self.pi_rest_service.stop()
        if self.cam_stream_service:
            self.cam_stream_service.stop()
        self.debug_display_service.stop()
        self._stop_tracer()

    def _maybe_start_streaming(self):
        try:
            self.cam_stream_service.start()
        except Exception as exc:
            print(f"[pi_robot] Camera streaming not available: {exc}")

    def _maybe_start_state_ws(self):
        self.state_ws_service.start()

    def _set_state(self, state: str | PiRobotState) -> bool:
        if isinstance(state, PiRobotState):
            state_enum = state
        elif isinstance(state, str):
            state_norm = state.strip().upper()
            state_enum = PiRobotState.__members__.get(state_norm)
        else:
            return False

        if state_enum is None:
            return False

        current = self.raspi_state.get_robot_state()
        if state_enum != current:
            self.raspi_state.set_robot_state(state_enum)
            self.raspi_state.log_event("state_change", state=state_enum.value)
        self._status_payload()
        return True

    def _status_payload(self):
        # Keep RaspiStateStore pi_status updated so host can reflect state/stop.
        try:
            status = self._handler.status_payload()
            try:
                # Ensure store is updated even if handler does not.
                self.raspi_state.set_pi_status(status)
            except Exception:
                pass
            self._last_status_ts = time.time()
            return status
        except Exception:
            state_val = self.raspi_state.get_robot_state().value
            status = {"state": state_val}
            try:
                self.raspi_state.set_pi_status(status)
                self._last_status_ts = time.time()
            except Exception:
                pass
            return status

    def _status_heartbeat(self, interval: float = 1.0):
        """Push periodic status so consumers see fresh timestamps even if state doesn't change."""
        now = time.time()
        if now - self._last_status_ts >= interval:
            self._status_payload()

    def _tick(self):
        """
        State machine heartbeat. Invokes the handler for the current state, if implemented.
        Passes self + common resources so handlers can drive robot or transition.
        """
        state_snapshot = self.raspi_state.snapshot()
        try:
            ran = run_state_handler(
                cmd_handler=self._handler,
            )
            if not ran:
                cur_state = state_snapshot.robot_state
                if self._last_unimplemented_state != cur_state:
                    print(f"[pi_robot] no handler registered for state {cur_state.value}")
                    self._last_unimplemented_state = cur_state
                return
        except NotImplementedError:
            cur_state = state_snapshot.robot_state
            if self._last_unimplemented_state != cur_state:
                print(f"[pi_robot] state handler for {cur_state.value} not implemented yet")
                self._last_unimplemented_state = cur_state
        except Exception as exc:
            cur_state = state_snapshot.robot_state
            print(f"[pi_robot] state handler {cur_state.value} error: {exc}")

    def _start_tracer_if_enabled(self):
        if not DEBUG_TRACE or VizTracer is None or self._tracer is not None:
            return
        log_dir = pathlib.Path(os.environ.get("APP_LOG_DIR", "logs"))
        out_file = os.environ.get("PI_DEBUG_TRACE_OUT", "viztracer_pi.json")
        dest = (ROOT_DIR / log_dir / out_file).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._tracer = VizTracer(
            output_file=str(dest),
            log_func_args=False,
            ignore_c_function=True,
            tracer_entries=100_000,
        )
        self._tracer.start()
        print(f"[pi_robot] VizTracer started (PI_DEBUG_TRACE=1) -> {dest}")

    def _stop_tracer(self):
        if self._tracer is None:
            return
        try:
            self._tracer.stop()
            self._tracer.save()
            print("[pi_robot] VizTracer trace saved.")
        except Exception as exc:
            print(f"[pi_robot] VizTracer save failed: {exc}")
        self._tracer = None
