from enum import Enum
import os
import time
import json
import urllib.request

class PiRobotState(str, Enum):
    INIT = "INIT"
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    ERROR = "ERROR"
    DETICSCAN = "DETICSCAN"
    FACESCAN = "FACESCAN"
    LOSETARGET = "LOSETARGET"
    TRACKING = "TRACKING"
    APPROACH = "APPROACH"
    DISCOVER = "DISCOVER"
    APPROACHSTOP = "APPROACHSTOP"


ALLOWED_STATES = {state.value for state in PiRobotState}

def to_label(state: PiRobotState | str) -> str:
    """Human-friendly label for a robot state."""
    state_enum = state if isinstance(state, PiRobotState) else PiRobotState.__members__.get(str(state).upper())
    labels = {
        PiRobotState.INIT: "Initializing",
        PiRobotState.IDLE: "Idle",
        PiRobotState.MANUAL: "Manual Control",
        PiRobotState.ERROR: "Error",
        PiRobotState.DETICSCAN: "Detic Scan",
        PiRobotState.FACESCAN: "Face Scan",
        PiRobotState.LOSETARGET: "Lose Target",
        PiRobotState.TRACKING: "Tracking Target",
        PiRobotState.APPROACH: "Approaching Target",
        PiRobotState.DISCOVER: "Discovering Environment",
        PiRobotState.APPROACHSTOP: "Approach Stopped",
    }
    return labels.get(state_enum, str(state_enum or state))

def is_state(state: PiRobotState | str, target: PiRobotState) -> bool:
    if isinstance(state, PiRobotState):
        return state is target
    if isinstance(state, str):
        state_enum = PiRobotState.__members__.get(state.upper())
        return state_enum is target
    return False

def handle_init(cmd_handler):
    """In INIT, watch for controller TRIANGLE press to transition to IDLE."""
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    set_state = getattr(cmd_handler, "set_state", None)
    if not raspi_state or not set_state:
        return
    try:
        ctrl = raspi_state.get_controller_state()
    except Exception:
        return
    buttons = ctrl.get("buttons", {}) if isinstance(ctrl, dict) else {}
    if buttons.get("TRIANGLE"):
        set_state(PiRobotState.IDLE)

def handle_idle(cmd_handler):
    """In IDLE, watch controller activity: if active -> MANUAL; else start queued tasks."""
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    set_state = getattr(cmd_handler, "set_state", None)
    if not raspi_state or not set_state:
        return
    try:
        ctrl = raspi_state.get_controller_state()
    except Exception:
        return
    active = bool(ctrl.get("manual_activate"))
    if active:
        cmd_handler({"cmd": "motors_control", "enable": True})
        set_state(PiRobotState.MANUAL)
        return

    # If not manually activated, see if there's a task to run.
    task_manager = getattr(raspi_state, "task_manager", None)
    if task_manager:
        task = task_manager.current or task_manager.try_next()
        if task:
            kind = str(task.get("kind", "")).lower()
            if kind == "approach":
                print(f"[pi_robot] starting APPROACH task: {task}")
                set_state(PiRobotState.APPROACH)
            else:
                print(f"[pi_robot] unknown task kind: {kind}")
                task_manager.finish_current()


def handle_manual(cmd_handler):
    """
    In MANUAL, if controller goes inactive, fall back to IDLE.
    Also drive motors using LX/LY from the PS2 controller.
    """
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    set_state = getattr(cmd_handler, "set_state", None)
    if not raspi_state or not set_state:
        return
    try:
        ctrl = raspi_state.get_controller_state()
    except Exception:
        return
    active = bool(ctrl.get("manual_activate"))
    if not active:
        # stop motion and drop back to IDLE
        try:
            cmd_handler({"cmd": "stop"})
        except Exception:
            pass
        cmd_handler({"cmd": "motors_control", "enable": False})
        cmd_handler({"cmd": "reset_head"})
        set_state(PiRobotState.IDLE)
        return

    sticks = ctrl.get("sticks") or {}
    try:
        lx = float(sticks.get("LX", 0))
        ly = float(sticks.get("LY", 0))
        rx = float(sticks.get("RX", 0))
        ry = float(sticks.get("RY", 0))
    except Exception:
        lx = ly = rx = ry = 0.0
    buttons = ctrl.get("buttons", {}) if isinstance(ctrl, dict) else {}

    # Convert -127..127 stick values to [-1, 1] with a small deadzone.
    def normalize_axis(v: float, deadzone: float = 6.0) -> float:
        val = v / 127.0
        if abs(val) < deadzone / 127.0:
            return 0.0
        return max(-1.0, min(1.0, val))

    throttle = -normalize_axis(ly)  # LY up should drive forward
    turn = normalize_axis(lx)       # LX left/right for turning
    head_yaw = normalize_axis(rx) * 6.0    # RX for head yaw control
    head_pitch = -normalize_axis(ry) * 3.0  # RY for head pitch control

    # Scale to motor commands (tune as needed)
    linear_gain = float(os.environ.get("PI_DRIVE_LINEAR", "0.8"))
    angular_gain = float(os.environ.get("PI_DRIVE_ANGULAR", "0.6"))
    v_cmd = throttle * linear_gain
    w_cmd = turn * angular_gain

    # Use robot drive via L1
    if buttons.get("L1"):
        try:
            cmd_handler({"cmd": "cmd_vel", "v": v_cmd, "w": w_cmd})
            raspi_state.set_movement(speed=float(v_cmd), turn=float(w_cmd))
        except Exception:
            pass

    # Head control via R1
    if buttons.get("R1"):
        try:
            cmd_handler({"cmd": "set_head", "dyaw": head_yaw, "dpitch": head_pitch})
        except Exception:
            pass


def handle_error(cmd_handler):
    """
    On ERROR: stop motors, clear tasks, and reset to INIT.
    """
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    set_state = getattr(cmd_handler, "set_state", None)
    if raspi_state:
        try:
            if hasattr(raspi_state, "task_manager"):
                raspi_state.task_manager.clear()  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        cmd_handler({"cmd": "stop"})
        cmd_handler({"cmd": "motors_control", "enable": False})
    except Exception:
        pass
    if set_state:
        set_state(PiRobotState.INIT)


def handle_deticscan(cmd_handler, object_name: str = "") -> tuple | None:
    """
    Look for an object_name in the latest detic detections stored on raspi_state.
    Returns the detection bbox if found, otherwise None.
    """
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    if not raspi_state or not object_name:
        return None
    det = raspi_state.find_detic_detection(object_name)
    if det:
        print(f"[pi_robot] Detected {object_name}: bbox={det.get('bbox')}, score={det.get('score')}")
        try:
            raspi_state.log_event("detic_found", label=object_name, bbox=det.get("bbox"), score=det.get("score"))
        except Exception:
            pass
        return det.get("bbox")
    else:
        print(f"[pi_robot] {object_name} not found in detic detections")
    return None


def handle_facescan(cmd_handler, person_name: str = "") -> tuple | None:
    """
    Look for a person_name in the latest face detections stored on raspi_state.
    Returns the detection bbox if found, otherwise None.
    """
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    if not raspi_state or not person_name:
        return None
    det = raspi_state.find_face_detection(person_name)
    if det:
        print(f"[pi_robot] Found face {person_name}: bbox={det.get('bbox')}, sim={det.get('sim')}")
        try:
            raspi_state.log_event("face_found", label=person_name, bbox=det.get("bbox"), sim=det.get("sim"))
        except Exception:
            pass
        return det.get("bbox")
    else:
        print(f"[pi_robot] Face {person_name} not found")
    return None


def handle_losetarget(cmd_handler):
    """TODO: implement LOSETARGET handling logic."""
    raise NotImplementedError("handle_losetarget is not implemented yet")


def handle_tracking(cmd_handler):
    """
    Tracking loop: push ROI to backend, steer toward center_x, and stop when close enough.
    """
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    set_state = getattr(cmd_handler, "set_state", None)
    if not raspi_state:
        return

    try:
        snap = raspi_state.snapshot()
        visual = snap.visual if hasattr(snap, "visual") else {}
        track = visual.get("track") if isinstance(visual, dict) else {}
    except Exception:
        track = {}

    err_x = track.get("err_x") if isinstance(track, dict) else None
    area = track.get("area") if isinstance(track, dict) else None

    # Stop when close enough (area threshold).
    area_thresh = 22000 # 640 x 480 image, adjust as needed
    try:
        if area is not None and area >= area_thresh:
            try:
                cmd_handler({"cmd": "stop"})
                cmd_handler({"cmd": "motors_control", "enable": False})
            except Exception:
                pass
            if set_state:
                set_state(PiRobotState.APPROACHSTOP)
            return
    except Exception:
        pass

    if err_x is None:
        return

    try:
        cx_raw = err_x
        cx = float(cx_raw)
    except Exception:
        return

    # center_x/err_x is already normalized to [-1, 1] (0 means centered).
    cx = max(-1.0, min(1.0, cx))
    error = cx  # negative => target left, positive => right
    turn_gain = float(os.environ.get("PI_TRACK_TURN_GAIN", "1.0"))
    forward = float(os.environ.get("PI_TRACK_FORWARD", "0.0"))

    print(f"[pi_robot] TRACKING: err_x={err_x}, error={error:.3f}, area={area}, v_cmd={forward:.3f}, w_cmd={error * turn_gain:.3f}")

    w_cmd = max(-0.8, min(0.8, error * turn_gain))
    v_cmd = forward
    try:
        cmd_handler({"cmd": "cmd_vel", "v": v_cmd, "w": w_cmd})
    except Exception:
        pass


def handle_approach(cmd_handler):
    """Example approach handler: consume a task then return to IDLE when done."""
    print("[pi_robot] Handling APPROACH state")
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    set_state = getattr(cmd_handler, "set_state", None)
    task_manager = getattr(raspi_state, "task_manager", None) if raspi_state else None
    task = None
    if task_manager:
        task = task_manager.current or task_manager.try_next()

    target_type = (task or {}).get("target_type")
    target = (task or {}).get("target")

    def finish_and_next() -> bool:
        """Finish current task; if another exists, re-enter APPROACH."""
        if task_manager and task:
            try:
                task_manager.finish_current()
            except Exception:
                pass
            nxt = task_manager.try_next() if task_manager else None
            if nxt:
                if set_state:
                    set_state(PiRobotState.APPROACH)
                return True
        if set_state:
            set_state(PiRobotState.IDLE)
        return False

    def seed_tracking(bbox) -> bool:
        if not bbox:
            return False
        try:
            if raspi_state:
                current_visual = {}
                try:
                    snap = raspi_state.snapshot()
                    current_visual = snap.visual if hasattr(snap, "visual") else {}
                except Exception:
                    current_visual = {}
                merged_visual = dict(current_visual or {})
                merged_visual["track"] = {"ts": time.time(), "bbox": bbox}
                raspi_state.set_visual_state(merged_visual)
            # Push ROI to backend once when we acquire it.
            try:
                base = os.environ.get("APP_BACKEND_REST_URL", "http://127.0.0.1:8080").rstrip("/")
                url = f"{base}/set_tracking_roi"
                data = json.dumps({"bbox": bbox}).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=1.5) as resp:
                        resp.read()
                except Exception as e:
                    print(f"[pi_robot] Failed to set tracking ROI: {e}")
            except Exception:
                pass
            if set_state:
                set_state(PiRobotState.TRACKING)
            return True
        except Exception:
            return False

    scanners = {
        "object": ("object", lambda tgt: handle_deticscan(cmd_handler, object_name=str(tgt))),
        "person": ("person", lambda tgt: handle_facescan(cmd_handler, person_name=str(tgt))),
    }

    if target_type == "person":
        cmd_handler({"cmd": "reset_head"})
        cmd_handler({"cmd": "set_head", "yaw": 0.0, "pitch": 20.0})

    label, scanner = scanners.get(str(target_type).lower(), (None, None))
    if not scanner:
        print(f"[pi_robot] Unknown approach target: {task}")
        finish_and_next()
        return

    print(f"[pi_robot] Approaching {label}: {target}")
    bbox = None
    try:
        bbox = scanner(target)
    except Exception:
        bbox = None

    if not bbox:
        print(f"[pi_robot] {label} {target} not found, skipping task.")
        finish_and_next()
        return

    if seed_tracking(bbox):
        return

    # If tracking seed failed, finish and go idle/next.
    finish_and_next()

def handle_approachstop(cmd_handler):
    """Example approach stop handler: stop motion and return to IDLE."""
    print("[pi_robot] Handling APPROACHSTOP state")
    set_state = getattr(cmd_handler, "set_state", None)

    try:
        cmd_handler({"cmd": "stop"})
    except Exception:
        pass
    try:
        cmd_handler({"cmd": "motors_control", "enable": False})
    except Exception:
        pass

    try:
        base = os.environ.get("APP_BACKEND_REST_URL", "http://127.0.0.1:8080").rstrip("/")
        url = f"{base}/stop_tracking"
        req = urllib.request.Request(
            url,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                resp.read()
        except Exception as e:
            print(f"[pi_robot] Failed to stop tracking: {e}")
    except Exception:
        pass

    if set_state:
        set_state(PiRobotState.IDLE)

def handle_discover(*args, **kwargs):
    """TODO: implement DISCOVER handling logic."""
    raise NotImplementedError("handle_discover is not implemented yet")

# Map of state -> handler function so host loop can dispatch generically.
STATE_HANDLERS = {
    PiRobotState.INIT: handle_init,
    PiRobotState.IDLE: handle_idle,
    PiRobotState.MANUAL: handle_manual,
    PiRobotState.ERROR: handle_error,
    PiRobotState.DETICSCAN: handle_deticscan,
    PiRobotState.FACESCAN: handle_facescan,
    PiRobotState.LOSETARGET: handle_losetarget,
    PiRobotState.TRACKING: handle_tracking,
    PiRobotState.APPROACH: handle_approach,
    PiRobotState.DISCOVER: handle_discover,
    PiRobotState.APPROACHSTOP: handle_approachstop,
}


def _global_stop_guard(cmd_handler) -> bool:
    """
    Runs for every state: if L2 or R2 is pressed, stop and go to IDLE.
    Returns True if a stop/transition was performed.
    """
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    set_state = getattr(cmd_handler, "set_state", None)
    robot = getattr(cmd_handler, "robot", None)
    if not raspi_state or not set_state:
        return False
    try:
        ctrl = raspi_state.get_controller_state()
    except Exception:
        return False
    buttons = ctrl.get("buttons", {}) if isinstance(ctrl, dict) else {}
    # Global stop trigger
    if buttons.get("L2") or buttons.get("R2"):
        task_manager = getattr(raspi_state, "task_manager", None) if raspi_state else None
        if task_manager:
            try:
                task_manager.clear()
            except Exception:
                pass
        set_state(PiRobotState.INIT)
        try:
            cmd_handler({"cmd": "stop"})
            cmd_handler({"cmd": "motors_control", "enable": False})
        except Exception:
            pass

        try:
            base = os.environ.get("APP_BACKEND_REST_URL", "http://127.0.0.1:8080").rstrip("/")
            url = f"{base}/stop_tracking"
            req = urllib.request.Request(
                url,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    resp.read()
            except Exception as e:
                print(f"[pi_robot] Failed to stop tracking: {e}")
        except Exception:
            pass

        return True
    return False

def run_state_handler(cmd_handler) -> bool:
    """
    Execute the handler for a given state if available.
    Returns True when a handler was found and invoked, False otherwise.
    """
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    state_enum = raspi_state.get_robot_state() if raspi_state else None
    if state_enum is None:
        return False
    if state_enum != PiRobotState.INIT and _global_stop_guard(cmd_handler):
        return True
    handler = STATE_HANDLERS.get(state_enum)
    if not handler:
        return False
    handler(cmd_handler)
    return True

__all__ = [
    "PiRobotState",
    "ALLOWED_STATES",
    "STATE_HANDLERS",
    "to_label",
    "is_state",
    "handle_init",
    "handle_idle",
    "handle_manual",
    "handle_error",
    "handle_deticscan",
    "handle_facescan",
    "handle_losetarget",
    "handle_tracking",
    "handle_approach",
    "handle_discover",
    "run_state_handler",
]
