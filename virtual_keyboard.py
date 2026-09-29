
import cv2
import numpy as np
import time

try:
    import pyautogui
    MOUSE_AVAILABLE = True
except ImportError:
    MOUSE_AVAILABLE = False


class VirtualKeyboard:
    DWELL_TIME = 1.2
    KEY_W = 78
    KEY_H = 70
    KEY_GAP = 8
    MARGIN = 16
    TEXT_H = 60

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

    CONTROL_KEYS = ["|◄", "◄", "⌫", "Space", "Delete", "►", "►|"]
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

        # ── 3. Row 3: 7 Control Keys (Horizontal Row across full left width)
        y1 = top_y + 2 * (kh + gap)
        y2 = y1 + kh
        ctrl_weights = [1.0, 1.0, 1.2, 2.2, 1.6, 1.0, 1.0]
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

        # ── 4. Row 4: 7 Alphabet Keys (Row 3 letters spread across left width)
        y1 = top_y + 3 * (kh + gap)
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

        # Calculate Canvas Dimensions
        max_x = max(x2 for _, _, _, x2, _ in self.key_list) + m
        max_y = max(y2 for _, _, _, _, y2 in self.key_list) + m + 24
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

        if hit != self.hovered_key:
            self.hovered_key    = hit
            self.dwell_start    = time.time() if hit else None
            self.dwell_progress = 0.0
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

    def _press(self, label):
        self.last_pressed = label
        if label in ("Save & next", "ENTER"):
            text = self.typed_text.strip()
            if text:
                if self._textpad is not None:
                    self._textpad.append(text)
                elif MOUSE_AVAILABLE:
                    pyautogui.write(text, interval=0.03)
                    pyautogui.press('enter')
            self.typed_text = ""
        elif label in ("⌫", "Backspace"):
            self.typed_text = self.typed_text[:-1]
        elif label in ("SPACE", "Space"):
            self.typed_text += " "
        elif label in ("DELETE", "Delete"):
            self.typed_text = ""
        elif label == "|◄":
            if MOUSE_AVAILABLE: pyautogui.press('home')
        elif label == "◄":
            if MOUSE_AVAILABLE: pyautogui.press('left')
        elif label == "►":
            if MOUSE_AVAILABLE: pyautogui.press('right')
        elif label == "►|":
            if MOUSE_AVAILABLE: pyautogui.press('end')
        else:
            self.typed_text += label

    # ── render ────────────────────────────────────────────────────────────────
    def render(self):
        if not self.visible:
            return
        img = np.full((self._canvas_h, self._canvas_w, 3), (20, 20, 30), dtype=np.uint8)

        # Typed-text bar
        cv2.rectangle(img, (self.MARGIN, 6), (self._canvas_w - self.MARGIN, self.TEXT_H - 6), (40, 40, 60), -1)
        cv2.rectangle(img, (self.MARGIN, 6), (self._canvas_w - self.MARGIN, self.TEXT_H - 6), (80, 80, 120), 1)
        disp = self.typed_text[-48:] if self.typed_text else "▮  start typing…"
        col  = (220, 220, 255) if self.typed_text else (80, 80, 100)
        cv2.putText(img, disp, (self.MARGIN + 8, self.TEXT_H - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 1, cv2.LINE_AA)

        now = time.time()
        for label, x1, y1, x2, y2 in self.key_list:
            hov = label == self.hovered_key
            
            elapsed = now - self.last_press_t
            progress = max(0.0, min(1.0, 1.0 - (elapsed / 0.3))) if label == self.last_pressed else 0.0
            prs = progress > 0.0
            
            spec = label in self.CONTROL_KEYS or label == "Save & next"
            is_num = label in ("1","2","3","4","5","6","7","8","9","0",".","?")

            if prs:
                normal_bg = (40, 70, 40) if label == "Save & next" else (40, 40, 70) if spec else (35, 35, 55)
                press_bg  = (0, 240, 120)
                bg = tuple(int(normal_bg[i] + (press_bg[i] - normal_bg[i]) * progress) for i in range(3))
                inset = int(3 * progress)
                rx1, ry1, rx2, ry2 = x1 + inset, y1 + inset, x2 - inset, y2 - inset
                text_col  = (10, 10, 10)
            else:
                if label == "Save & next":
                    bg = (50, 130, 70) if hov else (35, 95, 50)
                elif spec:
                    bg = (70, 90, 150) if hov else (45, 45, 75)
                elif is_num:
                    bg = (80, 70, 120) if hov else (45, 40, 65)
                else:
                    bg = (60, 80, 140) if hov else (35, 35, 55)
                rx1, ry1, rx2, ry2 = x1 + 2, y1 + 2, x2 - 2, y2 - 2
                text_col  = (230, 240, 255)

            cv2.rectangle(img, (rx1, ry1), (rx2, ry2), bg, -1)
            
            if hov and self.dwell_progress > 0:
                cx2, cy2 = (x1 + x2) // 2, (y1 + y2) // 2
                r = min(x2 - x1, y2 - y1) // 2 - 4
                cv2.ellipse(img, (cx2, cy2), (r, r), -90, 0, int(360 * self.dwell_progress), (0, 220, 255), 3)
                
            border_col = (0, 255, 100) if prs else (0, 220, 255) if hov else (60, 60, 90)
            cv2.rectangle(img, (rx1, ry1), (rx2, ry2), border_col, 1)
            
            fs  = 0.52 if len(label) > 6 else 0.68 if len(label) > 1 else 0.95
            thick = 2 if len(label) == 1 else 1
            tsz = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, thick)[0]
            tx  = rx1 + (rx2 - rx1 - tsz[0]) // 2
            ty  = ry1 + (ry2 - ry1 + tsz[1]) // 2
            cv2.putText(img, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs, text_col, thick, cv2.LINE_AA)

        cv2.putText(img, f"Layout: {self.current_layout.upper()}  |  Gaze-dwell / LEFT blink  |  Rest in top-left space",
                    (self.MARGIN, self._canvas_h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100, 130, 160), 1, cv2.LINE_AA)
        cv2.imshow("Virtual Keyboard", img)

