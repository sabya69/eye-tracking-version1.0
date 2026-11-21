"""
test_cursor.py  --  a distinct, high-visibility mouse cursor for the test screens.

The default arrow is thin and easy to lose on a full-screen test.  This builds a
32x32 colour cursor (amber ring + centre dot, thin dark outline so it is visible
on both dark and light backgrounds) and applies it to a window and all of its
children.  The hotspot is the exact centre, so the click point is the middle of
the ring.

If the custom cursor cannot be loaded (non-Windows, locked temp folder, ...)
it falls back to Tk's built-in "circle" cursor.  Nothing here can crash a test.
"""
import math
import os
import struct
import tempfile

FALLBACK = "circle"
_SIZE = 32
_cache = {"spec": None}


def _build_cur_bytes(size=_SIZE):
    ring_in, ring_out = 9.0, 12.0          # amber ring radii (px)
    dot_r = 2.6                            # centre dot radius
    amber = (224, 164, 88)                 # (R, G, B)  matches theme accent
    dark = (30, 26, 21)                    # outline
    c = (size - 1) / 2.0

    def cov(d, lo, hi):                    # soft 1px anti-aliased band
        return max(0.0, min(1.0, min(d - lo, hi - d) + 0.5))

    px = []
    for y in range(size):
        row = []
        for x in range(size):
            d = math.hypot(x - c, y - c)
            a_ring = cov(d, ring_in, ring_out)
            a_out = cov(d, ring_in - 1.4, ring_out + 1.4)
            a_dot = cov(d, -1, dot_r)
            a_dot_out = cov(d, -1, dot_r + 1.4)
            # compose: dark outline first, amber on top
            a_dark = max(a_out, a_dot_out)
            a_col = max(a_ring, a_dot)
            alpha = max(a_dark, a_col)
            if alpha <= 0.002:
                row.append((0, 0, 0, 0))
                continue
            w_col = a_col / alpha
            r = int(amber[0] * w_col + dark[0] * (1 - w_col))
            g = int(amber[1] * w_col + dark[1] * (1 - w_col))
            b = int(amber[2] * w_col + dark[2] * (1 - w_col))
            row.append((r, g, b, int(alpha * 255)))
        px.append(row)

    # BMP pixel data is bottom-up, BGRA
    pixel_data = b"".join(
        struct.pack("<BBBB", b, g, r, a)
        for row in reversed(px) for (r, g, b, a) in row
    )
    mask_row = ((size + 31) // 32) * 4
    and_mask = b"\x00" * (mask_row * size)      # alpha channel does the masking
    bih = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                      len(pixel_data) + len(and_mask), 0, 0, 0, 0)
    image = bih + pixel_data + and_mask
    hot = size // 2
    header = struct.pack("<HHH", 0, 2, 1)       # ICONDIR, type 2 = cursor
    entry = struct.pack("<BBBBHHII", size, size, 0, 0, hot, hot, len(image), 22)
    return header + entry + image


def _cursor_file():
    path = os.path.join(tempfile.gettempdir(), "gaze_test_cursor.cur")
    try:
        with open(path, "wb") as f:
            f.write(_build_cur_bytes())
        return path
    except Exception:
        return None


def cursor_spec(widget=None):
    """Return a Tk cursor spec that works on this machine."""
    if _cache["spec"] is not None:
        return _cache["spec"]
    spec = FALLBACK
    if os.name == "nt" and widget is not None:
        path = _cursor_file()
        if path:
            path = path.replace("\\", "/")
            for cand in ("@" + path, "@{" + path + "}"):
                try:
                    probe = widget.winfo_toplevel()
                    old = probe.cget("cursor")
                    probe.configure(cursor=cand)     # raises TclError if bad
                    probe.configure(cursor=old)
                    spec = cand
                    break
                except Exception:
                    continue
    _cache["spec"] = spec
    return spec


def apply_test_cursor(widget):
    """Apply the test cursor to `widget` and every child (recursively)."""
    spec = cursor_spec(widget)
    _apply(widget, spec)
    return spec


def _apply(w, spec):
    try:
        w.configure(cursor=spec)
    except Exception:
        pass
    for ch in w.winfo_children():
        _apply(ch, spec)
