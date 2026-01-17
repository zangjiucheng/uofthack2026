from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Optional, Tuple

from PIL import Image


@dataclass
class EyeCustomImages:
    left: Image.Image
    right: Image.Image


class EyeStateStore:
    _lock = threading.Lock()
    _mode: int = 1
    _custom: Optional[EyeCustomImages] = None
    _custom_version: int = 0

    @classmethod
    def set_mode(cls, mode: int) -> None:
        with cls._lock:
            cls._mode = mode

    @classmethod
    def set_custom(cls, left: Image.Image, right: Image.Image) -> None:
        with cls._lock:
            cls._custom = EyeCustomImages(left=left, right=right)
            cls._custom_version += 1

    @classmethod
    def clear_custom(cls) -> None:
        with cls._lock:
            cls._custom = None
            cls._custom_version += 1

    @classmethod
    def snapshot(cls) -> Tuple[int, Optional[EyeCustomImages], int]:
        with cls._lock:
            return cls._mode, cls._custom, cls._custom_version
