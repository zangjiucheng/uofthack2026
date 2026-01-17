from __future__ import annotations

from pi_hardware.lcd.animations import Timeline
from pi_hardware.lcd.renderer import EyeRenderer
from pi_hardware.lcd.drivers import DualDisplay
from pi_hardware.lcd.utils import now_s
import time


class EyePlayer:
    def __init__(self, displays: DualDisplay, renderer: EyeRenderer, fps: int = 30):
        self.displays = displays
        self.renderer = renderer
        self.fps = max(1, int(fps))

    def play(self, timeline: Timeline, duration_s: float | None = None, loop: bool = True) -> None:
        """
        Push frames to the two displays.
        If duration_s is None and loop=True: runs forever.
        """
        dt = 1.0 / self.fps
        t_start = now_s()
        while True:
            t = now_s() - t_start
            if duration_s is not None and t >= duration_s:
                break
            face = timeline.sample(t, loop=loop)
            left_img, right_img = self.renderer.render_face(face)
            self.displays.send(left_img, right_img)
            # basic frame pacing
            time.sleep(dt)
