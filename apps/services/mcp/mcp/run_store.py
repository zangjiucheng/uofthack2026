from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class McpRunStep:
    i: int
    kind: str
    name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    started_ts: Optional[float] = None
    ended_ts: Optional[float] = None
    ok: Optional[bool] = None
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class McpRunState:
    run_id: str
    created_ts: float
    status: str = "running"  # "running" | "done" | "failed" | "cancelled"
    plan: Dict[str, Any] = field(default_factory=dict)
    initial_state: Dict[str, Any] = field(default_factory=dict)
    vars: Dict[str, Any] = field(default_factory=dict)
    save: Dict[str, Any] = field(default_factory=dict)
    last: Dict[str, Any] = field(default_factory=dict)
    steps: List[McpRunStep] = field(default_factory=list)
    error: Optional[str] = None
    finished_ts: Optional[float] = None
    cancelled: bool = False


class McpRunStore:

    def __init__(self):
        self._lock = threading.Lock()
        self._runs: Dict[str, McpRunState] = {}

    def create(self, plan: Dict[str, Any], initial_state: Dict[str, Any]) -> McpRunState:
        run_id = uuid.uuid4().hex
        st = McpRunState(
            run_id=run_id,
            created_ts=time.time(),
            status="running",
            plan=plan or {},
            initial_state=initial_state or {},
            vars=dict((initial_state or {}).get("vars", {}) or {}),
            save=dict((initial_state or {}).get("save", {}) or {}),
            last=dict((initial_state or {}).get("last", {}) or {}),
        )
        with self._lock:
            self._runs[run_id] = st
        return st

    def get(self, run_id: str) -> Optional[McpRunState]:
        with self._lock:
            return self._runs.get(run_id)

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return False
            st.cancelled = True
            if st.status == "running":
                st.status = "cancelled"
                st.finished_ts = time.time()
            return True

    def finish(self, run_id: str, *, status: str, error: Optional[str] = None) -> bool:
        if status not in ("done", "failed", "cancelled"):
            status = "failed"
        with self._lock:
            st = self._runs.get(run_id)
            if not st:
                return False
            st.status = status
            st.error = error
            st.finished_ts = time.time()
            return True

    def to_dict(self, st: McpRunState) -> Dict[str, Any]:
        with self._lock:
            steps_out = [
                {
                    "i": s.i,
                    "kind": s.kind,
                    "name": s.name,
                    "args": dict(s.args or {}),
                    "started_ts": s.started_ts,
                    "ended_ts": s.ended_ts,
                    "ok": s.ok,
                    "result": dict(s.result or {}),
                    "error": s.error,
                }
                for s in st.steps
            ]
            return {
                "run_id": st.run_id,
                "created_ts": st.created_ts,
                "status": st.status,
                "plan": dict(st.plan or {}),
                "initial_state": dict(st.initial_state or {}),
                "vars": dict(st.vars or {}),
                "save": dict(st.save or {}),
                "last": dict(st.last or {}),
                "steps": steps_out,
                "error": st.error,
                "finished_ts": st.finished_ts,
                "cancelled": st.cancelled,
            }

    def list_ids(self, limit: int = 50) -> List[str]:
        with self._lock:
            # return newest first
            return list(reversed(list(self._runs.keys())))[0:limit]
