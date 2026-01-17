from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class EyeStyle:
    """
    Styling knobs:
    - bg: background color
    - fg: eye color
    - aa_scale: integer supersampling factor for smoother edges
    - mode: "1" monochrome or "L" grayscale
    """

    bg: int = 0
    fg: int = 255
    aa_scale: int = 2
    mode: str = "1"  # or "L"


@dataclass
class EyeState:
    """
    A single eye's state.
    All positions are normalized so you can animate easily:
      - look_x, look_y in [-1, 1] means shifting the eye shape inside the screen.
      - open in [0, 1] eyelid openness (1 fully open, 0 closed).
      - squint in [0, 1] makes the eye shorter (like happy/smirk).
      - tilt in degrees (small angles look expressive).
      - roundness in [0, 1] controls corner radius.
      - heart toggles a heart-shaped eye for "love" expressions.
    """

    look_x: float = 0.0
    look_y: float = 0.0
    open: float = 1.0
    squint: float = 0.0
    tilt_deg: float = 0.0
    roundness: float = 0.55  # corner radius relative

    # Optional asymmetry for expressions
    brow: float = 0.0  # [-1,1] negative = angry, positive = sad/curious
    heart: bool = False
    heart_scale: float = 1.0  # multiplier for heart size when heart=True


@dataclass
class FaceState:
    """Both eyes."""

    left: EyeState
    right: EyeState
