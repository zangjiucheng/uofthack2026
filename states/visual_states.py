import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class FaceDetection:
    bbox: Tuple[int, int, int, int]
    label: str
    sim: float


@dataclass
class FaceState:
    ts: float
    faces: List[FaceDetection] = field(default_factory=list)


@dataclass
class TrackState:
    ts: float
    bbox: Optional[Tuple[float, float, float, float]] = None  # x, y, w, h
    area: Optional[float] = None
    center_x: Optional[float] = None


@dataclass
class DeticDetection:
    label: str
    score: float
    bbox: Tuple[float, float, float, float] | None = None  # x1, y1, x2, y2


@dataclass
class DeticState:
    ts: float
    detections: List[DeticDetection] = field(default_factory=list)


class VisualStateStore:
    """Thread-safe container for latest visual pipeline states."""

    _lock = threading.Lock()
    _face: Optional[FaceState] = None
    _track: Optional[TrackState] = None
    _detic: Optional[DeticState] = None

    @classmethod
    def update(
        cls,
        face: Optional[FaceState] = None,
        track: Optional[TrackState] = None,
        detic: Optional[DeticState] = None,
    ) -> None:
        with cls._lock:
            if face is not None:
                cls._face = face
            if track is not None:
                cls._track = track
            if detic is not None:
                cls._detic = detic

    @classmethod
    def snapshot(cls):
        with cls._lock:
            return {
                "face": cls._face,
                "track": cls._track,
                "detic": cls._detic,
                "ts": time.time(),
            }
