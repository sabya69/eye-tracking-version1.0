"""
neo_cv.py  --  neumorphic / glass drawing helpers for the OpenCV windows
(virtual_keyboard.py and text_pad.py).

The heavy surfaces (backdrop, glass panels, raised keys) are rendered ONCE with
Pillow (same renderer as neo_ui.py) and cached as numpy images, so the per-frame
cost in the tracker loop is just a copy plus a few small pastes.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from neo_ui import (render_neu, render_glass, make_backdrop_image, rgb, mix, lighten, darken,
                    BG, TEXT, MUTED, ACCENT, GREEN, DANGER, PURPLE, AMBER, IS_DARK)

_FONTS = {}
_TEXT_FONTS = ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"]
_PLAIN_FONTS = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Arial.ttf"]
_SYMBOL_FONTS = ["seguisym.ttf", "DejaVuSans.ttf", "Arial Unicode.ttf"]


def font(size, bold=True, symbols=False):
    key = (int(size), bold, symbols)
    f = _FONTS.get(key)
    if f is None:
        cands = _SYMBOL_FONTS if symbols else (_TEXT_FONTS if bold else _PLAIN_FONTS)
        for name in cands:
            try:
                f = ImageFont.truetype(name, int(size))
                break
            except Exception:
                continue
        if f is None:
            f = ImageFont.load_default()
        _FONTS[key] = f
    return f


def is_symbol(label):
    return any(ord(ch) > 0x2000 for ch in label)


def to_bgr(pil_img):
    return np.ascontiguousarray(np.asarray(pil_img.convert("RGB"))[:, :, ::-1])


def crop_pad(img, x1, y1, x2, y2):
    if x1 >= 0 and y1 >= 0 and x2 <= img.width and y2 <= img.height:
        return img.crop((x1, y1, x2, y2))
    out = Image.new("RGB", (x2 - x1, y2 - y1), img.getpixel((0, 0)))
    out.paste(img, (-x1, -y1))
    return out


def draw_text_center(img, rect, text, size, fill, bold=True):
    d = ImageDraw.Draw(img)
    f = font(size, bold, symbols=is_symbol(text))
    x1, y1, x2, y2 = rect
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    d.text(((x1 + x2 - (r - l)) / 2 - l, (y1 + y2 - (b - t)) / 2 - t), text, font=f, fill=rgb(fill))


class Surface:
    """A PIL canvas with a soft backdrop on which glass panels, inset wells and raised
    keys are drawn.  `bare` keeps a copy without keys (source for hover/pressed patches)."""

    def __init__(self, w, h, depth=4):
        self.w, self.h, self.depth = w, h, depth
        self.mrg = int(depth * 1.9) + 1
        self.img = make_backdrop_image(w, h, BG, None, fade_edges=0, strength=0.85)
        self.bare = None

    def glass(self, rect, r=26, accent=None, accent_a=0.0, pad=14):
        x1, y1, x2, y2 = rect
        crop = crop_pad(self.img, x1 - pad, y1 - pad, x2 + pad, y2 + pad)
        self.img.paste(render_glass(crop, r=r, pad=pad, accent=accent, accent_a=accent_a), (x1 - pad, y1 - pad))

    def inset(self, rect, r=16, fill=None):
        x1, y1, x2, y2 = rect
        m = self.mrg + 2
        crop = crop_pad(self.img, x1 - m, y1 - m, x2 + m, y2 + m)
        im = render_neu(x2 - x1 + 2 * m, y2 - y1 + 2 * m, BG,
                        fill or darken(BG, 0.10 if IS_DARK else 0.02), r=r, depth=4, mode="inset", bg_img=crop)
        self.img.paste(im, (x1 - m, y1 - m))

    def freeze_bare(self):
        self.bare = self.img.copy()

    def key(self, rect, label, face, fg, state="rest", glow=None, size=None, paste=False):
        """Render one key; returns (x, y, PIL patch).  paste=True also bakes it into self.img."""
        x1, y1, x2, y2 = rect
        m = self.mrg
        src = self.bare if self.bare is not None else self.img
        crop = crop_pad(src, x1 - m, y1 - m, x2 + m, y2 + m)
        f = face
        if state == "hover":
            f = lighten(face, 0.08)
        elif state == "flash":
            f = mix(face, GREEN, 0.7)
        mode = "pressed" if state in ("down", "flash") else "raised"
        im = render_neu(x2 - x1 + 2 * m, y2 - y1 + 2 * m, BG, f, r=min(18, (y2 - y1) // 3), depth=self.depth,
                        mode=mode, glow=glow if mode == "raised" else None, glow_a=0.34, bg_img=crop)
        kh = y2 - y1
        sz = size or (max(14, int(kh * 0.40)) if len(label) == 1 else max(12, int(kh * 0.30)))
        off = 1 if mode == "pressed" else 0
        draw_text_center(im, (m + off, m + off, m + (x2 - x1) + off, m + (y2 - y1) + off), label, sz, fg)
        if paste:
            self.img.paste(im, (x1 - m, y1 - m))
        return x1 - m, y1 - m, im


def to_bgr_tuple(color):
    r, g, b = rgb(color)
    return (b, g, r)
