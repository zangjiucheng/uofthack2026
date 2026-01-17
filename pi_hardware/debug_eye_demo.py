# debug_eye_demo.py
"""
Run from repo root: `python pi_hardware/debug_eye_demo.py`
Opens a pygame window to preview animated LCD eyes (ESC or close to exit).
"""

import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

# Ensure repo root is on sys.path so `pi_hardware` can be imported when run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pi_hardware.lcd import (  # noqa: E402
    EyeRenderer,
    DualDisplay,
    FaceState,
    make_blink_timeline,
    make_emotion_transition,
    make_glance_timeline,
    make_heart_zoom_timeline,
    neutral,
    happy,
    angry,
    sleepy,
    surprised,
    wink_left,
    wink_right,
)


class PygameDualDisplay:
    """
    Minimal DualDisplay that blits left/right eye images into a pygame window.
    Press ESC or close the window to exit.
    """

    def __init__(self, width: int, height: int, scale: int = 3):
        import pygame

        self.width = width
        self.height = height
        self.scale = max(1, int(scale))
        pygame.init()
        self.screen = pygame.display.set_mode((width * self.scale * 2, height * self.scale))
        pygame.display.set_caption("LCD Eyes Demo")

    def send(self, left_img: Image.Image, right_img: Image.Image) -> None:
        import pygame

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise KeyboardInterrupt
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                raise KeyboardInterrupt

        def to_surface(img: Image.Image):
            surf = pygame.image.fromstring(img.convert("RGB").tobytes(), img.size, "RGB")
            if self.scale != 1:
                surf = pygame.transform.scale(surf, (img.width * self.scale, img.height * self.scale))
            return surf

        self.screen.fill((0, 0, 0))
        self.screen.blit(to_surface(left_img), (0, 0))
        self.screen.blit(to_surface(right_img), (self.width * self.scale, 0))
        pygame.display.flip()


if __name__ == "__main__":
    import pygame

    WIDTH, HEIGHT = 128, 64  # Adjust to your target LCD resolution
    FPS = 15
    RUN_SECONDS: Optional[float] = None  # None = loop until ESC/close

    display = PygameDualDisplay(width=WIDTH, height=HEIGHT, scale=3)
    dual = DualDisplay(left=display, right=display)  # reuse sender for both eyes

    renderer = EyeRenderer(width=WIDTH, height=HEIGHT)
    base_face = neutral()

    # State map and helpers
    STATES = {
        "1": ("neutral", neutral),
        "2": ("happy", happy),
        "3": ("angry", angry),
        "4": ("sleepy", sleepy),
        "5": ("surprised", surprised),
        "6": ("love_pulse", lambda: make_heart_zoom_timeline()),
        "q": ("wink_left", wink_left),
        "w": ("wink_right", wink_right),
        "a": ("glance_left", lambda: make_glance_timeline(base_face, x=-0.5, y=0.0)),
        "d": ("glance_right", lambda: make_glance_timeline(base_face, x=0.5, y=0.0)),
    }

    current_face = base_face
    timeline = make_blink_timeline(base_face, period_s=2.5, blink_s=0.2)
    transition: Optional[Tuple[float, float, any]] = None  # (start_time, duration, timeline)

    clock = pygame.time.Clock()
    t0 = time.perf_counter()
    try:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise KeyboardInterrupt
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        raise KeyboardInterrupt
                    key = pygame.key.name(event.key)
                    if key in STATES:
                        name, factory = STATES[key]
                        try:
                            new_face_or_tl = factory()
                            if isinstance(new_face_or_tl, FaceState):
                                tl = make_emotion_transition(current_face, new_face_or_tl, duration_s=0.25)
                                current_face = new_face_or_tl
                            else:
                                tl = new_face_or_tl
                            timeline = tl
                            t0 = time.perf_counter()
                            print(f"[demo] switched to {name}")
                        except Exception as exc:
                            print(f"[demo] failed to switch {name}: {exc}")

            t = time.perf_counter() - t0
            if RUN_SECONDS is not None and t >= RUN_SECONDS:
                break
            face = timeline.sample(t, loop=True)
            left_img, right_img = renderer.render_face(face)
            display.send(left_img, right_img)
            clock.tick(FPS)
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()
