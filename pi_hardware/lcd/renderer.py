from __future__ import annotations

from typing import Tuple
import math

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

        def shape_mask(shape: str) -> Image.Image:
            mask = Image.new("L", (W, H), 0)
            md = ImageDraw.Draw(mask)
            if shape == "square":
                md.rectangle([x0, y0, x1, y1], fill=255)
            elif shape == "circle":
                size = int(min(eye_w, eye_h) * clamp(st.shape_scale, 0.3, 1.3))
                x0c = int(cx - size / 2)
                y0c = int(cy - size / 2)
                x1c = x0c + size
                y1c = y0c + size
                md.ellipse([x0c, y0c, x1c, y1c], fill=255)
            elif shape == "round":
                md.ellipse([x0, y0, x1, y1], fill=255)
            elif shape == "star":
                size = max(4, int(min(eye_w, eye_h) * clamp(st.shape_scale, 0.3, 1.5)))
                outer = size / 2
                inner = outer * 0.4
                sx = clamp(st.shape_x_scale, 0.5, 2.0)
                sy = clamp(st.shape_y_scale, 0.5, 2.0)
                points = []
                for i in range(8):
                    ang = math.radians(i * 45 - 90)
                    rad = outer if i % 2 == 0 else inner
                    points.append((cx + rad * math.cos(ang) * sx, cy + rad * math.sin(ang) * sy))
                md.polygon(points, fill=255)
            elif shape == "diamond":
                size = max(4, int(min(eye_w, eye_h) * clamp(st.shape_scale, 0.3, 1.3)))
                half = size / 2
                points = [
                    (cx, cy - half),
                    (cx + half, cy),
                    (cx, cy + half),
                    (cx - half, cy),
                ]
                md.polygon(points, fill=255)
            elif shape == "hud":
                size = int(min(eye_w, eye_h) * clamp(st.shape_scale, 0.4, 1.3))
                x0c = int(cx - size / 2)
                y0c = int(cy - size / 2)
                x1c = x0c + size
                y1c = y0c + size
                md.ellipse([x0c, y0c, x1c, y1c], fill=255)
                ring_w = max(1, int(size * 0.18))
                md.ellipse([x0c + ring_w, y0c + ring_w, x1c - ring_w, y1c - ring_w], fill=0)
            else:
                md.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=255)
            return mask

        def draw_glow(mask: Image.Image) -> None:
            glow = Image.new(mode, (W, H), color=0)
            gd = ImageDraw.Draw(glow)
            offset = max(2, int(3 * s))
            glow_val = int(self.style.fg * 0.35)
            gd.bitmap((offset, -offset), mask, fill=glow_val)
            img.paste(glow, (0, 0), glow)

        def apply_fill(mask: Image.Image, *, gradient: bool = False) -> None:
            if gradient:
                grad = Image.new(mode, (W, H), color=0)
                gd = ImageDraw.Draw(grad)
                for y in range(H):
                    t = y / max(1, H - 1)
                    val = int(self.style.fg * (0.45 + 0.55 * (1.0 - t)))
                    gd.line([(0, y), (W, y)], fill=val)
                img.paste(grad, (0, 0), mask)
            else:
                img.paste(self.style.fg, (0, 0, W, H), mask)

        shape = st.shape
        if shape == "heart" or st.heart:
            draw_heart()
        else:
            mask = shape_mask(shape)
            if shape == "glow":
                draw_glow(mask)
                apply_fill(mask, gradient=True)
            else:
                apply_fill(mask)

            if shape == "hud":
                tick_len = max(2, int(6 * s))
                tick_w = max(1, int(2 * s))
                r_tick = int(min(eye_w, eye_h) * 0.5 * clamp(st.shape_scale, 0.4, 1.3))
                for ang_deg in (0, 45, 90, 135, 180, 225, 270, 315):
                    ang = math.radians(ang_deg)
                    x_start = int(cx + (r_tick - tick_len) * math.cos(ang))
                    y_start = int(cy + (r_tick - tick_len) * math.sin(ang))
                    x_end = int(cx + r_tick * math.cos(ang))
                    y_end = int(cy + r_tick * math.sin(ang))
                    d.line([x_start, y_start, x_end, y_end], fill=self.style.fg, width=tick_w)

        if st.pupil and not st.heart:
            p_scale = clamp(st.pupil_scale, 0.1, 0.7)
            p_size = int(min(eye_w, eye_h) * p_scale)
            max_dx = int(0.35 * eye_w)
            max_dy = int(0.35 * eye_h)
            px = cx + int(clamp(st.pupil_x, -1.0, 1.0) * max_dx)
            py = cy + int(clamp(st.pupil_y, -1.0, 1.0) * max_dy)
            px0 = int(px - p_size / 2)
            py0 = int(py - p_size / 2)
            px1 = px0 + p_size
            py1 = py0 + p_size
            d.ellipse([px0, py0, px1, py1], fill=self.style.bg)

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

    def render_face_surface(self, face: FaceState):
        """
        Convenience for pygame consumers: returns a tuple of pygame.Surface objects
        (converted from PIL) if pygame is available; otherwise returns PIL images.
        """
        left, right = self.render_face(face)
        try:
            import pygame  # type: ignore

            def to_surface(img: Image.Image):
                return pygame.image.fromstring(img.convert("RGB").tobytes(), img.size, "RGB")

            return to_surface(left), to_surface(right)
        except Exception:
            return left, right
