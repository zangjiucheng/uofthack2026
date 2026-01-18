"""
Lightweight Pi state store (no absolute pose). Captures telemetry/heartbeats and
event log for frontend consumption.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
import threading
import time

from states.event_states import Event
from states.robot_fsm import PiRobotState


class TaskManager:
    """Minimal single-threaded task queue (thread-safe via internal lock)."""

    def __init__(self):
        self._queue: list[dict] = []
        self.current: dict | None = None
        self._lock = threading.Lock()

    def enqueue(self, task: dict) -> bool:
        if not isinstance(task, dict):
            return False
        if not task.get("kind"):
            return False
        with self._lock:
            self._queue.append(task)
        return True

    def try_next(self) -> dict | None:
        with self._lock:
            if self.current is not None:
                return self.current
            if not self._queue:
                return None
            self.current = self._queue.pop(0)
            return self.current

    def finish_current(self):
        with self._lock:
            self.current = None

    def clear(self):
        with self._lock:
            self._queue.clear()
            self.current = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "current": self.current if self.current else None,
                "queue": list(self._queue),
            }


@dataclass
class MovementState:
    """Latest robot drive command/state."""

    ts: float = 0.0
    speed: float = 0.0   # linear-ish speed
    turn: float = 0.0    # turn rate


@dataclass
class RaspiState:
    pi_status: Dict[str, Any] = field(default_factory=lambda: {"connected": False, "last_ts": 0.0})
    events: List[Event] = field(default_factory=list)
    movement: MovementState = field(default_factory=MovementState)
    visual: Dict[str, Any] = field(default_factory=dict)
    controller: Dict[str, Any] = field(default_factory=dict)
    robot_state: PiRobotState = PiRobotState.INIT

    def log_event(self, kind: str, **data):
        evt = Event(time.time(), kind, data)
        self.events.append(evt)
        return evt

    def set_pi_status(self, status: Dict[str, Any]):
        """Track latest Pi status/heartbeat pushed from host <-> pi bridge."""
        now = time.time()
        merged = dict(self.pi_status)
        merged.update(status or {})
        # Inline battery info into pi_status if provided
        batt = status.get("battery") if isinstance(status, dict) else None
        if isinstance(batt, dict):
            merged["battery"] = dict(batt)
        # Consider anything beyond INIT as an active connection.
        state_val = merged.get("state")
        if state_val and str(state_val).upper() != PiRobotState.INIT.value:
            merged["connected"] = True
        merged.setdefault("connected", True)
        merged["last_ts"] = now
        self.pi_status = merged
        if "state" in merged:
            self.set_robot_state(merged["state"])

    def set_movement(
        self,
        *,
        speed: Optional[float] = None,
        turn: Optional[float] = None,
    ):
        """
        Record the latest drive command/odometry-ish state.
        """
        now = time.time()
        curr = self.movement
        speed = float(speed) if speed is not None else curr.speed
        turn = float(turn) if turn is not None else curr.turn
        self.movement = MovementState(
            ts=now,
            speed=speed,
            turn=turn,
        )
        return self.movement

    def set_visual(self, visual: Dict[str, Any]):
        self.visual = dict(visual)
        return self.visual

    def set_controller(self, controller: Dict[str, Any]):
        self.controller = dict(controller)
        return self.controller

    def set_robot_state(self, state: str | PiRobotState):
        if isinstance(state, PiRobotState):
            self.robot_state = state
            return self.robot_state
        if isinstance(state, str):
            state_enum = PiRobotState.__members__.get(state.upper())
            if state_enum:
                self.robot_state = state_enum
        return self.robot_state


@dataclass
class RaspiStateStore:
    """
    Thread-safe singleton-style wrapper around RaspiState so other services
    can share telemetry/events without passing mutable objects around.
    """

    _state: RaspiState = field(default_factory=RaspiState)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    task_manager: TaskManager = field(default_factory=TaskManager)
    max_events: int = 2000

    def snapshot(self) -> RaspiState:
        """Return a shallow copy of the current state (events/movement cloned)."""
        with self._lock:
            src = self._state
            state = RaspiState(
                pi_status=dict(src.pi_status),
                events=list(src.events),
                movement=MovementState(
                    ts=src.movement.ts,
                    speed=src.movement.speed,
                    turn=src.movement.turn,
                ),
                visual=dict(src.visual),
                controller=dict(src.controller),
                robot_state=src.robot_state,
            )
            # monkey-patch task_manager snapshot onto the dataclass dict for debug display
            state.extra = {"task_manager": self.task_manager.snapshot()}  # type: ignore[attr-defined]
        return state

    def snapshot_dict(self) -> dict:
        snap = self.snapshot()
        data = asdict(snap)
        extra = getattr(snap, "extra", None)
        if isinstance(extra, dict):
            data.update(extra)
        return data

    def log_event(self, kind: str, **data) -> Event:
        with self._lock:
            evt = self._state.log_event(kind, **data)
            if self.max_events and len(self._state.events) > self.max_events:
                self._state.events = self._state.events[-self.max_events :]
            return evt

    def set_pi_status(self, status: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._state.set_pi_status(status)
            return dict(self._state.pi_status)

    def set_movement(
        self,
        *,
        speed: Optional[float] = None,
        turn: Optional[float] = None,
    ) -> MovementState:
        with self._lock:
            return self._state.set_movement(speed=speed, turn=turn)

    def set_visual_state(self, visual: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            return self._state.set_visual(visual)

    def set_controller_state(self, controller: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            return self._state.set_controller(controller)

    def set_robot_state(self, state: str | PiRobotState) -> PiRobotState:
        with self._lock:
            return self._state.set_robot_state(state)

    def get_robot_state(self) -> PiRobotState:
        with self._lock:
            return self._state.robot_state

    def set_cpu_temp(self, temp_c: float) -> float:
        with self._lock:
            try:
                status = dict(self._state.pi_status)
                status["cpu_temp"] = float(temp_c)
                self._state.pi_status = status
            except Exception:
                pass
            return self._state.pi_status.get("cpu_temp", 0.0)

    def get_controller_state(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state.controller)

    def find_detic_detection(self, label: str) -> Dict[str, Any] | None:
        """
        Return the highest-score detic detection matching the given label (case-insensitive).
        Looks in visual['detic']['detections'] which is expected to be a list of dicts.
        """
        if not label:
            return None
        target = str(label).lower()
        best = None
        best_score = float("-inf")
        with self._lock:
            detic = {}
            try:
                detic = self._state.visual.get("detic", {})
            except Exception:
                detic = {}
            detections = detic.get("detections") if isinstance(detic, dict) else None
            if not isinstance(detections, list):
                return None
            for det in detections:
                if not isinstance(det, dict):
                    continue
                lbl = str(det.get("label", "")).lower()
                if lbl != target:
                    continue
                score = float(det.get("score", 0.0)) if det.get("score") is not None else 0.0
                if score > best_score:
                    best_score = score
                    best = det
        return best

    def find_face_detection(self, label: str) -> Dict[str, Any] | None:
        """
        Return the highest-similarity face detection matching the given label (case-insensitive).
        Looks in visual['face']['faces'] which is expected to be a list of dicts.
        """
        if not label:
            return None
        target = str(label).lower()
        best = None
        best_sim = float("-inf")
        with self._lock:
            face_block = {}
            try:
                face_block = self._state.visual.get("face", {})
            except Exception:
                face_block = {}
            faces = face_block.get("faces") if isinstance(face_block, dict) else None
            if not isinstance(faces, list):
                return None
            for det in faces:
                if not isinstance(det, dict):
                    continue
                lbl = str(det.get("label", "")).lower()
                if lbl != target:
                    continue
                sim = float(det.get("sim", 0.0)) if det.get("sim") is not None else 0.0
                if sim > best_sim:
                    best_sim = sim
                    best = det
        return best

    def load_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """
        Overwrite current raspi state from an external snapshot dict (e.g., WS).
        """
        if not isinstance(snapshot, dict):
            return
        with self._lock:
            try:
                # Restore pi_status and robot_state
                pi_status = snapshot.get("pi_status", {})
                if isinstance(pi_status, dict):
                    self._state.pi_status = dict(pi_status)
                    if "state" in pi_status:
                        self._state.set_robot_state(pi_status["state"])

                # Movement
                mv = snapshot.get("movement", {})
                if isinstance(mv, dict):
                    try:
                        ts = float(mv.get("ts", 0.0))
                        speed = float(mv.get("speed", 0.0))
                        turn = float(mv.get("turn", 0.0))
                        self._state.movement = MovementState(ts=ts, speed=speed, turn=turn)
                    except Exception:
                        pass

                # Visual and controller
                if isinstance(snapshot.get("visual"), dict):
                    self._state.visual = dict(snapshot["visual"])
                if isinstance(snapshot.get("controller"), dict):
                    self._state.controller = dict(snapshot["controller"])

                # Events (optional)
                events = snapshot.get("events")
                if isinstance(events, list):
                    try:
                        self._state.events = list(events)
                    except Exception:
                        pass
            except Exception:
                pass


def get_cpu_temp(store: RaspiStateStore | None = None, path: str = "/sys/class/thermal/thermal_zone0/temp") -> float:
    """
    Read CPU temperature (Celsius) from the typical Linux thermal zone path,
    store it in RaspiStateStore pi_status, and return the value.
    """
    try:
        with open(path) as f:
            temp = int(f.read()) / 1000.0
            if store:
                store.set_cpu_temp(temp)
            return temp
    except Exception:
        return 0.0
