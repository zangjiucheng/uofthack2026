from __future__ import annotations

from typing import Dict, Any

from pi_hardware.lcd.animations import (
    make_minimal_timeline,
    make_playful_timeline,
    make_heart_zoom_timeline,
    make_tech_timeline,
    make_noir_timeline,
    make_blink_timeline,
    FaceState,
    EyeState,
)


# Map of index -> preset factory + label
EYE_PRESETS: Dict[int, Dict[str, Any]] = {
    1: {"label": "Clean — ellipse", "factory": make_minimal_timeline},
    2: {"label": "Playful — far angle star", "factory": make_playful_timeline},
    3: {"label": "In love — heart", "factory": make_heart_zoom_timeline},
    4: {"label": "Tech — round rectangle", "factory": make_tech_timeline},
    5: {"label": "Noir — slit gaze, slow scan", "factory": make_noir_timeline},
    6: {"label": "Blink — simple", "factory": lambda: make_blink_timeline(FaceState(EyeState(open=1.0), EyeState(open=1.0)))},
}
