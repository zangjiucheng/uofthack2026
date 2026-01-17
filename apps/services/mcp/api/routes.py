from __future__ import annotations

import time
from typing import Any, Dict, Optional


def register_routes(
    registry,
    *,
    stt_service=None,
    kb_service=None,
    kb_ingest=None,
    planner_client=None,
    mcp_service=None,
    mcp_store=None,
    mcp_executor=None,
    event_state=None,
) -> None:

    def _log(kind: str, **data: Any) -> None:
        if event_state is not None:
            try:
                event_state.log_event(kind, **data)
            except Exception:
                pass

    def health(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": True,
            "ts": time.time(),
            "has_stt": stt_service is not None,
            "has_kb": kb_service is not None,
            "has_planner": planner_client is not None,
            "has_mcp": mcp_service is not None,
        }
    
    def stt_start(payload: Dict[str, Any]) -> Dict[str, Any]:
        if stt_service is None:
            return {"ok": False, "error": "stt service not configured"}
        resp = stt_service.start_listening()
        _log("rest_stt_start", ok=bool(resp.get("ok")))
        return resp

    def stt_stop(payload: Dict[str, Any]) -> Dict[str, Any]:
        if stt_service is None:
            return {"ok": False, "error": "stt service not configured"}
        resp = stt_service.stop_listening()
        _log("rest_stt_stop", ok=bool(resp.get("ok")))
        return resp

    def stt_latest(payload: Dict[str, Any]) -> Dict[str, Any]:
        if stt_service is None:
            return {"ok": False, "error": "stt service not configured"}
        return stt_service.latest()

    def stt_push_text(payload: Dict[str, Any]) -> Dict[str, Any]:
        if stt_service is None:
            return {"ok": False, "error": "stt service not configured"}
        text = (payload or {}).get("text", "")
        resp = stt_service.push_text(text)
        _log("rest_stt_push_text", ok=bool(resp.get("ok")), text=text)
        return resp

    def kb_query(payload: Dict[str, Any]) -> Dict[str, Any]:
        if kb_service is None:
            return {"ok": False, "error": "kb service not configured"}
        kind = (payload or {}).get("kind", "object")
        q = (payload or {}).get("q", "")
        top_k = int((payload or {}).get("top_k", 1))
        min_score = float((payload or {}).get("min_score", 0.55))
        return kb_service.query(kind=kind, q=q, top_k=top_k, min_score=min_score)

    def kb_last_seen(payload: Dict[str, Any]) -> Dict[str, Any]:
        if kb_service is None:
            return {"ok": False, "error": "kb service not configured"}
        kind = (payload or {}).get("kind", "object")
        label = (payload or {}).get("label", "")
        return kb_service.last_seen(kind=kind, label=label)

    def kb_list_entities(payload: Dict[str, Any]) -> Dict[str, Any]:
        if kb_service is None:
            return {"ok": False, "error": "kb service not configured"}
        kind = (payload or {}).get("kind")
        limit = int((payload or {}).get("limit", 200))
        return {"ok": True, "entities": kb_service.store.list_entities(kind=kind, limit=limit)}

    def kb_ingest_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ingest detections provided by the caller.
        Expected shape (all optional, but labeled fields help):
        {
          "ts": <timestamp>,
          "detic": { "ts": <timestamp>, "detections": [ { "label": "...", "score": 0.8, "bbox": [x1,y1,x2,y2]? }, ... ] },
          "face":  { "ts": <timestamp>, "faces": [ { "label"|"name"|"person": "...", "sim"|"score"|"conf": 0.7, "bbox": [...]? }, ... ] }
        }
        """
        if kb_ingest is None:
            return {"ok": False, "error": "kb ingest service not configured"}
        snap = payload or {}
        return kb_ingest.ingest_snapshot(snap)

    def notify(payload: Dict[str, Any]) -> Dict[str, Any]:
        text = str((payload or {}).get("text", "")).strip()
        if not text:
            return {"ok": False, "error": "text required"}
        _log("notify", text=text)
        return {"ok": True, "notified": text}

    def planner_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
        if planner_client is None:
            return {"ok": False, "error": "planner client not configured"}
        transcript = (payload or {}).get("transcript", "")
        context = (payload or {}).get("context") or {}
        resp = planner_client.plan(transcript=transcript, context=context)
        _log("rest_planner_plan", ok=bool(resp.get("ok")))
        return resp

    def planner_plan_from_stt(payload: Dict[str, Any]) -> Dict[str, Any]:
        if planner_client is None:
            return {"ok": False, "error": "planner client not configured"}
        if stt_service is None:
            return {"ok": False, "error": "stt service not configured"}

        snap = stt_service.latest()
        final_text = (snap.get("final") or "").strip()
        fallback = bool((payload or {}).get("fallback_to_partial", False))
        if not final_text and fallback:
            final_text = (snap.get("partial") or "").strip()

        if not final_text:
            return {"ok": False, "error": "no STT transcript available", "stt": snap}

        context = (payload or {}).get("context") or {}

        resp = planner_client.plan(transcript=final_text, context=context)
        _log("rest_planner_plan_from_stt", ok=bool(resp.get("ok")), transcript=final_text)
        return resp

    def mcp_execute_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
        if mcp_executor is None:
            return {"ok": False, "error": "mcp executor not configured"}
        plan = (payload or {}).get("plan")
        if not isinstance(plan, dict):
            return {"ok": False, "error": "plan must be an object"}
        run_id = mcp_executor.execute_plan(
            plan,
            initial_state={"source": "mcp_execute_plan", "vars": {}, "save": {}, "last": {}},
        )
        _log("rest_mcp_execute_plan", run_id=run_id)
        return {"ok": True, "run_id": run_id}

    def mcp_run(payload: Dict[str, Any]) -> Dict[str, Any]:
        if mcp_service is None:
            return {"ok": False, "error": "mcp service not configured"}

        text = ((payload or {}).get("text") or "").strip()
        use_stt = bool((payload or {}).get("use_stt", True))

        if not text and use_stt:
            if stt_service is None:
                return {"ok": False, "error": "stt not configured and no text provided"}
            snap = stt_service.latest()
            text = (snap.get("final") or "").strip()

        if not text:
            return {"ok": False, "error": "no transcript available"}

        context = (payload or {}).get("context") or {}

        try:
            if kb_service is not None:
                people = kb_service.store.list_entities(kind="person", limit=50)
                context.setdefault("known_people", [p.get("label") for p in people if p.get("label")])
        except Exception:
            pass

        resp = mcp_service.plan_and_execute(transcript=text, context=context)
        _log("rest_mcp_run", ok=bool(resp.get("ok")), transcript=text)
        return resp

    def mcp_status(payload: Dict[str, Any]) -> Dict[str, Any]:
        if mcp_store is None:
            return {"ok": False, "error": "mcp store not configured"}
        run_id = (payload or {}).get("run_id")
        if not run_id:
            return {"ok": False, "error": "run_id required"}
        st = mcp_store.get(str(run_id))
        if not st:
            return {"ok": False, "error": "run_id not found"}
        return {"ok": True, "run": mcp_store.to_dict(st)}

    def mcp_cancel(payload: Dict[str, Any]) -> Dict[str, Any]:
        if mcp_store is None:
            return {"ok": False, "error": "mcp store not configured"}
        run_id = (payload or {}).get("run_id")
        if not run_id:
            return {"ok": False, "error": "run_id required"}
        ok = mcp_store.cancel(str(run_id))
        _log("rest_mcp_cancel", ok=ok, run_id=str(run_id))
        return {"ok": ok}

    registry.register("health", health)

    registry.register("stt_start", stt_start)
    registry.register("stt_stop", stt_stop)
    registry.register("stt_latest", stt_latest)
    registry.register("stt_push_text", stt_push_text)

    registry.register("kb_query", kb_query)
    registry.register("kb_last_seen", kb_last_seen)
    registry.register("kb_list_entities", kb_list_entities)
    registry.register("kb_ingest_snapshot", kb_ingest_snapshot)
    registry.register("notify", notify)

    registry.register("planner_plan", planner_plan)
    registry.register("planner_plan_from_stt", planner_plan_from_stt)

    registry.register("mcp_execute_plan", mcp_execute_plan)
    registry.register("mcp_run", mcp_run)
    registry.register("mcp_status", mcp_status)
    registry.register("mcp_cancel", mcp_cancel)
