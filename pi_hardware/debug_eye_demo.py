# debug_eye_demo.py
"""
Run from repo root: `python pi_hardware/debug_eye_demo.py`
Opens a pygame window to preview animated LCD eyes (ESC or close to exit).
"""

import sys
import math
import time
from pathlib import Path
from typing import Optional, Tuple, Any, Callable, Dict

from PIL import Image

# Ensure repo root is on sys.path so `pi_hardware` can be imported when run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pi_hardware.lcd import (  # noqa: E402
    EyeRenderer,
    EyeStyle,
    EyeState,
    FaceState,
    make_blink_timeline,
    make_heart_zoom_timeline,
    make_minimal_timeline,
    make_playful_timeline,
    make_tech_timeline,
    make_noir_timeline,
)


class PygameDualDisplay:
    """
    Minimal DualDisplay that blits left/right eye images into a pygame window.
    Press ESC or close the window to exit.
    """

    def __init__(self, width: int, height: int, scale: int = 3, extra_height: int = 0):
        import pygame

        self.width = width
        self.height = height
        self.scale = max(1, int(scale))
        self.extra_height = max(0, int(extra_height))
        pygame.init()
        self.screen = pygame.display.set_mode((width * self.scale * 2, height * self.scale + self.extra_height))
        pygame.display.set_caption("LCD Eyes Demo")

    def send(self, left_img: Image.Image, right_img: Image.Image) -> None:
        import pygame

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

    SCALE = 3
    EYE_W = WIDTH * SCALE
    EYE_H = HEIGHT * SCALE
    DRAW_H = EYE_H
    BUTTON_H = 40

    display = PygameDualDisplay(width=WIDTH, height=HEIGHT, scale=SCALE, extra_height=BUTTON_H)
    renderer = EyeRenderer(width=WIDTH, height=HEIGHT, style=EyeStyle(mode="L", fg=255, bg=0, aa_scale=2))

    def playful_style(t: float) -> Dict[str, int]:
        fg = int(180 + 60 * (0.5 + 0.5 * math.sin(t * 3.0)))
        return {"fg": max(0, min(255, fg))}

    def tech_style(t: float) -> Dict[str, int]:
        fg = int(210 + 30 * (0.5 + 0.5 * math.sin(t * 1.8)))
        return {"fg": max(0, min(255, fg))}

    def no_style(_: float) -> Dict[str, int]:
        return {"fg": 255}

    SELECTIONS: Dict[str, Dict[str, Any]] = {
        "1": {"label": "Clean — ellipse", "kind": "timeline", "factory": make_minimal_timeline, "style_fn": no_style},
        "2": {"label": "Playful — far angle star", "kind": "timeline", "factory": make_playful_timeline, "style_fn": playful_style},
        "3": {"label": "In love — heart", "kind": "timeline", "factory": make_heart_zoom_timeline, "style_fn": no_style},
        "4": {"label": "Tech — round rectangle", "kind": "timeline", "factory": make_tech_timeline, "style_fn": tech_style},
        "5": {"label": "Noir — slit gaze, slow scan", "kind": "timeline", "factory": make_noir_timeline, "style_fn": no_style},
    }

    def prompt_choice() -> Dict[str, Any]:
        print("Select an eye animation:")
        for key, spec in SELECTIONS.items():
            print(f"  {key}) {spec['label']}")
        while True:
            choice = input("Enter choice (1,2,3,4,5): ").strip()
            if choice in SELECTIONS:
                return SELECTIONS[choice]
            print("Invalid choice. Try again.")

    def apply_blink(img: Image.Image, open_amt: float) -> Image.Image:
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

    def convert_board(surface: "pygame.Surface") -> Image.Image:
        import pygame

        data = pygame.image.tostring(surface, "RGB")
        img = Image.frombytes("RGB", surface.get_size(), data).convert("L")
        img = img.resize((WIDTH, HEIGHT), resample=Image.LANCZOS)
        return img

    def reset_board(surface: "pygame.Surface") -> None:
        surface.fill((0, 0, 0))

    def select_by_key(key: str) -> Dict[str, Any]:
        return SELECTIONS[key]

    state: Dict[str, Any] = {
        "label": "",
        "timeline": make_minimal_timeline(),
        "style_fn": no_style,
        "custom_active": False,
        "draw_mode": False,
    }
    custom_left = Image.new("L", (WIDTH, HEIGHT), color=0)
    custom_right = Image.new("L", (WIDTH, HEIGHT), color=0)
    custom_timeline = make_blink_timeline(FaceState(EyeState(open=1.0), EyeState(open=1.0)), period_s=2.5, blink_s=0.2)

    def activate_selection(spec: Dict[str, Any]) -> None:
        state["label"] = spec["label"]
        state["style_fn"] = spec["style_fn"]
        if spec["kind"] == "custom":
            state["draw_mode"] = True
            state["custom_active"] = False
        else:
            state["timeline"] = spec["factory"]()
            state["custom_active"] = False
            state["draw_mode"] = False
        print(f"[demo] selected {state['label']}")

    activate_selection(prompt_choice())

    clock = pygame.time.Clock()
    t0 = time.perf_counter()
    try:
        while True:
            if state["draw_mode"]:
                left_board = pygame.Surface((EYE_W, DRAW_H))
                reset_board(left_board)
                drawing = False
                last_pos: Optional[Tuple[int, int]] = None

                font = pygame.font.SysFont(None, 24)
                button_rect = pygame.Rect((EYE_W * 2 - 160) // 2, EYE_H + 4, 160, BUTTON_H - 8)

                while state["draw_mode"]:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            raise KeyboardInterrupt
                        if event.type == pygame.KEYDOWN:
                            if event.key == pygame.K_ESCAPE:
                                raise KeyboardInterrupt
                            key = pygame.key.name(event.key)
                            if key in SELECTIONS and key != "6":
                                activate_selection(select_by_key(key))
                                t0 = time.perf_counter()
                                break
                            if key == "c":
                                reset_board(left_board)
                        if event.type == pygame.MOUSEBUTTONDOWN:
                            mx, my = event.pos
                            if button_rect.collidepoint(mx, my):
                                custom_left = convert_board(left_board)
                                custom_right = custom_left.transpose(Image.FLIP_LEFT_RIGHT)
                                state["draw_mode"] = False
                                state["custom_active"] = True
                                t0 = time.perf_counter()
                                break
                            if 0 <= my < DRAW_H:
                                drawing = True
                                local_x = mx if mx < EYE_W else (EYE_W - (mx - EYE_W))
                                last_pos = (local_x, my)
                        if event.type == pygame.MOUSEBUTTONUP:
                            drawing = False
                            last_pos = None
                        if event.type == pygame.MOUSEMOTION and drawing:
                            mx, my = event.pos
                            if 0 <= my < DRAW_H:
                                buttons = pygame.mouse.get_pressed()
                                color = (0, 0, 0) if buttons[2] else (255, 255, 255)
                                pos_x = mx if mx < EYE_W else (EYE_W - (mx - EYE_W))
                                pos = (pos_x, my)
                                if last_pos is not None:
                                    pygame.draw.line(left_board, color, last_pos, pos, width=6)
                                pygame.draw.circle(left_board, color, pos, 4)
                                last_pos = pos

                    right_board = pygame.transform.flip(left_board, True, False)
                    display.screen.fill((0, 0, 0))
                    display.screen.blit(left_board, (0, 0))
                    display.screen.blit(right_board, (EYE_W, 0))

                    pygame.draw.rect(display.screen, (40, 40, 40), button_rect, border_radius=6)
                    pygame.draw.rect(display.screen, (200, 200, 200), button_rect, width=2, border_radius=6)
                    label_surf = font.render("Finish", True, (255, 255, 255))
                    display.screen.blit(label_surf, (button_rect.centerx - label_surf.get_width() // 2, button_rect.centery - label_surf.get_height() // 2))

                    hint = font.render("Draw on either side; right mirrors left. Right-click erases. C clears.", True, (180, 180, 180))
                    display.screen.blit(hint, (8, EYE_H + 10))
                    pygame.display.flip()
                    clock.tick(30)
                continue

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise KeyboardInterrupt
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        raise KeyboardInterrupt
                    key = pygame.key.name(event.key)
                    if key in SELECTIONS:
                        spec = select_by_key(key)
                        activate_selection(spec)
                        t0 = time.perf_counter()

            t = time.perf_counter() - t0
            if RUN_SECONDS is not None and t >= RUN_SECONDS:
                break
            style_updates = state["style_fn"](t)
            if "fg" in style_updates:
                renderer.style.fg = style_updates["fg"]
            if state["custom_active"]:
                face = custom_timeline.sample(t, loop=True)
                left_img = apply_blink(custom_left, face.left.open)
                right_img = apply_blink(custom_right, face.right.open)
            else:
                face = state["timeline"].sample(t, loop=True)
                left_img, right_img = renderer.render_face(face)
            display.send(left_img, right_img)
            clock.tick(FPS)
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()
