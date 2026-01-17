import os
import threading
from typing import Optional

import cv2
import numpy as np


class VideoFrameStore:
    """Thread-safe store for the latest display frame (BGR)."""

    _lock = threading.Lock()
    _frame: Optional[np.ndarray] = None

    @classmethod
    def set_frame(cls, frame: np.ndarray) -> None:
        with cls._lock:
            cls._frame = frame.copy()

    @classmethod
    def get_jpeg(cls, quality: Optional[int] = None) -> Optional[bytes]:
        with cls._lock:
            if cls._frame is None:
                return None
            q = quality if quality is not None else int(os.environ.get("APP_VIDEO_JPEG_QUALITY", "70"))
            ok, buf = cv2.imencode(".jpg", cls._frame, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if not ok:
                return None
            return buf.tobytes()
