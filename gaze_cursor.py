import cv2
import numpy as np


class GazeCursor:
    def __init__(self):
        self._sx    = 0.5   # smoothed normalised x in camera space
        self._sy    = 0.5
        self._alpha = 0.18  # EMA factor
        self._pulse = 0.0
        self.active = True

    def update(self, nx: float, ny: float):
        self._sx += self._alpha * (nx - self._sx)
        self._sy += self._alpha * (ny - self._sy)
        self._pulse = (self._pulse + 0.12) % (2 * np.pi)

    def draw(self, frame):
        if not self.active:
            return
        h, w = frame.shape[:2]
        cx = int(np.clip(self._sx, 0.01, 0.99) * w)
        cy = int(np.clip(self._sy, 0.01, 0.99) * h)

        pulse_r = int(14 + 3 * np.sin(self._pulse))
        # Outer pulsing ring
        cv2.circle(frame, (cx, cy), pulse_r, (0, 220, 255), 1, cv2.LINE_AA)
        # Centre dot
        cv2.circle(frame, (cx, cy), 3, (0, 255, 255), -1, cv2.LINE_AA)
        # Crosshair lines
        CROSS_LEN = 18; CROSS_GAP = 6
        cv2.line(frame, (cx - CROSS_LEN, cy), (cx - CROSS_GAP, cy), (0, 200, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (cx + CROSS_GAP, cy), (cx + CROSS_LEN, cy), (0, 200, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (cx, cy - CROSS_LEN), (cx, cy - CROSS_GAP), (0, 200, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (cx, cy + CROSS_GAP), (cx, cy + CROSS_LEN), (0, 200, 255), 1, cv2.LINE_AA)
        # Corner brackets for scifi HUD feel
        BOX_HALF = 24; BRACKET = 7
        bx1, by1 = cx - BOX_HALF, cy - BOX_HALF
        bx2, by2 = cx + BOX_HALF, cy + BOX_HALF
        bc = (0, 200, 255)
        for ox, oy, dx, dy in [(bx1,by1,1,1),(bx2,by1,-1,1),(bx1,by2,1,-1),(bx2,by2,-1,-1)]:
            cv2.line(frame, (ox, oy), (ox+dx*BRACKET, oy), bc, 1, cv2.LINE_AA)
            cv2.line(frame, (ox, oy), (ox, oy+dy*BRACKET), bc, 1, cv2.LINE_AA)

        cv2.putText(frame, "GAZE", (cx+BOX_HALF+4, cy-BOX_HALF+8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 200, 200), 1, cv2.LINE_AA)
