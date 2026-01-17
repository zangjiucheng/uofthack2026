from enum import Enum
import os

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
        set_state(PiRobotState.IDLE)
        return

    sticks = ctrl.get("sticks") or {}
    try:
        lx = float(sticks.get("LX", 0))
        ly = float(sticks.get("LY", 0))
    except Exception:
        lx = ly = 0.0

    # Convert -127..127 stick values to [-1, 1] with a small deadzone.
    def normalize_axis(v: float, deadzone: float = 6.0) -> float:
        val = v / 127.0
        if abs(val) < deadzone / 127.0:
            return 0.0
        return max(-1.0, min(1.0, val))

    throttle = -normalize_axis(ly)  # LY up should drive forward
    turn = normalize_axis(lx)       # LX left/right for turning

    # Scale to motor commands (tune as needed)
    linear_gain = float(os.environ.get("PI_DRIVE_LINEAR", "0.8"))
    angular_gain = float(os.environ.get("PI_DRIVE_ANGULAR", "0.6"))
    v_cmd = throttle * linear_gain
    w_cmd = turn * angular_gain

    # Use robot drive if available
    try:
        cmd_handler({"cmd": "cmd_vel", "v": v_cmd, "w": w_cmd})
        raspi_state.set_movement(speed=float(v_cmd), turn=float(w_cmd))
    except Exception:
        pass


def handle_error(cmd_handler):
    """TODO: implement ERROR handling logic."""
    raise NotImplementedError("handle_error is not implemented yet")


def handle_deticscan(cmd_handler):
    """TODO: implement DETICSCAN handling logic."""
    raise NotImplementedError("handle_deticscan is not implemented yet")


def handle_facescan(cmd_handler):
    """TODO: implement FACESCAN handling logic."""
    raise NotImplementedError("handle_facescan is not implemented yet")


def handle_losetarget(cmd_handler):
    """TODO: implement LOSETARGET handling logic."""
    raise NotImplementedError("handle_losetarget is not implemented yet")


def handle_tracking(cmd_handler):
    """TODO: implement TRACKING handling logic."""
    raise NotImplementedError("handle_tracking is not implemented yet")


def handle_approach(cmd_handler):
    """Example approach handler: consume a task then return to IDLE when done."""
    print("[pi_robot] Handling APPROACH state")
    raspi_state = getattr(cmd_handler, "raspi_state", None)
    set_state = getattr(cmd_handler, "set_state", None)
    task_manager = getattr(raspi_state, "task_manager", None) if raspi_state else None
    # Placeholder: here you would add navigation/approach logic.
    # For now, immediately finish the task and return to IDLE.
    if task_manager:
        try:
            task_manager.finish_current()
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
        try:
            cmd_handler({"cmd": "stop"})
        except Exception:
            pass
        task_manager = getattr(raspi_state, "task_manager", None) if raspi_state else None
        if task_manager:
            try:
                task_manager.clear()
            except Exception:
                pass
        set_state(PiRobotState.INIT)
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
