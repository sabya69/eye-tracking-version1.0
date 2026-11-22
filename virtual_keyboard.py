
import cv2
import numpy as np
import time
from PIL import Image, ImageDraw
import neo_cv as _cv
from neo_ui import BG, TEXT, MUTED, ACCENT, DANGER, PURPLE, AMBER, GREEN, IS_DARK, mix, lighten   # soft glass look

try:
    import pyautogui
    MOUSE_AVAILABLE = True
except ImportError:
    MOUSE_AVAILABLE = False


class VirtualKeyboard:
    DWELL_TIME = 1.2
    KEY_W = 78
    KEY_H = 70
    KEY_GAP = 14
    MARGIN = 16
    TEXT_H = 72

    LAYOUTS = {
        "normal": {
            "row1": list("QWERTYUIOP"),
            "row2": list("ASDFGHJKL"),
            "row3": list("ZXCVBNM"),
        },
        "alpha": {
            "row1": list("ABCDEFGHIJ"),
            "row2": list("KLMNOPQRS"),
            "row3": list("TUVWXYZ"),
        },
        "cluster": {
            "row1": list("ETAOIFGYPB"),
            "row2": list("NSHRDVKJX"),
            "row3": list("LCUMWQZ"),
        }
    }

    # "Delete" (wipe everything) is NOT in this row any more: it sits alone in the top-right
    # corner (CLEAR_KEY) and needs a second, separate dwell to confirm.
    CONTROL_KEYS = ["|◄", "◄", "⌫", "Space", "►", "►|"]
    CLEAR_KEY = "Delete"
    UNDO_KEY  = "Undo"            # header keys (like Ctrl+Z / Ctrl+Y) next to the text well
    REDO_KEY  = "Redo"
    HISTORY_KEYS = (UNDO_KEY, REDO_KEY)
    HISTORY_LABELS = {"Undo": "\u21B6  Undo", "Redo": "\u21B7  Redo"}
    CLEAR_CONFIRM = True          # False = old one-dwell behaviour
    CLEAR_CONFIRM_SECS = 3.0
    NUMPAD_KEYS = [
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
        [".", "0", "?"]
    ]

    def __init__(self):
        self.visible        = False
        self.typed_text     = ""
        self.hovered_key    = None
        self.dwell_start    = None
        self.dwell_progress = 0.0
        self.last_pressed   = None
        self.last_press_t   = 0.0
        self._textpad       = None   # set via link_textpad()
        self.current_layout = "normal"
        self._hist          = []      # undo stack: earlier values of typed_text
        self._redo          = []      # redo stack
        self._last_kind     = None    # groups edits so one Undo takes back a word / a run of backspaces
        self._armed_t       = 0.0     # time "Clear all" was armed (0 = not armed)
        self._clear_lock    = False   # after arming, gaze must leave the key before it can confirm
        self._surf          = None
        self._patches       = {}
        self._base_bgr      = None
        self.set_layout("normal")

    def set_layout(self, layout_name):
        if layout_name in self.LAYOUTS:
            self.current_layout = layout_name
            self._alphabet_rows = self.LAYOUTS[layout_name]
            self._build_layout()

    def _build_layout(self):
        self.key_list = []
        self.resting_rect = None

        kw = self.KEY_W
        kh = self.KEY_H
        gap = self.KEY_GAP
        m = self.MARGIN
        top_y = self.TEXT_H + m

        # Total left width is defined by 10 letter keys of Row 1
        left_x1 = m
        left_x_end = left_x1 + 10 * kw + 9 * gap
        w_left = left_x_end - left_x1

        # ── 1. Alphabet Row 1 (10 keys) ────────────────────────────────────
        y1 = top_y
        y2 = y1 + kh
        for i, char in enumerate(self._alphabet_rows["row1"]):
            x1 = left_x1 + i * (kw + gap)
            x2 = x1 + kw
            self.key_list.append((char, int(x1), int(y1), int(x2), int(y2)))

        # ── 2. Alphabet Row 2 (9 keys) ─────────────────────────────────────
        y1 = top_y + kh + gap
        y2 = y1 + kh
        for i, char in enumerate(self._alphabet_rows["row2"]):
            x1 = left_x1 + i * (kw + gap)
            x2 = x1 + kw
            self.key_list.append((char, int(x1), int(y1), int(x2), int(y2)))

        # ── 3. Row 3: 7 Alphabet Keys (Row 3 letters spread across left width)
        y1 = top_y + 2 * (kh + gap)
        y2 = y1 + kh
        r3_keys = self._alphabet_rows["row3"]
        avail_w_r3 = w_left - (len(r3_keys) - 1) * gap
        r3_kw = avail_w_r3 // len(r3_keys)
        cur_x = left_x1
        for i, char in enumerate(r3_keys):
            if i == len(r3_keys) - 1:
                x2 = left_x_end
            else:
                x2 = cur_x + r3_kw
            self.key_list.append((char, int(cur_x), int(y1), int(x2), int(y2)))
            cur_x = x2 + gap

        # ── 4. Row 4: 7 Control Keys (Horizontal Row across full left width)
        y1 = top_y + 3 * (kh + gap)
        y2 = y1 + kh
        ctrl_weights = [1.0, 1.0, 1.5, 4.2, 1.0, 1.0]
        sum_w = sum(ctrl_weights)
        avail_w_ctrl = w_left - (len(self.CONTROL_KEYS) - 1) * gap
        cur_x = left_x1
        for i, ckey in enumerate(self.CONTROL_KEYS):
            if i == len(self.CONTROL_KEYS) - 1:
                x2 = left_x_end
            else:
                x2 = cur_x + int(avail_w_ctrl * (ctrl_weights[i] / sum_w))
            self.key_list.append((ckey, int(cur_x), int(y1), int(x2), int(y2)))
            cur_x = x2 + gap

        # ── 5. Right Side: 3x4 Numpad Grid (Aligned with the 4 rows) ───────
        numpad_x_start = left_x_end + gap * 3
        np_kw = kw
        for r_idx, row in enumerate(self.NUMPAD_KEYS):
            ny1 = top_y + r_idx * (kh + gap)
            ny2 = ny1 + kh
            for c_idx, num_char in enumerate(row):
                nx1 = numpad_x_start + c_idx * (np_kw + gap)
                nx2 = nx1 + np_kw
                self.key_list.append((num_char, int(nx1), int(ny1), int(nx2), int(ny2)))

        # ── 6. CLEAR ALL: alone in the top-right corner, away from every typing key ──
        np_right = numpad_x_start + 3 * np_kw + 2 * gap
        self.key_list.append((self.CLEAR_KEY, int(numpad_x_start), 12, int(np_right), self.TEXT_H - 12))
        # ── 7. UNDO / REDO: right end of the header, between the text well and the numpad column ──
        hw = 118
        redo_x1, redo_x2 = int(left_x_end - hw), int(left_x_end)
        undo_x1, undo_x2 = int(redo_x1 - gap - hw), int(redo_x1 - gap)
        self.key_list.append((self.UNDO_KEY, undo_x1, 12, undo_x2, self.TEXT_H - 12))
        self.key_list.append((self.REDO_KEY, redo_x1, 12, redo_x2, self.TEXT_H - 12))
        self._text_bar = (m, 12, int(undo_x1 - gap), self.TEXT_H - 12)
        self._numpad_panel = (int(numpad_x_start - 14), int(top_y - 10), int(np_right + 14), int(top_y + 4 * kh + 3 * gap + 10))
        self._surf = None            # rebuild cached art for the new layout

        # Calculate Canvas Dimensions
        max_x = max(x2 for _, _, _, x2, _ in self.key_list) + m
        max_y = max(y2 for _, _, _, _, y2 in self.key_list) + m + 34
        self._canvas_w = int(max_x)
        self._canvas_h = int(max_y)

    @property
    def window_size(self):
        return self._canvas_w, self._canvas_h

    # ── API ───────────────────────────────────────────────────────────────────
    def link_textpad(self, pad):
        """Connect TextPad so Save & next / ENTER sends text there."""
        self._textpad = pad

    def toggle(self):
        self.visible = not self.visible
        if not self.visible:
            try: cv2.destroyWindow("Virtual Keyboard")
            except: pass

    def close(self):
        self.visible = False
        try: cv2.destroyWindow("Virtual Keyboard")
        except: pass

    def update_gaze(self, kx, ky):
        """Feed gaze in keyboard-window pixels. Returns activated key or None."""
        if not self.visible:
            return None
        hit = next((lbl for lbl, x1, y1, x2, y2 in self.key_list
                    if x1 <= kx < x2 and y1 <= ky < y2), None)

        if hit != self.CLEAR_KEY:
            self._clear_lock = False    # gaze left the Clear key -> it may be confirmed again
        if hit != self.hovered_key:
            self.hovered_key    = hit
            self.dwell_start    = time.time() if hit else None
            self.dwell_progress = 0.0
            return None
        if hit == self.CLEAR_KEY and self._clear_lock:
            self.dwell_progress = 0.0   # armed: look away and back to confirm
            return None
        if hit and self.dwell_start:
            self.dwell_progress = min(1.0, (time.time() - self.dwell_start) / self.DWELL_TIME)
            if self.dwell_progress >= 1.0 and time.time() - self.last_press_t > self.DWELL_TIME * 0.8:
                self._press(hit)
                self.last_press_t   = time.time()
                self.dwell_start    = time.time()
                self.dwell_progress = 0.0
                return hit
        return None

    def blink_press(self):
        """Activate hovered key on left-blink."""
        if self.hovered_key and self.visible and time.time() - self.last_press_t > 0.4:
            hit = self.hovered_key
            self._press(hit)
            self.last_press_t   = time.time()
            self.dwell_start    = time.time()
            self.dwell_progress = 0.0
            return hit
        return None

    def _request_clear(self):
        """Two-step clear: first activation arms the key, a second one (after the gaze left and
        came back, or a deliberate second blink) within CLEAR_CONFIRM_SECS wipes the text."""
        now = time.time()
        if not self.CLEAR_CONFIRM:
            self._remember("clear")
            self.typed_text = ""
            return
        if self._armed_t and now - self._armed_t <= self.CLEAR_CONFIRM_SECS:
            self._remember("clear")
            self.typed_text = ""
            self._armed_t = 0.0
            self._clear_lock = False
        else:
            self._armed_t = now
            self._clear_lock = True     # staring at the key must not confirm by itself

    # ── undo / redo ───────────────────────────────────────────────────────────
    def _remember(self, kind):
        """Call BEFORE typed_text changes.  Saves the old text unless this edit continues the
        same run (letters, backspaces) - Space and Clear always start a new undo step."""
        if kind != self._last_kind or kind in ("space", "clear", "enter"):
            self._hist.append(self.typed_text)
            if len(self._hist) > 200:
                del self._hist[0]
            del self._redo[:]
        self._last_kind = kind

    def _undo(self):
        if self._hist:
            self._redo.append(self.typed_text)
            self.typed_text = self._hist.pop()
        self._last_kind = None

    def _redo_step(self):
        if self._redo:
            self._hist.append(self.typed_text)
            self.typed_text = self._redo.pop()
        self._last_kind = None

    def _press(self, label):
        if label != self.CLEAR_KEY:
            self._armed_t = 0.0         # any other key cancels a pending clear
        self.last_pressed = label
        if label == self.UNDO_KEY:
            self._undo()
            return
        if label == self.REDO_KEY:
            self._redo_step()
            return
        if label in ("Save & next", "ENTER"):
            text = self.typed_text.strip()
            self._remember("enter")
            if text:
                if self._textpad is not None:
                    self._textpad.append(text)
                elif MOUSE_AVAILABLE:
                    pyautogui.write(text, interval=0.03)
                    pyautogui.press('enter')
            self.typed_text = ""
        elif label in ("⌫", "Backspace"):
            self._remember("del")
            self.typed_text = self.typed_text[:-1]
        elif label in ("SPACE", "Space"):
            self._remember("space")
            self.typed_text += " "
        elif label in ("DELETE", "Delete"):
            self._request_clear()
        elif label == "|◄":
            if MOUSE_AVAILABLE: pyautogui.press('home')
        elif label == "◄":
            if MOUSE_AVAILABLE: pyautogui.press('left')
        elif label == "►":
            if MOUSE_AVAILABLE: pyautogui.press('right')
        elif label == "►|":
            if MOUSE_AVAILABLE: pyautogui.press('end')
        else:
            self._remember("ins")
            self.typed_text += label

    # ── render ────────────────────────────────────────────────────────────────
    def _face_fg(self, label):
        base = BG
        lift = lighten(base, 0.04) if IS_DARK else base
        if label == self.CLEAR_KEY:
            if self._armed_t:
                return DANGER, ("#1A1510" if IS_DARK else "#FFFFFF"), DANGER
            return mix(lift, DANGER, 0.22), DANGER, DANGER
        if label in self.HISTORY_KEYS:
            return mix(lift, GREEN, 0.16), TEXT, None
        if label in self.CONTROL_KEYS:
            return mix(lift, ACCENT, 0.14), (AMBER if label == "⌫" else TEXT), None
        if label in ("1","2","3","4","5","6","7","8","9","0",".","?"):
            return mix(lift, PURPLE, 0.12), TEXT, None
        return lift, TEXT, None

    def _build_art(self):
        """Render backdrop, glass numpad panel, text well and all keys once (Pillow)."""
        S = _cv.Surface(self._canvas_w, self._canvas_h, depth=4)
        S.glass(self._numpad_panel, r=28, accent=PURPLE, accent_a=0.07)
        S.inset(self._text_bar, r=16)
        S.freeze_bare()
        for label, x1, y1, x2, y2 in self.key_list:
            face, fg, glow = self._face_fg(label)
            if label == self.CLEAR_KEY:
                label_txt, size = "✕  Clear all", 17
            elif label in self.HISTORY_KEYS:
                label_txt, size = self.HISTORY_LABELS[label], 16
            else:
                label_txt, size = label, None
            S.key((x1, y1, x2, y2), label_txt, face, fg, "rest", glow, size, paste=True)
        _cv.draw_text_center(S.img, (self.MARGIN, self._canvas_h - 30, self._canvas_w - self.MARGIN, self._canvas_h - 8),
                             f"Layout: {self.current_layout.upper()}   ·   Gaze-dwell / LEFT blink   ·   Rest in top-left space",
                             13, MUTED, bold=False)
        self._surf = S
        self._patches = {}
        self._base_bgr = _cv.to_bgr(S.img)

    def _patch(self, label, state, armed):
        key = (label, state, armed)
        p = self._patches.get(key)
        if p is None:
            rect = next((x1, y1, x2, y2) for l, x1, y1, x2, y2 in self.key_list if l == label)
            face, fg, glow = self._face_fg(label)
            if label == self.CLEAR_KEY:
                txt, size = ("Look away, then dwell again" if armed else "✕  Clear all"), (14 if armed else 17)
            elif label in self.HISTORY_KEYS:
                txt, size = self.HISTORY_LABELS[label], 16
            else:
                txt, size = label, None
            x, y, im = self._surf.key(rect, txt, face, fg, state, glow, size)
            p = (x, y, _cv.to_bgr(im))
            self._patches[key] = p
        return p

    @staticmethod
    def _paste(img, patch):
        x, y, pm = patch
        h, w = pm.shape[:2]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(img.shape[1], x + w), min(img.shape[0], y + h)
        if x2 > x1 and y2 > y1:
            img[y1:y2, x1:x2] = pm[y1 - y:y2 - y, x1 - x:x2 - x]

    def render(self):
        if not self.visible:
            return
        if self._surf is None:
            self._build_art()
        # expire an un-confirmed "Clear all"
        if self._armed_t and time.time() - self._armed_t > self.CLEAR_CONFIRM_SECS:
            self._armed_t = 0.0
            self._clear_lock = False
        img = self._base_bgr.copy()
        armed = bool(self._armed_t)
        now = time.time()

        # keys whose look differs from the baked "rest" image
        for label, x1, y1, x2, y2 in self.key_list:
            hov = label == self.hovered_key
            flash = label == self.last_pressed and (now - self.last_press_t) < 0.3
            if flash:
                self._paste(img, self._patch(label, "flash", armed))
            elif hov:
                self._paste(img, self._patch(label, "hover", armed))
            elif label == self.CLEAR_KEY and armed:
                self._paste(img, self._patch(label, "rest", armed))
            if hov and self.dwell_progress > 0:
                cx2, cy2 = (x1 + x2) // 2, (y1 + y2) // 2
                r = min(x2 - x1, y2 - y1) // 2 - 4
                cv2.ellipse(img, (cx2, cy2), (r, r), -90, 0, int(360 * self.dwell_progress),
                            _cv.to_bgr_tuple(ACCENT), 3, cv2.LINE_AA)

        # typed text inside the inset well
        tx1, ty1, tx2, ty2 = self._text_bar
        disp = self.typed_text[-34:] if self.typed_text else "start typing…"
        pil = Image.fromarray(img[ty1:ty2, tx1:tx2, ::-1])
        d = ImageDraw.Draw(pil)
        f = _cv.font(22, bold=bool(self.typed_text))
        l, t, r, b = d.textbbox((0, 0), disp, font=f)
        d.text((16 - l, (ty2 - ty1 - (b - t)) / 2 - t), disp, font=f,
               fill=_cv.rgb(TEXT if self.typed_text else MUTED))
        img[ty1:ty2, tx1:tx2] = np.asarray(pil)[:, :, ::-1]
        cv2.imshow("Virtual Keyboard", img)
