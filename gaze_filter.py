"""
gaze_filter.py  --  One-Euro filter for steady-yet-responsive gaze smoothing.

A fixed EMA has to choose: smooth (laggy) or responsive (jittery).  The One-Euro
filter changes its smoothing with speed: when the gaze is nearly still it
smooths strongly (no jitter, stable dwell/click target); when the eyes make a
fast jump (saccade) it smooths very little, so the cursor catches up quickly.

Units: positions in screen pixels, time in seconds.
"""
import math


class _LowPass:
    def __init__(self):
        self.y = None

    def __call__(self, x, alpha):
        self.y = x if self.y is None else self.y + alpha * (x - self.y)
        return self.y


class OneEuro:
    def __init__(self, min_cutoff=0.25, beta=0.002, d_cutoff=1.0):
        self.min_cutoff = min_cutoff   # Hz: lower = steadier when still
        self.beta = beta               # higher = less lag when moving fast
        self.d_cutoff = d_cutoff
        self._x = _LowPass()
        self._dx = _LowPass()
        self._last_t = None
        self._last_raw = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self):
        self.__init__(self.min_cutoff, self.beta, self.d_cutoff)

    def __call__(self, x, t):
        if self._last_t is None:
            self._last_t, self._last_raw = t, x
            return self._x(x, 1.0)
        dt = max(1e-3, min(0.25, t - self._last_t))
        self._last_t = t
        dx = (x - self._last_raw) / dt
        self._last_raw = x
        edx = self._dx(dx, self._alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x(x, self._alpha(cutoff, dt))
