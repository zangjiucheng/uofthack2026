from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .conditions import eval_cond
from .resolver import resolve_args, resolve_value
from .run_store import McpRunStep, McpRunState, McpRunStore

ToolInvoker = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def _on_fail_mode(step: Dict[str, Any]) -> str:
    mode = (step.get("on_fail") or "stop")
    if not isinstance(mode, str):
        return "stop"
    mode = mode.strip().lower()
    return mode if mode in ("stop", "continue") else "stop"


class McpExecutor:
    def __init__(
        self,
        *,
        store: McpRunStore,
        tool_invoker: ToolInvoker,
        allow_tools: Optional[Set[str]] = None,
        max_steps: int = 20,
        per_step_timeout_s: float = 20.0,
    ):
        self.store = store
        self.tool_invoker = tool_invoker
        self.allow_tools: Optional[Set[str]] = allow_tools
        self.max_steps = int(max_steps)
        self.per_step_timeout_s = float(per_step_timeout_s)

    def execute_plan(self, plan: Dict[str, Any], initial_state: Optional[Dict[str, Any]] = None) -> str:
        st = self.store.create(plan=plan or {}, initial_state=initial_state or {})
        t = threading.Thread(target=self._run, args=(st.run_id,), daemon=True)
        t.start()
        return st.run_id

    def _run(self, run_id: str) -> None:
        st = self.store.get(run_id)
        if not st:
            return

        with self.store._lock:
            st.status = "running"
            st.error = None
            st.finished_ts = None

        plan = st.plan or {}
        policy = plan.get("policy") or {}
        max_steps = min(int(policy.get("max_steps", self.max_steps)), self.max_steps)
        per_step_timeout = min(float(policy.get("per_step_timeout_s", self.per_step_timeout_s)), self.per_step_timeout_s)

        state: Dict[str, Any] = {"vars": st.vars, "save": st.save, "last": st.last}

        plan_vars = plan.get("vars") or {}
        if isinstance(plan_vars, dict):
            for k, v in plan_vars.items():
                if k not in state["vars"]:
                    state["vars"][k] = v

        steps = plan.get("steps") or []
        if not isinstance(steps, list):
            self.store.finish(run_id, status="failed", error="plan.steps must be a list")
            return

        ok = self._exec_steps(st, steps, state, path="steps", max_steps=max_steps, per_step_timeout=per_step_timeout)

        if st.cancelled or st.status == "cancelled":
            self.store.finish(run_id, status="cancelled")
            return

        if not ok:
            self.store.finish(run_id, status="failed", error=st.error or "execution failed")
            return

        self.store.finish(run_id, status="done")

    def _exec_steps(
        self,
        st: McpRunState,
        steps: List[Dict[str, Any]],
        state: Dict[str, Any],
        *,
        path: str,
        max_steps: int,
        per_step_timeout: float,
    ) -> bool:
        for idx, step in enumerate(steps):
            if st.cancelled or st.status == "cancelled":
                return False

            if not isinstance(step, dict):
                return self._fail(st, f"invalid step at {path}[{idx}]")

            if self._step_count(st) >= max_steps:
                return self._fail(st, f"max_steps exceeded ({max_steps})")

            step_type = (step.get("type") or "").strip().lower()
            step_path = f"{path}[{idx}]"

            ok, result = self._dispatch_step(st, step, state, path=step_path, max_steps=max_steps, per_step_timeout=per_step_timeout)

            if ok:
                continue

            mode = _on_fail_mode(step)
            if mode == "stop":
                if isinstance(result, dict) and result.get("error"):
                    st.error = str(result.get("error"))
                else:
                    st.error = st.error or f"step failed at {step_path}"
                return False

            # mode == "continue"
            fb = step.get("fallback") or []
            if fb:
                if not isinstance(fb, list):
                    return self._fail(st, f"fallback must be an array at {step_path}")
                if not self._exec_steps(st, fb, state, path=f"{step_path}.fallback", max_steps=max_steps, per_step_timeout=per_step_timeout):
                    return False

            if isinstance(result, dict):
                st.last = result
                state["last"] = st.last
            else:
                st.last = {"ok": False, "error": "step failed (soft)"}
                state["last"] = st.last

        return True

    def _dispatch_step(
        self,
        st: McpRunState,
        step: Dict[str, Any],
        state: Dict[str, Any],
        *,
        path: str,
        max_steps: int,
        per_step_timeout: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        step_type = (step.get("type") or "").strip().lower()

        if step_type == "tool":
            return self._exec_tool_step(st, step, state, path=path, per_step_timeout=per_step_timeout)

        if step_type == "set":
            return self._exec_set_step(st, step, state, path=path)

        if step_type == "if":
            return self._exec_if_step(st, step, state, path=path, max_steps=max_steps, per_step_timeout=per_step_timeout)

        if step_type == "wait":
            return self._exec_wait_step(st, step, state, path=path, max_steps=max_steps, per_step_timeout=per_step_timeout)

        return False, {"ok": False, "error": f"unknown step type '{step_type}' at {path}"}

    def _exec_tool_step(
        self,
        st: McpRunState,
        step: Dict[str, Any],
        state: Dict[str, Any],
        *,
        path: str,
        per_step_timeout: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        name = step.get("name")
        if not isinstance(name, str) or not name.strip():
            res = {"ok": False, "error": f"tool step missing name at {path}"}
            self._log_step(st, kind="tool", name="", args={}, path=path, ok=False, result=res)
            return False, res
        name = name.strip()

        if self.allow_tools is not None and name not in self.allow_tools:
            res = {"ok": False, "error": f"tool '{name}' not allowed"}
            self._log_step(st, kind="tool", name=name, args={}, path=path, ok=False, result=res)
            return False, res

        args = step.get("args") or {}
        if not isinstance(args, dict):
            res = {"ok": False, "error": f"tool args must be object at {path}"}
            self._log_step(st, kind="tool", name=name, args={}, path=path, ok=False, result=res)
            return False, res

        resolved_args = resolve_args(args, state)

        started = time.time()
        result = self._call_with_timeout(name, resolved_args, timeout_s=per_step_timeout)
        ended = time.time()

        # Save results
        save_as = step.get("save_as")
        if isinstance(save_as, str) and save_as.strip():
            st.save[save_as.strip()] = result
        st.save[name] = result

        st.last = result
        state["last"] = result

        ok = not (isinstance(result, dict) and result.get("ok") is False)

        self._log_step(
            st,
            kind="tool",
            name=name,
            args=resolved_args,
            path=path,
            ok=ok,
            result=result,
            started_ts=started,
            ended_ts=ended,
        )
        return ok, result

    def _exec_set_step(self, st: McpRunState, step: Dict[str, Any], state: Dict[str, Any], *, path: str) -> Tuple[bool, Dict[str, Any]]:
        var = step.get("var")
        if not isinstance(var, str) or not var.strip():
            res = {"ok": False, "error": f"set step missing var at {path}"}
            self._log_step(st, kind="set", name="", args={}, path=path, ok=False, result=res)
            return False, res

        value = resolve_value(step.get("value"), state)
        st.vars[var.strip()] = value
        res = {"ok": True, "set": var.strip(), "value": value}

        st.last = res
        state["last"] = res

        self._log_step(st, kind="set", name=var.strip(), args={"value": value}, path=path, ok=True, result=res)
        return True, res

    def _exec_if_step(
        self,
        st: McpRunState,
        step: Dict[str, Any],
        state: Dict[str, Any],
        *,
        path: str,
        max_steps: int,
        per_step_timeout: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        cond = step.get("cond")
        if not isinstance(cond, dict):
            res = {"ok": False, "error": f"if step missing cond at {path}"}
            self._log_step(st, kind="if", name="if", args={}, path=path, ok=False, result=res)
            return False, res

        then_steps = step.get("then") or []
        else_steps = step.get("else") or []
        if not isinstance(then_steps, list) or not isinstance(else_steps, list):
            res = {"ok": False, "error": f"if then/else must be arrays at {path}"}
            self._log_step(st, kind="if", name="if", args={}, path=path, ok=False, result=res)
            return False, res

        take_then = bool(eval_cond(cond, state))
        res = {"ok": True, "if": take_then}
        st.last = res
        state["last"] = res

        self._log_step(st, kind="if", name="if", args={"take_then": take_then}, path=path, ok=True, result=res)

        branch = then_steps if take_then else else_steps
        branch_name = "then" if take_then else "else"
        ok = self._exec_steps(st, branch, state, path=f"{path}.{branch_name}", max_steps=max_steps, per_step_timeout=per_step_timeout)
        return ok, st.last if isinstance(st.last, dict) else {"ok": False, "error": "if branch failed"}

    def _exec_wait_step(
        self,
        st: McpRunState,
        step: Dict[str, Any],
        state: Dict[str, Any],
        *,
        path: str,
        max_steps: int,
        per_step_timeout: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        timeout_s = float(step.get("timeout_s") or 60.0)
        poll_s = float(step.get("poll_s") or 0.5)

        cond = step.get("cond")
        if not isinstance(cond, dict):
            res = {"ok": False, "error": f"wait step missing cond at {path}"}
            self._log_step(st, kind="wait", name="wait", args={}, path=path, ok=False, result=res)
            return False, res

        tick_steps = step.get("tick") or []
        refresh_steps = step.get("refresh") or []
        if not isinstance(tick_steps, list) or not isinstance(refresh_steps, list):
            res = {"ok": False, "error": f"wait tick/refresh must be arrays at {path}"}
            self._log_step(st, kind="wait", name="wait", args={}, path=path, ok=False, result=res)
            return False, res

        started = time.time()
        self._log_step(st, kind="wait", name="wait", args={"timeout_s": timeout_s, "poll_s": poll_s}, path=path, ok=True, result={"ok": True, "wait": "started"})

        while (time.time() - started) < timeout_s:
            if st.cancelled or st.status == "cancelled":
                res = {"ok": False, "error": "cancelled"}
                self._log_step(st, kind="wait", name="wait", args={}, path=path, ok=False, result=res)
                st.last = res
                state["last"] = res
                return False, res

            if self._step_count(st) >= max_steps:
                res = {"ok": False, "error": f"max_steps exceeded ({max_steps}) during wait"}
                self._log_step(st, kind="wait", name="wait", args={}, path=path, ok=False, result=res)
                st.last = res
                state["last"] = res
                return False, res

            if tick_steps:
                if not self._exec_steps(st, tick_steps, state, path=f"{path}.tick", max_steps=max_steps, per_step_timeout=per_step_timeout):
                    return False, st.last if isinstance(st.last, dict) else {"ok": False, "error": "wait tick failed"}

            if refresh_steps:
                if not self._exec_steps(st, refresh_steps, state, path=f"{path}.refresh", max_steps=max_steps, per_step_timeout=per_step_timeout):
                    return False, st.last if isinstance(st.last, dict) else {"ok": False, "error": "wait refresh failed"}

            if eval_cond(cond, state):
                res = {"ok": True, "wait": "satisfied"}
                st.last = res
                state["last"] = res
                self._log_step(st, kind="wait", name="wait", args={}, path=path, ok=True, result=res)
                return True, res

            time.sleep(poll_s)

        res = {"ok": True, "wait": "timeout", "timeout_s": timeout_s}
        st.last = res
        state["last"] = res
        self._log_step(st, kind="wait", name="wait", args={}, path=path, ok=True, result=res)
        return True, res

    def _step_count(self, st: McpRunState) -> int:
        return len(st.steps)

    def _fail(self, st: McpRunState, msg: str) -> bool:
        st.error = msg
        return False

    def _log_step(
        self,
        st: McpRunState,
        *,
        kind: str,
        name: str,
        args: Dict[str, Any],
        path: str,
        ok: bool,
        result: Dict[str, Any],
        started_ts: Optional[float] = None,
        ended_ts: Optional[float] = None,
    ) -> None:
        if isinstance(result, dict) and "path" not in result:
            result = dict(result)
            result["path"] = path

        with self.store._lock:
            i = len(st.steps)
            s = McpRunStep(
                i=i,
                kind=kind,
                name=name,
                args=args or {},
                started_ts=started_ts,
                ended_ts=ended_ts,
                ok=ok,
                result=result or {},
                error=(result.get("error") if isinstance(result, dict) else None),
            )
            st.steps.append(s)

    def _call_with_timeout(self, tool: str, args: Dict[str, Any], *, timeout_s: float) -> Dict[str, Any]:
        out: Dict[str, Any] = {"ok": False, "error": "timeout"}
        done = threading.Event()

        def worker() -> None:
            nonlocal out
            try:
                out = self.tool_invoker(tool, args)
                if not isinstance(out, dict):
                    out = {"ok": False, "error": "tool returned non-dict"}
                elif "ok" not in out and "error" in out:
                    out = {"ok": False, "error": out.get("error")}
                elif "ok" not in out:
                    out = {"ok": True, **out}
            except Exception as exc:
                out = {"ok": False, "error": str(exc)}
            finally:
                done.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        done.wait(timeout=timeout_s)
        if not done.is_set():
            return {"ok": False, "error": f"tool timeout after {timeout_s}s"}
        return out
