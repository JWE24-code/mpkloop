"""Drum voice generators. A kit recipe is a list of 8 voices, each
{"name": ..., "gen": <generator>, "args": {...}, "pan": -1..1, "level": 0..1}
in bank-B pad order (bottom row 1-4, top row 5-8). Recipes live in
factory/kits.json and in ~/Music/mpkloop/library/kits/<name>/kit.json."""
import numpy as np
from scipy.signal import lfilter

from .dsp import TWO_PI, biquad, square

GENERATORS = {}


def gen(fn):
    GENERATORS[fn.__name__] = fn
    return fn


class Ctx:
    """Sample rate plus a seeded noise source, so a kit renders the same every time."""

    def __init__(self, sr, seed=7):
        self.sr = sr
        self.rng = np.random.default_rng(seed)

    def noise(self, sec):
        return self.rng.uniform(-1, 1, int(sec * self.sr))

    def t(self, sec):
        return np.arange(int(sec * self.sr)) / self.sr

    def filt(self, kind, f, q, x):
        b, a = biquad(kind, f, q, self.sr)
        return lfilter(b, a, x)

    def sweep(self, f_hi, f_lo, sweep, length):
        t = self.t(length)
        f = f_lo + (f_hi - f_lo) * np.exp(-t / sweep)
        return t, np.sin(TWO_PI * np.cumsum(f) / self.sr)


@gen
def kick(c, f_hi=155, f_lo=45, sweep=0.045, decay=0.22, length=0.5, click=0.5, drive=1.6, sub=0.0):
    t, x = c.sweep(f_hi, f_lo, sweep, length)
    x = x * np.exp(-t / decay)
    if sub:  # extra sine an octave down for long 808 tails
        x += sub * np.sin(TWO_PI * f_lo * 0.5 * t) * np.exp(-t / (decay * 1.3))
    k = int(0.004 * c.sr)
    x[:k] += c.noise(0.004)[:k] * click
    return np.tanh(x * drive)


@gen
def snare(c, tone=185, tone_decay=0.06, hp=1200, noise_decay=0.09, mix=0.8, length=0.3, body=0.6, tone2=0.0):
    t = c.t(length)
    b = np.sin(TWO_PI * tone * t) * np.exp(-t / tone_decay)
    if tone2:
        b += 0.5 * np.sin(TWO_PI * tone2 * t) * np.exp(-t / (tone_decay * 0.7))
    return body * b + mix * c.filt("hp", hp, 0.7, c.noise(length)) * np.exp(-t / noise_decay)


@gen
def brush(c, hp=2500, decay=0.12, length=0.35, swell=0.03, level=0.8):
    """Brushed snare: noise that swells in instead of hitting."""
    t = c.t(length)
    env = np.minimum(t / swell, 1.0) * np.exp(-t / decay)
    return c.filt("hp", hp, 0.5, c.noise(length)) * env * level


@gen
def hat(c, hp=7000, decay=0.018, length=0.08, level=0.9, metallic=False, bp=0.0):
    t = c.t(length)
    if metallic:  # 808 style: six detuned squares
        src = sum(square((fr * t) % 1, fr / c.sr) for fr in (205, 304, 369, 522, 540, 800)) / 6
    else:
        src = c.noise(length)
    x = c.filt("hp", hp, 0.7, src)
    if bp:
        x = c.filt("bp", bp, 1.2, x) * 2.0
    return x * np.exp(-t / decay) * level


@gen
def ride(c, decay=0.6, length=1.4, level=0.5):
    t = c.t(length)
    src = sum(square((fr * t) % 1, fr / c.sr) for fr in (311, 412, 587, 722, 919, 1340)) / 6
    ping_ = np.sin(TWO_PI * 2650 * t) * np.exp(-t / 0.08) * 0.6
    return (c.filt("hp", 4500, 0.6, src) * np.exp(-t / decay) + ping_) * level


@gen
def clap(c, bp=1300, tail=0.11, level=2.2, spread=0.011):
    n = int(0.35 * c.sr)
    burst = np.zeros(n)
    for k, d in enumerate((0, spread, 2 * spread)):
        i = int(d * c.sr)
        burst[i:] += np.exp(-np.arange(n - i) / ((0.008 if k < 2 else tail) * c.sr))
    return c.filt("bp", bp, 1.8, c.noise(0.35) * burst) * level


@gen
def tone(c, f_hi=155, f_lo=95, sweep=0.07, decay=0.17, length=0.45, level=0.9, drive=1.0):
    t, x = c.sweep(f_hi, f_lo, sweep, length)
    x = x * np.exp(-t / decay) * level
    return np.tanh(x * drive) if drive != 1.0 else x


@gen
def ping(c, freqs=((1750, 1.0), (520, 0.5)), decay=0.01, length=0.06, level=1.0):
    t = c.t(length)
    return sum(np.sin(TWO_PI * f * t) * w for f, w in freqs) * np.exp(-t / decay) * level


@gen
def cowbell(c, f1=540, f2=800, decay=0.09, level=1.4):
    t = c.t(0.35)
    cb = (square((f1 * t) % 1, f1 / c.sr) + square((f2 * t) % 1, f2 / c.sr)) * 0.5
    return c.filt("bp", (f1 + f2) * 0.67, 2.0, cb) * np.exp(-t / decay) * level


@gen
def shaker(c, length=0.12, hp=5000, level=0.7, attack=0.02, decay=0.035):
    t = c.t(length)
    env = np.minimum(t / attack, 1.0) * np.exp(-t / decay)
    return c.filt("hp", hp, 0.7, c.noise(length)) * env * level


@gen
def tambourine(c):
    return hat(c, 6500, 0.08, 0.35, 0.6, metallic=True) + shaker(c, 0.35, 7000, 0.5)


@gen
def noise_hit(c, bp=3000, q=0.8, decay=0.12, length=0.5, level=1.4, sweep=0.0):
    t = c.t(length)
    x = c.filt("bp", bp, q, c.noise(length))
    if sweep:  # filter opening up over the hit (techno "zap" noise)
        x = c.filt("lp", bp * 3, 0.7, x)
    return x * np.exp(-t / decay) * level


@gen
def woodblock(c, f=1900, f2=750, decay=0.02, level=3.0):
    return c.filt("bp", f, 4.0, ping(c, ((f, 1.0), (f2, 0.3)), decay, 0.1)) * level


@gen
def zap(c, f_hi=2400, f_lo=90, sweep=0.025, decay=0.12, length=0.3, level=0.6):
    return tone(c, f_hi, f_lo, sweep, decay, length, level)


@gen
def glitch(c, length=0.09, rate=3, level=0.9, seed=1):
    """Chopped noise/sine burst: a few random gates over a short buffer."""
    t = c.t(length)
    rng = np.random.default_rng(seed)
    gates = (rng.random(int(length * 1000 * rate / 10)) > 0.4).astype(float)
    g = np.repeat(gates, int(np.ceil(len(t) / len(gates))))[: len(t)]
    f = 400 + 3000 * rng.random()
    x = (np.sin(TWO_PI * f * t) * 0.6 + c.noise(length) * 0.5) * g
    return x * np.exp(-t / (length * 0.5)) * level


@gen
def reverse_cymbal(c, length=0.5, level=0.8):
    t = c.t(length)
    return c.filt("hp", 5000, 0.6, c.noise(length)) * (t / length) ** 2.5 * level


# ---- post effects on a voice

def crush(x, c, hold=4, bits=6):
    x = np.repeat(x[::hold], hold)[: len(x)]
    q = 2 ** (bits - 1)
    return c.filt("lp", 5000, 0.7, np.round(x * q) / q)


def drive(x, c, amount=2.0):
    return np.tanh(x * amount) / np.tanh(amount)


def lowpass(x, c, f=3000):
    return c.filt("lp", f, 0.7, x)


POST = {"crush": crush, "drive": drive, "lowpass": lowpass}


def _pan(x, p):
    """(n,) -> (n, 2) constant power pan, p in -1..1."""
    a = (p + 1.0) * 0.25 * np.pi
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1)


def render_voice(v, c):
    args = dict(v.get("args", {}))
    scale = args.pop("level", None) if "level" not in GENERATORS[v["gen"]].__code__.co_varnames else None
    x = GENERATORS[v["gen"]](c, **args)
    for name, args in v.get("post", []):
        x = POST[name](x, c, **(args or {}))
    name = v["name"]
    quiet = any(w in name for w in ("Hat", "Shaker", "Triangle", "Tambourine", "Ride"))
    peak = v.get("peak", 0.6 if quiet else 0.9) * (scale if scale is not None else 1.0)
    x = x * (peak / max(np.abs(x).max(), 1e-6))
    return _pan(x.astype(np.float32), v.get("pan", 0.0))


def render_kit(recipe, sr):
    """-> [(name, stereo buffer), ...] in pad order."""
    c = Ctx(sr)
    return [(v["name"], render_voice(v, c)) for v in recipe["voices"][:8]]
