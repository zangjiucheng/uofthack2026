from __future__ import annotations

import os
import threading
import time
import base64
from io import BytesIO

from core.services import Service
from states.raspi_states import RaspiStateStore
from pi_hardware.lcd.renderer import EyeRenderer
from pi_hardware.lcd.animations import FaceState, EyeState, make_blink_timeline
from pi_hardware.lcd.presets import EYE_PRESETS


class EyeRenderService(Service):
    name = "eye_render"

    def __init__(self, raspi_state: RaspiStateStore, bot=None, *, width: int = 128, height: int = 64):
        self.raspi_state = raspi_state
        self.bot = bot
        self.width = width
        self.height = height
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._renderer = EyeRenderer(width=width, height=height)

        try:
            default_mode = int(os.environ.get("PI_EYE_MODE", "1"))
        except Exception:
            default_mode = 1
        self.mode = default_mode if default_mode in EYE_PRESETS else 1
        self._timeline = EYE_PRESETS[self.mode]["factory"]()
        self._custom_left = None
        self._custom_right = None

    def set_mode(self, mode: int):
        if mode in EYE_PRESETS:
            self.mode = mode
            self._timeline = EYE_PRESETS[mode]["factory"]()

    def clear(self):
        """Turn off both eye displays."""
        blank = self._renderer.render_face_surface(FaceState(EyeState(open=0.0), EyeState(open=0.0)))
        left, right = blank if isinstance(blank, tuple) else (None, None)
        if self.bot and getattr(self.bot, "eyes", None):
            try:
                self.bot.eyes.update_from_surfaces(left, right)
            except Exception:
                pass
        try:
            self.raspi_state.set_visual_state({"eyes": {"mode": 0, "label": "cleared", "ts": time.time()}})
        except Exception:
            pass

    def set_custom_images(self, left_img, right_img):
        """
        Set custom PIL images (already sized to OLED) to blink with.
        """
        self.mode = 0
        self._custom_left = left_img
        self._custom_right = right_img
        base_face = FaceState(EyeState(open=1.0), EyeState(open=1.0))
        print("Making blink timeline for custom images")
        self._timeline = make_blink_timeline(base_face, period_s=2.5, blink_s=0.2)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            t0 = time.time()
            while not self._stop.is_set():
                t = time.time() - t0
                face = self._timeline.sample(t, loop=True)
                if self._custom_left is not None and self._custom_right is not None:
                    left_surface = self._custom_left
                    right_surface = self._custom_right
                    # Apply blink openness
                    try:
                        from PIL import Image

                        def apply_open(img: Image.Image, open_amt: float) -> Image.Image:
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

                        left_surface = apply_open(left_surface, face.left.open)
                        right_surface = apply_open(right_surface, face.right.open)
                    except Exception:
                        pass
                else:
                    left_surface, right_surface = self._renderer.render_face_surface(face)

                # Push to hardware if available
                if self.bot and getattr(self.bot, "eyes", None):
                    try:
                        self.bot.eyes.update_from_surfaces(left_surface, right_surface)
                    except Exception:
                        pass

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None


def _encode_img(img) -> str:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
