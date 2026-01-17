import os
import threading
import pathlib
from utils.warning_filters import configure_warning_filters

# Apply warning filters before importing heavy deps that emit deprecation noise.
ROOT_DIR = pathlib.Path(os.getcwd()).resolve()
configure_warning_filters()

from core.services import Service, ServiceContext
from states.event_states import EventState
from states.raspi_states import RaspiStateStore
from states.controller_state import ControllerStateStore
from states.visual_state_service import VisualStateService
from apps.services.backend import (
    BackendTeleopService,
    PS2ListenerService,
    RestApiService,
    StreamService,
    WebsocketService,
    EyeStreamService,
)

DEBUG_TRACE = os.environ.get("APP_DEBUG_TRACE", "0") == "1"
try:
    from viztracer import VizTracer  # optional dependency
except Exception:  # pragma: no cover
    VizTracer = None


class HostBackendService(Service):
    """
    Orchestrates the host backend by wiring together streaming, websockets,
    REST, and optional hardware listeners.
    """

    name = "host_backend"

    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.cfg = ctx.config
        self.raspi_state = RaspiStateStore()
        self.event_state = EventState()
        self.controller_state = ControllerStateStore()
        self._stop = threading.Event()
        self._tracer = None

        self.stream_service = StreamService(self.event_state, stop_event=self._stop)
        self.websocket_service = WebsocketService(self.event_state, self.controller_state, self.raspi_state)
        self.eye_stream_service = EyeStreamService()
        self.ps2_service = PS2ListenerService(self.event_state, self.controller_state)
        self.teleop_service = BackendTeleopService(self.controller_state, self.event_state)
        self.rest_service = RestApiService()
        self.visual_service = VisualStateService()
        self.rest_service.register_host_handlers(self.stream_service, self.event_state, eye_state=True)

    def start(self) -> None:
        # Run in a worker thread so Service.start returns immediately if desired.
        self._stop.clear()
        self._start_tracer_if_enabled()
        if self.threads.is_running("host_main"):
            return
        main_thread = self.threads.start("host_main", self._run)
        try:
            while main_thread.is_alive():
                main_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            self.stop()
        finally:
            self._stop_tracer()

    def stop(self) -> None:
        self._stop.set()
        self.stream_service.stop()
        self.ps2_service.stop()
        self.teleop_service.stop()
        self.rest_service.stop()
        self.websocket_service.stop()
        self.eye_stream_service.stop()
        self.threads.join("host_main", timeout=1.0)
        self._stop_tracer()

    def _run(self):  # pragma: no cover - interactive path
        self.websocket_service.start()
        self.eye_stream_service.start()
        self.ps2_service.start()
        self.teleop_service.start()
        self.rest_service.start()
        self.visual_service.start()
        try:
            self.stream_service.start()
        finally:
            self._stop.set()
            self.ps2_service.stop()
            self.teleop_service.stop()
            self.rest_service.stop()
            self.websocket_service.stop()
            self.visual_service.stop()

    def _start_tracer_if_enabled(self):
        if not DEBUG_TRACE or VizTracer is None or self._tracer is not None:
            return
        log_dir = pathlib.Path(os.environ.get("APP_LOG_DIR", "logs"))
        out_file = os.environ.get("APP_DEBUG_TRACE_OUT", "viztracer.json")
        dest = (ROOT_DIR / log_dir / out_file).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Constrain tracing to keep buffers smaller and avoid dump-time segfaults.
        self._tracer = VizTracer(
            output_file=str(dest),
            max_stack_depth=6,
            log_func_args=False,
            ignore_c_function=True,
            tracer_entries=300_000,  # cap total entries
        )
        self._tracer.start()
        print(f"[host_backend] VizTracer started (APP_DEBUG_TRACE=1) -> {dest}")

    def _stop_tracer(self):
        if self._tracer is None:
            return
        try:
            self._tracer.stop()
            self._tracer.save()
            print("[host_backend] VizTracer trace saved.")
        except Exception as exc:
            print(f"[host_backend] VizTracer save failed: {exc}")
        self._tracer = None
