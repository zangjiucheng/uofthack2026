"""
Keyboard-driven PS2 controller simulator.

Emits PS2-style events (`kind`, `payload`, `raw`) so downstream code can treat
it like `input.ps2_lib.PS2Reader` output. A small wrapper keeps the old
`start_keyboard_teleop` name, translating left-stick motion into linear/angular
velocities.
"""

from __future__ import annotations

import select
import sys
import termios
import threading
import time
import tty
from typing import Callable, Dict, Optional, Tuple

# Buttons mimic the Arduino PS2 serial output
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

STICK_AXES = ("LX", "LY", "RX", "RY")

# Key bindings (lower-cased) for sticks and buttons
STICK_KEYS = {
    "w": ("LY", -1),
    "s": ("LY", 1),
    "a": ("LX", -1),
    "d": ("LX", 1),
    "i": ("RY", -1),
    "k": ("RY", 1),
    "j": ("RX", -1),
    "l": ("RX", 1),
}

BUTTON_KEYS = {
    "1": "START",
    "2": "SELECT",
    "t": "TRIANGLE",
    "x": "CROSS",
    "c": "CIRCLE",
    "z": "SQUARE",
    "f": "L1",
    "g": "R1",
    "v": "L2",
    "b": "R2",
    "[": "L3",
    "]": "R3",
}

DPAD_KEYS = {
    "ARROW_UP": "UP",
    "ARROW_DOWN": "DOWN",
    "ARROW_LEFT": "LEFT",
    "ARROW_RIGHT": "RIGHT",
}


def _print_help():
    print(
        "[teleop] keyboard PS2 controls:\n"
        "  - Sticks: WASD for LX/LY, IJKL for RX/RY\n"
        "  - Buttons: 1=START, 2=SELECT, T=Triangle, X=Cross, C=Circle, Z=Square\n"
        "             F=L1, G=R1, V=L2, B=R2, [=L3, ]=R3, arrows=D-pad\n"
        "  - Q quits the teleop loop"
    )


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


def _read_key() -> str:
    """
    Read a single key (including arrow escape sequences) from stdin.
    Returns a sentinel name like ARROW_UP for arrow keys.
    """
    ch = sys.stdin.read(1)
    if not ch:
        return ""
    if ch == "\x1b":  # escape sequence for arrows
        seq = sys.stdin.read(2)
        if seq == "[A":
            return "ARROW_UP"
        if seq == "[B":
            return "ARROW_DOWN"
        if seq == "[C":
            return "ARROW_RIGHT"
        if seq == "[D":
            return "ARROW_LEFT"
        return ""
    return ch


def _format_sticks_raw(sticks: Dict[str, int]) -> str:
    return "sticks " + ",".join(f"{axis}={int(sticks.get(axis, 0))}" for axis in STICK_AXES)


def _format_buttons_raw(buttons: Dict[str, bool]) -> str:
    return "buttons " + ",".join(f"{name}={1 if buttons.get(name) else 0}" for name in BUTTON_ORDER)


def start_fake_ps2_input(
    on_event: Callable[[str, Dict, str], None],
    stop_event: threading.Event,
    *,
    axis_step: int = 18,
    decay_rate: int = 12,
    poll_interval: float = 0.02,
    heartbeat: float = 0.3,
    button_hold: float = 0.35,
) -> Optional[threading.Thread]:
    """
    Start a background thread that converts keyboard input to PS2-like events.

    on_event(kind, payload, raw_line) is invoked for:
      - kind == "sticks" with LX/LY/RX/RY ints in [-127, 127]
      - kind == "kv" with all button states as bools
    """
    if not sys.stdin.isatty():
        print("[teleop] stdin is not a TTY; keyboard teleop disabled.")
        return None

    def loop():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        _print_help()

        sticks: Dict[str, int] = {axis: 0 for axis in STICK_AXES}
        buttons: Dict[str, bool] = {name: False for name in BUTTON_ORDER}
        button_expiry: Dict[str, float] = {}
        last_buttons_emit = 0.0
        last_sticks_emit = 0.0

        def emit_state(force: bool = False):
            nonlocal last_buttons_emit, last_sticks_emit
            now = time.time()
            if force or (now - last_sticks_emit) >= heartbeat:
                try:
                    on_event("sticks", dict(sticks), _format_sticks_raw(sticks))
                except Exception:
                    pass
                last_sticks_emit = now
            if force or (now - last_buttons_emit) >= heartbeat:
                try:
                    on_event("kv", dict(buttons), _format_buttons_raw(buttons))
                except Exception:
                    pass
                last_buttons_emit = now

        try:
            while not stop_event.is_set():
                now = time.time()
                changed_sticks = False
                changed_buttons = False

                # Decay sticks toward center so movement stops when keys are released.
                for axis in STICK_AXES:
                    val = sticks.get(axis, 0)
                    if val == 0:
                        continue
                    delta = decay_rate if val > 0 else -decay_rate
                    new_val = val - delta
                    if (val > 0 and new_val < 0) or (val < 0 and new_val > 0):
                        new_val = 0
                    new_val = _clamp(new_val, -127, 127)
                    if new_val != val:
                        sticks[axis] = new_val
                        changed_sticks = True

                # Auto-release momentary buttons.
                expired = [name for name, ts in button_expiry.items() if now >= ts]
                for name in expired:
                    if buttons.get(name):
                        buttons[name] = False
                        changed_buttons = True
                    button_expiry.pop(name, None)

                rlist, _, _ = select.select([sys.stdin], [], [], poll_interval)
                if rlist:
                    key = _read_key()
                    if not key:
                        continue
                    key_lower = key.lower()
                    if key_lower == "q":
                        stop_event.set()
                        break
                    if key in DPAD_KEYS:
                        btn = DPAD_KEYS[key]
                        buttons[btn] = True
                        button_expiry[btn] = now + button_hold
                        changed_buttons = True
                    elif key_lower in BUTTON_KEYS:
                        btn = BUTTON_KEYS[key_lower]
                        buttons[btn] = True
                        button_expiry[btn] = now + button_hold
                        changed_buttons = True
                    elif key_lower in STICK_KEYS:
                        axis, direction = STICK_KEYS[key_lower]
                        new_val = _clamp(sticks[axis] + direction * axis_step, -127, 127)
                        if new_val != sticks[axis]:
                            sticks[axis] = new_val
                            changed_sticks = True

                if changed_sticks:
                    last_sticks_emit = 0.0  # force emit below
                if changed_buttons:
                    last_buttons_emit = 0.0

                emit_state(force=False)
            # Final zeroed state to ensure downstream consumers stop.
            sticks = {axis: 0 for axis in STICK_AXES}
            buttons = {name: False for name in BUTTON_ORDER}
            emit_state(force=True)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def start_keyboard_teleop(
    cmd_callback: Callable[[float, float], None],
    stop_event: threading.Event,
    *,
    linear: float = 0.8,
    angular: float = 0.6,
) -> Optional[threading.Thread]:
    """
    Backward-compatible wrapper that drives cmd_callback(v, w) from left stick.
    """

    def on_event(kind: str, payload: Dict, raw: str):
        if kind != "sticks":
            return
        try:
            lx = float(payload.get("LX", 0) or 0)
            ly = float(payload.get("LY", 0) or 0)
        except Exception:
            return

        def normalize_axis(val: float, deadzone: float = 6.0) -> float:
            v_norm = val / 127.0
            if abs(v_norm) < deadzone / 127.0:
                return 0.0
            return max(-1.0, min(1.0, v_norm))

        throttle = -normalize_axis(ly)
        turn = normalize_axis(lx)
        v_cmd = throttle * linear
        w_cmd = turn * angular
        try:
            cmd_callback(v_cmd, w_cmd)
        except Exception:
            pass

    return start_fake_ps2_input(on_event, stop_event)


__all__ = ["start_fake_ps2_input", "start_keyboard_teleop"]
