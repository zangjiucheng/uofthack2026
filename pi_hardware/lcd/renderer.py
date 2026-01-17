from __future__ import annotations

from typing import Tuple

from PIL import Image, ImageDraw

from pi_hardware.lcd.model import EyeStyle, EyeState, FaceState
from pi_hardware.lcd.utils import clamp, lerp


class EyeRenderer:
    def __init__(self, width: int = 256, height: int = 128, style: EyeStyle | None = None):
        self.w = width
        self.h = height
        self.style = style or EyeStyle()

    def render_eye(self, st: EyeState) -> Image.Image:
        """
        Returns a PIL image sized (w,h) in style.mode.
        The eye is drawn as a rounded rectangle whose height changes with st.open/squint.
        """
        s = max(1, int(self.style.aa_scale))
        W, H = self.w * s, self.h * s

        mode = "L"
        img = Image.new(mode, (W, H), color=self.style.bg)
        d = ImageDraw.Draw(img)

        # Base eye box (before look offset)
        margin_x = int(20 * s)
        margin_y = int(18 * s)

        base_w = W - 2 * margin_x
        base_h = H - 2 * margin_y

        # openness affects height (blink), squint reduces height too
        open_amt = clamp(st.open, 0.0, 1.0)
        squint_amt = clamp(st.squint, 0.0, 1.0)

        # Make blink feel more “snappy”: keep almost full, then collapse
        # but still continuous for animation
        h_scale = lerp(0.08, 1.0, open_amt)  # minimum slit
        h_scale *= lerp(1.0, 0.55, squint_amt)

        eye_h = int(base_h * h_scale)
        eye_w = base_w

        # Look offset inside screen
        dx = int(st.look_x * 0.18 * base_w)
        dy = int(st.look_y * 0.18 * base_h)

        cx = W // 2 + dx
        cy = H // 2 + dy

        x0 = cx - eye_w // 2
        y0 = cy - eye_h // 2
        x1 = cx + eye_w // 2
        y1 = cy + eye_h // 2

        # Corner radius
        r = int(min(eye_w, eye_h) * clamp(st.roundness, 0.0, 1.0) * 0.5)

        def draw_heart():
            size = max(4, int(min(eye_w, eye_h) * clamp(st.heart_scale, 0.2, 1.4)))
            # Sample classic heart implicit curve: (x^2 + y^2 - 1)^3 - x^2 y^3 <= 0
            mask = Image.new("L", (size, size), 0)
            pixels = mask.load()
            for iy in range(size):
                for ix in range(size):
                    # map pixel to [-1.3, 1.3] range
                    x = 2.6 * (ix / (size - 1) - 0.5)
                    y = 2.6 * (1.0 - iy / (size - 1) - 0.5)  # flip y so heart is upright
                    v = (x * x + y * y - 1) ** 3 - (x * x) * (y ** 3)
                    if v <= 0:
                        pixels[ix, iy] = 255
            heart_img = Image.new(mode, (size, size), color=self.style.bg)
            heart_img.paste(self.style.fg, (0, 0, size, size), mask)
            x_off = int(cx - size / 2)
            y_off = int(cy - size / 2)
            img.paste(heart_img, (x_off, y_off), mask)

        # Draw the eye shape
        if st.heart:
            draw_heart()
        else:
            d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=self.style.fg)

        # Add a simple "brow" cut that changes expression (optional)
        # brow < 0 => angry (cut more from top inside)
        # brow > 0 => sad/curious (cut more from bottom inside)
        brow = clamp(st.brow, -1.0, 1.0)
        if abs(brow) > 1e-3:
            cut = int(abs(brow) * 0.22 * eye_h)
            if brow < 0:
                # cut top
                d.rectangle([x0, y0, x1, y0 + cut], fill=self.style.bg)
            else:
                # cut bottom
                d.rectangle([x0, y1 - cut, x1, y1], fill=self.style.bg)

        # Tilt: rotate around center, then crop back
        tilt = st.tilt_deg
        if abs(tilt) > 1e-3:
            img = img.rotate(tilt, resample=Image.BICUBIC, center=(cx, cy), fillcolor=self.style.bg)

        # Downsample AA
        if s != 1:
            img = img.resize((self.w, self.h), resample=Image.LANCZOS)

        # Convert to requested mode
        if self.style.mode == "1":
            # threshold
            img = img.point(lambda p: 255 if p > 127 else 0, mode="1")
        else:
            img = img.convert("L")
        return img

    def render_face(self, face: FaceState) -> Tuple[Image.Image, Image.Image]:
        return self.render_eye(face.left), self.render_eye(face.right)
