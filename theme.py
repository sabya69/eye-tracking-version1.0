"""
theme.py  --  warm, eye-comfort colour theme for the tkinter interface.

Only the *interface* windows (launcher, experiment, notepad, emergency,
keyboard accuracy) use this.  The OpenCV camera window is NOT affected.

HOW TO USE
    from theme import T
    bg = T("#FFFFFF")      # -> warm cream when the theme is on

SWITCH
    Set WARM_THEME = False to get the original cool/white colours back
    (no other file needs to be edited).
"""

WARM_THEME = True

# original colour  ->  warm replacement
# (low blue light, softer contrast: cream / sand backgrounds, brown text)
_MAP = {
    # backgrounds / surfaces
    "#FFFFFF": "#FBF3E4",   # white surface        -> warm cream
    "#F8FAFC": "#F3E9D6",   # light page bg        -> soft sand
    "#F5F6F8": "#F3E9D6",   # launcher bg          -> soft sand
    "#F1F5F9": "#EFE4CE",
    "#EFEFEF": "#EADFC8",   # button hover
    "#E5E7EB": "#E0D3BA",   # separators / bars
    "#E2E8F0": "#D6C7A8",   # borders
    "#DDE1E7": "#D6C7A8",
    "#CBD5E1": "#CDBE9F",
    "#BFDBFE": "#EBD3A8",   # light-blue highlight -> light amber
    # text
    "#1A1D23": "#3B2F24",   # main text            -> warm dark brown
    "#0F172A": "#3B2F24",
    "#334155": "#4A3C2E",
    "#475569": "#6E5E49",
    "#6B7280": "#7A6A55",   # muted text
    "#64748B": "#85755F",
    "#000000": "#2B2118",   # fixation cross
    # accents (blue/purple removed -> warm tones)
    "#2563EB": "#A5602F",   # blue accent          -> sienna
    "#3B82F6": "#C07A45",
    "#1D4ED8": "#7F4624",
    "#1E3A8A": "#5C3A21",
    "#7C3AED": "#8E5A7A",   # purple               -> dusty mauve
    "#16A34A": "#5E8C3A",   # green                -> olive
    "#15803D": "#4F7A2F",
    "#D97706": "#C98A2B",   # amber
    "#EA580C": "#C96A2B",
    "#C2410C": "#A8541F",
    "#DC2626": "#C8402A",   # danger red           -> burnt red
    "#B91C1C": "#A63A26",
}


def _auto_warm(hex_color):
    """Fallback for any colour not in the map: cut blue, slightly cut green."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = min(255, int(r * 0.98 + 6))
    g = int(g * 0.93)
    b = int(b * 0.72)
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def T(hex_color):
    """Return the warm version of a hex colour (or the original if disabled)."""
    if not WARM_THEME:
        return hex_color
    key = hex_color.upper()
    return _MAP.get(key) or _auto_warm(hex_color)
