"""Signal processing: poly synth, drum kit, metronome, delay, reverb, filters.

Everything is block based and vectorised with numpy; recursive filters go
through scipy's lfilter (C speed) with explicit state so they can run per block.
"""
import numpy as np
from scipy.signal import lfilter

TWO_PI = 2.0 * np.pi


# ---------------------------------------------------------------- filters

def biquad(kind, freq, q, sr):
    """RBJ cookbook biquad coefficients (b, a)."""
    freq = min(max(freq, 10.0), sr * 0.45)
    w = TWO_PI * freq / sr
    c, s = np.cos(w), np.sin(w)
    alpha = s / (2.0 * q)
    if kind == "lp":
        b = [(1 - c) / 2, 1 - c, (1 - c) / 2]
    elif kind == "hp":
        b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
    else:  # band pass, constant peak gain
        b = [alpha, 0.0, -alpha]
    a0 = 1 + alpha
    return np.array(b) / a0, np.array([1.0, -2 * c / a0, (1 - alpha) / a0])


class StereoFilter:
    """Biquad on an (n, 2) block that keeps its state between blocks."""

    def __init__(self):
        self.zi = np.zeros((2, 2))

    def process(self, x, kind, freq, q, sr):
        b, a = biquad(kind, freq, q, sr)
        y, self.zi = lfilter(b, a, x, axis=0, zi=self.zi)
        return y

    def reset(self):
        self.zi[:] = 0


def onepole_lp(x, coef, zi):
    """y[n] = (1-coef)*x[n] + coef*y[n-1] along axis 0."""
    return lfilter([1.0 - coef], [1.0, -coef], x, axis=0, zi=zi)


# ---------------------------------------------------------------- oscillators

def _blep(t, dt):
    y = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt
    y[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt
    y[m] = x * x + x + x + 1.0
    return y


def phase_ramp(ph0, dt, n):
    p = ph0 + dt * np.arange(1, n + 1)
    return p % 1.0, (ph0 + dt * n) % 1.0


def saw(ph, dt):
    return 2.0 * ph - 1.0 - _blep(ph, dt)


def square(ph, dt):
    return np.where(ph < 0.5, 1.0, -1.0) + _blep(ph, dt) - _blep((ph + 0.5) % 1.0, dt)


# ---------------------------------------------------------------- envelopes

class ADSR:
    """Linear ADSR evaluated once per block, interpolated within the block."""

    def __init__(self, a, d, s, r):
        self.a, self.d, self.s, self.r = max(a, 1e-4), max(d, 1e-4), s, max(r, 1e-4)
        self.stage = "a"
        self.v = 0.0
        self.rel_rate = 0.0

    def release(self, sr):
        if self.stage != "off":
            self.stage = "r"
            self.rel_rate = max(self.v, 1e-6) / (self.r * sr)

    def block(self, n, sr):
        v0 = self.v
        rem = float(n)
        while rem > 0:
            if self.stage == "a":
                rate = 1.0 / (self.a * sr)
                need = (1.0 - self.v) / rate
                if need <= rem:
                    self.v, rem, self.stage = 1.0, rem - need, "d"
                else:
                    self.v += rate * rem
                    rem = 0
            elif self.stage == "d":
                rate = max(1.0 - self.s, 1e-6) / (self.d * sr)
                need = (self.v - self.s) / rate
                if need <= rem:
                    self.v, rem, self.stage = self.s, rem - need, "s"
                else:
                    self.v -= rate * rem
                    rem = 0
            elif self.stage == "s":
                self.v = self.s
                if self.s <= 0.0:
                    self.stage = "off"
                rem = 0
            elif self.stage == "r":
                self.v -= self.rel_rate * rem
                if self.v <= 0:
                    self.v, self.stage = 0.0, "off"
                rem = 0
            else:
                self.v = 0.0
                rem = 0
        return v0 + (self.v - v0) * np.arange(1, n + 1) / n


# ---------------------------------------------------------------- synth

# Sound library. osc: saw2 / super / saw1 / square / pulse / tri / sine / bass / fm / organ
# optional: detune (cents), sub, pw (pulse width), intervals (stacked semitones),
# noise (breath), vib (built-in vibrato, semitones), ratio/index (fm)
CATEGORIES = ["Pads", "Keys", "Bass", "Leads", "Plucks", "Bells", "Organ+"]


def _p(cat, name, osc, amp, fenv=(0.01, 0.3, 1.0, 0.3), fenv_amt=0.0, cutoff=16000, reso=0.0, gain=0.3, **kw):
    return dict(cat=cat, name=name, osc=osc, amp=amp, fenv=fenv, fenv_amt=fenv_amt, cutoff=cutoff,
                reso=reso, gain=gain, **kw)


PATCHES = [
    _p("Pads", "Saw Pad", "saw2", (0.35, 0.6, 0.85, 1.4), (0.8, 1.5, 0.4, 1.4), 1.2, 1400, 0.15, 0.32, detune=9, sub=0.25),
    _p("Pads", "Strings", "super", (0.6, 0.5, 0.9, 1.2), (0.8, 1.0, 0.6, 1.0), 0.6, 2200, 0.05, 0.3, detune=12, vib=0.05),
    _p("Pads", "Glass Pad", "fm", (0.5, 1.0, 0.8, 1.6), (0.5, 2.0, 0.5, 1.5), 0.0, 9000, 0.0, 0.3, ratio=2.0, index=1.2),
    _p("Pads", "Dark Pad", "pulse", (0.8, 1.0, 0.85, 2.0), (1.5, 2.0, 0.3, 2.0), 1.0, 500, 0.2, 0.32, pw=0.35, detune=7, sub=0.3),
    _p("Pads", "Sweep Pad", "saw2", (0.4, 1.0, 0.8, 1.5), (2.5, 2.5, 0.2, 2.0), 2.5, 250, 0.5, 0.28, detune=10),
    _p("Keys", "FM Keys", "fm", (0.002, 1.4, 0.25, 0.5), (0.002, 0.9, 0.15, 0.5), 0.0, 9000, 0.0, 0.38, ratio=1.0, index=2.6),
    _p("Keys", "E-Piano", "fm", (0.002, 1.8, 0.3, 0.5), (0.002, 0.6, 0.1, 0.4), 0.0, 7000, 0.0, 0.4, ratio=1.0, index=1.6),
    _p("Keys", "Clav", "pulse", (0.001, 0.4, 0.2, 0.1), (0.001, 0.15, 0.1, 0.1), 2.5, 900, 0.3, 0.35, pw=0.15),
    _p("Keys", "Toy Piano", "fm", (0.001, 0.8, 0.0, 0.6), (0.001, 0.3, 0.0, 0.3), 0.0, 10000, 0.0, 0.3, ratio=4.0, index=1.4),
    _p("Keys", "Lo-Fi Keys", "tri", (0.003, 1.2, 0.3, 0.4), (0.002, 0.8, 0.2, 0.3), 1.0, 1200, 0.1, 0.4, detune=6, vib=0.08, noise=0.02),
    _p("Bass", "Sub Bass", "bass", (0.003, 0.35, 0.7, 0.12), (0.002, 0.18, 0.0, 0.1), 2.5, 320, 0.25, 0.5),
    _p("Bass", "Acid", "saw1", (0.001, 0.3, 0.55, 0.08), (0.001, 0.22, 0.0, 0.1), 4.5, 220, 0.82, 0.38),
    _p("Bass", "Reese", "saw2", (0.01, 0.5, 0.9, 0.2), (0.01, 0.5, 0.6, 0.2), 0.5, 400, 0.15, 0.4, detune=22),
    _p("Bass", "FM Bass", "fm", (0.002, 0.5, 0.4, 0.12), (0.002, 0.25, 0.1, 0.1), 0.0, 3000, 0.0, 0.45, ratio=1.0, index=2.2),
    _p("Bass", "Pluck Bass", "square", (0.001, 0.3, 0.0, 0.1), (0.001, 0.12, 0.0, 0.1), 3.0, 250, 0.3, 0.45, sub=0.4),
    _p("Leads", "Square Lead", "square", (0.005, 0.25, 0.75, 0.25), (0.005, 0.3, 0.3, 0.3), 1.5, 2600, 0.3, 0.3, detune=4),
    _p("Leads", "Saw Lead", "super", (0.005, 0.3, 0.8, 0.3), (0.005, 0.4, 0.5, 0.3), 1.2, 2500, 0.2, 0.26, detune=8, vib=0.1),
    _p("Leads", "Pulse Lead", "pulse", (0.005, 0.3, 0.8, 0.25), (0.005, 0.3, 0.4, 0.3), 1.0, 3000, 0.25, 0.32, pw=0.22, detune=3, vib=0.1),
    _p("Leads", "Chip Lead", "square", (0.001, 0.05, 0.9, 0.05), gain=0.22),
    _p("Leads", "Fifth Lead", "saw1", (0.005, 0.3, 0.75, 0.3), (0.005, 0.35, 0.4, 0.3), 1.5, 1800, 0.3, 0.3, intervals=(0, 7)),
    _p("Plucks", "Pluck", "saw1", (0.001, 0.35, 0.0, 0.25), (0.001, 0.16, 0.0, 0.2), 4.0, 300, 0.35, 0.45, sub=0.15),
    _p("Plucks", "Bright Pluck", "super", (0.001, 0.45, 0.0, 0.35), (0.001, 0.25, 0.0, 0.3), 3.0, 600, 0.2, 0.38, detune=10),
    _p("Plucks", "Kalimba", "fm", (0.001, 0.9, 0.0, 0.6), (0.001, 0.08, 0.0, 0.1), 0.0, 9000, 0.0, 0.4, ratio=6.0, index=0.8),
    _p("Plucks", "Harp", "tri", (0.001, 1.5, 0.0, 1.0), (0.001, 0.4, 0.0, 0.5), 2.0, 800, 0.0, 0.45),
    _p("Plucks", "Chord Stab", "saw1", (0.002, 0.3, 0.0, 0.2), (0.001, 0.2, 0.0, 0.2), 3.0, 500, 0.25, 0.45, intervals=(0, 4, 7)),
    _p("Bells", "Bell", "fm", (0.001, 2.6, 0.0, 2.6), (0.001, 1.6, 0.0, 1.6), 0.0, 12000, 0.0, 0.3, ratio=3.5, index=4.0),
    _p("Bells", "Marimba", "fm", (0.001, 0.5, 0.0, 0.4), (0.001, 0.06, 0.0, 0.1), 0.0, 6000, 0.0, 0.45, ratio=4.0, index=1.0),
    _p("Bells", "Vibes", "fm", (0.001, 2.5, 0.0, 1.5), (0.001, 0.2, 0.0, 0.3), 0.0, 9000, 0.0, 0.35, ratio=4.0, index=0.6, vib=0.12),
    _p("Bells", "Glockenspiel", "fm", (0.001, 1.4, 0.0, 1.0), (0.001, 0.3, 0.0, 0.3), 0.0, 12000, 0.0, 0.25, ratio=5.4, index=1.5),
    _p("Bells", "Crystal", "fm", (0.3, 2.0, 0.4, 2.5), (0.3, 2.0, 0.2, 2.0), 0.0, 12000, 0.0, 0.25, ratio=7.0, index=2.5),
    _p("Organ+", "Organ", "organ", (0.004, 0.1, 1.0, 0.07), gain=0.22, cutoff=7000),
    _p("Organ+", "Perc Organ", "organ", (0.002, 0.4, 0.6, 0.06), gain=0.24, cutoff=7000),
    _p("Organ+", "Flute", "sine", (0.06, 0.3, 0.85, 0.2), (0.06, 0.3, 0.8, 0.2), 0.5, 3500, 0.0, 0.45, noise=0.08, vib=0.15),
    _p("Organ+", "Brass", "saw2", (0.06, 0.4, 0.8, 0.25), (0.08, 0.5, 0.5, 0.3), 1.5, 900, 0.1, 0.3, detune=6, vib=0.05),
    _p("Organ+", "Choir", "tri", (0.4, 0.6, 0.8, 1.2), (0.4, 0.6, 0.8, 1.2), 0.3, 1400, 0.3, 0.4, detune=10, noise=0.03, vib=0.1),
]


class Voice:
    def __init__(self, note, vel, patch, attack, release, sr):
        self.note, self.vel, self.p = note, vel, patch
        a, d, s, r = patch["amp"]
        self.env = ADSR(attack, d, s, release)
        self.fenv = ADSR(*patch["fenv"])
        self.ph = np.random.rand(16)  # free running oscillator phases
        self.zi = np.zeros(2)
        self.down = True       # key physically held
        self.sustained = False  # held by pedal after key up
        self.gain = (0.25 + 0.75 * (vel / 127.0) ** 1.4) * patch["gain"]

    @property
    def done(self):
        return self.env.stage == "off"

    def render(self, n, sr, semis, cutoff, reso, mod, vib_wave=0.0):
        p = self.p
        semis = semis + p.get("vib", 0.0) * vib_wave
        f = 440.0 * 2.0 ** ((self.note - 69 + semis) / 12.0)
        osc = p["osc"]
        if osc in ("saw2", "square", "saw1", "super", "bass", "pulse", "tri", "sine"):
            cents = p.get("detune", 0)
            if osc == "super":
                spreads = (-1.0, -0.6, -0.2, 0.2, 0.6, 1.0)
            elif cents:
                spreads = (-1.0, 1.0)
            else:
                spreads = (0.0,)
            ivs = p.get("intervals", (0,))
            x = np.zeros(n)
            k = 0
            for iv in ivs:
                for sp in spreads:
                    dt = f * 2.0 ** (iv / 12.0 + sp * cents / 1200.0) / sr
                    ph, self.ph[k] = phase_ramp(self.ph[k], dt, n)
                    k += 1
                    if osc == "square":
                        x += square(ph, dt)
                    elif osc == "pulse":
                        x += saw(ph, dt) - saw((ph + p.get("pw", 0.5)) % 1.0, dt)
                    elif osc == "tri":
                        x += 4.0 * np.abs(ph - 0.5) - 1.0
                    elif osc == "sine":
                        x += np.sin(TWO_PI * ph)
                    else:
                        x += saw(ph, dt)
            x /= k ** 0.5
            if osc == "bass":
                ph, self.ph[14] = phase_ramp(self.ph[14], f / sr, n)
                x = 0.35 * x + np.sin(TWO_PI * ph)
            sub = p.get("sub", 0.0)
            if sub:
                ph, self.ph[15] = phase_ramp(self.ph[15], f * 0.5 / sr, n)
                x += sub * np.sin(TWO_PI * ph)
            if p.get("noise"):
                x += p["noise"] * np.random.uniform(-1.0, 1.0, n)
        elif osc == "fm":
            ph_c, self.ph[0] = phase_ramp(self.ph[0], f / sr, n)
            ph_m, self.ph[1] = phase_ramp(self.ph[1], f * p["ratio"] / sr, n)
            idx = p["index"] * (0.3 + 0.7 * self.fenv.v) * (0.5 + self.vel / 127.0)
            x = np.sin(TWO_PI * ph_c + idx * np.sin(TWO_PI * ph_m))
        else:  # organ drawbars
            ph, self.ph[0] = phase_ramp(self.ph[0], f / sr, n)
            x = np.zeros(n)
            for h, w in ((0.5, 0.6), (1, 1.0), (2, 0.7), (3, 0.45), (4, 0.35), (6, 0.2), (8, 0.15)):
                if f * h < sr * 0.45:
                    x += w * np.sin(TWO_PI * ((ph * h) % 1.0))
        fe = self.fenv.block(n, sr)
        amp = self.env.block(n, sr)
        if p["fenv_amt"] or cutoff < 15000:
            fc = cutoff * 2.0 ** (p["fenv_amt"] * fe[n // 2] * (0.4 + 0.6 * self.vel / 127.0)
                                  + (self.note - 60) / 24.0 + mod * 1.5)
            b, a = biquad("lp", fc, 0.707 + reso * 14.0, sr)
            x, self.zi = lfilter(b, a, x, zi=self.zi)
        return x * amp * self.gain


class Synth:
    MAX_VOICES = 12

    def __init__(self, sr, patches=None):
        self.sr = sr
        self.voices = []
        self.patches = patches or PATCHES
        self.patch_index = 0
        self.patch = self.patches[0]
        self.cutoff = self.patch["cutoff"]
        self.reso = self.patch["reso"]
        self.attack = self.patch["amp"][0]
        self.release = self.patch["amp"][3]
        self.bend = 0.0      # -1..1 (joystick X)
        self.mod = 0.0       # 0..1 (joystick Y)
        self.sustain = False
        self.lfo = 0.0

    def set_patch(self, i):
        self.patch_index = i % len(self.patches)
        self.patch = self.patches[self.patch_index]
        self.cutoff, self.reso = self.patch["cutoff"], self.patch["reso"]
        self.attack, self.release = self.patch["amp"][0], self.patch["amp"][3]

    def note_on(self, note, vel):
        for v in self.voices:  # retrigger same key
            if v.note == note and not v.done:
                v.env.release(self.sr)
                v.down = v.sustained = False
        live = [v for v in self.voices if not v.done]
        if len(live) >= self.MAX_VOICES:
            victim = next((v for v in live if not v.down), live[0])
            self.voices.remove(victim)
        self.voices.append(Voice(note, vel, self.patch, self.attack, self.release, self.sr))

    def note_off(self, note):
        for v in self.voices:
            if v.note == note and v.down:
                v.down = False
                if self.sustain:
                    v.sustained = True
                else:
                    v.env.release(self.sr)
                    v.fenv.release(self.sr)

    def set_sustain(self, on):
        self.sustain = on
        if not on:
            for v in self.voices:
                if v.sustained:
                    v.sustained = False
                    v.env.release(self.sr)
                    v.fenv.release(self.sr)

    def all_off(self):
        self.voices.clear()

    def render(self, n):
        out = np.zeros(n)
        self.lfo = (self.lfo + 5.5 * n / self.sr) % 1.0
        wave = np.sin(TWO_PI * self.lfo)
        semis = self.bend * 2.0 + self.mod * 0.35 * wave
        for v in self.voices:
            v.env.r = max(self.release, 1e-3)
            out += v.render(n, self.sr, semis, self.cutoff, self.reso, self.mod, wave)
        self.voices = [v for v in self.voices if not v.done]
        return out


# ---------------------------------------------------------------- drums & one-shots

def _env(n, decay_s, sr):
    return np.exp(-np.arange(n) / (decay_s * sr))


def _pan(x, p):
    """mono -> (n,2) with constant power pan p in -1..1."""
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1)


def make_kits(sr):
    """Factory drum kits (see factory/kits.json); the Library adds user kits on top."""
    import json
    from pathlib import Path
    from . import drumsynth
    recipes = json.loads((Path(__file__).parent / "factory" / "kits.json").read_text())
    return [(k["name"], drumsynth.render_kit(k, sr)) for k in recipes]


def make_click(sr, freq, level):
    n = int(0.03 * sr)
    t = np.arange(n) / sr
    x = np.sin(TWO_PI * freq * t) * _env(n, 0.006, sr) * level
    return _pan(x.astype(np.float32), 0.0)


class OneShots:
    """Plays pre-rendered (m,2) samples; used for drums and the metronome."""

    def __init__(self):
        self.v = []  # [sample, pos, gain, offset, group]

    def trigger(self, sample, gain, offset=0, group=None):
        if group is not None:  # choke group (closed hat cuts open hat)
            self.v = [x for x in self.v if x[4] != group]
        self.v.append([sample, 0, gain, offset, group])

    def render(self, n):
        out = np.zeros((n, 2))
        keep = []
        for x in self.v:
            s, pos, g, off = x[0], x[1], x[2], x[3]
            take = min(n - off, len(s) - pos)
            if take > 0:
                out[off:off + take] += s[pos:pos + take] * g
            x[1], x[3] = pos + take, 0
            if x[1] < len(s):
                keep.append(x)
        self.v = keep
        return out


# ---------------------------------------------------------------- effects

class PingPongDelay:
    def __init__(self, sr, max_s=3.0):
        self.sr = sr
        self.N = int(max_s * sr)
        self.buf = np.zeros((self.N, 2))
        self.w = 0
        self.zi = np.zeros((1, 2))
        self.D = int(0.375 * sr)

    def process(self, x, time_s, fb):
        n = len(x)
        target = int(min(max(time_s * self.sr, n + 1), self.N - n - 1))
        # glide toward new delay time to avoid hard jumps
        self.D += int((target - self.D) * 0.25) if abs(target - self.D) > 64 else target - self.D
        idx = (self.w - self.D + np.arange(n)) % self.N
        y = self.buf[idx]
        damped, self.zi = onepole_lp(y, 0.35, self.zi)
        widx = (self.w + np.arange(n)) % self.N
        mono = (x[:, 0] + x[:, 1]) * 0.5
        self.buf[widx, 0] = mono + fb * damped[:, 1]
        self.buf[widx, 1] = fb * damped[:, 0]
        self.w = (self.w + n) % self.N
        return y


class FDNReverb:
    LENS = (1123, 1361, 1597, 1847, 2083, 2297, 2593, 2861)

    def __init__(self, sr):
        self.sr = sr
        scale = sr / 48000.0
        self.lens = [max(int(l * scale), 1100) for l in self.LENS]
        self.lines = [np.zeros(l) for l in self.lens]
        self.w = [0] * 8
        h = np.array([[1.0]])
        while h.shape[0] < 8:
            h = np.block([[h, h], [h, -h]])
        self.H = h / np.sqrt(8)
        self.zi = np.zeros((8, 1))
        self.set_size(0.5)

    def set_size(self, size):
        rt60 = 0.5 + size * 6.0
        self.g = np.array([10 ** (-3.0 * l / (rt60 * self.sr)) for l in self.lens])
        self.damp = 0.15 + 0.5 * (1 - size)

    def process(self, x):
        n = len(x)
        Y = np.empty((8, n))
        idxs = []
        for i in range(8):
            idx = (self.w[i] + np.arange(n)) % self.lens[i]
            idxs.append(idx)
            Y[i] = self.lines[i][idx]
        Yd, self.zi = lfilter([1 - self.damp], [1, -self.damp], Y, axis=1, zi=self.zi)
        fb = self.H @ (Yd * self.g[:, None])
        inp = np.empty((8, n))
        inp[:4] = x[:, 0] * 0.5
        inp[4:] = x[:, 1] * 0.5
        for i in range(8):
            self.lines[i][idxs[i]] = fb[i] + inp[i]
            self.w[i] = (self.w[i] + n) % self.lens[i]
        out = np.stack([Y[0::2].sum(0), Y[1::2].sum(0)], axis=1) * 0.35
        return out
