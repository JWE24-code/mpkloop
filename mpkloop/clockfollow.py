"""Follow an external 24 ppqn MIDI clock (Switchbox): tempo estimate and tick -> time model.

Runs entirely on the MIDI thread. It never touches the audio state; it only posts engine
events (`ext_tempo`, `ext_start`, `ext_stop`, `ext_cont`), which the audio callback applies at
a block boundary through the usual mechanisms."""
import time
from collections import deque

import numpy as np

PPQN = 24
STALE_S = 1.0           # no tick for this long = the clock is gone ("waiting for clock")


def _fit(n, t):
    """Least-squares line t = tm + s * (n - nm) with robust re-fits (drops outlier ticks)."""
    for _ in range(3):
        nm, tm = n.mean(), t.mean()
        dn = n - nm
        s = float((dn * (t - tm)).sum() / (dn * dn).sum())
        r = t - (tm + s * dn)
        sig = 1.4826 * float(np.median(np.abs(r)))
        keep = np.abs(r) <= max(3.0 * sig, 5e-4)
        if keep.all() or keep.sum() < 8:
            break
        n, t = n[keep], t[keep]
    return float(nm), float(tm), s, sig


class TickEstimator:
    """Smoothed tempo and a tick-time model from noisy tick arrival times.

    - tick numbers are reconstructed from the intervals (a lost tick advances the count, a
      duplicate/bunched one is ignored), so the model survives dropouts
    - the line is fitted over up to `long` ticks (16 beats), outliers rejected by residual
    - if the last `short` ticks disagree with the long fit (tempo change) the old ticks are dropped
    - the result is snapped to 0.1 BPM when it is that close (Switchbox tempos are multiples of 0.1)"""

    def __init__(self, long=384, short=96, min_ticks=96, snap=True):
        self.long, self.short, self.min_ticks, self.snap = long, short, min_ticks, snap
        self.pts = deque(maxlen=long)
        self.n = -1
        self.last_t = None
        self.model = None       # (n_ref, t_ref, seconds per tick)
        self.bpm = None
        self.jitter = 0.0       # robust sigma of the arrival times (s)
        self.resets = 0
        self.bias_drops = 0
        self.need = min_ticks   # ticks in the window before the tempo is trusted

    def reset(self):
        self.resets += 1
        self.pts.clear()
        self.model, self.bpm = None, None

    @property
    def period(self):
        return self.model[2] if self.model else None

    def add(self, t):
        """Register a tick that arrived at time t. Returns its tick number, or None if ignored."""
        if self.last_t is None:
            self.n = 0
        else:
            delta = t - self.last_t
            per = self.period or (self.pts[-1][1] - self.pts[-2][1] if len(self.pts) > 1 else None)
            if per:
                # count ticks from the interval to the previous one; jitter must not look like a
                # missing tick, so only a clear gap (> 2.4 ticks) adds to the count
                if delta < 0.01 * per:
                    return None                 # the same tick twice
                k = int(round(delta / per)) if delta > 2.4 * per else 1
                if k > 8:                       # clock stopped for a while: start over
                    self.reset()
                    k = 1
                self.n += k
            else:
                if delta < 0.002:
                    return None
                self.n += 1
        self.last_t = t
        self.pts.append((self.n, t))
        self._update()
        return self.n

    def _update(self):
        cnt = len(self.pts)
        if self.model is not None and cnt >= 48:
            # sustained bias of the newest ticks against the fitted line = tempo step or a mis-numbered tick
            tail = list(self.pts)[-12:]
            bias = sum(t - self.time_of(n) for n, t in tail) / 12
            if abs(bias) > max(5.0 * self.jitter / 12 ** 0.5, 0.002):
                for _ in range(cnt - 12):
                    self.pts.popleft()
                self.bias_drops += 1
                self.need = max(self.min_ticks, 192)
                cnt = 12
        if cnt < 8 or (cnt % 4 and self.model is not None):
            return
        a = np.array(self.pts)
        n, t = a[:, 0], a[:, 1]
        nm, tm, s, sig = _fit(n, t)
        if len(n) > self.short:
            _, _, s2, _ = _fit(n[-self.short:], t[-self.short:])
            if abs(s2 - s) / s > 0.0035:        # tempo moved: forget the old ticks
                for _ in range(len(n) - self.short):
                    self.pts.popleft()
                nm, tm, s, sig = _fit(n[-self.short:], t[-self.short:])
        self.model = (nm, tm, s)
        self.jitter = sig
        if len(self.pts) < self.need:
            return                              # a rough line is good enough for timing, not for the tempo
        self.need = self.min_ticks
        bpm = 60.0 / (PPQN * s)
        if self.snap and len(self.pts) >= 192 and abs(bpm - round(bpm, 1)) < 0.03:
            bpm = round(bpm, 1)
        self.bpm = bpm

    def time_of(self, n):
        nm, tm, s = self.model
        return tm + (n - nm) * s

    def tick_at(self, t):
        nm, tm, s = self.model
        return nm + (t - tm) / s


class ClockFollower:
    """Feeds MIDI clock / start / stop / continue messages to the estimator and the engine."""

    def __init__(self, post, now=time.perf_counter):
        self.post, self.now = post, now
        self.est = TickEstimator()
        self.origin_n = None        # tick number of the last Start (bar 1 beat 1)
        self.pending_start = False
        self.last_tick_t = None
        self.posted_bpm = None
        self.ticks = 0

    # ---- MIDI thread
    def on_message(self, kind, t=None):
        t = self.now() if t is None else t
        if kind == "clock":
            self._tick(t)
        elif kind == "start":
            self.pending_start = True       # tick 0 is the next clock message
        elif kind == "continue":
            self.post("ext_cont")
        elif kind == "stop":
            self.pending_start = False
            self.post("ext_stop")

    def _tick(self, t):
        if self.last_tick_t is not None and t - self.last_tick_t > STALE_S:
            self.est.reset()                # the source went away and came back
            self.est.last_t = None
            self.posted_bpm = None
            self.origin_n = None
        resets = self.est.resets
        n = self.est.add(t)
        self.last_tick_t = t
        if n is None:
            return
        self.ticks += 1
        if self.origin_n is None or self.est.resets != resets:
            self.origin_n = n               # no bar reference yet (or the numbering was restarted)
        est = self.est
        tol = 0.01 if len(est.pts) >= 192 else 0.04     # a mature estimate is worth a re-trim (it may have snapped)
        if est.bpm is not None and (self.posted_bpm is None or abs(est.bpm - self.posted_bpm) >= tol):
            self.posted_bpm = est.bpm
            self.post("ext_tempo", est.bpm)
        if self.pending_start:
            self.pending_start = False
            self.origin_n = n
            self.post("ext_start", est.time_of(n) if est.model else t)

    # ---- any thread (read-only)
    def alive(self, now=None):
        now = self.now() if now is None else now
        return self.last_tick_t is not None and now - self.last_tick_t < STALE_S

    @property
    def period(self):
        """Seconds per tick (None until the estimate exists)."""
        return self.est.period

    @property
    def bpm(self):
        return self.est.bpm

    def bar_origin_time(self, now, ticks_per_bar):
        """Time of the most recent bar line (counted from the last Start) at or before `now`."""
        est, o = self.est, self.origin_n
        if est.model is None or o is None:
            return None
        k = np.floor((est.tick_at(now) - o) / ticks_per_bar)
        return est.time_of(o + k * ticks_per_bar)
