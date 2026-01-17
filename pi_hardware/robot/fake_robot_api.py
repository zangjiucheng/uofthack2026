"""
Lightweight fake robot_api.Bot implementation for local testing without hardware.

Exposes:
    bot.motors.left/right.rps (floats), bot.motors.enabled (bool)
    bot.head.yaw/pitch (floats)
    bot.position.x/y/direction and basic actions reset/forward/turn/face (no-op)

Used by cmd_handler to exercise the control path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _MotorSide:
    rps: float = 0.0


class _Motors:
    def __init__(self):
        self.left = _MotorSide()
        self.right = _MotorSide()
        self.enabled: bool = False


class _Head:
    def __init__(self):
        self.yaw: float = 0.0
        self.pitch: float = 0.0


class _Position:
    def __init__(self):
        self.x: float = 0.0
        self.y: float = 0.0
        self.direction: float = 0.0  # degrees

    def reset(self, x: float = 0.0, y: float = 0.0, dir: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.direction = float(dir)

    def forward(self, distance: float, velocity: float | None = None, **kwargs):
        # simple dead-reckoning update
        self.x += distance

    def turn(self, degrees: float, **kwargs):
        self.direction += degrees

    def face(self, direction: float, **kwargs):
        self.direction = direction


class FakeBot:
    def __init__(self, track_width: float = 0.30, wheel_radius: float = 0.05):
        self.motors = _Motors()
        self.head = _Head()
        self.position = _Position()
        self.track_width = track_width
        self.wheel_radius = wheel_radius

    def stop(self):
        self.motors.enabled = False
        self.motors.left.rps = 0.0
        self.motors.right.rps = 0.0
        print("[fake_bot] stop -> motors disabled, rps=0")

    def drive(self, left_rps: float, right_rps: float):
        self.motors.enabled = True
        self.motors.left.rps = float(left_rps)
        self.motors.right.rps = float(right_rps)
        print(f"[fake_bot] drive L={self.motors.left.rps:+.3f} rps, R={self.motors.right.rps:+.3f} rps")