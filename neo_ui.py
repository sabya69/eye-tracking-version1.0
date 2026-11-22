"""
neo_ui.py  --  shared Neumorphism + Glassmorphism widget kit for the tkinter UI.

Tkinter has no blur, no soft shadows and no transparency, so every "soft"
surface here is rendered with Pillow (two offset blurred shadows for the
neumorphic look, a blurred + tinted + bordered crop of the backdrop for the
glass look) and shown as an image on a Canvas.  Colours are derived from
theme.py, so THEME_MODE ("pearl" | "dusk" | "warm" | "classic") still works.

WHAT'S IN HERE
    Backdrop        soft gradient + colour blobs; glass widgets sample it
    NeuButton       drop-in replacement for tk.Button (raised / pressed)
    NeuText/NeuEntry  tk.Text / tk.Entry sitting in an inset neumorphic well
    NeuScrollbar    slim scrollbar that matches
    GlassPanel      frosted container with a `.body` frame for children
    GlassCard       big clickable glass tile (title + description)
    NeoKeyboard     the on-screen keyboard (see CLEAR_ALL notes below)

SAFER "CLEAR ALL"
    The old keyboard had a "Delete" key (wipes the whole text) right beside
    Space and the arrow keys, so a mis-click erased the paragraph.  It now:
      1. lives alone in the top-right corner, away from every typing key, and
      2. needs a second tap within CONFIRM_WINDOW_MS to actually clear
         (set CONFIRM_CLEAR_ALL = False for the old one-tap behaviour).
"""
import tkinter as tk
from tkinter import font as tkfont
import weakref

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageTk

from theme import T, THEME_MODE

# ─────────────────────────────────────────────────────────────────────────────
#  SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
CONFIRM_CLEAR_ALL  = True     # True: "Clear all" needs a 2nd tap.  False: one tap.
CONFIRM_WINDOW_MS  = 3000     # how long the 2nd tap stays valid

IS_DARK = THEME_MODE == "dusk"

# ─────────────────────────────────────────────────────────────────────────────
#  PALETTE  (all derived from theme.T so the three theme modes keep working)
# ─────────────────────────────────────────────────────────────────────────────
BG      = T("#F5F6F8")     # page
SURFACE = T("#FFFFFF")     # raised surface
TEXT    = T("#1A1D23")
MUTED   = T("#6B7280")
ACCENT  = T("#2563EB")
GREEN   = T("#16A34A")
AMBER   = T("#D97706")
PURPLE  = T("#7C3AED")
DANGER  = T("#DC2626")
BORDER  = T("#DDE1E7")

# Colour blobs behind the glass  (x, y, radius, colour, strength)
BLOBS = [
    (0.12, 0.18, 0.46, ACCENT, 0.40),
    (0.88, 0.22, 0.42, PURPLE, 0.34),
    (0.62, 0.95, 0.50, GREEN,  0.28),
    (0.30, 0.80, 0.34, AMBER,  0.18),
]


# ─────────────────────────────────────────────────────────────────────────────
#  COLOUR HELPERS
# ─────────────────────────────────────────────────────────────────────────────
_NAMED = {"white": (255, 255, 255), "black": (0, 0, 0)}


def rgb(h):
    if isinstance(h, (tuple, list)):
        return tuple(int(v) for v in h[:3])
    if h.lower() in _NAMED:
        return _NAMED[h.lower()]
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexc(c):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in rgb(c))


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def lighten(c, t):
    return mix(c, (255, 255, 255), t)


def darken(c, t):
    return mix(c, (0, 0, 0), t)


def _shadow_pair(bg):
    """(dark shadow colour, light shadow colour) for a given surface colour."""
    if IS_DARK:
        return darken(bg, 0.55), lighten(bg, 0.085)
    return darken(bg, 0.16), lighten(bg, 0.80)


_DARK_A  = 0.95 if IS_DARK else 0.85
_LIGHT_A = 0.95 if IS_DARK else 1.00


# ─────────────────────────────────────────────────────────────────────────────
#  IMAGE RENDERING
# ─────────────────────────────────────────────────────────────────────────────
_IMG_CACHE = {}


def _cached(key, fn):
    im = _IMG_CACHE.get(key)
    if im is None:
        if len(_IMG_CACHE) > 900:
            _IMG_CACHE.clear()
        im = fn()
        _IMG_CACHE[key] = im
    return im


def _rr_mask(size, box, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, max(1, int(r)), fill=255)
    return m


def _grad(W, H, c1, c2):
    """Diagonal gradient, c1 at top-left to c2 at bottom-right."""
    ys, xs = np.mgrid[0:H, 0:W]
    t = ((xs / max(1, W - 1)) + (ys / max(1, H - 1))) / 2.0
    a1 = np.array(rgb(c1), dtype=np.float32)
    a2 = np.array(rgb(c2), dtype=np.float32)
    arr = a1[None, None, :] * (1 - t[..., None]) + a2[None, None, :] * t[..., None]
    return Image.fromarray(arr.clip(0, 255).astype("uint8"), "RGB")


def render_neu(w, h, bg, face=None, r=14, depth=5, mode="raised",
               glow=None, glow_a=0.40, bg_img=None, convex=0.06, outline=None):
    """Neumorphic surface.  mode = 'raised' | 'pressed' | 'inset'.
    `bg` is the surface colour around it (or `bg_img` a PIL crop of the backdrop)."""
    w, h = max(10, int(w)), max(10, int(h))
    ss = 2 if w * h <= 300_000 else 1
    W, H = w * ss, h * ss
    if bg_img is not None:
        base = bg_img.convert("RGB")
        if base.size != (W, H):
            base = base.resize((W, H), Image.BILINEAR)
    else:
        base = Image.new("RGB", (W, H), rgb(bg))
    face = face if face is not None else bg
    d = max(1, depth * ss)
    pad = int(d * 1.9) + 1
    box = (pad, pad, W - pad - 1, H - pad - 1)
    rr = min(int(r * ss), (box[2] - box[0]) // 2, (box[3] - box[1]) // 2)
    el = _rr_mask((W, H), box, rr)
    dark_c, light_c = _shadow_pair(bg)
    sig, off = max(1.0, d * 0.55), int(d * 0.65)

    if mode == "raised":
        if glow is not None:
            gl = ImageChops.offset(el, 0, int(d * 0.35)).filter(ImageFilter.GaussianBlur(d * 1.15))
            base = Image.composite(Image.new("RGB", (W, H), rgb(glow)), base,
                                   gl.point(lambda v: int(v * glow_a)))
        dk = ImageChops.offset(el, off, off).filter(ImageFilter.GaussianBlur(sig))
        lt = ImageChops.offset(el, -off, -off).filter(ImageFilter.GaussianBlur(sig))
        base = Image.composite(Image.new("RGB", (W, H), rgb(dark_c)), base,
                               dk.point(lambda v: int(v * _DARK_A)))
        base = Image.composite(Image.new("RGB", (W, H), rgb(light_c)), base,
                               lt.point(lambda v: int(v * _LIGHT_A)))
        face_img = _grad(W, H, lighten(face, convex), darken(face, convex))
        base.paste(face_img, (0, 0), el)
        # hair-line top-left rim for a crisp edge
        rim = ImageChops.subtract(el, _rr_mask((W, H), (box[0] + ss, box[1] + ss, box[2] - ss, box[3] - ss), max(1, rr - ss)))
        rim = ImageChops.multiply(rim, _grad(W, H, (255, 255, 255), (0, 0, 0)).convert("L")).point(
            lambda v: int(v * (0.16 if IS_DARK else 0.55)))
        base = Image.composite(Image.new("RGB", (W, H), (255, 255, 255)), base, rim)
    else:  # pressed / inset
        shade = 0.07 if mode == "inset" else 0.05
        face_img = _grad(W, H, darken(face, shade + 0.03), darken(face, shade * 0.4))
        base.paste(face_img, (0, 0), el)
        inv = ImageChops.invert(el)
        k = 1.25 if mode == "inset" else 1.0
        dk = ImageChops.multiply(
            ImageChops.offset(inv, int(off * k), int(off * k)).filter(ImageFilter.GaussianBlur(sig * k)), el)
        lt = ImageChops.multiply(
            ImageChops.offset(inv, -off, -off).filter(ImageFilter.GaussianBlur(sig)), el)
        base = Image.composite(Image.new("RGB", (W, H), rgb(darken(bg, 0.62 if IS_DARK else 0.22))), base,
                               dk.point(lambda v: int(v * 0.95)))
        base = Image.composite(Image.new("RGB", (W, H), rgb(light_c)), base,
                               lt.point(lambda v: int(v * (0.55 if IS_DARK else 0.9))))
    if outline is not None:
        ImageDraw.Draw(base).rounded_rectangle(box, rr, outline=rgb(outline), width=max(2, 2 * ss))
    if ss > 1:
        base = base.resize((w, h), Image.LANCZOS)
    return base


def render_glass(bg_img, r=22, pad=14, tint=(255, 255, 255), tint_a=None,
                 blur=16, border=None, accent=None, accent_a=0.0,
                 shadow=None, sheen=None, grain=2):
    """Frosted glass panel drawn onto a crop of the backdrop (same size as bg_img).
    `pad` is the margin kept free for the soft drop shadow."""
    tint_a = tint_a if tint_a is not None else (0.075 if IS_DARK else 0.38)
    border = border if border is not None else (0.34 if IS_DARK else 0.85)
    shadow = shadow if shadow is not None else (0.55 if IS_DARK else 0.22)
    sheen = sheen if sheen is not None else (0.10 if IS_DARK else 0.35)
    orig = bg_img.convert("RGB")
    W, H = orig.size
    box = (pad, pad, W - pad - 1, H - pad - 1)
    el = _rr_mask((W, H), box, min(r, (box[2] - box[0]) // 2, (box[3] - box[1]) // 2))
    out = orig.copy()
    # soft drop shadow (outside only)
    sh = ImageChops.offset(el, 0, int(pad * 0.45)).filter(ImageFilter.GaussianBlur(max(2, pad * 0.5)))
    sh = ImageChops.multiply(sh, ImageChops.invert(el))
    out = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), out, sh.point(lambda v: int(v * shadow)))
    # frosted body
    glass = orig.filter(ImageFilter.GaussianBlur(blur))
    glass = Image.blend(glass, Image.new("RGB", (W, H), rgb(tint)), tint_a)
    ga = np.asarray(glass).astype(np.float32)
    ys, xs = np.mgrid[0:H, 0:W]
    t = ((xs - pad) / max(1, W - 2 * pad) + (ys - pad) / max(1, H - 2 * pad)) / 2.0
    s = np.clip(1.0 - t * 1.6, 0, 1) * sheen
    ga = ga * (1 - s[..., None]) + 255.0 * s[..., None]
    if accent is not None and accent_a > 0:
        al = np.clip(1.0 - t * 1.4, 0, 1) * accent_a
        ga = ga * (1 - al[..., None]) + np.array(rgb(accent), np.float32)[None, None, :] * al[..., None]
    if grain:
        rng = np.random.default_rng(3)
        ga = ga + rng.integers(-grain, grain + 1, (H, W, 1))
    glass = Image.fromarray(ga.clip(0, 255).astype("uint8"), "RGB")
    out.paste(glass, (0, 0), el)
    # gradient border (bright top-left, dim bottom-right)
    bw = 2
    inner = _rr_mask((W, H), (box[0] + bw, box[1] + bw, box[2] - bw, box[3] - bw),
                     max(1, min(r, (box[2] - box[0]) // 2) - bw))
    ring = ImageChops.subtract(el, inner)
    gl = np.clip(1.0 - t * 0.75, 0.25, 1.0) * border
    ring_a = (np.asarray(ring).astype(np.float32) * gl).clip(0, 255).astype("uint8")
    bc = rgb(accent) if (accent is not None and accent_a > 0.12) else (255, 255, 255)
    out = Image.composite(Image.new("RGB", (W, H), bc), out, Image.fromarray(ring_a, "L"))
    return out


def make_backdrop_image(w, h, base, blobs=None, fade_edges=0, strength=1.0, seed=11):
    """Soft colour-blob gradient.  fade_edges>0 fades the blobs out to the flat
    `base` colour over that many px so the image melts into a flat parent."""
    w, h = max(8, int(w)), max(8, int(h))
    sw, sh = max(4, w // 4), max(4, h // 4)
    arr = np.zeros((sh, sw, 3), np.float32)
    arr[:] = np.array(rgb(base), np.float32)
    ys, xs = np.mgrid[0:sh, 0:sw].astype(np.float32)
    k = 1.0 if IS_DARK else 0.55
    for fx, fy, fr, col, st in (blobs if blobs is not None else BLOBS):
        d2 = ((xs - fx * sw) ** 2 + (ys - fy * sh) ** 2) / ((fr * max(sw, sh)) ** 2)
        a = np.exp(-d2 * 2.4) * st * strength * k
        arr = arr * (1 - a[..., None]) + np.array(rgb(col), np.float32)[None, None, :] * a[..., None]
    if fade_edges:
        fe = max(1.0, fade_edges / 4.0)
        edge = np.minimum.reduce([xs, ys, sw - 1 - xs, sh - 1 - ys])
        m = np.clip(edge / fe, 0, 1)
        m = m * m * (3 - 2 * m)
        arr = np.array(rgb(base), np.float32)[None, None, :] * (1 - m[..., None]) + arr * m[..., None]
    img = Image.fromarray(arr.clip(0, 255).astype("uint8"), "RGB").resize((w, h), Image.BICUBIC)
    rng = np.random.default_rng(seed)
    n = rng.integers(-1, 2, (h, w, 1))
    return Image.fromarray((np.asarray(img).astype(np.int16) + n).clip(0, 255).astype("uint8"), "RGB")


def draw_orb(img, cx, cy, radius, color):
    """Soft glowing disc with a thin ring, anti-aliased, drawn into a PIL image."""
    ss = 4
    R = int(radius + 18)
    x0, y0 = int(cx - R), int(cy - R)
    patch = img.crop((x0, y0, x0 + 2 * R, y0 + 2 * R)).resize((2 * R * ss, 2 * R * ss), Image.BILINEAR)
    S = 2 * R * ss
    c = S // 2
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse((c - (radius + 6) * ss, c - (radius + 6) * ss,
                                  c + (radius + 6) * ss, c + (radius + 6) * ss), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(7 * ss)).point(lambda v: int(v * 0.55))
    patch = Image.composite(Image.new("RGB", (S, S), rgb(color)), patch, glow)
    disk = Image.new("L", (S, S), 0)
    ImageDraw.Draw(disk).ellipse((c - radius * ss, c - radius * ss, c + radius * ss, c + radius * ss), fill=255)
    base_c = mix(patch.getpixel((4, 4)), color, 0.30)
    patch = Image.composite(Image.new("RGB", (S, S), rgb(base_c)), patch, disk)
    ring = ImageChops.subtract(disk, Image.new("L", (S, S), 0))
    inner = Image.new("L", (S, S), 0)
    ImageDraw.Draw(inner).ellipse((c - (radius - 2) * ss, c - (radius - 2) * ss,
                                   c + (radius - 2) * ss, c + (radius - 2) * ss), fill=255)
    ring = ImageChops.subtract(disk, inner)
    patch = Image.composite(Image.new("RGB", (S, S), rgb(mix(color, (255, 255, 255), 0.25))), patch, ring)
    img.paste(patch.resize((2 * R, 2 * R), Image.LANCZOS), (x0, y0))
    return img


# ─────────────────────────────────────────────────────────────────────────────
#  BACKDROP  (lives on a Canvas; glass children crop from it)
# ─────────────────────────────────────────────────────────────────────────────
class Backdrop:
    def __init__(self, canvas, base=None, blobs=None, fade_edges=0, strength=1.0):
        self.canvas = canvas
        self.base = base or BG
        self.blobs = blobs
        self.fade = fade_edges
        self.strength = strength
        self._pil = None
        self._comp = None            # backdrop + glass panels drawn on it (what widgets sample)
        self._photo = None
        self._extra = []             # PhotoImages of drawn glass panels (keep references)
        self.ver = 0                 # bumps whenever the composite changes
        self._size = (0, 0)
        self._children = weakref.WeakSet()
        canvas._neo_backdrop = self
        canvas.configure(bg=self.base)
        canvas.bind("<Configure>", self._on_cfg, add="+")
        self._job = None

    # -- image ---------------------------------------------------------------
    def pil(self, w=None, h=None):
        w = w or self.canvas.winfo_width()
        h = h or self.canvas.winfo_height()
        w, h = max(w, 8), max(h, 8)
        if self._pil is None or self._size != (w, h):
            self._pil = make_backdrop_image(w, h, self.base, self.blobs, self.fade, self.strength)
            self._size = (w, h)
            self._photo = None
            self._comp = None
        return self._pil

    def set_strength(self, v):
        """0 = flat colour (use for stimulus screens), 1 = full colour blobs."""
        if abs(v - self.strength) > 1e-6:
            self.strength = v
            self._pil = None
            self._photo = None
            self._comp = None

    def draw(self):
        """(Re)draw the backdrop item.  Call after canvas.delete('all')."""
        try:
            im = self.pil()
            self._comp = im.copy()
            self._extra = []
            self.ver += 1
            if self._photo is None:
                self._photo = ImageTk.PhotoImage(im)
            self.canvas.delete("neo_bg")
            self.canvas.create_image(0, 0, image=self._photo, anchor="nw", tags="neo_bg")
            self.canvas.tag_lower("neo_bg")
        except tk.TclError:
            pass

    def crop(self, widget, w, h):
        """Crop of the backdrop that lies under `widget` (w x h)."""
        im = self.pil()
        try:
            x = widget.winfo_rootx() - self.canvas.winfo_rootx()
            y = widget.winfo_rooty() - self.canvas.winfo_rooty()
        except tk.TclError:
            x = y = 0
        return self.crop_xy(x, y, w, h)

    def draw_glass(self, x1, y1, x2, y2, r=26, accent=None, accent_a=0.0, tags=(), pad=14):
        """Frosted glass panel (x1,y1)-(x2,y2) drawn straight onto the canvas."""
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        self.pil()
        if self._comp is None:
            self._comp = self._pil.copy()
        crop = self.crop_xy(x1 - pad, y1 - pad, x2 - x1 + 2 * pad, y2 - y1 + 2 * pad)
        im = render_glass(crop, r=r, pad=pad, accent=accent, accent_a=accent_a)
        self._comp.paste(im, (x1 - pad, y1 - pad))      # later widgets sample the panel too
        self.ver += 1
        ph = ImageTk.PhotoImage(im)
        self._extra.append(ph)
        return self.canvas.create_image(x1 - pad, y1 - pad, image=ph, anchor="nw", tags=tags)

    def crop_xy(self, x, y, w, h):
        im = self._comp if self._comp is not None else self.pil()
        if x >= 0 and y >= 0 and x + w <= im.width and y + h <= im.height:
            return im.crop((x, y, x + w, y + h))
        out = Image.new("RGB", (w, h), rgb(self.base))
        out.paste(im, (-x, -y))
        return out

    def register(self, widget):
        self._children.add(widget)

    # -- events --------------------------------------------------------------
    def _on_cfg(self, _e=None):
        if self._job:
            try:
                self.canvas.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.canvas.after(60, self._refresh)

    def _refresh(self):
        self._job = None
        try:
            self.pil()
            self.draw()
            for w in list(self._children):
                try:
                    w._render()
                except Exception:
                    pass
            self.canvas.event_generate("<<NeoBackdropChanged>>")
        except tk.TclError:
            pass


def find_backdrop(widget):
    w = widget
    while w is not None:
        if getattr(w, "_neo_opaque", False):        # a solid container hides the backdrop
            return None
        bd = getattr(w, "_neo_backdrop", None)
        if bd is not None:
            return bd
        w = getattr(w, "master", None)
    return None


def _bg_of(master, fallback=None):
    """Background colour of the container a widget is about to be placed in."""
    try:
        return master.cget("bg")
    except Exception:
        return fallback or BG


# ─────────────────────────────────────────────────────────────────────────────
#  NeuButton  -- drop-in for tk.Button
# ─────────────────────────────────────────────────────────────────────────────
class NeuButton(tk.Canvas):
    """variant: None (auto) | 'raised' | 'accent' | 'danger' | 'ghost'.
    If `bg` differs from the parent's colour it is used as the face colour."""

    def __init__(self, master, text="", command=None, font=None, fg=None, bg=None,
                 variant=None, radius=14, depth=4, padx=18, pady=10,
                 width=None, height=None, state="normal", cursor="hand2",
                 textvariable=None, anchor="center", justify="center",
                 wraplength=0, **ignored):
        self._parent_bg = _bg_of(master)
        super().__init__(master, bg=self._parent_bg, highlightthickness=0, bd=0,
                         cursor=cursor if state != "disabled" else "arrow")
        self._text = text
        self._tv = textvariable
        self._cmd = command
        self._font = tkfont.Font(font=font) if font else tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self._fg = fg
        self._face_arg = bg
        self._variant = variant
        self._r, self._depth = radius, depth
        self._padx, self._pady = padx, pady
        self._wchars, self._hlines = width, height
        self._state = state
        self._anchor = anchor
        self._justify = justify
        self._wrap = wraplength
        self._hover = self._down = False
        self._imgs = []
        self._job = None
        self._pad = int(depth * 1.9) + 2
        if textvariable is not None:
            textvariable.trace_add("write", lambda *_: self._set_text(textvariable.get()))
            self._text = textvariable.get()
        self._bd = find_backdrop(master)
        if self._bd is not None:
            self._bd.register(self)
        self._resize_request()
        self.bind("<Configure>", lambda e: self._schedule())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # -- tk.Button compatibility ----------------------------------------------
    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        redraw = False
        for k in list(kw):
            v = kw[k]
            if k == "text":
                self._text = v; redraw = True; kw.pop(k)
            elif k in ("fg", "foreground"):
                self._fg = v; redraw = True; kw.pop(k)
            elif k in ("bg", "background"):
                self._face_arg = v; redraw = True; kw.pop(k)
            elif k == "font":
                self._font = tkfont.Font(font=v); redraw = True; kw.pop(k)
            elif k == "command":
                self._cmd = v; kw.pop(k)
            elif k == "state":
                self._state = v
                super().configure(cursor="arrow" if v == "disabled" else "hand2")
                redraw = True; kw.pop(k)
            elif k in ("padx", "pady"):
                setattr(self, "_" + k, v); redraw = True; kw.pop(k)
            elif k == "width":
                self._wchars = v; redraw = True; kw.pop(k)
            elif k == "height":
                self._hlines = v; redraw = True; kw.pop(k)
            elif k in ("relief", "bd", "borderwidth", "activebackground", "activeforeground",
                       "highlightbackground", "highlightcolor", "highlightthickness",
                       "selectcolor", "anchor", "justify", "overrelief", "takefocus"):
                kw.pop(k)
        if kw:
            super().configure(**kw)
        if redraw:
            self._resize_request()
            self._schedule()

    config = configure

    def cget(self, key):
        m = {"text": self._text, "fg": self._fg, "foreground": self._fg,
             "bg": self._face_arg or self._parent_bg, "background": self._face_arg or self._parent_bg,
             "state": self._state, "command": self._cmd, "relief": "flat"}
        return m[key] if key in m else super().cget(key)

    __getitem__ = cget

    def invoke(self):
        if self._state != "disabled" and self._cmd:
            return self._cmd()

    def flash(self):
        self._down = True; self._render()
        self.after(120, lambda: (setattr(self, "_down", False), self._render()))

    # -- internals -------------------------------------------------------------
    def _set_text(self, t):
        self._text = t
        self._resize_request()
        self._schedule()

    def _resolve(self):
        """-> (variant, face, text colour)"""
        v = self._variant
        face = None
        if v is None and self._face_arg and hexc(self._face_arg) != hexc(self._parent_bg):
            v, face = "color", self._face_arg
        v = v or "raised"
        fg = self._fg or TEXT
        if v == "accent":
            face = face or ACCENT
        elif v == "danger":
            face = face or DANGER
        if v in ("accent", "danger", "color"):
            lum = (rgb(face)[0] * 299 + rgb(face)[1] * 587 + rgb(face)[2] * 114) / 1000
            fg = "#1A1510" if lum > 150 else "#F8F2E6"
        if v == "ghost":
            face = self._parent_bg
        face = face or lighten(self._parent_bg, 0.035 if IS_DARK else 0.0)
        return v, face, fg

    def _resize_request(self):
        lines = str(self._text).split("\n") or [""]
        f = self._font
        if self._wchars:
            tw = f.measure("0") * int(self._wchars)
        else:
            tw = max(f.measure(l) for l in lines)
            if self._wrap:
                tw = min(tw, self._wrap)
        lh = f.metrics("linespace")
        th = lh * (int(self._hlines) if self._hlines else len(lines))
        super().configure(width=int(tw + 2 * self._padx + 2 * self._pad),
                          height=int(th + 2 * self._pady + 2 * self._pad))

    def _schedule(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(15, self._render)

    def _render(self):
        self._job = None
        try:
            w, h = self.winfo_width(), self.winfo_height()
        except tk.TclError:
            return
        if w < 12 or h < 12:
            return
        variant, face, fg = self._resolve()
        disabled = self._state == "disabled"
        state = "pressed" if (self._down and not disabled) else ("hover" if self._hover and not disabled else "rest")
        bd_img, bd_key = None, ("flat", hexc(self._parent_bg))
        if self._bd is not None:
            try:
                x, y = self.winfo_rootx() - self._bd.canvas.winfo_rootx(), self.winfo_rooty() - self._bd.canvas.winfo_rooty()
                bd_img, bd_key = self._bd.crop(self, w, h), ("bd", id(self._bd), x, y, self._bd._size, self._bd.ver)
            except tk.TclError:
                pass
        key = ("btn", w, h, variant, hexc(face), state, self._r, self._depth, bd_key)

        def build():
            f = face
            if state == "hover":
                f = lighten(face, 0.07 if variant != "ghost" else 0.04)
            mode = "pressed" if state == "pressed" else "raised"
            if variant == "ghost" and state == "rest":      # flat until hovered
                return bd_img.copy() if bd_img is not None else Image.new("RGB", (w, h), rgb(self._parent_bg))
            glow = face if variant in ("accent", "danger", "color") and state != "pressed" else None
            return render_neu(w, h, self._parent_bg, f, self._r, self._depth, mode,
                              glow=glow, glow_a=0.45 if state == "hover" else 0.30, bg_img=bd_img)

        im = _cached(key, build)
        self._imgs = [ImageTk.PhotoImage(im)]
        self.delete("all")
        self.create_image(0, 0, image=self._imgs[0], anchor="nw")
        off = 1 if state == "pressed" else 0
        col = fg if not disabled else mix(fg, self._parent_bg, 0.6)
        kw = dict(text=self._text, fill=hexc(col) if not isinstance(col, str) else col,
                  font=self._font, justify=self._justify)
        if self._wrap:
            kw["width"] = self._wrap
        self.create_text(w // 2 + off, h // 2 + off, anchor="center", **kw)

    def _inside(self, e):
        return 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()

    def _on_enter(self, _e):
        self._hover = True; self._schedule()

    def _on_leave(self, _e):
        self._hover = self._down = False; self._schedule()

    def _on_press(self, _e):
        if self._state == "disabled":
            return
        self._down = True; self._render()

    def _on_release(self, e):
        was = self._down
        self._down = False
        self._render()
        if was and self._inside(e) and self._state != "disabled" and self._cmd:
            self._cmd()


# ─────────────────────────────────────────────────────────────────────────────
#  NeuWell / NeuText / NeuScrollbar
# ─────────────────────────────────────────────────────────────────────────────
class _NeuWell(tk.Canvas):
    """Inset neumorphic frame that hosts one child (used by NeuText)."""

    def __init__(self, master, radius=18, depth=6, margin=14):
        pbg = _bg_of(master)
        super().__init__(master, bg=pbg, highlightthickness=0, bd=0)
        self._pbg, self._r, self._depth, self._m = pbg, radius, depth, margin
        self.fill = darken(pbg, 0.10) if IS_DARK else lighten(pbg, 0.45)
        self._child = None
        self._win = None
        self._imgs = []
        self._job = None
        self._err = False
        self._pad = int(depth * 1.9) + 2
        self.bind("<Configure>", self._on_cfg)

    def set_error(self, on):
        self._err = bool(on)
        self._render()

    @property
    def fill_hex(self):
        return hexc(self.fill)

    def attach(self, child):
        self._child = child
        self._win = self.create_window(self._pad + self._m, self._pad + self._m, window=child, anchor="nw")
        child.update_idletasks()
        self.configure(width=child.winfo_reqwidth() + 2 * (self._pad + self._m),
                       height=child.winfo_reqheight() + 2 * (self._pad + self._m))

    def _on_cfg(self, e):
        if self._win is not None:
            inner = self._pad + self._m
            self.itemconfigure(self._win, width=max(10, e.width - 2 * inner), height=max(10, e.height - 2 * inner))
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(25, self._render)

    def _render(self):
        self._job = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        key = ("well", w, h, hexc(self._pbg), self._r, self._depth, self._err)
        im = _cached(key, lambda: render_neu(w, h, self._pbg, self.fill, self._r, self._depth, "inset",
                                             outline=DANGER if self._err else None))
        self._imgs = [ImageTk.PhotoImage(im)]
        self.delete("neo_img")
        self.create_image(0, 0, image=self._imgs[0], anchor="nw", tags="neo_img")
        self.tag_lower("neo_img")


class _WellMixin:
    """pack()/grid()/place() address the surrounding well instead of the widget."""
    def pack(self, *a, **k):
        return self._well.pack(*a, **k)

    def grid(self, *a, **k):
        return self._well.grid(*a, **k)

    def place(self, *a, **k):
        return self._well.place(*a, **k)

    def pack_forget(self):
        return self._well.pack_forget()

    def grid_forget(self):
        return self._well.grid_forget()

    def place_forget(self):
        return self._well.place_forget()

    def set_error(self, on=True):
        """Outline the well in the danger colour (used for validation)."""
        self._well.set_error(on)


class NeuText(_WellMixin, tk.Text):
    """tk.Text inside an inset neumorphic well; drop-in for tk.Text."""

    def __init__(self, master, radius=18, depth=6, margin=10, **kw):
        well = _NeuWell(master, radius, depth, margin)
        kw["bg"] = well.fill_hex
        kw.setdefault("fg", TEXT)
        kw.update(relief="flat", bd=0, highlightthickness=0)
        kw.setdefault("insertbackground", ACCENT)
        kw.setdefault("selectbackground", T("#BFDBFE"))
        kw.setdefault("selectforeground", TEXT)
        tk.Text.__init__(self, well, **kw)
        well.attach(self)
        self._well = well

    def destroy(self):
        try:
            tk.Text.destroy(self)
        finally:
            try:
                self._well.destroy()
            except Exception:
                pass


class NeuEntry(_WellMixin, tk.Entry):
    """tk.Entry inside an inset neumorphic well; drop-in for tk.Entry."""

    def __init__(self, master, radius=16, depth=5, margin=8, **kw):
        well = _NeuWell(master, radius, depth, margin)
        kw["bg"] = well.fill_hex
        kw.setdefault("fg", TEXT)
        kw.update(relief="flat", bd=0, highlightthickness=0)
        kw.setdefault("insertbackground", ACCENT)
        kw.setdefault("selectbackground", T("#BFDBFE"))
        kw.setdefault("selectforeground", TEXT)
        tk.Entry.__init__(self, well, **kw)
        well.attach(self)
        self._well = well

    def destroy(self):
        try:
            tk.Entry.destroy(self)
        finally:
            try:
                self._well.destroy()
            except Exception:
                pass


class NeuScrollbar(tk.Canvas):
    """Slim scrollbar compatible with Text.yview / yscrollcommand."""

    def __init__(self, master, command=None, width=16, **ignored):
        pbg = _bg_of(master)
        super().__init__(master, width=width, bg=pbg, highlightthickness=0, bd=0, cursor="hand2")
        self._cmd, self._pbg = command, pbg
        self._lo, self._hi = 0.0, 1.0
        self._drag = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)

    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        if "command" in kw:
            self._cmd = kw.pop("command")
        if kw:
            super().configure(**kw)

    config = configure

    def set(self, lo, hi):
        self._lo, self._hi = float(lo), float(hi)
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if h < 20:
            return
        self.create_line(w // 2, 8, w // 2, h - 8, fill=hexc(darken(self._pbg, 0.35)), width=4, capstyle="round")
        if self._hi - self._lo < 0.999:
            y1 = 8 + (h - 16) * self._lo
            y2 = 8 + (h - 16) * self._hi
            self.create_line(w // 2, y1 + 3, w // 2, max(y1 + 8, y2 - 3), width=8, capstyle="round",
                             fill=hexc(lighten(self._pbg, 0.22) if IS_DARK else darken(self._pbg, 0.25)))

    def _press(self, e):
        h = max(1, self.winfo_height())
        frac = (e.y - 8) / max(1, h - 16)
        if self._lo <= frac <= self._hi:
            self._drag = frac - self._lo
        else:
            self._drag = (self._hi - self._lo) / 2
            self._move_to(frac - self._drag)

    def _motion(self, e):
        if self._drag is None:
            return
        h = max(1, self.winfo_height())
        self._move_to((e.y - 8) / max(1, h - 16) - self._drag)

    def _move_to(self, f):
        if self._cmd:
            self._cmd("moveto", max(0.0, min(1.0, f)))


# ─────────────────────────────────────────────────────────────────────────────
#  GlassPanel  (flat container; `.body` holds the children)
# ─────────────────────────────────────────────────────────────────────────────
class GlassPanel(tk.Canvas):
    def __init__(self, master, padx=20, pady=12, radius=20, pad=10, accent=None, **ignored):
        pbg = _bg_of(master)
        super().__init__(master, bg=pbg, highlightthickness=0, bd=0)
        self._pbg, self._r, self._pd, self._accent = pbg, radius, pad, accent
        self._bd = find_backdrop(master)
        if self._bd is not None:
            self._bd.register(self)
        self._tint = lighten(pbg, 0.07 if IS_DARK else 0.0) if self._bd is None else None
        body_bg = hexc(mix(pbg, (255, 255, 255), 0.065 if IS_DARK else 0.35)) if self._bd is None else hexc(mix(pbg, (255, 255, 255), 0.07))
        self.body = tk.Frame(self, bg=body_bg, padx=padx, pady=pady)
        self.body._neo_opaque = True
        self.body_bg = body_bg
        self._win = self.create_window(pad + 2, pad + 2, window=self.body, anchor="nw")
        self._imgs = []
        self._job = None
        self.body.bind("<Configure>", self._on_body)
        self.bind("<Configure>", self._on_cfg)

    def _on_body(self, e):
        self.configure(width=e.width + 2 * (self._pd + 2), height=e.height + 2 * (self._pd + 2))

    def _on_cfg(self, e):
        self.itemconfigure(self._win, width=max(10, e.width - 2 * (self._pd + 2)))
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(25, self._render)

    def _render(self):
        self._job = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 24 or h < 24:
            return
        if self._bd is not None:
            src = self._bd.crop(self, w, h)
            skey = ("bd", id(self._bd), self.winfo_rootx(), self.winfo_rooty(), self._bd.ver)
        else:
            src, skey = Image.new("RGB", (w, h), rgb(self._pbg)), ("flat", hexc(self._pbg))
        key = ("gp", w, h, self._r, self._pd, skey, self._accent)
        im = _cached(key, lambda: render_glass(src, self._r, self._pd, accent=self._accent,
                                               accent_a=0.0 if not self._accent else 0.10))
        self._imgs = [ImageTk.PhotoImage(im)]
        self.delete("neo_img")
        self.create_image(0, 0, image=self._imgs[0], anchor="nw", tags="neo_img")
        self.tag_lower("neo_img")


# ─────────────────────────────────────────────────────────────────────────────
#  GlassCard  (clickable tile with a title + description)
# ─────────────────────────────────────────────────────────────────────────────
class GlassCard(tk.Canvas):
    def __init__(self, master, title, sub, color, command, width=260, height=150,
                 title_font=("Segoe UI", 16, "bold"), sub_font=("Segoe UI", 11),
                 icon=None, orb=True, **ignored):
        pbg = _bg_of(master)
        super().__init__(master, width=width, height=height, bg=pbg, highlightthickness=0, bd=0, cursor="hand2")
        self._pbg, self._title, self._sub, self._color = pbg, title, sub, color
        self._cmd, self._tf, self._sf, self._icon = command, title_font, sub_font, icon
        self._orb = orb
        self._hover = self._down = False
        self._imgs = []
        self._bd = find_backdrop(master)
        if self._bd is not None:
            self._bd.register(self)
        self._job = None
        self.bind("<Configure>", lambda e: self._schedule())
        self.bind("<Enter>", lambda e: (setattr(self, "_hover", True), self._schedule()))
        self.bind("<Leave>", lambda e: (setattr(self, "_hover", False), setattr(self, "_down", False), self._schedule()))
        self.bind("<ButtonPress-1>", lambda e: (setattr(self, "_down", True), self._render()))
        self.bind("<ButtonRelease-1>", self._release)

    def _release(self, e):
        was = self._down
        self._down = False
        self._render()
        if was and 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() and self._cmd:
            self._cmd()

    def _schedule(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(15, self._render)

    def _render(self):
        self._job = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 40 or h < 40:
            return
        if self._bd is not None:
            src = self._bd.crop(self, w, h)
            skey = ("bd", id(self._bd), self.winfo_rootx(), self.winfo_rooty(), self._bd.ver)
        else:
            src, skey = Image.new("RGB", (w, h), rgb(self._pbg)), ("flat", hexc(self._pbg))
        hov = self._hover or self._down
        orb = 28
        x0 = 40
        key = ("gc", w, h, skey, hexc(self._color), hov, self._down, orb)

        def build():
            im = render_glass(
                src, r=26, pad=14, accent=self._color, accent_a=0.22 if hov else 0.12,
                tint_a=(0.12 if IS_DARK else 0.46) if hov else None,
                border=0.68 if hov else None)
            if not self._orb:
                return im
            return draw_orb(im, x0 + orb, h // 2 + (2 if self._down else 0), orb, self._color)

        im = _cached(key, build)
        self._imgs = [ImageTk.PhotoImage(im)]
        self.delete("all")
        self.create_image(0, 0, image=self._imgs[0], anchor="nw")
        off = 2 if self._down else 0
        cy = h // 2 + off
        if not self._orb:                                    # centred layout (selection screens)
            tw = w - 70
            tcol = hexc(mix(self._color, (255, 255, 255), 0.30)) if hov else self._color
            t = self.create_text(w // 2, 0, text=self._title, anchor="n", width=tw, justify="center",
                                 fill=tcol, font=self._tf)
            sb = self.create_text(w // 2, 0, text=self._sub, anchor="n", width=tw, justify="center",
                                  fill=MUTED, font=self._sf)
            th, sh = self.bbox(t), self.bbox(sb)
            theight, sheight = th[3] - th[1], sh[3] - sh[1]
            y0 = cy - (theight + 12 + sheight) / 2
            self.coords(t, w // 2, y0)
            self.coords(sb, w // 2, y0 + theight + 12)
            return
        if self._icon:
            self.create_text(x0 + orb, cy, text=self._icon, fill=hexc(mix(self._color, (255, 255, 255), 0.35)),
                             font=("Segoe UI Emoji", 20))
        tx = x0 + 2 * orb + 26
        tw = max(80, w - tx - 36)
        t = self.create_text(tx, 0, text=self._title, anchor="nw", width=tw,
                             fill=hexc(mix(self._color, (255, 255, 255), 0.30)) if hov else TEXT, font=self._tf)
        sb = self.create_text(tx, 0, text=self._sub, anchor="nw", width=tw, fill=MUTED, font=self._sf)
        th = self.bbox(t); sh = self.bbox(sb)
        theight, sheight = th[3] - th[1], sh[3] - sh[1]
        y0 = cy - (theight + 8 + sheight) / 2
        self.coords(t, tx, y0)
        self.coords(sb, tx, y0 + theight + 8)


# ─────────────────────────────────────────────────────────────────────────────
#  NeoKeyboard  -- on-screen keyboard drawn on a single glass-backed canvas
# ─────────────────────────────────────────────────────────────────────────────
class NeoKeyboard(tk.Canvas):
    LAYOUTS = {
        "normal":  {"row1": list("QWERTYUIOP"), "row2": list("ASDFGHJKL"), "row3": list("ZXCVBNM")},
        "alpha":   {"row1": list("ABCDEFGHIJ"), "row2": list("KLMNOPQRS"), "row3": list("TUVWXYZ")},
        "cluster": {"row1": list("ETAOIFGYPB"), "row2": list("NSHRDVKJX"), "row3": list("LCUMWQZ")},
    }
    LAYOUT_NAMES = {"normal": "QWERTY", "alpha": "ALPHABETICAL", "cluster": "FREQUENCY"}
    CTRL = [("|◄", 1.0), ("◄", 1.0), ("⌫", 1.5), ("Space", 4.2), ("►", 1.0), ("►|", 1.0)]
    NUMPAD = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], [".", "0", "?"]]
    CLEAR_ID = "Delete"          # action id (kept so existing logic/log files still match)

    def __init__(self, master, target=None, layout="normal", notepad_app=None, on_key=None,
                 confirm_clear=None, **ignored):
        pbg = _bg_of(master)
        super().__init__(master, bg=pbg, highlightthickness=0, bd=0, cursor="hand2")
        self._pbg = pbg
        self._target, self.notepad_app, self._on_key = target, notepad_app, on_key
        self._layout = layout if layout in self.LAYOUTS else "normal"
        self._confirm = CONFIRM_CLEAR_ALL if confirm_clear is None else confirm_clear
        self._armed = False
        self._arm_job = None
        self._shift = self._caps = False
        self._keys = []                  # dicts: id, label, kind, rect
        self._panel = None
        self._comp = None                # composite PIL (backdrop + panel) used as key base
        self._photos = {}
        self._hover = self._down = self._flash = None
        self._job = None
        self._geom = None
        self._bdrop = Backdrop(self, base=pbg, fade_edges=90, strength=0.9)
        self.bind("<<NeoBackdropChanged>>", lambda e: self._relayout(force=True))
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<ButtonPress-1>", self._bpress)
        self.bind("<ButtonRelease-1>", self._brelease)

    # -- public API (same as the old OnScreenKeyboard) --------------------------
    def set_layout(self, layout):
        self._layout = layout if layout in self.LAYOUTS else "normal"
        self._relayout(force=True)

    # -- layout ---------------------------------------------------------------
    def _relayout(self, force=False):
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(5 if force else 30, self._build)

    def _build(self):
        self._job = None
        W, H = self.winfo_width(), self.winfo_height()
        if W < 200 or H < 120:
            return
        d = 5 if H >= 620 else 4 if H >= 420 else 3          # shadow depth of the keys
        mrg = int(d * 1.9) + 1                               # margin render_neu keeps around a key
        g = max(8, 2 * mrg - 2)                              # gap >= 2*margin -> shadows never clip
        m = mrg + max(4, int(min(W, H) * 0.012))
        head_h = max(40, int(H * 0.085))
        top = m + head_h + g
        usable_h = H - top - m
        rh = (usable_h - 3 * g) / 4.0
        col_gap = g + 6
        left_w = int((W - 2 * m - col_gap) * 0.795)
        np_x1 = m + left_w + col_gap
        np_x2 = W - m
        keys = []

        def add(kid, label, kind, x1, y1, x2, y2):
            keys.append(dict(id=kid, label=label, kind=kind, tag="k%d" % len(keys),
                             rect=(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))))

        lay = self.LAYOUTS[self._layout]
        for ri, rowname in enumerate(("row1", "row2", "row3")):
            row = lay[rowname]
            y1 = top + ri * (rh + g)
            kw = (left_w - (len(row) - 1) * g) / len(row)
            for ci, ch in enumerate(row):
                x1 = m + ci * (kw + g)
                add(ch, ch, "alpha", x1, y1, x1 + kw, y1 + rh)
        y1 = top + 3 * (rh + g)
        tot = sum(wt for _, wt in self.CTRL)
        avail = left_w - (len(self.CTRL) - 1) * g
        x = m
        for lab, wt in self.CTRL:
            kw = avail * wt / tot
            add(lab, lab, "ctrl", x, y1, x + kw, y1 + rh)
            x += kw + g
        # numpad lives inside a glass panel
        pp = max(12, g)
        panel = (np_x1, top - mrg // 2, np_x2, top + usable_h + mrg // 2)
        px1, py1, px2, py2 = panel
        title_h = max(22, int(rh * 0.26))
        in_x1, in_x2 = px1 + pp + mrg, px2 - pp - mrg
        in_y1, in_y2 = py1 + pp + title_h + mrg, py2 - pp - mrg
        ng = max(8, g - 2)
        nrh = (in_y2 - in_y1 - 3 * ng) / 4.0
        nkw = (in_x2 - in_x1 - 2 * ng) / 3.0
        for ri, row in enumerate(self.NUMPAD):
            for ci, ch in enumerate(row):
                x1 = in_x1 + ci * (nkw + ng)
                y1 = in_y1 + ri * (nrh + ng)
                add(ch, ch, "num", x1, y1, x1 + nkw, y1 + nrh)
        # CLEAR ALL: alone in the top-right corner, away from every typing key
        add(self.CLEAR_ID, "\u2715  Clear all", "clear", np_x1, m, np_x2, m + head_h)

        self._keys, self._panel = keys, panel
        self._title_h, self._pp = title_h, pp
        self._geom = (W, H, g, rh, m, head_h)
        self._d, self._mrg = d, mrg
        # base image = backdrop + glass numpad panel (keys are rendered on crops of it)
        comp = self._bdrop.pil(W, H).copy()
        pad = 14
        crop = self._crop(comp, px1 - pad, py1 - pad, px2 + pad, py2 + pad)
        glass = render_glass(crop, r=28, pad=pad, accent=PURPLE, accent_a=0.07)
        comp.paste(glass, (px1 - pad, py1 - pad))
        self._comp = comp
        self._comp_photo = ImageTk.PhotoImage(comp)
        self._photos = {}
        self._draw_all()

    @staticmethod
    def _crop(img, x1, y1, x2, y2):
        if x1 >= 0 and y1 >= 0 and x2 <= img.width and y2 <= img.height:
            return img.crop((x1, y1, x2, y2))
        out = Image.new("RGB", (x2 - x1, y2 - y1), img.getpixel((0, 0)))
        out.paste(img, (-x1, -y1))
        return out

    # -- drawing ---------------------------------------------------------------
    def _key_style(self, k):
        """-> (face colour, text colour, glow colour or None)"""
        kind, base = k["kind"], self._pbg
        lift = lighten(base, 0.04) if IS_DARK else base
        if kind == "alpha":
            return lift, TEXT, None
        if kind == "ctrl":
            return mix(lift, ACCENT, 0.14), (AMBER if k["id"] == "\u232b" else TEXT), None
        if kind == "num":
            return mix(lift, PURPLE, 0.12), TEXT, None
        if self._armed:                                  # clear key, waiting for 2nd tap
            return DANGER, ("#1A1510" if IS_DARK else "#FFFFFF"), DANGER
        return mix(lift, DANGER, 0.22), DANGER, DANGER

    def _key_photo(self, k, state):
        cache_key = (k["tag"], state, self._armed if k["kind"] == "clear" else 0)
        ph = self._photos.get(cache_key)
        if ph is None:
            x1, y1, x2, y2 = k["rect"]
            mrg = self._mrg
            crop = self._crop(self._comp, x1 - mrg, y1 - mrg, x2 + mrg, y2 + mrg)
            face, _, glow = self._key_style(k)
            f = face
            if state == "hover":
                f = lighten(face, 0.07 if IS_DARK else 0.0)
            elif state == "flash":
                f = mix(face, GREEN, 0.7)
            mode = "pressed" if state in ("down", "flash") else "raised"
            im = render_neu(x2 - x1 + 2 * mrg, y2 - y1 + 2 * mrg, self._pbg, f,
                            r=min(18, (y2 - y1) // 3), depth=self._d, mode=mode,
                            glow=(glow if (glow and mode == "raised") else None),
                            glow_a=0.34, bg_img=crop)
            ph = ImageTk.PhotoImage(im)
            self._photos[cache_key] = ph
        return ph

    def _font_for(self, k):
        rh = k["rect"][3] - k["rect"][1]
        kind = k["kind"]
        if kind == "alpha":
            return ("Segoe UI", max(14, min(34, int(rh * 0.34))), "bold")
        if kind == "num":
            return ("Segoe UI", max(13, min(28, int(rh * 0.34))), "bold")
        if kind == "clear":
            return ("Segoe UI", max(10, min(15, int(rh * 0.27))), "bold")
        return ("Segoe UI", max(12, min(22, int(rh * 0.27))), "bold")

    def _state_of(self, k):
        kid = k["id"]
        if self._flash == kid:
            return "flash"
        if self._down == kid:
            return "down"
        if self._hover == kid:
            return "hover"
        return "rest"

    def _draw_all(self):
        self.delete("all")
        self.create_image(0, 0, image=self._comp_photo, anchor="nw", tags="bg")
        px1, py1, px2, py2 = self._panel
        self.create_text((px1 + px2) // 2, py1 + self._pp + self._title_h // 2, text="NUMBERS",
                         fill=MUTED, font=("Segoe UI", max(9, int(self._title_h * 0.42)), "bold"))
        W, H, g, rh, m, head_h = self._geom
        self.create_text(m + 8, m + head_h // 2, anchor="w",
                         text="%s  KEYBOARD" % self.LAYOUT_NAMES.get(self._layout, ""),
                         fill=MUTED, font=("Segoe UI", max(10, int(head_h * 0.30)), "bold"))
        for k in self._keys:
            self._draw_key(k)

    def _draw_key(self, k):
        self.delete(k["tag"])
        st = self._state_of(k)
        x1, y1, x2, y2 = k["rect"]
        self.create_image(x1 - self._mrg, y1 - self._mrg, image=self._key_photo(k, st),
                          anchor="nw", tags=k["tag"])
        _, fg, _ = self._key_style(k)
        label = "Tap again to clear" if (self._armed and k["kind"] == "clear") else k["label"]
        off = 1 if st in ("down", "flash") else 0
        self.create_text((x1 + x2) // 2 + off, (y1 + y2) // 2 + off, text=label, fill=fg,
                         font=self._font_for(k), tags=k["tag"])

    # -- interaction -----------------------------------------------------------
    def _hit(self, x, y):
        for k in self._keys:
            x1, y1, x2, y2 = k["rect"]
            if x1 <= x < x2 and y1 <= y < y2:
                return k
        return None

    def _set_hover(self, kid):
        if kid == self._hover:
            return
        old = self._hover
        self._hover = kid
        for k in self._keys:
            if k["id"] in (old, kid):
                self._draw_key(k)

    def _motion(self, e):
        k = self._hit(e.x, e.y)
        self._set_hover(k["id"] if k else None)

    def _bpress(self, e):
        k = self._hit(e.x, e.y)
        if k:
            self._down = k["id"]
            self._draw_key(k)

    def _brelease(self, e):
        k = self._hit(e.x, e.y)
        was = self._down
        self._down = None
        for kk in self._keys:
            if kk["id"] == was:
                self._draw_key(kk)
        if k and k["id"] == was:
            self._activate(k)

    def _activate(self, k):
        kid = k["id"]
        self._flash = kid
        self._draw_key(k)
        self.after(150, lambda: self._unflash(k))
        self._press(kid)

    def _unflash(self, k):
        if self._flash == k["id"]:
            self._flash = None
            try:
                self._draw_key(k)
            except tk.TclError:
                pass

    # -- key logic (same behaviour as the old OnScreenKeyboard._press) ------------
    def _press(self, key):
        t = self._target
        if key == self.CLEAR_ID:
            return self._request_clear()
        if self._armed:                       # any other key cancels a pending clear
            self._disarm()
        if self._on_key is not None:
            return self._on_key(key)
        if key in ("Save & next", "Enter"):
            if getattr(self, "notepad_app", None) and hasattr(self.notepad_app, "_save"):
                self.notepad_app._save()
            elif t:
                t.insert("insert", "\n")
        elif key in ("⌫", "Backspace"):
            if t and t.index("insert") != "1.0":
                t.delete("insert-1c", "insert")
        elif key == "|◄":
            if t: t.mark_set("insert", "1.0")
        elif key == "◄":
            if t and t.index("insert") != "1.0":
                t.mark_set("insert", "insert-1c")
        elif key == "►":
            if t: t.mark_set("insert", "insert+1c")
        elif key == "►|":
            if t: t.mark_set("insert", "end-1c")
        elif key == "Space":
            if t: t.insert("insert", " ")
        else:
            if t: t.insert("insert", key)
        if t:
            t.see("insert")
            t.focus_set()

    def _request_clear(self):
        if not self._confirm:
            return self._do_clear()
        if self._armed:
            self._disarm()
            return self._do_clear()
        self._armed = True
        self._photos = {kk: v for kk, v in self._photos.items()
                        if not any(k["tag"] == kk[0] and k["kind"] == "clear" for k in self._keys)}
        self._redraw_clear()
        self._arm_job = self.after(CONFIRM_WINDOW_MS, self._disarm)

    def _disarm(self):
        if self._arm_job:
            try:
                self.after_cancel(self._arm_job)
            except Exception:
                pass
            self._arm_job = None
        if self._armed:
            self._armed = False
            try:
                self._redraw_clear()
            except tk.TclError:
                pass

    def _redraw_clear(self):
        for k in self._keys:
            if k["kind"] == "clear":
                self._draw_key(k)

    def _do_clear(self):
        if self._on_key is not None:
            return self._on_key(self.CLEAR_ID)
        t = self._target
        if t:
            t.delete("1.0", "end")
            t.focus_set()


# aliases so launcher.py / keyboardaccuracy.py can keep calling it OnScreenKeyboard
OnScreenKeyboard = NeoKeyboard
