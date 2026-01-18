import base64
import os
import time
import json
import urllib.request
import urllib.error

from core.services import Service
from routes.rest_api import start_rest_server, CommandRegistry
from states.eye_state import EyeStateStore
from .eye_stream_service import EyeStreamService
from states.visual_states import VisualStateStore, TrackState


class RestApiService(Service):
    name = "rest_api"

    def __init__(self, registry: CommandRegistry | None = None):
        self._registry = registry or CommandRegistry()
        self._server = None

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

    def register(self, name: str, handler):
        self._registry.register(name, handler)

    def register_host_handlers(self, stream_service, event_state, eye_state: bool = False):
        pi_rest_url = os.environ.get("APP_PI_REST_URL", "").rstrip("/")

        def _file_to_b64(path: str) -> tuple[bool, str | None, str | None]:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                return True, base64.b64encode(data).decode("utf-8"), None
            except Exception as exc:
                return False, None, str(exc)

        def _post_pi(path: str, payload: dict):
            print(f"[rest_api] posting to pi at {pi_rest_url} with payload: {payload}")
            if not pi_rest_url:
                return {"ok": False, "error": "APP_PI_REST_URL not set"}
            print(f"[rest_api] pi_rest_url: {pi_rest_url}")
            url = f"{pi_rest_url}/{path.lstrip('/')}"
            data = json.dumps(payload or {}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            print(f"[rest_api] pi request URL: {url}, data: {data}")
            try:
                with urllib.request.urlopen(req, timeout=2) as resp:
                    body = resp.read().decode("utf-8") or "{}"
            except Exception as exc:  # pragma: no cover - network/IO
                return {"ok": False, "error": str(exc)}
            try:
                return json.loads(body)
            except Exception:
                return {"ok": False, "error": "invalid response", "raw": body}

        def _planner_base_url() -> str:
            base = (os.environ.get("APP_PLANNER_URL") or "").strip().rstrip("/")
            if base:
                return base
            host = (os.environ.get("APP_PLANNER_HOST") or "127.0.0.1").strip()
            port = (os.environ.get("APP_PLANNER_PORT") or "8091").strip()
            host_with_scheme = host if host.startswith(("http://", "https://")) else f"http://{host}"
            return f"{host_with_scheme}:{port}".rstrip("/")

        def _post_planner(payload: dict, meta: dict | None = None):
            planner_base = _planner_base_url()
            print(f"[rest_api] posting to planner at {planner_base} with payload: {payload}")
            if not planner_base:
                return {"ok": False, "error": "planner URL not configured"}
            url = f"{planner_base}/plan"
            data = json.dumps(payload or {}).encode("utf-8")
            print(f"[rest_api] planner request URL: {url}, data: {data}")
            token = (os.environ.get("APP_PLANNER_TOKEN") or "").strip()
            headers = {"Content-Type": "application/json"}
            if token:
                headers["X-Planner-Token"] = token
                print("[rest_api] using planner token for request")
            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read().decode(resp.headers.get_content_charset() or "utf-8") or "{}"
            except Exception as exc: 
                return {"ok": False, "error": f"planner request failed: {exc}", "planner_url": url, "input": meta or {}}
            try:
                print(f"[rest_api] planner raw response: {body}")
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    parsed.setdefault("planner_url", url)
                    if meta:
                        parsed.setdefault("input", meta)
                    print(f"[rest_api] planner response: {parsed}")
                    return parsed
                return {"ok": False, "error": "invalid planner response", "raw": parsed, "planner_url": url, "input": meta or {}}
            except Exception:
                return {"ok": False, "error": "invalid planner response", "raw": body, "planner_url": url, "input": meta or {}}

        def _extract_tool_payload(plan: dict) -> tuple[str | None, dict]:
            tool = None
            payload: dict = {}
            if not isinstance(plan, dict):
                return tool, payload
            tool = plan.get("tool")
            payload = plan.get("payload") or {}
            action = plan.get("action")
            if isinstance(action, dict):
                tool = action.get("tool") or action.get("name") or tool
                if action.get("payload") is not None:
                    payload = action.get("payload")
                elif action.get("args") is not None:
                    payload = action.get("args")
            if not isinstance(payload, dict):
                payload = {}
            return tool, payload

        def _execute_plan(plan: dict):
            tool, payload = _extract_tool_payload(plan)
            if not tool:
                return {"ok": False, "error": "plan missing tool"}
            print(f"[rest_api] executing tool '{tool}' with payload: {payload}")
            result = self._registry.dispatch(tool, payload)
            print(f"[rest_api] tool '{tool}' result: {result}")
            return {"ok": True, "tool": tool, "payload": payload, "result": result}

        def _handle_planner_response(resp: dict):
            if not isinstance(resp, dict):
                return {"ok": False, "error": "invalid planner response"}
            if not resp.get("ok"):
                print(f"[rest_api] planner returned error: {resp}")
                return resp

            mode = resp.get("mode")
            print(f"[rest_api] planner mode: {mode}")
            if mode == "chat":
                print(f"[rest_api] chat reply: {resp.get('reply', '')}")
                return {"ok": True, "mode": "chat", "reply": resp.get("reply", "")}

            if mode == "plan":
                plan = resp.get("plan")
                if not isinstance(plan, dict):
                    return {"ok": False, "error": "planner returned invalid plan"}
                print(f"[rest_api] received plan: {plan}")
                exec_resp = _execute_plan(plan)
                print(f"[rest_api] plan execution response: {exec_resp}")
                if not exec_resp.get("ok"):
                    return exec_resp
                return {
                    "ok": True,
                    "mode": "plan",
                    "plan": plan,
                    "tool": exec_resp.get("tool"),
                    "payload": exec_resp.get("payload"),
                    "result": exec_resp.get("result"),
                    "message": "command executed",
                }

            return resp

        def start_face_record(payload):
            name = payload.get("name")
            if not name:
                return {"ok": False, "error": "name required"}
            if stream_service.queue_face_enroll(name):
                return {"ok": True, "msg": f"face record start requested for {name}"}
            return {"ok": False, "error": "face pipeline not available"}

        def start_tracking(payload):
            VisualStateStore.update(track=TrackState(ts=time.time()))
            return {"ok": True, "msg": "tracking start requested"}

        def set_tracking_roi(payload):
            bbox = payload.get("bbox") or payload.get("roi")
            try:
                if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    x1, y1, x2, y2 = [float(v) for v in bbox]
                    w, h = x2 - x1, y2 - y1
                    if w <= 0 or h <= 0:
                        return {"ok": False, "error": "bbox width/height must be positive"}
                    roi = (x1, y1, w, h)
                elif isinstance(bbox, dict):
                    x = float(bbox.get("x", bbox.get("left")))
                    y = float(bbox.get("y", bbox.get("top")))
                    w = float(bbox.get("w", bbox.get("width")))
                    h = float(bbox.get("h", bbox.get("height")))
                    roi = (x, y, w, h)
                else:
                    return {"ok": False, "error": "bbox must be [x1,y1,x2,y2] or {x,y,w,h}"}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

            stream_service.set_track_roi(roi)
            event_state.log_event("rest_tracking_roi", bbox=roi)
            return {"ok": True, "msg": "tracking ROI updated", "roi": roi}

        def stop_tracking(payload):
            stream_service.request_track_reset()
            event_state.log_event("rest_tracking_stop")
            return {"ok": True, "msg": "tracking reset"}

        def set_face_only(payload):
            enabled = bool(payload.get("enabled"))
            if enabled and not stream_service.face_pipeline_available:
                return {"ok": False, "error": "face pipeline not available"}
            ok = stream_service.set_face_only(enabled)
            return {"ok": ok, "face_only": enabled} if ok else {"ok": False, "error": "face pipeline not available"}

        def reset_face_db(payload):
            if stream_service.reset_face_db():
                return {"ok": True, "msg": "face db reset"}
            return {"ok": False, "error": "face pipeline not available"}

        def update_detic_objects(payload):
            raw = payload.get("object_list", payload.get("objects"))
            vocabulary = payload.get("vocabulary", "lvis")
            threshold_raw = payload.get("score_threshold", payload.get("output_score_threshold", 0.3))

            if raw is None:
                objects = None
            elif isinstance(raw, str):
                objects = [x.strip() for x in raw.split(",") if x.strip()]
            elif isinstance(raw, list):
                try:
                    objects = [str(x).strip() for x in raw if str(x).strip()]
                except Exception:
                    return {"ok": False, "error": "object_list items must be strings"}
            else:
                return {"ok": False, "error": "object_list must be a list or comma-separated string"}

            try:
                score_threshold = float(threshold_raw)
            except Exception:
                return {"ok": False, "error": "score_threshold must be a number"}

            ok, error = stream_service.update_detic_object_list(
                objects,
                vocabulary=vocabulary,
                output_score_threshold=score_threshold,
            )
            if ok:
                return {
                    "ok": True,
                    "msg": "detic object list updated",
                    "object_list": objects,
                    "vocabulary": vocabulary,
                    "score_threshold": score_threshold,
                }
            return {"ok": False, "error": error or "detic pipeline not active"}

        def trigger_detic(payload):
            ok, error = stream_service.trigger_detic_once()
            if ok:
                return {"ok": True, "msg": "detic inference queued"}
            return {"ok": False, "error": error or "detic pipeline not active"}

        def approach_object(payload):
            obj = (payload or {}).get("object")
            print(f"[rest_api] approach_object in backend called with payload: {payload}")
            if not obj or not isinstance(obj, str):
                return {"ok": False, "error": "object (str) required"}
            return _post_pi("approach_object", {"object": obj})

        def approach_person(payload):
            person = (payload or {}).get("name")
            if not person or not isinstance(person, str):
                return {"ok": False, "error": "name (str) required"}
            return _post_pi("approach_person", {"name": person})

        def update_face_record(payload):
            pid = payload.get("id", payload.get("person_id"))
            name = payload.get("name")
            try:
                person_id = int(pid)
            except Exception:
                return {"ok": False, "error": "id (int) required"}
            if stream_service.queue_face_update(person_id, name=name):
                return {"ok": True, "msg": f"face update start requested for id {person_id}", "id": person_id, "name": name}
            return {"ok": False, "error": "face pipeline not available"}

        def delete_face(payload):
            pid = payload.get("id", payload.get("person_id"))
            try:
                person_id = int(pid)
            except Exception:
                return {"ok": False, "error": "id (int) required"}
            if stream_service.delete_face(person_id):
                return {"ok": True, "msg": f"face {person_id} deleted", "id": person_id}
            return {"ok": False, "error": "face not found or pipeline unavailable"}

        def list_faces(payload):
            faces = stream_service.list_faces()
            if faces is None:
                return {"ok": False, "error": "face pipeline not available"}
            return {"ok": True, "faces": faces}

        def list_detics(payload):
            snap = VisualStateStore.snapshot()
            detic_state = snap.get("detic")
            if detic_state is None:
                return {"ok": False, "error": "detic state unavailable"}

            detections = getattr(detic_state, "detections", None) or []
            labels: list[str] = []
            for det in detections:
                label = getattr(det, "label", None)
                if label:
                    labels.append(str(label))

            return {"ok": True, "detections": labels, "ts": getattr(detic_state, "ts", None)}

        def eyes_mode(payload):
            try:
                mode = int(payload.get("mode"))
            except Exception:
                return {"ok": False, "error": "mode must be int"}
            if mode < 1 or mode > 6:
                return {"ok": False, "error": "mode must be 1-6"}
            EyeStateStore.set_mode(mode)
            _post_pi("eyes_mode", {"mode": mode})
            return {"ok": True, "mode": mode}

        def eyes_custom(payload):
            decoded = EyeStreamService.decode_custom_image(payload)
            if decoded is None:
                return {"ok": False, "error": "invalid image payload"}
            left, right = decoded
            EyeStateStore.set_custom(left, right)
            EyeStateStore.set_mode(6)
            _post_pi("eyes_custom", payload)
            return {"ok": True, "mode": 6}

        def eyes_state(payload):
            mode, custom, _ = EyeStateStore.snapshot()
            return {"ok": True, "mode": mode, "has_custom": custom is not None}

        def post_text_message(payload):
            """
            Send a text message to the MCP LLM planner.
            Accepts { "text": "..." }.
            """
            text = str((payload or {}).get("text", "")).strip()
            if not text:
                return {"ok": False, "error": "text required"}
            context = payload.get("context") if isinstance(payload, dict) else None
            planner_payload = {"transcript": text}
            print(f"[rest_api] posting text to planner: {text}")
            if isinstance(context, dict):
                planner_payload["context"] = context
            resp = _post_planner(planner_payload, meta={"text": text, "source": "post_text_message"})
            return _handle_planner_response(resp)

        def post_mp3(payload):
            """
            Send MP3 audio (base64 or file path) to the MCP LLM planner.
            Accepts audio_b64 or audio_path (mp3 file).
            """
            audio_b64 = (payload or {}).get("audio_b64")
            audio_path = (payload or {}).get("audio_path")
            if not audio_b64 and audio_path:
                ok, data, err = _file_to_b64(audio_path)
                if not ok or not data:
                    return {"ok": False, "error": f"failed to read mp3: {err}"}
                audio_b64 = data
            if not audio_b64:
                return {"ok": False, "error": "audio_b64 or audio_path required"}
            context = payload.get("context") if isinstance(payload, dict) else None
            planner_payload = {"audio_b64": str(audio_b64)}
            if isinstance(context, dict):
                planner_payload["context"] = context
            resp = _post_planner(planner_payload, meta={"has_audio_b64": True, "format": "mp3", "source": "post_mp3"})
            return _handle_planner_response(resp)

        def post_wav(payload):
            """
            Send WAV audio (base64 or file path) to the MCP LLM planner.
            Accepts audio_b64 or audio_path (wav file).
            """
            audio_b64 = (payload or {}).get("audio_b64")
            audio_path = (payload or {}).get("audio_path")
            if not audio_b64 and audio_path:
                ok, data, err = _file_to_b64(audio_path)
                if not ok or not data:
                    return {"ok": False, "error": f"failed to read wav: {err}"}
                audio_b64 = data
            if not audio_b64:
                return {"ok": False, "error": "audio_b64 or audio_path required"}
            context = payload.get("context") if isinstance(payload, dict) else None
            planner_payload = {"audio_b64": str(audio_b64)}
            print(f"[rest_api] posting wav audio to planner")
            if isinstance(context, dict):
                planner_payload["context"] = context
            resp = _post_planner(planner_payload, meta={"has_audio_b64": True, "format": "wav", "source": "post_wav"})
            return _handle_planner_response(resp)

        self.register("start_face_record", start_face_record)
        self.register("approach_object", approach_object)
        self.register("approach_person", approach_person)
        self.register("update_face_record", update_face_record)
        self.register("delete_face", delete_face)
        self.register("list_faces", list_faces)
        self.register("start_tracking", start_tracking)
        self.register("set_tracking_roi", set_tracking_roi)
        self.register("stop_tracking", stop_tracking)
        self.register("set_face_only", set_face_only)
        self.register("reset_face_db", reset_face_db)
        self.register("update_detic_objects", update_detic_objects)
        self.register("trigger_detic", trigger_detic)
        self.register("list_detics", list_detics)
        if eye_state:
            self.register("eyes_mode", eyes_mode)
            self.register("eyes_custom", eyes_custom)
            self.register("eyes_state", eyes_state)
        self.register("post_text_message", post_text_message)
        self.register("post_mp3", post_mp3)
        self.register("post_wav", post_wav)

    def start(self):
        if self._server is not None:
            return
        if os.environ.get("APP_REST", "0") != "1":
            return
        host = os.environ.get("APP_REST_HOST", "0.0.0.0")
        port = int(os.environ.get("APP_REST_PORT", "8080"))
        self._server = start_rest_server(self._registry, host=host, port=port)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
