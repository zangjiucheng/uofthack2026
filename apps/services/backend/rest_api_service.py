import os
import time
import json
import urllib.request
import urllib.error

from core.services import Service
from routes.rest_api import start_rest_server, CommandRegistry
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

    def register_host_handlers(self, stream_service, event_state):
        pi_rest_url = os.environ.get("APP_PI_REST_URL", "").rstrip("/")

        def _post_pi(path: str, payload: dict):
            if not pi_rest_url:
                return {"ok": False, "error": "APP_PI_REST_URL not set"}
            url = f"{pi_rest_url}/{path.lstrip('/')}"
            data = json.dumps(payload or {}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=2) as resp:
                    body = resp.read().decode("utf-8") or "{}"
            except Exception as exc:  # pragma: no cover - network/IO
                return {"ok": False, "error": str(exc)}
            try:
                return json.loads(body)
            except Exception:
                return {"ok": False, "error": "invalid response", "raw": body}

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
