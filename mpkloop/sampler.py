"""Sampler: one stereo sample, played chromatically from the keys or chopped
into 8 equal slices for the bank B pads. Its output joins the live bus, so
anything you play with it is recorded into loops like the synth and drums."""
import numpy as np

from .dsp import ADSR, OneShots, StereoFilter

ROOT = 60   # C4 plays the sample at its original pitch
MAX_REC_SECONDS = 10


def to_stereo(x):
    x = np.asarray(x, np.float32)
    if x.ndim == 1:
        x = x[:, None]
    return np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x[:, :2]


class SampleVoice:
    def __init__(self, note, vel, rate, attack, release):
        self.note, self.rate = note, rate
        self.pos = 0.0
        self.env = ADSR(attack, 0.01, 1.0, release)
        self.gain = 0.25 + 0.75 * (vel / 127.0) ** 1.4
        self.down, self.sustained = True, False

    @property
    def done(self):
        return self.env.stage == "off"


class Sampler:
    MAX_VOICES = 8

    def __init__(self, sr):
        self.sr = sr
        self.buf = None          # (m, 2) float32
        self.name = ""
        self.pitch = 0.0         # semitones
        self.start = 0.0         # 0..1 of the sample
        self.length = 1.0        # 0..1 of what's left after start
        self.attack, self.release = 0.002, 0.25
        self.vol = 0.8
        self.cutoff = 18000.0
        self.reverse = False
        self.voices = []
        self.chops = OneShots()
        self.filter = StereoFilter()
        self.sustain = False
        self.bend = 0.0
        self._slices = None      # cache key + slices

    # ------------------------------------------------------------ region / slices

    def set_buffer(self, buf, name):
        self.buf = np.ascontiguousarray(to_stereo(buf)) if buf is not None else None
        self.name = name
        self.voices.clear()

    def region(self):
        if self.buf is None or len(self.buf) < 64:
            return None
        m = len(self.buf)
        s = int(self.start * (m - 64))
        e = s + max(int(self.length * (m - s)), 64)
        r = self.buf[s:min(e, m)]
        return r[::-1] if self.reverse else r

    def slice(self, k):
        key = (id(self.buf), self.start, self.length, self.reverse, round(self.pitch))
        if self._slices is None or self._slices[0] != key:
            r = self.region()
            if r is None:
                return None
            L = len(r) // 8
            rate = 2 ** (round(self.pitch) / 12.0)
            out = []
            fade = min(64, max(L // 4, 1))
            for i in range(8):
                x = r[i * L:(i + 1) * L].astype(np.float64)
                if rate != 1.0:
                    ph = np.arange(0, len(x) - 1, rate)
                    i0 = ph.astype(np.int64)
                    x = x[i0] + (x[i0 + 1] - x[i0]) * (ph - i0)[:, None]
                x = x.copy()
                x[:fade] *= np.linspace(0, 1, fade)[:, None]
                x[-fade:] *= np.linspace(1, 0, fade)[:, None]
                out.append(x)
            self._slices = (key, out)
        return self._slices[1][k]

    # ------------------------------------------------------------ playing

    def chop(self, k, vel, offset=0):
        x = self.slice(k)
        if x is not None:
            self.chops.trigger(x, (0.15 + 0.85 * vel / 127.0) ** 1.5, offset)

    def note_on(self, note, vel):
        if self.buf is None:
            return
        for v in self.voices:
            if v.note == note and not v.done:
                v.env.release(self.sr)
                v.down = v.sustained = False
        live = [v for v in self.voices if not v.done]
        if len(live) >= self.MAX_VOICES:
            self.voices.remove(next((v for v in live if not v.down), live[0]))
        rate = 2 ** ((note - ROOT + self.pitch) / 12.0)
        self.voices.append(SampleVoice(note, vel, rate, self.attack, self.release))

    def note_off(self, note):
        for v in self.voices:
            if v.note == note and v.down:
                v.down = False
                if self.sustain:
                    v.sustained = True
                else:
                    v.env.release(self.sr)

    def set_sustain(self, on):
        self.sustain = on
        if not on:
            for v in self.voices:
                if v.sustained:
                    v.sustained = False
                    v.env.release(self.sr)

    def all_off(self):
        self.voices.clear()
        self.chops.v.clear()

    def render(self, n):
        out = self.chops.render(n)
        r = self.region() if self.voices else None
        if r is not None:
            L = len(r)
            bend = 2 ** (self.bend * 2.0 / 12.0)
            for v in self.voices:
                v.env.r = max(self.release, 1e-3)
                ph = v.pos + v.rate * bend * np.arange(n)
                ok = ph < L - 1
                i0 = np.minimum(ph.astype(np.int64), L - 2)
                f = (ph - i0)[:, None]
                y = r[i0] + (r[i0 + 1] - r[i0]) * f
                y = y * (ok * v.env.block(n, self.sr) * v.gain)[:, None]
                out += y
                v.pos = ph[-1] + v.rate * bend
                if v.pos >= L - 1:
                    v.env.stage = "off"
            self.voices = [v for v in self.voices if not v.done]
        if self.cutoff < 17500:
            out = self.filter.process(out, "lp", self.cutoff, 0.8, self.sr)
        return out * self.vol

    # ------------------------------------------------------------ session

    def state(self):
        return dict(name=self.name, pitch=self.pitch, start=self.start, length=self.length,
                    attack=self.attack, release=self.release, vol=self.vol, cutoff=self.cutoff,
                    reverse=self.reverse)

    def load(self, d, buf):
        d = d or {}
        for k in ("pitch", "start", "length", "attack", "release", "vol", "cutoff", "reverse"):
            if k in d:
                setattr(self, k, d[k])
        self.set_buffer(buf, d.get("name", ""))
