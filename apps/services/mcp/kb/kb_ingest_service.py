from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Dict, Optional, Tuple, List

from .kb_service import KbService


SnapshotProvider = Callable[[], Dict[str, Any]]


@dataclass
class IngestStats:
    ok: bool
    detic_ingested: int = 0
    face_ingested: int = 0
    errors: int = 0
    last_snapshot_ts: Optional[float] = None
    msg: Optional[str] = None


class KbIngestService:

    def __init__(
        self,
        kb_service: KbService,
        snapshot_provider: SnapshotProvider,
        *,
        detic_min_score: float = 0.35,
        face_min_score: float = 0.60,
        dedup_window_s: float = 1.0,
        interval_s: Optional[float] = None,
    ):
        self.kb = kb_service
        self.snapshot_provider = snapshot_provider

        self.detic_min_score = float(detic_min_score)
        self.face_min_score = float(face_min_score)
        self.dedup_window_s = float(dedup_window_s)
        self.interval_s = interval_s

        self._last_detic_ts: float = 0.0
        self._last_face_ts: float = 0.0

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if is_dataclass(obj):
            try:
                return asdict(obj)
            except Exception:
                pass
        if hasattr(obj, "__dict__"):
            try:
                return dict(obj.__dict__)
            except Exception:
                pass
        return {}

    def ingest_snapshot(self, snap: Dict[str, Any], *, stats: Optional[IngestStats] = None) -> Dict[str, Any]:
        stats = stats or IngestStats(ok=True)

        try:
            if str(os.environ.get("KB_INGEST_DEBUG", "0")).strip() == "1":
                keys = list(snap.keys()) if isinstance(snap, dict) else []
                print(f"[kb_ingest] snapshot keys={keys} raw={snap}")
        except Exception:
            pass

        snap_ts = snap.get("ts") or snap.get("timestamp")
        try:
            if snap_ts is not None:
                stats.last_snapshot_ts = float(snap_ts)
        except Exception:
            stats.last_snapshot_ts = None

        pose = self._extract_pose(snap)

        detic_ts = self._extract_detic_ts(snap) or snap.get("ts")
        if detic_ts is None:
            detic_ts = stats.last_snapshot_ts

        detic_list = self._extract_detic_objects(snap)
        if detic_ts is None:
            detic_ts = time.time()

        if detic_ts > self._last_detic_ts:
            for obj in detic_list:
                try:
                    label = obj.get("label") or obj.get("name")
                    if not label:
                        continue
                    score = float(obj.get("score", obj.get("conf", 0.0)) or 0.0)
                    if score < self.detic_min_score:
                        continue

                    bbox = self._extract_bbox(obj)
                    extra = {k: v for k, v in obj.items() if k not in ("label", "name", "score", "conf", "bbox")}

                    self.kb.ingest_detection(
                        kind="object",
                        label=str(label),
                        ts=float(detic_ts),
                        score=score,
                        bbox=bbox,
                        pose=pose,
                        extra=extra,
                        dedup_window_s=self.dedup_window_s,
                    )
                    stats.detic_ingested += 1
                except Exception as exc:
                    if str(os.environ.get("KB_INGEST_DEBUG", "0")).strip() == "1":
                        print(f"[kb_ingest] detic error for obj={obj}: {exc}")
                    stats.errors += 1

            self._last_detic_ts = float(detic_ts)

        face_ts  = self._extract_face_ts(snap)  or snap.get("ts")
        if face_ts is None:
            face_ts = stats.last_snapshot_ts
        if face_ts is None:
            face_ts = time.time()

        faces = self._extract_faces(snap)
        if face_ts > self._last_face_ts:
            for f in faces:
                try:
                    label = f.get("name") or f.get("label") or f.get("person")
                    if not label:
                        continue
                    score = float(f.get("score", f.get("conf", 0.0)) or 0.0)
                    if score < self.face_min_score:
                        continue

                    bbox = self._extract_bbox(f)
                    extra = {k: v for k, v in f.items() if k not in ("name", "label", "person", "score", "conf", "bbox")}

                    self.kb.ingest_detection(
                        kind="person",
                        label=str(label),
                        ts=float(face_ts),
                        score=score,
                        bbox=bbox,
                        pose=pose,
                        extra=extra,
                        dedup_window_s=self.dedup_window_s,
                    )
                    stats.face_ingested += 1
                except Exception as exc:
                    if str(os.environ.get("KB_INGEST_DEBUG", "0")).strip() == "1":
                        print(f"[kb_ingest] face error for face={f}: {exc}")
                    stats.errors += 1

            self._last_face_ts = float(face_ts)

        return {
            "ok": True,
            "detic_ingested": stats.detic_ingested,
            "face_ingested": stats.face_ingested,
            "errors": stats.errors,
            "last_snapshot_ts": stats.last_snapshot_ts,
        }

    def _extract_pose(self, snap: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """
        Accepts either:
          snap["pose"] = {"x":..,"y":..,"heading":..}
        or:
          snap["robot"]["pose"] = ...
        """
        pose = snap.get("pose")
        if isinstance(pose, dict):
            return self._pose_from_dict(pose)

        robot = snap.get("robot")
        if isinstance(robot, dict) and isinstance(robot.get("pose"), dict):
            return self._pose_from_dict(robot["pose"])

        return None

    def _pose_from_dict(self, d: Dict[str, Any]) -> Optional[Dict[str, float]]:
        try:
            x = float(d.get("x", 0.0))
            y = float(d.get("y", 0.0))
            heading = float(d.get("heading", d.get("yaw", 0.0)))
            return {"x": x, "y": y, "heading": heading}
        except Exception:
            return None

    def _extract_detic_objects(self, snap: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Tailored to visual_states.py schema (serialized):
          snap["detic"] = { "ts": float, "detections": [ {label, score, bbox?}, ... ] }

        Returns list of dicts with keys: label, score, bbox (optional).
        """
        detic = snap.get("detic")
        detic_dict = self._to_dict(detic)

        # Primary path: detic.detections
        dets = detic_dict.get("detections")
        if isinstance(dets, list):
            out: List[Dict[str, Any]] = []
            for d in dets:
                d_dict = self._to_dict(d)
                label = d_dict.get("label")
                score = d_dict.get("score")
                bbox = d_dict.get("bbox")
                if label is None:
                    continue
                out.append({"label": label, "score": score, "bbox": bbox})
            return out

        # Compatibility fallbacks (if your API ever returns these)
        for k in ("objects", "detic_objects"):
            v = snap.get(k)
            if isinstance(v, list):
                return [o for o in v if isinstance(o, dict)]

        return []

    def _extract_faces(self, snap: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Tailored to visual_states.py schema (serialized):
          snap["face"] = { "ts": float, "faces": [ {bbox, label, sim}, ... ] }

        Normalizes to list of dicts with keys: name, score, bbox
        - name comes from "label"
        - score comes from "sim" (face similarity)
        """
        face = snap.get("face")
        face_dict = self._to_dict(face)
        faces = face_dict.get("faces")
        if isinstance(faces, list):
            out: List[Dict[str, Any]] = []
            for f in faces:
                f_dict = self._to_dict(f)
                name = f_dict.get("label") or f_dict.get("name")
                sim = f_dict.get("sim")
                bbox = f_dict.get("bbox")
                if not name:
                    continue
                out.append({"name": name, "score": sim, "bbox": bbox})
            return out

        # Compatibility fallbacks
        for k in ("faces", "face_objects"):
            v = snap.get(k)
            if isinstance(v, list):
                # try to normalize basic shapes
                out: List[Dict[str, Any]] = []
                for f in v:
                    if isinstance(f, dict):
                        out.append(
                            {
                                "name": f.get("label") or f.get("name") or f.get("person"),
                                "score": f.get("sim") or f.get("score") or f.get("conf"),
                                "bbox": f.get("bbox"),
                            }
                        )
                return [x for x in out if x.get("name")]
        return []

    def _extract_detic_ts(self, snap: Dict[str, Any]) -> Optional[float]:
        detic = self._to_dict(snap.get("detic"))
        if isinstance(detic.get("ts"), (int, float)):
            return float(detic["ts"])
        return None

    def _extract_face_ts(self, snap: Dict[str, Any]) -> Optional[float]:
        face = self._to_dict(snap.get("face"))
        if isinstance(face.get("ts"), (int, float)):
            return float(face["ts"])
        return None

    def _extract_bbox(self, obj: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
        """
        Accepts:
          obj["bbox"] = [x1,y1,x2,y2] OR {x,y,w,h} OR {left,top,width,height}
        Returns (x1,y1,x2,y2)
        """
        bbox = obj.get("bbox")
        if bbox is None:
            return None
        try:
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                x1, y1, x2, y2 = [float(v) for v in bbox]
                return (x1, y1, x2, y2)
            if isinstance(bbox, dict):
                if "w" in bbox or "width" in bbox:
                    x = float(bbox.get("x", bbox.get("left", 0.0)))
                    y = float(bbox.get("y", bbox.get("top", 0.0)))
                    w = float(bbox.get("w", bbox.get("width", 0.0)))
                    h = float(bbox.get("h", bbox.get("height", 0.0)))
                    return (x, y, x + w, y + h)
        except Exception:
            return None
        return None

    def _get_float(self, snap: Dict[str, Any], keys: List[str]) -> Optional[float]:
        for k in keys:
            v = snap.get(k)
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, dict) and isinstance(v.get("ts"), (int, float)):
                return float(v["ts"])
        return None

    def _get_path(self, d: Dict[str, Any], path: Tuple[str, ...]) -> Any:
        cur: Any = d
        for p in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur
