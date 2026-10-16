"""Track insert effects, the kick-triggered ducker and the global perform FX
(stutter, master crush). Block based like dsp.py; every effect keeps its state
between blocks."""
import numpy as np
from scipy.signal import lfilter

from .dsp import StereoFilter, TWO_PI

FX_TYPES = ["Off", "Crush", "Drive", "Chorus", "Tape", "Comb"]


class Crush:
    """Sample-rate reduction (sample and hold) plus bit reduction."""

    def __init__(self):
        self.count = 0
        self.held = None

    def process(self, x, amt):
        n = len(x)
        if self.held is None or len(self.held) != x.shape[1]:
            self.held = np.zeros(x.shape[1])
        hold = 1 + int(amt * 15)
        bits = 12 - 9 * amt
        idx = self.count + np.arange(n)
        src = (idx // hold) * hold - self.count   # where each held value was taken
        y = np.where((src >= 0)[:, None], x[np.maximum(src, 0)], self.held)
        last = (idx[-1] // hold) * hold - self.count
        if last >= 0:
            self.held = x[last].copy()
        self.count = (self.count + n) % hold
        q = 2 ** (bits - 1)
        return np.round(y * q) / q


class Drive:
    def __init__(self):
        self.tone = StereoFilter()

    def process(self, x, amt, sr):
        g = 1 + amt * 14
        y = np.tanh(x * g) / np.tanh(g) * (1 - 0.35 * amt)
        return self.tone.process(y, "lp", 14000 - 8000 * amt, 0.7, sr)


class ModDelay:
    """Stereo ring buffer read at fractional, modulated delays."""

    def __init__(self, sr, max_s=0.08):
        self.N = int(max_s * sr)
        self.buf = np.zeros((self.N, 2))
        self.w = 0

    def write(self, x):
        n = len(x)
        self.buf[(self.w + np.arange(n)) % self.N] = x
        self.w = (self.w + n) % self.N

    def read(self, delay):
        """delay: (n,) shared or (n, 2) per channel, in samples back from the
        samples just written. Returns (n, 2)."""
        n = len(delay)
        pos = (self.w - n + np.arange(n)) if delay.ndim == 1 else (self.w - n + np.arange(n))[:, None]
        pos = pos - delay
        i0 = np.floor(pos).astype(np.int64)
        f = pos - i0
        i0 %= self.N
        i1 = i0 + 1
        i1[i1 == self.N] = 0
        if delay.ndim == 1:
            a, b, f = self.buf[i0], self.buf[i1], f[:, None]
        else:
            a = np.stack([self.buf[i0[:, 0], 0], self.buf[i0[:, 1], 1]], axis=1)
            b = np.stack([self.buf[i1[:, 0], 0], self.buf[i1[:, 1], 1]], axis=1)
        return a + (b - a) * f


class Chorus:
    def __init__(self, sr):
        self.sr = sr
        self.d = ModDelay(sr)
        self.ph = 0.0

    def process(self, x, amt):
        n, sr = len(x), self.sr
        self.d.write(x)
        t = self.ph + np.arange(n) * 0.8 / sr
        self.ph = (self.ph + n * 0.8 / sr) % 1.0
        depth = (1.0 + 4.0 * amt) * 1e-3 * sr
        base = 0.012 * sr
        lfo = np.sin(TWO_PI * (t[:, None] + np.array([0.0, 0.25])))
        mix = 0.3 + 0.4 * amt
        return x * (1 - 0.5 * mix) + self.d.read(base + depth * lfo) * mix


class Tape:
    """Wow and flutter, a little saturation and a closing low-pass."""

    def __init__(self, sr):
        self.sr = sr
        self.d = ModDelay(sr)
        self.ph = np.zeros(2)
        self.lp = StereoFilter()

    def process(self, x, amt):
        n, sr = len(x), self.sr
        self.d.write(np.tanh(x * (1 + amt)) / np.tanh(1 + amt))
        k = np.arange(n) / sr
        wow = np.sin(TWO_PI * (self.ph[0] + 0.55 * k))
        flut = np.sin(TWO_PI * (self.ph[1] + 6.3 * k))
        self.ph = (self.ph + np.array([0.55, 6.3]) * n / sr) % 1.0
        delay = 0.006 * sr + amt * sr * (0.0025 * wow + 0.0004 * flut)
        y = self.d.read(delay)
        return self.lp.process(y, "lp", 12000 * 2 ** (-2 * amt), 0.7, sr)


class Comb:
    """Feedback comb tuned to 110-440 Hz: metallic resonance."""

    def __init__(self, sr):
        self.sr = sr
        self.D = int(sr / 220)
        self.hist = np.zeros((self.D, 2))   # the last D outputs

    def process(self, x, amt):
        # y[k] = (1-fb) x[k] + fb y[k-D], computed D samples at a time
        fb = 0.55 + 0.4 * amt
        n, D = len(x), self.D
        y = np.empty_like(x)
        for s in range(0, n, D):
            e = min(s + D, n)
            back = self.hist[: e - s] if s == 0 else y[s - D:e - D]
            y[s:e] = (1 - fb) * x[s:e] + fb * back
        self.hist = y[-D:].copy() if n >= D else np.concatenate([self.hist[n:], y])
        mix = 0.35 + 0.6 * amt
        return x * (1 - mix) + y * mix


class Insert:
    """One effect slot on a track; switching type resets the effect state."""

    def __init__(self, sr):
        self.sr = sr
        self.kind = "Off"
        self.fx = None

    def process(self, x, kind, amt):
        if kind == "Off":
            self.kind, self.fx = "Off", None
            return x
        if kind != self.kind:
            self.kind = kind
            cls = {"Crush": Crush, "Drive": Drive, "Chorus": Chorus, "Tape": Tape, "Comb": Comb}[kind]
            self.fx = cls() if kind in ("Crush", "Drive") else cls(self.sr)
        if kind == "Drive":
            return self.fx.process(x, amt, self.sr)
        return self.fx.process(x, amt)


class Ducker:
    """Shared envelope: jumps to 1 on every kick and decays; tracks use 1 - duck*env."""

    def __init__(self, sr):
        self.sr = sr
        self.env = 0.0
        self.decay = np.exp(-1.0 / (0.16 * sr))
        self.hits = []
        self.zi = np.zeros(1)

    def trigger(self, offset=0):
        self.hits.append(offset)

    def block(self, n):
        k = np.arange(n)
        env = self.env * self.decay ** (k + 1)
        for o in sorted(self.hits):
            o = min(max(o, 0), n - 1)
            env[o:] = self.decay ** (k[: n - o])
        self.hits = []
        self.env = float(env[-1])
        # ~1.5 ms smoothing so the dip doesn't click
        out, self.zi = lfilter([0.015], [1, -0.985], env, zi=self.zi)
        return out


class Perform:
    """Stutter (beat repeat) and master crush, applied to a (n, C) multi-bus block."""

    def __init__(self, sr, channels=6, hist_s=8.0):
        self.sr = sr
        self.N = int(hist_s * sr)
        self.hist = np.zeros((self.N, channels))
        self.w = 0
        self.div = None          # requested stutter length in beats
        self.seg = None          # (start index in hist, length) while repeating
        self.k = 0               # samples played since the repeat started
        self.wait = 0            # samples until the next 1/16 grid line
        self.crush = False
        self.crusher = Crush()

    def stutter(self, div):
        self.div = div
        if div is None:
            self.seg = None

    def process(self, x, pos, beat_len, running):
        n, C = x.shape
        out = x
        if self.div is not None and self.seg is None:
            grid = beat_len / 4.0
            nxt = int(np.ceil(pos / grid) * grid) - pos if running else 0
            if nxt < n:
                # repeat the division that ends at the grid line
                L = max(int(self.div * beat_len), 256)
                L = min(L, self.N // 2)
                self.seg = ((self.w + nxt - L) % self.N, L)
                self.k = -nxt
        if self.seg is not None:
            s, L = self.seg
            k = self.k + np.arange(n)
            on = k >= 0
            kk = np.maximum(k, 0) % L
            y = self.hist[(s + kk) % self.N]
            fade = np.minimum(1.0, np.minimum(kk, L - kk) / 64.0)[:, None]
            out = np.where(on[:, None], y * fade, x)
            self.k += n
            # write only the pre-stutter part so the repeated slice stays intact
            pre = int(np.clip(-k[0], 0, n))
            if pre:
                self.hist[(self.w + np.arange(pre)) % self.N] = x[:pre]
                self.w = (self.w + pre) % self.N
        else:
            self.hist[(self.w + np.arange(n)) % self.N] = x
            self.w = (self.w + n) % self.N
        if self.crush:
            out = self.crusher.process(out, 0.75)
        return out

