from __future__ import annotations

from dataclasses import dataclass
from typing import List, Callable

from pi_hardware.lcd.model import EyeState, FaceState
from pi_hardware.lcd.utils import clamp, lerp, ease_in_out, ease_out, ease_in


@dataclass
class Keyframe:
    t: float  # seconds from start
    left: EyeState
    right: EyeState
    ease: Callable[[float], float] = ease_in_out


class Timeline:
    """
    A simple keyframe timeline. It interpolates numeric fields of EyeState.
    """

    def __init__(self, frames: List[Keyframe]):
        if not frames:
            raise ValueError("Timeline requires at least one keyframe.")
        self.frames = sorted(frames, key=lambda k: k.t)
        self.duration = self.frames[-1].t

    @staticmethod
    def _interp_eye(a: EyeState, b: EyeState, t: float) -> EyeState:
        return EyeState(
            look_x=lerp(a.look_x, b.look_x, t),
            look_y=lerp(a.look_y, b.look_y, t),
            open=lerp(a.open, b.open, t),
            squint=lerp(a.squint, b.squint, t),
            tilt_deg=lerp(a.tilt_deg, b.tilt_deg, t),
            roundness=lerp(a.roundness, b.roundness, t),
            brow=lerp(a.brow, b.brow, t),
            heart=a.heart if t < 0.5 else b.heart,
            heart_scale=lerp(a.heart_scale, b.heart_scale, t),
        )

    def sample(self, t_abs: float, loop: bool = True) -> FaceState:
        if self.duration <= 0:
            k = self.frames[0]
            return FaceState(k.left, k.right)

        t = t_abs % self.duration if loop else clamp(t_abs, 0.0, self.duration)

        i = 0
        while i + 1 < len(self.frames) and not (self.frames[i].t <= t <= self.frames[i + 1].t):
            i += 1
        if i + 1 >= len(self.frames):
            k = self.frames[-1]
            return FaceState(k.left, k.right)

        k0, k1 = self.frames[i], self.frames[i + 1]
        seg = k1.t - k0.t
        if seg <= 1e-9:
            return FaceState(k1.left, k1.right)

        u = (t - k0.t) / seg
        u = k1.ease(u)
        return FaceState(
            left=self._interp_eye(k0.left, k1.left, u),
            right=self._interp_eye(k0.right, k1.right, u),
        )


# Ready-made “emotions”
def neutral() -> FaceState:
    e = EyeState(open=1.0, squint=0.0, roundness=0.60, brow=0.0)
    return FaceState(left=e, right=EyeState(**e.__dict__))


def happy() -> FaceState:
    l = EyeState(open=0.90, squint=0.55, roundness=0.75, brow=0.15, tilt_deg=-2.0)
    r = EyeState(open=0.90, squint=0.55, roundness=0.75, brow=0.15, tilt_deg=2.0)
    return FaceState(l, r)


def angry() -> FaceState:
    l = EyeState(open=0.95, squint=0.15, roundness=0.40, brow=-0.55, tilt_deg=4.0)
    r = EyeState(open=0.95, squint=0.15, roundness=0.40, brow=-0.55, tilt_deg=-4.0)
    return FaceState(l, r)


def sleepy() -> FaceState:
    l = EyeState(open=0.35, squint=0.30, roundness=0.60, brow=0.20)
    r = EyeState(open=0.35, squint=0.30, roundness=0.60, brow=0.20)
    return FaceState(l, r)


def love() -> FaceState:
    l = EyeState(open=0.95, squint=0.10, roundness=0.95, brow=0.45, tilt_deg=-4.0, look_x=-0.08, look_y=-0.05, heart=True)
    r = EyeState(open=0.95, squint=0.10, roundness=0.95, brow=0.45, tilt_deg=4.0, look_x=0.08, look_y=-0.05, heart=True)
    return FaceState(l, r)


def surprised() -> FaceState:
    l = EyeState(open=1.0, squint=0.0, roundness=0.95, brow=0.35, tilt_deg=0.0)
    r = EyeState(open=1.0, squint=0.0, roundness=0.95, brow=0.35, tilt_deg=0.0)
    return FaceState(l, r)


def wink_left() -> FaceState:
    l = EyeState(open=0.05, squint=0.8, roundness=0.6, brow=-0.05, tilt_deg=-4.0)
    r = EyeState(open=0.95, squint=0.15, roundness=0.70, brow=0.10, tilt_deg=2.0)
    return FaceState(l, r)


def wink_right() -> FaceState:
    r = EyeState(open=0.05, squint=0.8, roundness=0.6, brow=-0.05, tilt_deg=4.0)
    l = EyeState(open=0.95, squint=0.15, roundness=0.70, brow=0.10, tilt_deg=-2.0)
    return FaceState(l, r)


def look(face: FaceState, x: float, y: float) -> FaceState:
    l = EyeState(**face.left.__dict__)
    r = EyeState(**face.right.__dict__)
    l.look_x, l.look_y = x, y
    r.look_x, r.look_y = x, y
    return FaceState(l, r)


def make_blink_timeline(base: FaceState, period_s: float = 3.5, blink_s: float = 0.18) -> Timeline:
    t0 = 0.0
    t_b = max(0.05, period_s - blink_s)
    t1 = t_b + blink_s * 0.45  # close
    t2 = t_b + blink_s  # reopen

    open_face = base
    closed_l = EyeState(**base.left.__dict__); closed_l.open = 0.02
    closed_r = EyeState(**base.right.__dict__); closed_r.open = 0.02
    closed_face = FaceState(closed_l, closed_r)

    return Timeline([
        Keyframe(t0, open_face.left, open_face.right, ease=ease_in_out),
        Keyframe(t_b, open_face.left, open_face.right, ease=ease_in_out),
        Keyframe(t1, closed_face.left, closed_face.right, ease=ease_in),
        Keyframe(t2, open_face.left, open_face.right, ease=ease_out),
        Keyframe(period_s, open_face.left, open_face.right, ease=ease_in_out),
    ])


def make_emotion_transition(a: FaceState, b: FaceState, duration_s: float = 0.35) -> Timeline:
    return Timeline([
        Keyframe(0.0, a.left, a.right, ease=ease_in_out),
        Keyframe(duration_s, b.left, b.right, ease=ease_in_out),
    ])


def make_glance_timeline(base: FaceState, x: float, y: float, *, travel_s: float = 0.25, hold_s: float = 0.35, return_s: float = 0.25) -> Timeline:
    t0 = 0.0
    t1 = travel_s
    t2 = t1 + hold_s
    t3 = t2 + return_s
    glanced = look(base, x, y)
    return Timeline([
        Keyframe(t0, base.left, base.right, ease=ease_in_out),
        Keyframe(t1, glanced.left, glanced.right, ease=ease_in_out),
        Keyframe(t2, glanced.left, glanced.right, ease=ease_in_out),
        Keyframe(t3, base.left, base.right, ease=ease_in_out),
    ])


def make_wink_timeline(base: FaceState, *, which: str = "left", duration_s: float = 0.3, hold_s: float = 0.2) -> Timeline:
    wink_face = wink_left() if which.lower().startswith("l") else wink_right()
    t0 = 0.0
    t1 = duration_s * 0.6
    t2 = t1 + hold_s
    t3 = t2 + duration_s * 0.4
    return Timeline([
        Keyframe(t0, base.left, base.right, ease=ease_in_out),
        Keyframe(t1, wink_face.left, wink_face.right, ease=ease_in),
        Keyframe(t2, wink_face.left, wink_face.right, ease=ease_out),
        Keyframe(t3, base.left, base.right, ease=ease_in_out),
    ])


def make_heart_zoom_timeline(base: FaceState | None = None, *, min_scale: float = 0.6, max_scale: float = 1.15, period_s: float = 1.4) -> Timeline:
    start = love() if base is None else base
    small = FaceState(
        EyeState(**{**start.left.__dict__, "heart": True, "heart_scale": min_scale}),
        EyeState(**{**start.right.__dict__, "heart": True, "heart_scale": min_scale}),
    )
    big = FaceState(
        EyeState(**{**start.left.__dict__, "heart": True, "heart_scale": max_scale}),
        EyeState(**{**start.right.__dict__, "heart": True, "heart_scale": max_scale}),
    )
    t0 = 0.0
    t1 = period_s * 0.4
    t2 = period_s * 0.7
    t3 = period_s
    return Timeline([
        Keyframe(t0, small.left, small.right, ease=ease_in_out),
        Keyframe(t1, big.left, big.right, ease=ease_out),
        Keyframe(t2, small.left, small.right, ease=ease_in_out),
        Keyframe(t3, small.left, small.right, ease=ease_in_out),
    ])
