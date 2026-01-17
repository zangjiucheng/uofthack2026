from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


class DisplayDriver(Protocol):
    """Hardware driver you implement."""

    width: int
    height: int

    def send(self, img: Image.Image) -> None:
        """Send a PIL image to the display."""
        ...


@dataclass
class DualDisplay:
    """Two physical displays: left and right eye."""

    left: DisplayDriver
    right: DisplayDriver

    def send(self, left_img: Image.Image, right_img: Image.Image) -> None:
        self.left.send(left_img)
        self.right.send(right_img)
