import asyncio
import base64
import io
import os
import threading
import time
from typing import Optional

from PIL import Image

from core.services import Service
from pi_hardware.lcd import (
    EyeRenderer,
    EyeStyle,
    FaceState,
    EyeState,
    make_minimal_timeline,
    make_playful_timeline,
    make_heart_zoom_timeline,
    make_blink_timeline,
    make_tech_timeline,
    make_noir_timeline,
)
from states.eye_state import EyeStateStore

try:  # optional deps
    from routes.ws_common import start_video_ws
except Exception:  # pragma: no cover - optional dependency
    start_video_ws = None


class EyeStreamService(Service):
    name = "eye_stream"

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._renderer = EyeRenderer(width=128, height=64, style=EyeStyle(mode="L", fg=255, bg=0, aa_scale=2))
        self._last_mode: Optional[int] = None
        self._last_custom_version: Optional[int] = None
        self._timeline = make_minimal_timeline()
        self._t0 = time.perf_counter()
        self._custom_blink = make_blink_timeline(FaceState(EyeState(open=1.0), EyeState(open=1.0)), period_s=2.6, blink_s=0.2)

    def start(self) -> None:
        if self._thread is not None:
            return
        if start_video_ws is None:
            print("[eye_stream] websockets not available; eye WS disabled.")
            return
        if os.environ.get("APP_EYE_WS", "1") != "1":
            return

        host = os.environ.get("APP_EYE_WS_HOST", "0.0.0.0")
        port = int(os.environ.get("APP_EYE_WS_PORT", "8892"))
        interval = float(os.environ.get("APP_EYE_WS_INTERVAL", "0.1"))
        send_timeout = float(os.environ.get("APP_EYE_WS_SEND_TIMEOUT", "0.2"))

        def runner():
            try:
                asyncio.run(
                    start_video_ws(
                        self.get_jpeg,
                        host=host,
                        port=port,
                        interval=interval,
                        send_timeout=send_timeout,
                    )
                )
            except Exception as exc:  # pragma: no cover
                print(f"[eye_stream] Eye WS failed: {exc}")

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
        print(f"[eye_stream] Eye WS at ws://{host}:{port}")

    def stop(self) -> None:
        self._thread = None

    def _apply_blink(self, img: Image.Image, open_amt: float) -> Image.Image:
        open_amt = max(0.05, min(1.0, float(open_amt)))
        if open_amt >= 0.98:
            return img
        new_h = max(1, int(img.height * open_amt))
        y0 = (img.height - new_h) // 2
        y1 = y0 + new_h
        cropped = img.crop((0, y0, img.width, y1))
        out = Image.new(img.mode, img.size, color=0)
        out.paste(cropped, (0, y0))
        return out

    def _select_timeline(self, mode: int):
        if mode == 1:
            return make_minimal_timeline()
        if mode == 2:
            return make_playful_timeline()
        if mode == 3:
            return make_heart_zoom_timeline(min_scale=0.9, max_scale=1.35)
        if mode == 4:
            return make_tech_timeline()
        if mode == 5:
            return make_noir_timeline()
        return make_minimal_timeline()

    def get_jpeg(self) -> Optional[bytes]:
        mode, custom, custom_version = EyeStateStore.snapshot()

        if mode != self._last_mode:
            self._timeline = self._select_timeline(mode)
            self._t0 = time.perf_counter()
            self._last_mode = mode

        if custom_version != self._last_custom_version:
            self._t0 = time.perf_counter()
            self._last_custom_version = custom_version

        t = time.perf_counter() - self._t0
        if mode == 6 and custom is not None:
            face = self._custom_blink.sample(t, loop=True)
            left_img = self._apply_blink(custom.left, face.left.open)
            right_img = self._apply_blink(custom.right, face.right.open)
        else:
            face = self._timeline.sample(t, loop=True)
            left_img, right_img = self._renderer.render_face(face)

        combined = Image.new("L", (left_img.width * 2, left_img.height), color=0)
        combined.paste(left_img, (0, 0))
        combined.paste(right_img, (left_img.width, 0))
        rgb = combined.convert("RGB")
        buff = io.BytesIO()
        rgb.save(buff, format="JPEG", quality=85)
        return buff.getvalue()

    @staticmethod
    def decode_custom_image(payload: dict) -> Optional[tuple[Image.Image, Image.Image]]:
        data = payload.get("image")
        left_data = payload.get("left")
        right_data = payload.get("right")
        mirror = bool(payload.get("mirror", True))

        if data:
            img = _decode_image(data)
            if img is None:
                return None
            left = img.convert("L").resize((128, 64), resample=Image.LANCZOS)
            right = left.transpose(Image.FLIP_LEFT_RIGHT) if mirror else left
            return left, right

        if left_data and right_data:
            left = _decode_image(left_data)
            right = _decode_image(right_data)
            if left is None or right is None:
                return None
            return (
                left.convert("L").resize((128, 64), resample=Image.LANCZOS),
                right.convert("L").resize((128, 64), resample=Image.LANCZOS),
            )
        return None


def _decode_image(data: str) -> Optional[Image.Image]:
    if data.startswith("data:"):
        try:
            data = data.split(",", 1)[1]
        except Exception:
            return None
    try:
        raw = base64.b64decode(data)
        return Image.open(io.BytesIO(raw))
    except Exception:
        return None
