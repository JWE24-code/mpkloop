"""Step sequencer lane: 8 lanes (the current kit's 8 sounds) x up to 16 sixteenth
steps. It plays on its own bus, in phase with bar 1, and is never recorded into
loops."""
import numpy as np

LEVELS = {1: 0.45, 2: 0.75, 3: 1.0}   # step velocity 1 soft / 2 normal / 3 accent
LENGTHS = [8, 12, 16]


def vel_level(velocity):
    return 1 if velocity < 60 else (2 if velocity < 110 else 3)


class StepSeq:
    def __init__(self):
        self.pattern = np.zeros((8, 16), np.int8)
        self.length = 16
        self.swing = 0.0      # 0 = straight, 1 = 75% (MPC style)
        self.lane = 0
        self.half = 0         # which 8 steps the bank B pads edit
        self.on = False
        self.rec = False      # finger drums are written into the pattern
        self.muted = False
        self.vol, self.pan, self.dsend, self.rsend = 0.8, 0.0, 0.0, 0.1
        self.skip = set()     # (global step, lane) already played live while recording
        self.level = 0.0
        self.gains = np.zeros(2)

    # ------------------------------------------------------------ timing

    def step_time(self, g, step):
        return g * step + (self.swing * step * 0.5 if g % 2 else 0.0)

    def hits(self, pos, n, beat_len):
        """[(offset, lane, level)] for steps starting inside [pos, pos+n)."""
        step = beat_len / 4.0
        out = []
        for g in range(max(int(pos // step) - 1, 0), int((pos + n) // step) + 1):
            t = int(round(self.step_time(g, step)))
            if pos <= t < pos + n:
                col = g % self.length
                for lane in np.nonzero(self.pattern[:, col])[0]:
                    if (g, lane) in self.skip:
                        self.skip.discard((g, lane))
                        continue
                    out.append((t - pos, int(lane), LEVELS[int(self.pattern[lane, col])]))
        return out

    def record_hit(self, pos, lane, velocity, beat_len):
        """Quantize a live pad hit to the nearest step and store it."""
        step = beat_len / 4.0
        g = int(round(pos / step))
        self.pattern[lane, g % self.length] = vel_level(velocity)
        if g * step > pos:          # that step hasn't played yet: don't double it
            self.skip.add((g, lane))

    # ------------------------------------------------------------ editing

    def toggle(self, lane, col, level=2):
        self.pattern[lane, col] = 0 if self.pattern[lane, col] else level

    def cycle_vel(self, lane, col):
        self.pattern[lane, col] = (self.pattern[lane, col] % 3) + 1

    def strip(self, lane=None):
        """16-char view of one lane (or any lane) for the track table."""
        cols = self.pattern.any(axis=0) if lane is None else self.pattern[lane] > 0
        return "".join(("●" if cols[c] else "·") if c < self.length else " " for c in range(16))

    # ------------------------------------------------------------ session

    def state(self):
        return dict(pattern=self.pattern.tolist(), length=self.length, swing=self.swing, on=self.on,
                    muted=self.muted, vol=self.vol, pan=self.pan, dsend=self.dsend, rsend=self.rsend)

    def load(self, d):
        d = d or {}
        self.pattern = np.array(d.get("pattern", np.zeros((8, 16))), np.int8).reshape(8, 16)
        self.length = d.get("length", 16)
        self.swing = d.get("swing", 0.0)
        self.on = d.get("on", False)
        self.muted = d.get("muted", False)
        for k, v in (("vol", 0.8), ("pan", 0.0), ("dsend", 0.0), ("rsend", 0.1)):
            setattr(self, k, d.get(k, v))
        self.skip.clear()
