from __future__ import annotations

import os

from core.services import Service
from routes.rest_api import CommandRegistry, start_rest_server
from states.raspi_states import TaskManager
from pi_hardware.lcd.presets import EYE_PRESETS
from pi_hardware.lcd.renderer import EyeRenderer
from pi_hardware.lcd.model import FaceState, EyeStyle
from pi_hardware.robot.robot_api import Bot
import base64
import time
from io import BytesIO
from PIL import Image

class PiRestApiService(Service):
    """
    Minimal REST API for the Pi side to enqueue high-level tasks.
    Controlled by APP_PI_REST=1 (default: disabled).
    """

    name = "pi_rest_api"

    def __init__(self, task_manager: TaskManager, eye_render_service=None):
        self._registry = CommandRegistry()
        self._server = None
        self.task_manager = task_manager
        self.eye_render_service = eye_render_service
        self._eye_renderer = EyeRenderer(width=128, height=64, style=EyeStyle(mode="1"))
        try:
            self._bot = Bot()
        except Exception:
            self._bot = None

    def start(self):
        if self._server is not None:
            return
        if os.environ.get("PI_REST", "0") != "1":
            return

        def approach_object(payload):
            obj = (payload or {}).get("object")
            if not obj or not isinstance(obj, str):
                return {"ok": False, "error": "object (str) required"}
            task = {"kind": "approach", "target_type": "object", "target": obj}
            queued = self.task_manager.enqueue(task)
            print(f"[pi_rest_api] Enqueued approach_object task: {task}")
            return {"ok": queued, "task": task}

        def approach_person(payload):
            person = (payload or {}).get("name")
            if not person or not isinstance(person, str):
                return {"ok": False, "error": "name (str) required"}
            task = {"kind": "approach", "target_type": "person", "target": person}
            queued = self.task_manager.enqueue(task)
            print(f"[pi_rest_api] Enqueued approach_person task: {task}")
            return {"ok": queued, "task": task}

        def eyes_mode(payload):
            mode = (payload or {}).get("mode")
            if not isinstance(mode, int) or mode not in EYE_PRESETS:
                return {"ok": False, "error": f"mode (int) required in {sorted(EYE_PRESETS.keys())}"}
            preset = EYE_PRESETS[mode]
            try:
                print(f"[pi_rest_api] Updating eyes to mode {mode}: {preset['label']}")
                if self.eye_render_service:
                    try:
                        self.eye_render_service.set_mode(mode)
                    except Exception as exc:
                        return {"ok": False, "error": str(exc)}
                return {"ok": True, "label": preset["label"]}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        def eyes_clear(payload):
            return {"ok": True, "msg": "eyes clear not implemented yet"}

        def eyes_custom(payload):
            if not self.eye_render_service:
                return {"ok": False, "error": "eye_render_service not available"}
            img_b64 = (payload or {}).get("image")
            if not isinstance(img_b64, str):
                return {"ok": False, "error": "image (base64 PNG/JPEG) required"}

            def decode(img_b64: str):
                try:
                    raw = base64.b64decode(img_b64)
                    return Image.open(BytesIO(raw)).convert("1").resize((128, 64))
                except Exception:
                    return None

            left_img = decode(img_b64)
            if left_img is None:
                return {"ok": False, "error": "failed to decode images"}
            right_img = left_img.transpose(method=Image.FLIP_LEFT_RIGHT)

            try:
                self.eye_render_service.set_custom_images(left_img, right_img)
                payload_state = {
                    "mode": 0,
                    "label": "custom",
                    "ts": time.time(),
                }
                self.eye_render_service.raspi_state.set_visual_state({"eyes": payload_state})
                return {"ok": True}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        self._registry.register("approach_object", approach_object)
        self._registry.register("approach_person", approach_person)
        self._registry.register("eyes_mode", eyes_mode)
        self._registry.register("eyes_custom", eyes_custom)

        host = os.environ.get("PI_REST_HOST", "0.0.0.0")
        port = int(os.environ.get("PI_REST_PORT", "8081"))
        self._server = start_rest_server(self._registry, host=host, port=port)

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
