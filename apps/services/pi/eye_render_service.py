from __future__ import annotations

import math
import os
import threading
import time
import base64
from io import BytesIO

from core.services import Service
from pi_hardware.robot.robot_api import Bot
from states.raspi_states import RaspiStateStore
from pi_hardware.lcd.renderer import EyeRenderer
from pi_hardware.lcd.animations import FaceState, EyeState, make_blink_timeline
from pi_hardware.lcd.presets import EYE_PRESETS
from apps.services.pi.eye_animations_lib import eyes as eyes2
from apps.services.pi.eye_animations_lib import lcd_frame
import random


class RandomEyeMovement:
    def __init__(self, eyes: eyes2.Eyes):
        self.duration = random.uniform(2.0, 5.0)
        self.eyes = eyes

        if random.random() < 0.2:
            direction = random.random() * 2 * 3.14159
            distance = random.uniform(0.5, 1)
            self.eyes.look_at_x = distance * math.cos(direction)
            self.eyes.look_at_y = distance * math.sin(direction)

        if random.random() < 0.3:
            self.eyes.curious = random.choice([True, False])

    def cleanup(self):
        self.eyes.look_at_x = 0
        self.eyes.look_at_y = 0


class ShakeHeadMovement(RandomEyeMovement):
    def __init__(self, eyes: eyes2.Eyes):
        super().__init__(eyes)
        eyes.shake_refuse()

    def cleanup(self):
        pass


class SadFaceMovement(RandomEyeMovement):
    def __init__(self, eyes: eyes2.Eyes):
        super().__init__(eyes)
        eyes.mood = eyes2.Eyes.MOOD_SAD

    def cleanup(self):
        self.eyes.mood = eyes2.Eyes.MOOD_DEFAULT


class HappyFaceMovement(RandomEyeMovement):
    def __init__(self, eyes: eyes2.Eyes):
        super().__init__(eyes)
        eyes.mood = eyes2.Eyes.MOOD_HAPPY

    def cleanup(self):
        self.eyes.mood = eyes2.Eyes.MOOD_DEFAULT


class PlainFaceMovement(RandomEyeMovement):
    def __init__(self, eyes: eyes2.Eyes):
        super().__init__(eyes)
        eyes.mood = eyes2.Eyes.MOOD_DEFAULT

    def cleanup(self):
        pass


class LookAroundWonderMovement(RandomEyeMovement):
    def __init__(self, eyes: eyes2.Eyes):
        super().__init__(eyes)
        self.eyes = eyes
        eyes.curious = True
        eyes.mood = eyes2.Eyes.MOOD_DEFAULT

        direction = random.random() * 2 * 3.14159
        distance = random.uniform(0.65, 1)
        self.eyes.look_at_x = distance * math.cos(direction)
        self.eyes.look_at_y = distance * math.sin(direction)

    def cleanup(self):
        self.eyes.curious = False
        self.eyes.mood = eyes2.Eyes.MOOD_DEFAULT
        self.eyes.look_at_x = 0
        self.eyes.look_at_y = 0
        if random.random() < 0.3:
            self.eyes.blink()
            self.eyes.shake_refuse()


class LookAroundAngryMovement(RandomEyeMovement):
    def __init__(self, eyes: eyes2.Eyes):
        super().__init__(eyes)
        self.eyes = eyes
        self.eyes.mood = eyes2.Eyes.MOOD_ANGRY
        eyes.curious = True

        direction = random.random() * 2 * 3.14159
        distance = random.uniform(0.5, 1)
        self.eyes.look_at_x = distance * math.cos(direction)
        self.eyes.look_at_y = distance * math.sin(direction)

    def cleanup(self):
        self.eyes.curious = False
        self.eyes.look_at_x = 0
        self.eyes.mood = eyes2.Eyes.MOOD_DEFAULT
        self.eyes.look_at_y = 0
        if random.random() < 0.3:
            self.eyes.blink()
            self.eyes.shake_refuse()


class EyeRenderService(Service):
    name = "eye_render"

    def __init__(self, raspi_state: RaspiStateStore, bot=None, *, width: int = 128, height: int = 64):
        self.raspi_state = raspi_state
        self.bot: Bot = bot
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

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            bot = self.bot
            left_lcd = eyes2.lcd_frame.LCDDisplay()
            right_lcd = eyes2.lcd_frame.LCDDisplay()
            eyes = eyes2.Eyes(left_lcd, right_lcd)
            eyes.auto_blink = True
            eyes.apply_rounded_rectangle(48, 48, 12)

            last_tick_time = time.time()
            next_random_movement = PlainFaceMovement(eyes)

            while not self._stop.is_set():
                now = time.time()
                dt = now - last_tick_time
                last_tick_time = now
                eyes.tick(dt)
                eyes.render()
                bot.eyes.update_from_surfaces(left_lcd.surf, right_lcd.surf)
                time.sleep(1 / 60)

                next_random_movement.duration -= dt
                if next_random_movement.duration <= 0:
                    next_random_movement.cleanup()
                    movement_class = random.choice([
                        ShakeHeadMovement,
                        SadFaceMovement,
                        HappyFaceMovement,
                        PlainFaceMovement,
                        LookAroundWonderMovement,
                        LookAroundAngryMovement,
                    ])
                    next_random_movement = movement_class(eyes)

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
