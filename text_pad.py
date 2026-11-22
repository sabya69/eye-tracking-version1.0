
import cv2
import numpy as np
import time
import datetime
import os
from PIL import Image, ImageDraw
import neo_cv as _cv
from neo_ui import BG, TEXT, MUTED, ACCENT, GREEN, PURPLE, AMBER, IS_DARK, mix, lighten   # soft glass look


class TextPad:
    DWELL_TIME = 1.0
    PAD_W = 700;  PAD_H = 566
    MARGIN = 24;  BTN_H = 56;  BTN_GAP = 20
    LINE_H = 30;  FONT_SCALE = 0.60;  FONT_PX = 21
    FONT   = cv2.FONT_HERSHEY_SIMPLEX

    # Fixed window position on screen — gaze mapping uses these offsets
    PAD_WIN_X = 50    # pixels from left edge of screen
    PAD_WIN_Y = 80    # pixels from top edge of screen

    # (display label, action key, button color BGR)
    BUTTONS = [
        ("ALPHA KB",    "alpha",   (0, 110, 180)),
        ("QWERTY KB",   "normal",  (120, 55, 0)),
        ("CLUSTER KB",  "cluster", (60, 0, 100)),
    ]

    def __init__(self):
        self.visible      = False
        self.buffer       = ""
        self._hovered     = None
        self._dwell_start = None
        self._dwell_prog  = 0.0
        self._last_act_t  = 0.0
        self._flash_msg   = ""
        self._flash_t     = 0.0
        self._cooldown    = 1.5
        self._gaze_dot    = None   # (x, y) in pad-window pixels, drawn as indicator
        self._vkb         = None
        self._surf        = None   # cached neumorphic / glass art (built on first render)
        self._patches     = {}
        # ── Heatmap support ──────────────────────────────────────────────────
        self.last_saved_path    = None   # path of the most recently saved file
        self._typing_gaze_pts   = []     # (norm_x, norm_y) collected while typing
        self._heatmap_pending   = False  # set True after save so tracker can act

        # pre-compute button rects  (action, x1, y1, x2, y2)
        total_w = self.PAD_W - 2*self.MARGIN
        n  = len(self.BUTTONS)
        bw = (total_w - (n-1)*self.BTN_GAP) // n
        by = self.PAD_H - self.MARGIN - self.BTN_H
        self._btn_rects = []
        bx = self.MARGIN
        for _, action, _ in self.BUTTONS:
            self._btn_rects.append((action, bx, by, bx+bw, by+self.BTN_H))
            bx += bw + self.BTN_GAP

    # ── text area ─────────────────────────────────────────────────────────────
    @property
    def _text_area(self):
        x1 = self.MARGIN
        y1 = self.MARGIN + 40
        x2 = self.PAD_W - self.MARGIN
        y2 = self.PAD_H - self.MARGIN - self.BTN_H - self.BTN_GAP - 12
        return x1, y1, x2, y2

    # ── public API ────────────────────────────────────────────────────────────
    def link_keyboard(self, vkb):
        """Connect VirtualKeyboard to control layouts."""
        self._vkb = vkb

    def toggle(self):
        self.visible = not self.visible
        if not self.visible:
            try: cv2.destroyWindow("Text Pad")
            except: pass

    def close(self):
        self.visible = False
        try: cv2.destroyWindow("Text Pad")
        except: pass

    def append(self, text: str):
        """Add a sentence/word from the virtual keyboard."""
        if self.buffer and not self.buffer.endswith(" "):
            self.buffer += " "
        self.buffer += text
        self.visible = True          # auto-open pad when text arrives
        self._flash("Added to pad!")
        print(f"[TextPad] Received: {text!r}  (total {len(self.buffer)} chars)")

    def save_now(self):
        """Called directly by keyboard shortcut S — always works."""
        self._save()

    def record_gaze(self, norm_x: float, norm_y: float):
        """Called by tracker each frame when the text pad is visible.
        Accumulates normalised gaze points for heatmap generation."""
        if self.visible:
            self._typing_gaze_pts.append((float(norm_x), float(norm_y)))

    def pop_heatmap_data(self):
        """Return (gaze_pts, saved_path) and reset the pending flag.
        Returns None if no heatmap is ready yet."""
        if not self._heatmap_pending:
            return None
        self._heatmap_pending = False
        pts  = list(self._typing_gaze_pts)
        path = self.last_saved_path
        # Keep the gaze list so the final-session heatmap still has all points
        return pts, path

    def update_gaze(self, screen_x: float, screen_y: float):
      
        if not self.visible:
            return None
        kx = int(screen_x - self.PAD_WIN_X)
        ky = int(screen_y - self.PAD_WIN_Y)
        self._gaze_dot = (kx, ky)

        hit = next((act for act,x1,y1,x2,y2 in self._btn_rects
                    if x1<=kx<x2 and y1<=ky<y2), None)
        if hit != self._hovered:
            self._hovered     = hit
            self._dwell_start = time.time() if hit else None
            self._dwell_prog  = 0.0
            return None
        if hit and self._dwell_start:
            self._dwell_prog = min(1.0, (time.time()-self._dwell_start)/self.DWELL_TIME)
            if self._dwell_prog >= 1.0 and time.time()-self._last_act_t > self._cooldown:
                self._last_act_t  = time.time()
                self._dwell_start = time.time()
                self._dwell_prog  = 0.0
                self._do(hit)
                return hit
        return None

    def blink_press(self):
        """Trigger hovered button on left blink."""
        if self._hovered and self.visible and time.time()-self._last_act_t > 0.5:
            self._do(self._hovered)
            self._last_act_t = time.time()
            return self._hovered
        return None

    def _do(self, action: str):
        if action in ("alpha", "normal", "cluster"):
            if self._vkb is not None:
                self._vkb.set_layout(action)
                self._vkb.visible = True
                self._flash(f"Opened {action} layout!")
        elif action == "save":  self._save()
        elif action == "clear":
            self.buffer = ""
            self._flash("Cleared!")
        elif action == "close": self.close()

    def _save(self):
        if not self.buffer.strip():
            self._flash("Nothing to save!")
            return
        fname = "typed_text_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write(self.buffer.strip())
            self._flash(f"Saved: {fname}")
            print(f"[TextPad] Saved -> {fname}")
            # ── Signal heatmap generation ─────────────────────────────────
            self.last_saved_path  = os.path.abspath(fname)
            self._heatmap_pending = True
        except Exception as e:
            self._flash("Save failed!")
            print(f"[TextPad] Save error: {e}")

    def _flash(self, msg: str):
        self._flash_msg = msg
        self._flash_t   = time.time()

    # ── word-wrap ─────────────────────────────────────────────────────────────
    def _wrap(self, text: str, max_w: int):
        f = _cv.font(self.FONT_PX, bold=False)
        lines, cur = [], ""
        for word in text.split(" "):
            test = (cur + " " + word).strip()
            if f.getlength(test) <= max_w:
                cur = test
            else:
                if cur: lines.append(cur)
                cur = word
        if cur: lines.append(cur)
        return lines

    # ── render ────────────────────────────────────────────────────────────────
    _FACES = {"alpha": AMBER, "normal": ACCENT, "cluster": PURPLE}

    def _face(self, action):
        lift = lighten(BG, 0.04) if IS_DARK else BG
        return mix(lift, self._FACES.get(action, ACCENT), 0.30)

    def _build_art(self):
        S = _cv.Surface(self.PAD_W, self.PAD_H, depth=4)
        m = self.MARGIN
        S.glass((m, 10, self.PAD_W - m, 10 + 40), r=20, pad=10)
        tx1, ty1, tx2, ty2 = self._text_area
        S.inset((tx1, ty1, tx2, ty2), r=16)
        S.freeze_bare()
        _cv.draw_text_center(S.img, (m, 10, self.PAD_W - m, 50), "Text Pad  ·  Gaze-to-Type Buffer   |   S = save now", 15, TEXT, bold=True)
        for (disp, action, _c), (_a, x1, y1, x2, y2) in zip(self.BUTTONS, self._btn_rects):
            S.key((x1, y1, x2, y2), disp, self._face(action), TEXT, "rest", None, 16, paste=True)
        _cv.draw_text_center(S.img, (m, self.PAD_H - 22, self.PAD_W - m, self.PAD_H - 4),
                             "Gaze-dwell or left-blink buttons  ·  S=save  T=toggle  ESC=end", 12, MUTED, bold=False)
        self._surf = S
        self._base_bgr = _cv.to_bgr(S.img)
        self._patches = {}

    def _patch(self, action, state):
        k = (action, state)
        p = self._patches.get(k)
        if p is None:
            disp = next(d for d, a, _ in self.BUTTONS if a == action)
            rect = next((x1, y1, x2, y2) for a, x1, y1, x2, y2 in self._btn_rects if a == action)
            x, y, im = self._surf.key(rect, disp, self._face(action), TEXT, state, None, 16)
            p = (x, y, _cv.to_bgr(im))
            self._patches[k] = p
        return p

    def render(self):
        if not self.visible:
            return
        if self._surf is None:
            self._build_art()
        img = self._base_bgr.copy()

        # buttons: hover look + dwell ring
        for (disp, action, _c), (_a, x1, y1, x2, y2) in zip(self.BUTTONS, self._btn_rects):
            if self._hovered == action:
                x, y, pm = self._patch(action, "hover")
                img[y:y + pm.shape[0], x:x + pm.shape[1]] = pm
                if self._dwell_prog > 0:
                    cv2.ellipse(img, ((x1 + x2) // 2, (y1 + y2) // 2), (min(x2 - x1, y2 - y1) // 2 - 4,) * 2, -90, 0,
                                int(360 * self._dwell_prog), _cv.to_bgr_tuple(ACCENT), 3, cv2.LINE_AA)

        tx1, ty1, tx2, ty2 = self._text_area
        pil = Image.fromarray(img[:, :, ::-1])
        d = ImageDraw.Draw(pil)
        # typed text
        placeholder = "Start typing with the virtual keyboard, then press ENTER"
        raw = self.buffer if self.buffer else placeholder
        pad = 14
        lines = self._wrap(raw, tx2 - tx1 - 2 * pad)
        max_lines = max(1, (ty2 - ty1 - 16) // self.LINE_H)
        vis = lines[-max_lines:]
        f = _cv.font(self.FONT_PX, bold=False)
        col = _cv.rgb(TEXT if self.buffer else MUTED)
        for i, line in enumerate(vis):
            d.text((tx1 + pad, ty1 + 10 + i * self.LINE_H), line, font=f, fill=col)
        # char / word count
        wc = len(self.buffer.split()) if self.buffer.strip() else 0
        d.text((tx1, ty2 + 12), f"{len(self.buffer)} chars  ·  {wc} words", font=_cv.font(13, bold=False),
               fill=_cv.rgb(MUTED))
        # flash message
        now = time.time()
        if now - self._flash_t < 2.5 and self._flash_msg:
            fade = min(1.0, (2.5 - (now - self._flash_t)) / 0.5)
            c = tuple(int(a * fade + b * (1 - fade)) for a, b in zip(_cv.rgb(GREEN), _cv.rgb(BG)))
            ff = _cv.font(17, bold=True)
            d.text((tx2 - d.textlength(self._flash_msg, font=ff), ty2 + 9), self._flash_msg, font=ff, fill=c)
        img = np.ascontiguousarray(np.asarray(pil)[:, :, ::-1])

        # blinking caret
        if self.buffer and int(time.time() * 2) % 2 == 0 and vis:
            lw = int(f.getlength(vis[-1]))
            cx2 = tx1 + pad + lw + 4
            cy2 = ty1 + 10 + (len(vis) - 1) * self.LINE_H
            cv2.line(img, (cx2, cy2 + 2), (cx2, cy2 + self.FONT_PX + 4), _cv.to_bgr_tuple(ACCENT), 2, cv2.LINE_AA)

        # gaze dot indicator
        if self._gaze_dot:
            gx, gy = self._gaze_dot
            if 0 <= gx < self.PAD_W and 0 <= gy < self.PAD_H:
                cv2.circle(img, (gx, gy), 7, _cv.to_bgr_tuple(ACCENT), -1, cv2.LINE_AA)
                cv2.circle(img, (gx, gy), 7, (20, 20, 20), 1, cv2.LINE_AA)
                cv2.circle(img, (gx, gy), 14, _cv.to_bgr_tuple(ACCENT), 1, cv2.LINE_AA)

        # pin window to fixed screen position so gaze mapping is accurate
        cv2.imshow("Text Pad", img)
        cv2.moveWindow("Text Pad", self.PAD_WIN_X, self.PAD_WIN_Y)
