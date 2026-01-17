from __future__ import annotations

from typing import Callable
import math

from states.robot_fsm import PiRobotState
from states.raspi_states import RaspiStateStore


def make_cmd_handler(
    *,
    robot,  # expected to be robot_api.Bot() or duck-typed object with .motors/.head/.position
    set_state: Callable[[str | PiRobotState], bool],
    raspi_state: RaspiStateStore,
):
    """
    Build a simple command handler that drives hardware actions for the Pi.
    Supports linear/angular velocity (converted to wheel RPS), head control, and basic pose ops.
    """
    TRACK_WIDTH_M = float(getattr(robot, "track_width", 0.30) or 0.30)
    WHEEL_RADIUS_M = float(getattr(robot, "wheel_radius", 0.05) or 0.05)
    WHEEL_CIRC = 2 * math.pi * WHEEL_RADIUS_M

    def status_payload():
        try:
            state_val = raspi_state.get_robot_state().value
        except Exception:
            state_val = None
        status = {"state": state_val}
        try:
            status["motors_enabled"] = bool(getattr(robot, "motors", None) and getattr(robot.motors, "enabled", False))
            status["motors_left_rps"] = getattr(getattr(robot, "motors", None), "left", None) and getattr(
                robot.motors.left, "rps", None
            )
            status["motors_right_rps"] = getattr(getattr(robot, "motors", None), "right", None) and getattr(
                robot.motors.right, "rps", None
            )
        except Exception:
            pass
        try:
            raspi_state.set_pi_status(status)
        except Exception:
            pass
        return status

    def _resp(ok: bool, **extra):
        out = {"ok": ok, "status": status_payload()}
        out.update(extra)
        return out

    def _set_wheel_rps(left_rps: float, right_rps: float, *, enable: bool = True):
        try:
            robot.motors.enabled = bool(enable)
            robot.motors.left.rps = float(left_rps)
            robot.motors.right.rps = float(right_rps)
        except Exception:
            # fallback to MotorController API if present
            try:
                robot.drive(left_rps, right_rps)
            except Exception:
                pass

    def handler(payload):
        cmd_raw = payload.get("cmd") or ""
        cmd = cmd_raw.lower()
        if cmd == "stop":
            _set_wheel_rps(0.0, 0.0, enable=False)
            try:
                raspi_state.set_movement(speed=0.0, turn=0.0)
            except Exception:
                pass
            return _resp(True)
        if cmd == "cmd_vel":
            v = float(payload.get("v", 0.0))
            w = float(payload.get("w", 0.0))
            # Convert to wheel linear speeds then RPS.
            left = v - 0.5 * TRACK_WIDTH_M * w
            right = v + 0.5 * TRACK_WIDTH_M * w
            left_rps = left / WHEEL_CIRC
            right_rps = right / WHEEL_CIRC
            _set_wheel_rps(left_rps, right_rps, enable=True)
            return _resp(True, rps={"left": left_rps, "right": right_rps})
        if cmd == "set_head":
            yaw = float(payload.get("yaw", 0.0))
            pitch = float(payload.get("pitch", 0.0))
            try:
                robot.head.yaw = yaw
                robot.head.pitch = pitch
                return _resp(True, head={"yaw": yaw, "pitch": pitch})
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if cmd == "reset_pose":
            x = float(payload.get("x", 0.0))
            y = float(payload.get("y", 0.0))
            direction = float(payload.get("dir", payload.get("direction", 0.0)))
            try:
                robot.position.reset(x=x, y=y, dir=direction)
                return _resp(True, pose={"x": x, "y": y, "dir": direction})
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if cmd == "forward":
            dist = float(payload.get("distance", 0.0))
            vel = float(payload.get("velocity", payload.get("speed", 0.0)))
            try:
                robot.position.forward(distance=dist, velocity=vel)
                return _resp(True)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if cmd == "turn":
            deg = float(payload.get("degrees", payload.get("deg", 0.0)))
            try:
                robot.position.turn(degrees=deg)
                return _resp(True)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if cmd == "face":
            direction = float(payload.get("direction", payload.get("dir", 0.0)))
            try:
                robot.position.face(direction=direction)
                return _resp(True)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if cmd in {"visual_state", "visual"}:
            visual = payload.get("state") or payload.get("visual") or payload.get("result") or {}
            if isinstance(visual, dict):
                raspi_state.set_visual_state(visual)
                return _resp(True, visual=visual)
            return {"ok": False, "error": "visual payload must be a dict"}
        if cmd == "status":
            return _resp(True)
        return {"ok": False, "error": "unknown cmd"}

    handler.status_payload = status_payload
    handler.robot = robot
    handler.raspi_state = raspi_state
    handler.set_state = set_state
    return handler
