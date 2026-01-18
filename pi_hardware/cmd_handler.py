from __future__ import annotations

from typing import Callable
import time
import os

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
    def clamp(v: float, lo: float, hi: float) -> float:
        return lo if v < lo else hi if v > hi else v

    # Smooth motor state (normalized -1..1 style speeds)
    ACCEL_RATE = 1.8
    DECEL_RATE = 2.4
    MAX_SPEED = 1.0
    motor_state = {
        "left": 0.0,
        "right": 0.0,
        "run": 0.0,
        "turn": 0.0,
        "last_ts": time.time(),
    }

    def status_payload():
        try:
            state_val = raspi_state.get_robot_state().value
        except Exception:
            state_val = None
        status = {"state": state_val}
        try:
            motors = getattr(robot, "motors", None)
            status["motors_enabled"] = bool(motors and getattr(motors, "enabled", False))

            def _unwrap(val):
                if val is None:
                    return None
                try:
                    return float(getattr(val, "rps", val))
                except Exception:
                    return None

            status["motors_left_rps"] = _unwrap(getattr(motors, "left", None))
            status["motors_right_rps"] = _unwrap(getattr(motors, "right", None))

            batt = getattr(robot, "battery", None)
            if batt:
                status["battery"] = {
                    "voltage": float(getattr(batt, "voltage", 0.0)),
                    "cell_voltage": float(getattr(batt, "cell_voltage", 0.0)),
                    "cells": int(getattr(batt, "cells", 0)),
                    "percentage": float(getattr(batt, "percentage", 0.0)),
                }
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

    def _apply_wheel_speeds(target_left: float, target_right: float, *, enable: bool = True):
        """
        Smoothly ramp motor speeds toward targets (normalized units) to avoid jerks.
        """
        now = time.time()
        dt = now - motor_state["last_ts"]
        motor_state["last_ts"] = now
        dt = min(dt, 0.2)

        def _ramp(current: float, target: float) -> float:
            rate = ACCEL_RATE if abs(target) > abs(current) else DECEL_RATE
            step = rate * dt
            if current < target:
                return min(target, current + step)
            return max(target, current - step)

        cur_left, cur_right = motor_state["left"], motor_state["right"]
        next_left = _ramp(cur_left, clamp(target_left, -MAX_SPEED, MAX_SPEED))
        next_right = _ramp(cur_right, clamp(target_right, -MAX_SPEED, MAX_SPEED))

        motor_state["left"] = next_left
        motor_state["right"] = next_right
        motor_state["run"] = (next_left + next_right) * 0.5
        motor_state["turn"] = (next_left - next_right) * 0.5

        try:
            robot.motors.enabled = bool(enable)
            robot.motors.left = float(next_left)
            robot.motors.right = float(next_right)
        except Exception:
            # fallback to MotorController API if present
            try:
                robot.drive(next_left, next_right)
            except Exception:
                pass

    def _apply_head(payload: dict):
        try:
            dyaw = payload.get("dyaw")
            dpitch = payload.get("dpitch")
            yaw = payload.get("yaw")
            pitch = payload.get("pitch")

            dyaw = float(dyaw) if dyaw is not None else None
            dpitch = float(dpitch) if dpitch is not None else None
            yaw = float(yaw) if yaw is not None else None
            pitch = float(pitch) if pitch is not None else None
        except Exception:
            return {"ok": False, "error": "invalid yaw/pitch/dyaw/dpitch"}

        current_yaw = float(getattr(getattr(robot, "head", None), "yaw", 0.0))
        current_pitch = float(getattr(getattr(robot, "head", None), "pitch", 0.0))

        yaw_target = yaw if yaw is not None else current_yaw + (dyaw or 0.0)
        pitch_target = pitch if pitch is not None else current_pitch + (dpitch or 0.0)

        yaw_min = float(os.environ.get("PI_HEAD_YAW_MIN", "-60"))
        yaw_max = float(os.environ.get("PI_HEAD_YAW_MAX", "60"))
        pitch_min = float(os.environ.get("PI_HEAD_PITCH_MIN", "-30"))
        pitch_max = float(os.environ.get("PI_HEAD_PITCH_MAX", "45"))

        yaw_target = max(yaw_min, min(yaw_max, yaw_target))
        pitch_target = max(pitch_min, min(pitch_max, pitch_target))

        try:
            robot.head.yaw = yaw_target
            robot.head.pitch = pitch_target
            return {"ok": True, "head": {"yaw": yaw_target, "pitch": pitch_target}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    def handler(payload):
        cmd_raw = payload.get("cmd") or ""
        cmd = cmd_raw.lower()
        if cmd == "stop":
            _apply_wheel_speeds(0.0, 0.0)
            try:
                raspi_state.set_movement(speed=0.0, turn=0.0)
            except Exception:
                pass
            return _resp(True)
        if cmd == "motors_control":
            motor_enable = bool(payload.get("enable", True))
            print(f"[pi_robot] motors_control: enable={motor_enable}")
            _apply_wheel_speeds(0.0, 0.0, enable=motor_enable)
            try:
                raspi_state.set_movement(speed=0.0, turn=0.0)
            except Exception:
                pass
            return _resp(True)
        if cmd == "cmd_vel":
            v = float(payload.get("v", 0.0))
            w = float(payload.get("w", 0.0))
            target_run = clamp(v, -MAX_SPEED, MAX_SPEED)
            target_turn = clamp(w, -MAX_SPEED, MAX_SPEED)
            target_left = target_run + target_turn
            target_right = target_run - target_turn
            _apply_wheel_speeds(target_left, target_right, enable=True)
            try:
                raspi_state.set_movement(speed=float(target_run), turn=float(target_turn))
            except Exception:
                pass
            return _resp(True, rps={"left": motor_state["left"], "right": motor_state["right"]})
        if cmd == "reset_head":
            robot.head.yaw = 0.0
            robot.head.pitch = 0.0
            return _resp(True, head={"yaw": 0.0, "pitch": 0.0})
        if cmd == "set_head":
            result = _apply_head(payload)
            if isinstance(result, dict) and result.get("ok"):
                return _resp(True, head=result.get("head"))
            return result if isinstance(result, dict) else {"ok": False, "error": "head update failed"}
        if cmd in {"visual_state", "visual"}:
            visual = payload.get("state") or payload.get("visual") or payload.get("result") or {}
            if isinstance(visual, dict):
                raspi_state.set_visual_state(visual)
                return _resp(True, visual=visual)
            return {"ok": False, "error": "visual payload must be a dict"}
        return {"ok": False, "error": "unknown cmd"}

    handler.status_payload = status_payload
    handler.robot = robot
    handler.raspi_state = raspi_state
    handler.set_state = set_state
    return handler
