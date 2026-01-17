import os
import threading
import time
import sys
import multiprocessing as mp

from core.services import Service
from states.raspi_states import RaspiStateStore

class PiDebugDisplayService(Service):
    """Optional local pygame overlay showing robot status."""

    name = "pi_debug_display"

    def __init__(self, raspi_state: RaspiStateStore):
        self._enabled = os.environ.get("PI_DEBUG_LOCAL", "0") == "1"
        self._raspi_state = raspi_state
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._proc: mp.Process | None = None
        self._mp_stop: mp.Event | None = None
        self._mp_queue: mp.Queue | None = None

    def start(self):
        if not self._enabled or self._thread:
            return

        if sys.platform == "darwin":
            # On macOS, pygame must run on the main thread of its own process.
            self._start_macos_display()
            return

        def runner():
            try:
                import pygame
            except Exception:
                print("[pi_robot] pygame not available; debug window disabled.")
                return

            pygame.init()
            screen = pygame.display.set_mode((800, 480), pygame.RESIZABLE)
            pygame.display.set_caption("Pi Robot Debug")
            font = pygame.font.SysFont("Menlo", 16)
            clock = pygame.time.Clock()
            scroll = 0
            while not self._stop.is_set():
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._stop.set()
                        break
                    if event.type == pygame.VIDEORESIZE:
                        screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                    if event.type == pygame.MOUSEBUTTONDOWN:
                        if event.button == 4:  # scroll up
                            scroll = min(scroll + 30, 0)
                        elif event.button == 5:  # scroll down
                            scroll -= 30
                raspi_state = self._raspi_state.snapshot_dict()
                visual = raspi_state.get("visual", {})
                sections = _build_sections(raspi_state, visual)
                scroll = _render_sections(screen, font, sections, scroll)
                pygame.display.flip()
                clock.tick(10)
            pygame.quit()

        self._stop.clear()
        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

    def stop(self):
        if self._proc:
            if self._mp_stop:
                self._mp_stop.set()
            self._proc.join(timeout=2.0)
            self._proc = None
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=1.0)
            self._thread = None
        self._stop.clear()

    def _start_macos_display(self):
        if self._proc:
            return

        def producer(stop_evt: threading.Event, queue: mp.Queue):
            while not stop_evt.is_set():
                try:
                    queue.put(self._raspi_state.snapshot_dict(), timeout=0.1)
                except Exception:
                    pass
                time.sleep(0.5)

        self._stop.clear()
        self._mp_stop = mp.Event()
        self._mp_queue = mp.Queue()
        prod_thread = threading.Thread(target=producer, args=(self._stop, self._mp_queue), daemon=True)
        prod_thread.start()
        self._thread = prod_thread
        self._proc = mp.Process(target=_mp_pygame_consumer, args=(self._mp_stop, self._mp_queue), daemon=True)
        self._proc.start()


def _mp_pygame_consumer(stop_evt: mp.Event, queue: mp.Queue):
    """Run the pygame display loop in a separate process (macOS-friendly)."""
    try:
        import pygame
    except Exception:
        print("[pi_robot] pygame not available; debug window disabled.")
        return

    pygame.init()
    screen = pygame.display.set_mode((800, 480), pygame.RESIZABLE)
    pygame.display.set_caption("Pi Robot Debug")
    font = pygame.font.SysFont("Menlo", 16)
    clock = pygame.time.Clock()
    latest = {}
    scroll = 0
    while not stop_evt.is_set():
        try:
            while True:
                latest = queue.get_nowait()
        except Exception:
            pass
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                stop_evt.set()
                break
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 4:
                    scroll = min(scroll + 30, 0)
                elif event.button == 5:
                    scroll -= 30
        raspi_state = latest or {}
        visual = raspi_state.get("visual", {})
        sections = _build_sections(raspi_state, visual)
        scroll = _render_sections(screen, font, sections, scroll)
        pygame.display.flip()
        clock.tick(10)
    pygame.quit()


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    curr = ""
    for word in words:
        candidate = word if not curr else f"{curr} {word}"
        if font.size(candidate)[0] <= max_width:
            curr = candidate
        else:
            if curr:
                lines.append(curr)
            curr = word
    if curr:
        lines.append(curr)
    return lines


def _build_sections(raspi_state: dict, visual: dict) -> list[tuple[str, list[str]]]:
    pi_status = raspi_state.get("pi_status", {})
    movement = raspi_state.get("movement", {})
    events = raspi_state.get("events", [])
    controller = raspi_state.get("controller", {})
    task_manager = raspi_state.get("task_manager", {})
    tasks_section = []
    if task_manager:
        current = task_manager.get("current")
        queue = task_manager.get("queue") or task_manager.get("_queue") or []
        tasks_section.append(f"current: {current}")
        tasks_section.append(f"queue: {queue}")
    state_label = pi_status.get("state") or raspi_state.get("robot_state")
    sections = [
        ("Status", [f"State: {state_label}"]),
        ("Pi Status", [f"Connected: {pi_status.get('connected')}", f"Last ts: {pi_status.get('last_ts')}"]),
        ("Movement", [f"speed: {movement.get('speed')}", f"turn: {movement.get('turn')}"]),
        ("Controller", [f"active: {controller.get('active')}", f"sticks/buttons: {controller}"]),
        ("Visual", [f"{visual}"]),
        ("Tasks", tasks_section if tasks_section else ["(empty)"]),
        ("Raw Raspi", [_safe_repr(raspi_state)]),
        ("Events", [f"count: {len(events)}"]),
    ]
    return sections


def _render_sections(screen, font, sections: list[tuple[str, list[str]]], scroll: int) -> int:
    screen.fill((20, 20, 20))
    max_w = screen.get_width() - 20
    y = 10 + scroll
    header_color = (180, 220, 255)
    text_color = (240, 240, 240)
    for title, items in sections:
        header = font.render(title, True, header_color)
        screen.blit(header, (10, y))
        y += 20
        for item in items:
            for wrapped in _wrap_text(str(item), font, max_width=max_w):
                surf = font.render(f"• {wrapped}", True, text_color)
                screen.blit(surf, (20, y))
                y += 20
        y += 6
    return scroll


def _safe_repr(val):
    try:
        return repr(val)
    except Exception:
        return "<unreprable>"
