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
            shape=a.shape if t < 0.5 else b.shape,
            shape_scale=lerp(a.shape_scale, b.shape_scale, t),
            shape_x_scale=lerp(a.shape_x_scale, b.shape_x_scale, t),
            shape_y_scale=lerp(a.shape_y_scale, b.shape_y_scale, t),
            pupil=a.pupil if t < 0.5 else b.pupil,
            pupil_scale=lerp(a.pupil_scale, b.pupil_scale, t),
            pupil_x=lerp(a.pupil_x, b.pupil_x, t),
            pupil_y=lerp(a.pupil_y, b.pupil_y, t),
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


def _with_eye(eye: EyeState, **updates: float | bool) -> EyeState:
    data = dict(eye.__dict__)
    data.update(updates)
    return EyeState(**data)


def _with_face(face: FaceState, *, left: EyeState | None = None, right: EyeState | None = None) -> FaceState:
    return FaceState(left or EyeState(**face.left.__dict__), right or EyeState(**face.right.__dict__))


def _blink(face: FaceState, *, open_amt: float = 0.05) -> FaceState:
    return FaceState(
        _with_eye(face.left, open=open_amt),
        _with_eye(face.right, open=open_amt),
    )


def _wink(face: FaceState, *, which: str) -> FaceState:
    if which.lower().startswith("l"):
        return FaceState(
            _with_eye(face.left, open=0.05, squint=0.85, tilt_deg=-4.0),
            _with_eye(face.right, open=0.95, squint=0.20, tilt_deg=2.0),
        )
    return FaceState(
        _with_eye(face.left, open=0.95, squint=0.20, tilt_deg=-2.0),
        _with_eye(face.right, open=0.05, squint=0.85, tilt_deg=4.0),
    )


def make_straight_man_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.95, squint=0.08, roundness=0.15, brow=-0.20, tilt_deg=-1.0, shape="square"),
        EyeState(open=0.95, squint=0.08, roundness=0.15, brow=-0.20, tilt_deg=1.0, shape="square"),
    )
    glance_r = look(base, 0.35, 0.0)
    glance_l = look(base, -0.20, 0.0)
    blink = _blink(base, open_amt=0.04)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.6, glance_r.left, glance_r.right),
        Keyframe(1.1, base.left, base.right),
        Keyframe(1.35, blink.left, blink.right, ease=ease_in),
        Keyframe(1.5, base.left, base.right, ease=ease_out),
        Keyframe(2.0, glance_l.left, glance_l.right),
        Keyframe(2.6, base.left, base.right),
    ])


def make_straight_woman_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.98, squint=0.12, roundness=0.78, brow=0.10, tilt_deg=-2.0, shape="round_rect"),
        EyeState(open=0.98, squint=0.12, roundness=0.78, brow=0.10, tilt_deg=2.0, shape="round_rect"),
    )
    glance_up = look(base, 0.15, -0.25)
    glance_left = look(base, -0.25, 0.05)
    blink = _blink(base, open_amt=0.06)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.5, glance_up.left, glance_up.right),
        Keyframe(1.0, base.left, base.right),
        Keyframe(1.25, blink.left, blink.right, ease=ease_in),
        Keyframe(1.4, base.left, base.right, ease=ease_out),
        Keyframe(2.0, glance_left.left, glance_left.right),
        Keyframe(2.7, base.left, base.right),
    ])


def make_lesbian_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.94, squint=0.20, roundness=0.65, brow=-0.05, tilt_deg=-2.0, shape="circle"),
        EyeState(open=0.94, squint=0.20, roundness=0.65, brow=-0.05, tilt_deg=2.0, shape="circle"),
    )
    wink = _wink(base, which="left")
    glance_left = look(base, -0.35, 0.0)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.4, wink.left, wink.right, ease=ease_in),
        Keyframe(0.7, base.left, base.right, ease=ease_out),
        Keyframe(1.2, glance_left.left, glance_left.right),
        Keyframe(1.9, base.left, base.right),
    ])


def make_gay_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.96, squint=0.30, roundness=0.78, brow=0.15, tilt_deg=-3.0, shape="star", shape_scale=0.9),
        EyeState(open=0.96, squint=0.30, roundness=0.78, brow=0.15, tilt_deg=3.0, shape="star", shape_scale=0.9),
    )
    wink = _wink(base, which="right")
    glance_right = look(base, 0.35, 0.0)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.45, wink.left, wink.right, ease=ease_in),
        Keyframe(0.8, base.left, base.right, ease=ease_out),
        Keyframe(1.3, glance_right.left, glance_right.right),
        Keyframe(2.0, base.left, base.right),
    ])


def make_bisexual_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.98, squint=0.10, roundness=0.65, brow=0.05, tilt_deg=-1.0, shape="round"),
        EyeState(open=0.98, squint=0.10, roundness=0.65, brow=0.05, tilt_deg=1.0, shape="round"),
    )
    glance_l = look(base, -0.35, 0.0)
    glance_r = look(base, 0.35, 0.0)
    blink1 = _blink(base, open_amt=0.05)
    blink2 = _blink(base, open_amt=0.08)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.5, glance_l.left, glance_l.right),
        Keyframe(1.0, base.left, base.right),
        Keyframe(1.25, blink1.left, blink1.right, ease=ease_in),
        Keyframe(1.4, base.left, base.right, ease=ease_out),
        Keyframe(1.7, glance_r.left, glance_r.right),
        Keyframe(2.1, base.left, base.right),
        Keyframe(2.3, blink2.left, blink2.right, ease=ease_in),
        Keyframe(2.45, base.left, base.right, ease=ease_out),
        Keyframe(2.9, base.left, base.right),
    ])


def make_trans_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.97, squint=0.12, roundness=0.68, brow=0.20, tilt_deg=-1.5, shape="diamond", shape_scale=0.95),
        EyeState(open=0.97, squint=0.12, roundness=0.68, brow=0.20, tilt_deg=1.5, shape="diamond", shape_scale=0.95),
    )
    glance_up = look(base, 0.0, -0.35)
    glance_down = look(base, 0.0, 0.35)
    blink = _blink(base, open_amt=0.06)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.6, glance_up.left, glance_up.right),
        Keyframe(1.2, base.left, base.right),
        Keyframe(1.5, glance_down.left, glance_down.right),
        Keyframe(2.0, base.left, base.right),
        Keyframe(2.2, blink.left, blink.right, ease=ease_in),
        Keyframe(2.35, base.left, base.right, ease=ease_out),
        Keyframe(2.9, base.left, base.right),
    ])


def make_queer_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=1.0, squint=0.0, roundness=0.90, brow=0.25, tilt_deg=-2.0, shape="heart", heart_scale=0.75),
        EyeState(open=1.0, squint=0.0, roundness=0.90, brow=0.25, tilt_deg=2.0, shape="heart", heart_scale=0.75),
    )
    big = FaceState(
        _with_eye(base.left, heart=True, heart_scale=1.15),
        _with_eye(base.right, heart=True, heart_scale=1.15),
    )
    glance = look(base, 0.15, -0.15)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.5, big.left, big.right, ease=ease_out),
        Keyframe(0.9, base.left, base.right, ease=ease_in_out),
        Keyframe(1.4, glance.left, glance.right),
        Keyframe(2.0, base.left, base.right),
    ])


def make_minimal_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=1.0, squint=0.0, roundness=1.0, shape="round"),
        EyeState(open=1.0, squint=0.0, roundness=1.0, shape="round"),
    )
    glance_left = look(base, -0.35, 0.0)
    glance_right = look(base, 0.35, 0.0)
    return Timeline([
        Keyframe(0.0, glance_left.left, glance_left.right),
        Keyframe(1.6, glance_right.left, glance_right.right),
        Keyframe(3.2, glance_left.left, glance_left.right),
    ])


def make_playful_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.96, squint=0.05, roundness=0.70, shape="star", shape_scale=1.4, shape_y_scale=1.35, look_x=0.45, look_y=-0.35),
        EyeState(open=0.96, squint=0.05, roundness=0.70, shape="star", shape_scale=1.4, shape_y_scale=1.35, look_x=0.45, look_y=-0.35),
    )
    wink = _wink(base, which="left")
    p1 = look(base, 0.55, -0.25)
    p2 = look(base, 0.35, -0.45)
    p3 = look(base, 0.50, -0.15)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.35, wink.left, wink.right, ease=ease_in),
        Keyframe(0.7, base.left, base.right, ease=ease_out),
        Keyframe(0.5, p1.left, p1.right, ease=ease_in_out),
        Keyframe(1.0, p2.left, p2.right, ease=ease_in_out),
        Keyframe(1.4, p3.left, p3.right, ease=ease_in_out),
        Keyframe(1.9, base.left, base.right, ease=ease_in_out),
    ])


def make_tech_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.95, squint=0.05, roundness=0.30, shape="round_rect"),
        EyeState(open=0.95, squint=0.05, roundness=0.30, shape="round_rect"),
    )
    open_wide = FaceState(
        _with_eye(base.left, open=0.75, squint=0.2),
        _with_eye(base.right, open=1.0, squint=0.0),
    )
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.8, open_wide.left, open_wide.right, ease=ease_in_out),
        Keyframe(2.2, open_wide.left, open_wide.right, ease=ease_in_out),
    ])


def make_creative_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.95, squint=0.18, roundness=0.75, shape="glow", tilt_deg=-1.5, look_x=-0.15),
        EyeState(open=0.90, squint=0.10, roundness=0.75, shape="glow", tilt_deg=2.5, look_x=0.2),
    )
    sway_left = look(base, -0.25, -0.1)
    sway_right = look(base, 0.25, 0.1)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.8, sway_left.left, sway_left.right),
        Keyframe(1.6, sway_right.left, sway_right.right),
        Keyframe(2.4, base.left, base.right),
    ])


def make_noir_timeline() -> Timeline:
    base = FaceState(
        EyeState(open=0.55, squint=0.55, roundness=0.2, brow=-0.25, tilt_deg=-2.0, shape="round_rect"),
        EyeState(open=0.55, squint=0.55, roundness=0.2, brow=-0.25, tilt_deg=2.0, shape="round_rect"),
    )
    glance_left = look(base, -0.35, 0.0)
    glance_right = look(base, 0.35, 0.0)
    blink = _blink(base, open_amt=0.03)
    return Timeline([
        Keyframe(0.0, base.left, base.right),
        Keyframe(0.8, glance_left.left, glance_left.right),
        Keyframe(1.4, base.left, base.right),
        Keyframe(1.65, blink.left, blink.right, ease=ease_in),
        Keyframe(1.8, base.left, base.right, ease=ease_out),
        Keyframe(2.4, glance_right.left, glance_right.right),
        Keyframe(3.0, base.left, base.right),
    ])
