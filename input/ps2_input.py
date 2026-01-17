import os
import sys
import threading
from queue import Empty, SimpleQueue
from typing import Dict

import pygame

sys.path.append(os.path.dirname(__file__))
from ps2_lib import PS2Reader  # noqa: E402
from sim_engine import GameWorld  # noqa: E402

# macOS often looks like "/dev/cu.usbmodemXXXX" or "/dev/cu.usbserialXXXX"
PORT = "/dev/cu.usbmodem1301"
BAUD = 115200

SCREEN = (960, 600)
BG = (10, 12, 18)
TEXT = (230, 235, 245)
ACCENT = (90, 180, 255)
CAR = (240, 120, 80)
GRID = (30, 34, 46)
DIM = (80, 90, 110)
ENEMY = (255, 94, 105)
BULLET = (255, 230, 120)
HEALTH = (200, 255, 180)
AXIS_DEADZONE = 6

BUTTON_ORDER = [
    "START",
    "SELECT",
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "L1",
    "R1",
    "L2",
    "R2",
    "L3",
    "R3",
    "CROSS",
    "CIRCLE",
    "SQUARE",
    "TRIANGLE",
]


def reader_worker(queue: SimpleQueue, stop: threading.Event):
    with PS2Reader(PORT, BAUD, timeout=1) as reader:
        for kind, payload, line in reader:
            if stop.is_set():
                break
            queue.put((kind, payload, line))


def draw_text(surface, text, pos, font, color=TEXT):
    surface.blit(font.render(text, True, color), pos)


def draw_grid(surface):
    for x in range(0, SCREEN[0], 40):
        pygame.draw.line(surface, GRID, (x, 0), (x, SCREEN[1]))
    for y in range(0, SCREEN[1], 40):
        pygame.draw.line(surface, GRID, (0, y), (SCREEN[0], y))


def draw_buttons(surface, buttons: Dict[str, int], origin, font):
    x, y = origin
    for name in BUTTON_ORDER:
        val = buttons.get(name, 0)
        color = ACCENT if val else DIM
        pygame.draw.rect(surface, color, (x, y, 120, 26), border_radius=6)
        draw_text(surface, name, (x + 8, y + 5), font, BG if val else TEXT)
        y += 30


def clamp01(val: float):
    return max(-1.0, min(1.0, val))


def main():
    pygame.init()
    screen = pygame.display.set_mode(SCREEN)
    pygame.display.set_caption("PS2 Robot Car")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Menlo", 18)

    queue: SimpleQueue = SimpleQueue()
    stop = threading.Event()
    thread = threading.Thread(target=reader_worker, args=(queue, stop), daemon=True)
    thread.start()

    sticks = {"LX": 128, "LY": 128, "RX": 128, "RY": 128}
    buttons: Dict[str, bool] = {name: False for name in BUTTON_ORDER}
    prev_buttons: Dict[str, bool] = buttons.copy()

    world = GameWorld(SCREEN[0], SCREEN[1])
    car = world.car
    paused = False
    drift_mode = False
    boost_mode = False
    base_max_speed = car.max_speed
    base_friction = car.friction

    try:
        while True:
            dt = clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise KeyboardInterrupt
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    world = GameWorld(SCREEN[0], SCREEN[1])
                    car = world.car
                    base_max_speed = car.max_speed
                    base_friction = car.friction
                    drift_mode = False
                    boost_mode = False

            while True:
                try:
                    kind, payload, raw = queue.get_nowait()
                except Empty:
                    break
                if kind == "sticks":
                    sticks.update(payload)
                elif kind == "kv":
                    prev_buttons = buttons.copy()
                    buttons.update({k.upper(): bool(v) for k, v in payload.items()})

            # Button edge actions
            def pressed(name: str) -> bool:
                return buttons.get(name, False) and not prev_buttons.get(name, False)

            if pressed("START"):
                world = GameWorld(SCREEN[0], SCREEN[1])
                car = world.car
                base_max_speed = car.max_speed
                base_friction = car.friction
                drift_mode = False
                boost_mode = False
            if pressed("SELECT"):
                paused = not paused
            if pressed("CIRCLE"):
                drift_mode = not drift_mode
                car.friction = 0.92 if drift_mode else base_friction
            if pressed("TRIANGLE"):
                boost_mode = not boost_mode
                car.max_speed = base_max_speed * (1.4 if boost_mode else 1.0)
            if buttons.get("R2") or buttons.get("L2"):
                world.attempt_fire()

            def normalize_axis(v: int) -> float:
                if abs(v) < AXIS_DEADZONE:
                    return 0.0
                return clamp01(v / 127.0)

            throttle = -normalize_axis(sticks["LY"])
            steer = normalize_axis(sticks["RX"])
            brake = bool(buttons.get("SQUARE", False))

            alive = world.player_health > 0
            if not paused and alive:
                world.update(throttle=throttle, steer=steer, brake=brake, dt=dt)

            screen.fill(BG)
            draw_grid(screen)
            pygame.draw.polygon(screen, CAR, car.as_polygon())
            for p in world.projectiles:
                pygame.draw.circle(screen, BULLET, (int(p.x), int(p.y)), 5)
            for e in world.enemies:
                pygame.draw.circle(screen, ENEMY, (int(e.x), int(e.y)), 18)
                hp_ratio = max(0.0, min(1.0, e.hp / 2))
                pygame.draw.rect(
                    screen,
                    DIM,
                    (int(e.x - 13), int(e.y - 22), 26, 4),
                    border_radius=3,
                )
                pygame.draw.rect(
                    screen,
                    HEALTH,
                    (int(e.x - 13), int(e.y - 22), int(26 * hp_ratio), 4),
                    border_radius=3,
                )

            draw_text(screen, f"Throttle (LY): {throttle:+.2f}", (20, 18), font)
            draw_text(screen, f"Steer (RX): {steer:+.2f}", (20, 42), font)
            draw_text(screen, f"Brake (Square): {int(brake)}", (20, 66), font)
            draw_text(screen, f"Paused (Select): {paused}", (20, 90), font)
            draw_text(screen, f"Drift (Circle): {drift_mode}", (20, 114), font)
            draw_text(screen, f"Boost (Triangle): {boost_mode}", (20, 138), font)
            draw_text(screen, f"Level: {world.level}", (20, 162), font, TEXT)
            draw_text(screen, f"Health: {world.player_health}", (20, 186), font, HEALTH)
            draw_text(screen, f"Kills: {world.kills}", (20, 210), font, ACCENT)
            if not alive:
                draw_text(screen, "Down! Press START or R to restart", (20, 234), font, ENEMY)
            draw_text(screen, "Press R to reset; hold L2/R2 to shoot", (20, 258), font, ACCENT)
            draw_text(screen, "Buttons", (800, 24), font, TEXT)
            draw_buttons(screen, buttons, (780, 50), font)
            pygame.display.flip()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        thread.join(timeout=1)
        pygame.quit()


if __name__ == "__main__":
    main()
