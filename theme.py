"""
theme.py  --  eye-comfort colour themes for the tkinter interface.

Only the *interface* windows (launcher, experiment, notepad, emergency,
keyboard accuracy) use this.  The OpenCV camera window is NOT affected.

HOW TO USE
    from theme import T
    bg = T("#FFFFFF")      # -> themed colour for the current mode

SWITCH  (change THEME_MODE below, nothing else needs editing)
    "dusk"    : dark, warm, low-glare palette.  Best for LONG test sessions
                (no large bright surface, no pure white, no blue light).
    "warm"    : the previous cream / sand light theme.
    "classic" : the original cool white colours.
"""

THEME_MODE = "dusk"            # "dusk" | "warm" | "classic"
WARM_THEME = THEME_MODE != "classic"   # kept for backward compatibility

# ----------------------------------------------------------------------------
#  DUSK  -  dark warm palette (text/background contrast about 9:1, never 21:1)
# ----------------------------------------------------------------------------
_DUSK = {
    # surfaces
    "#FFFFFF": "#26211B",   # surface / experiment background
    "#F8FAFC": "#1E1A15",   # page background
    "#F5F6F8": "#1E1A15",   # launcher / keyboard background
    "#F1F5F9": "#2B251E",
    "#EFEFEF": "#3A3228",   # button hover
    "#E5E7EB": "#3A3228",   # separators / bars
    "#E2E8F0": "#4A4034",   # borders
    "#DDE1E7": "#4A4034",
    "#CBD5E1": "#5A4E40",
    "#BFDBFE": "#5C4630",   # selection highlight
    # text
    "#1A1D23": "#E9DDC6",   # main text -> soft cream (not pure white)
    "#0F172A": "#E9DDC6",
    "#475569": "#B7A88E",
    "#6B7280": "#A89A82",   # muted text
    "#64748B": "#A89A82",
    "#000000": "#E9DDC6",   # fixation cross
    # key / button fills (previously dark slate / navy)
    "#334155": "#4A4034",   # control keys
    "#1E3A8A": "#5A4630",   # numpad keys
    # accents (lighter so they read on a dark background)
    "#2563EB": "#E0A458",   # blue accent   -> amber
    "#3B82F6": "#E8B675",
    "#1D4ED8": "#C98A3D",
    "#7C3AED": "#C79AB8",   # purple        -> dusty mauve
    "#16A34A": "#9DBF7A",   # green         -> sage
    "#15803D": "#85A866",
    "#D97706": "#E0A458",   # amber
    "#EA580C": "#E0905A",
    "#C2410C": "#C97A45",
    "#DC2626": "#E8806A",   # danger        -> soft coral
    "#B91C1C": "#D4705C",
}

# ----------------------------------------------------------------------------
#  WARM  -  previous light cream theme
# ----------------------------------------------------------------------------
_WARM = {
    "#FFFFFF": "#FBF3E4", "#F8FAFC": "#F3E9D6", "#F5F6F8": "#F3E9D6",
    "#F1F5F9": "#EFE4CE", "#EFEFEF": "#EADFC8", "#E5E7EB": "#E0D3BA",
    "#E2E8F0": "#D6C7A8", "#DDE1E7": "#D6C7A8", "#CBD5E1": "#CDBE9F",
    "#BFDBFE": "#EBD3A8",
    "#1A1D23": "#3B2F24", "#0F172A": "#3B2F24", "#334155": "#4A3C2E",
    "#475569": "#6E5E49", "#6B7280": "#7A6A55", "#64748B": "#85755F",
    "#000000": "#2B2118",
    "#2563EB": "#A5602F", "#3B82F6": "#C07A45", "#1D4ED8": "#7F4624",
    "#1E3A8A": "#5C3A21", "#7C3AED": "#8E5A7A", "#16A34A": "#5E8C3A",
    "#15803D": "#4F7A2F", "#D97706": "#C98A2B", "#EA580C": "#C96A2B",
    "#C2410C": "#A8541F", "#DC2626": "#C8402A", "#B91C1C": "#A63A26",
}

# Light text drawn ON a strong coloured key (control / numpad keys).
# Use  TXT_LIGHT  instead of T("#F8FAFC") for those, so it stays readable.
TXT_LIGHT = "#F1E6D0" if THEME_MODE == "dusk" else "#F8FAFC"

_MAP = _DUSK if THEME_MODE == "dusk" else _WARM


def _auto_warm(hex_color):
    """Fallback for any colour not in the map."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if THEME_MODE == "dusk":
        # invert lightness roughly, then warm it
        lum = (r * 299 + g * 587 + b * 114) / 1000.0
        if lum > 140:      # light colour -> dark warm
            r, g, b = int(r * 0.17), int(g * 0.15), int(b * 0.12)
        else:              # dark colour  -> light warm
            r, g, b = min(255, int(r * 0.4 + 170)), min(255, int(g * 0.4 + 155)), min(255, int(b * 0.4 + 125))
        return "#{:02X}{:02X}{:02X}".format(r, g, b)
    r = min(255, int(r * 0.98 + 6))
    g = int(g * 0.93)
    b = int(b * 0.72)
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def T(hex_color):
    """Return the themed version of a hex colour (or the original in 'classic')."""
    if THEME_MODE == "classic":
        return hex_color
    key = hex_color.upper()
    return _MAP.get(key) or _auto_warm(hex_color)
