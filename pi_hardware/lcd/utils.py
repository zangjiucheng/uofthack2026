from __future__ import annotations

import time
from typing import Callable

EasingFn = Callable[[float], float]


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_in_out(t: float) -> float:
    # smoothstep-like
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def ease_out(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t


def now_s() -> float:
    return time.perf_counter()
