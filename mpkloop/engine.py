"""Looper engine. All state changes happen inside the audio callback (process),
fed by an event queue that the MIDI thread and the UI append to."""
import math
import time
from collections import deque

import numpy as np

from . import dsp
from .library import CATEGORIES, Library
from .fx import FX_TYPES, Ducker, Insert, Perform
from .sampler import MAX_REC_SECONDS, Sampler
from .seq import LENGTHS, LEVELS as LEVELS_SEQ, StepSeq

NTRACKS = 16
TRACK_PAGES = {0, 1, 2, 3, 4, 5, 8, 9, 10}   # pages with one knob per track (8 per track bank)
RING_SECONDS = 150          # capture history; also the maximum loop length
HOLD_SECONDS = 0.7          # hold a loop pad this long to clear the track
UNDO_DEPTH = 3

REC_MODES = ["Free→Tempo", "Quantize", "1 bar", "2 bars", "4 bars", "8 bars"]
DELAY_DIVS = [("1/16", 0.25), ("1/8", 0.5), ("1/8.", 0.75), ("1/4", 1.0), ("1/4.", 1.5), ("1/2", 2.0)]
RATES = [-2.0, -1.0, -0.5, 0.5, 1.0, 2.0]
PADB_MODES = ["Drums", "Steps", "Chops", "Scenes", "FX"]
OLD_KITS = ["Classic", "808", "Electro", "Lo-Fi", "Percussion"]   # kit order before the library
STUTTER_CYCLE = [None, 1.0, 0.5, 0.25]          # computer key x: off, 1/4, 1/8, 1/16
FX_PADS = ["Rep 1/2", "Rep 1/4", "Rep 1/8", "Rep 1/16", "TapeStop", "Reverse", "Half", "Crush"]
SCENE_FIELDS = ("vol", "pan", "filt", "muted", "dsend", "rsend", "fx", "fxamt", "duck")


class Param:
    """A knob-controllable parameter, stored as a normalised 0..1 value."""

    def __init__(self, label, apply, lo=0.0, hi=1.0, default=0.0, fmt="{:.2f}",
                 choices=None, curve=1.0, ticks=100, locked=None, get=None):
        self.label, self.apply_fn, self.lo, self.hi, self.get = label, apply, lo, hi, get
        self.fmt, self.choices, self.curve, self.locked = fmt, choices, curve, locked
        self.ticks = ticks if not choices else max(3 * (len(choices) - 1), 1)
        self.norm = 0.0
        self.set_value(default)

    @property
    def value(self):
        if self.choices:
            return self.choices[round(self.norm * (len(self.choices) - 1))]
        return self.lo + (self.hi - self.lo) * self.norm ** self.curve

    def set_value(self, v, apply=True):
        if self.choices:
            self.norm = self.choices.index(v) / max(len(self.choices) - 1, 1)
        else:
            x = min(max((v - self.lo) / (self.hi - self.lo), 0.0), 1.0)
            self.norm = x ** (1.0 / self.curve)
        if apply:
            self.apply_fn(self.value)

    def set_norm(self, x):
        if self.locked and self.locked():
            return
        self.norm = min(max(x, 0.0), 1.0)
        self.apply_fn(self.value)

    def nudge(self, ticks):
        self.set_norm(self.norm + ticks / self.ticks)

    def text(self):
        if self.locked and self.locked():
            return "LOCK"
        v = self.value
        return self.fmt(v) if callable(self.fmt) else self.fmt.format(v)


class Track:
    def __init__(self, i, sr):
        self.i = i
        self.vol, self.pan, self.filt, self.rate = 0.8, 0.0, 0.0, 1.0
        self.dsend = self.rsend = 0.0
        self.muted = False
        self.solo = False
        self.mute_at = None     # transport sample where a queued mute/unmute lands
        self.label = ""
        self.fx, self.fxamt, self.duck = "Off", 0.5, 0.0
        self.insert = Insert(sr)
        self.filter = dsp.StereoFilter()
        self.gains = np.zeros(2)  # current L/R gain (for ramping)
        self.reset()

    def reset(self):
        self.state = "empty"   # empty armed rec closing play odub
        self.buf = None
        self.length = 0
        self.anchor = 0         # transport sample where loop phase == 0
        self.S = self.E = None  # record start / end (transport samples)
        self.fixed_end = False
        self.free = False
        self.undo = []          # [(buf, notes)]
        self.notes = []         # [[offset, "on"/"off", number, velocity, instrument]]
        self.on_grid = True     # playing at pos - anchor (False while varispeed)
        self.phase = 0.0        # used when rate != 1
        self.start_offset = 0
        self.level = 0.0
        self.filter.reset()


def _db(v):
    return "-inf" if v <= 1e-4 else f"{20 * math.log10(v):+.0f}dB"


def _pan(v):
    return "C" if abs(v) < 0.03 else (f"L{abs(v) * 100:.0f}" if v < 0 else f"R{v * 100:.0f}")


def _filt(v):
    if abs(v) < 0.03:
        return "off"
    return f"LP{abs(v) * 100:.0f}" if v < 0 else f"HP{v * 100:.0f}"


def _rate(v):
    return {-2.0: "rev2x", -1.0: "rev", -0.5: "rev½", 0.5: "½x", 1.0: "1x", 2.0: "2x"}[v]


class Engine:
    def __init__(self, sr=48000, block=256):
        self.sr, self.block = sr, block
        self.events = deque()
        self.lock_tempo = lambda: any(t.state != "empty" for t in self.tracks)

        self.beats = 4
        self.bar = 0
        self.tempo = 120.0
        self.set_tempo(120.0)
        self.running = False
        self.pos = 0
        self.count_in_end = None
        self.ring_len = RING_SECONDS * sr
        self.ring = np.zeros((self.ring_len, 2), np.float32)
        self.tracks = [Track(i, sr) for i in range(NTRACKS)]
        self.track_bank = 0              # pads / keys 1-8 address tracks 1-8 or 9-16

        self.lib = Library(sr)
        self.synth = dsp.Synth(sr, self.lib.patches)
        self.sampler = Sampler(sr)
        self.key_inst = "Synth"          # what the keys play: Synth / Sampler
        self.sample_rec = None           # list of blocks while sampling
        self.seq = StepSeq()
        self.seq_drums = dsp.OneShots()
        self.ducker = Ducker(sr)
        self.perform = Perform(sr)
        self.tape_target = self.tape_rate = 1.0
        self.rev_all = self.half_all = False
        self.stutter_i = 0
        self.scenes = [None] * 8
        self.scene = None                # last recalled scene
        self.pending_scene = None
        self.padb_mode = "Drums"
        self.padb_down = {}
        self.note_log = deque(maxlen=50000)   # (pos, kind, number, velocity, instrument)
        self.clip = True                 # master tanh (off for stem export)
        self.kits = self.lib.kits
        self.kit_index = 0
        self.cat_memory = {}  # category -> last patch used in it
        self.drums = dsp.OneShots()
        self.metro = dsp.OneShots()
        self.click_hi = dsp.make_click(sr, 1600, 0.5)
        self.click_lo = dsp.make_click(sr, 1000, 0.35)
        self.delay = dsp.PingPongDelay(sr)
        self.reverb = dsp.FDNReverb(sr)
        self.master_filter = dsp.StereoFilter()
        self.pressure = 0.0
        self.pressure_smooth = 0.0

        # global settings (set via params below)
        self.rec_mode = "Quantize"
        self.count_in = True
        self.metro_level = 0.5
        self.input_gain = 0.0
        self.delay_div = 0.75
        self.delay_fb = 0.4
        self.master = 0.85
        self.synth_vol, self.drum_vol = 0.8, 0.8
        self.live_dsend, self.live_rsend = 0.0, 0.15
        self.input_latency = 0   # round-trip samples, set when the stream opens

        self.page = 0
        self.pages = self._build_pages()
        self.pickup = [False] * 8   # absolute-mode knob pickup state
        self.knob_last = [None] * 8

        # status for the UI / device / clock threads
        self.levels = np.zeros(2)
        self.cpu = 0.0
        self.message = ""
        self.message_t = 0.0
        self.log = deque(maxlen=8)   # (time, text) for the UI
        self.changed = False         # loops changed since last save/load
        self.session_name = ""
        self.session_demo = False
        self.clock_ref = (0, time.perf_counter())
        self.transport_gen = 0  # bumps on every transport start
        self.on_page_change = None
        self.bounce = None       # callable(block) when bouncing
        self.xruns = 0

    # ------------------------------------------------------------ params / pages

    def _build_pages(self):
        T, S, Q = self.tracks, self.synth, self.sampler
        tp = lambda attr, i: (lambda v: setattr(T[i], attr, v))
        tg = lambda attr, i: (lambda: getattr(T[i], attr))
        ob = lambda obj, attr: dict(apply=lambda v: setattr(obj, attr, v), get=lambda: getattr(obj, attr))

        def tparams(label, attr, *a, **kw):
            setter = kw.pop("setter", None)
            return [Param(f"T{i + 1} {label}", setter(i) if setter else tp(attr, i), *a, get=tg(attr, i), **kw)
                    for i in range(NTRACKS)]

        pages = [
            ("VOLUME", tparams("Vol", "vol", 0, 1.25, 0.8, _db, curve=2.0)),
            ("PAN", tparams("Pan", "pan", -1, 1, 0.0, _pan)),
            ("FILTER", tparams("Filter", "filt", -1, 1, 0.0, _filt)),
            ("RATE", tparams("Speed", "rate", setter=self._rate_setter, choices=RATES, default=1.0, fmt=_rate)),
            ("DELAY SEND", tparams("Delay", "dsend", 0, 1, 0.0, "{:.0%}")),
            ("REVERB SEND", tparams("Reverb", "rsend", 0, 1, 0.0, "{:.0%}")),
            ("SOUND", [
                Param("Cutoff", lo=40, hi=16000, default=S.cutoff, fmt="{:.0f}Hz", curve=3.0, **ob(S, "cutoff")),
                Param("Resonance", lo=0, hi=0.95, default=S.reso, fmt="{:.0%}", **ob(S, "reso")),
                Param("Attack", lo=0.001, hi=3.0, default=S.attack, fmt="{:.3f}s", curve=3.0, **ob(S, "attack")),
                Param("Release", lo=0.01, hi=5.0, default=S.release, fmt="{:.2f}s", curve=3.0, **ob(S, "release")),
                Param("Synth Vol", lambda v: setattr(self, "synth_vol", v), 0, 1.25, 0.8, _db, curve=2.0),
                Param("Drum Vol", lambda v: setattr(self, "drum_vol", v), 0, 1.25, 0.8, _db, curve=2.0),
                Param("Live Delay", lambda v: setattr(self, "live_dsend", v), 0, 1, 0.0, "{:.0%}"),
                Param("Live Reverb", lambda v: setattr(self, "live_rsend", v), 0, 1, 0.15, "{:.0%}"),
            ]),
            ("GLOBAL", [
                Param("Tempo", self.set_tempo, 50, 200, 120, "{:.1f}", ticks=300, locked=self.lock_tempo,
                      get=lambda: self.tempo),
                Param("Rec Mode", lambda v: setattr(self, "rec_mode", v), choices=REC_MODES,
                      default="Quantize", fmt="{}"),
                Param("Metronome", lambda v: setattr(self, "metro_level", v), 0, 1, 0.5, "{:.0%}"),
                Param("Input Gain", lambda v: setattr(self, "input_gain", v), 0, 2, 0.0, _db, curve=2.0),
                Param("Delay Time", lambda v: setattr(self, "delay_div", v), choices=[d for _, d in DELAY_DIVS],
                      default=0.75, fmt=lambda v: dict((d, n) for n, d in DELAY_DIVS)[v]),
                Param("Delay Fdbk", lambda v: setattr(self, "delay_fb", v), 0, 0.92, 0.4, "{:.0%}"),
                Param("Reverb Size", self.reverb_size, 0, 1, 0.5, "{:.0%}"),
                Param("Master", lambda v: setattr(self, "master", v), 0, 1.25, 0.85, _db, curve=2.0),
            ]),
            # pages 8+ are only reachable with the computer arrows (PROG CHANGE pads select 0-7)
            ("TRACK FX", tparams("FX", "fx", choices=FX_TYPES, default="Off", fmt="{}")),
            ("FX AMOUNT", tparams("FX Amt", "fxamt", 0, 1, 0.5, "{:.0%}")),
            ("DUCK", tparams("Duck", "duck", 0, 1, 0.0, "{:.0%}")),
            ("SEQ", [
                Param("Lane", choices=list(range(8)), default=0, fmt=lambda v: self.kits[self.kit_index][1][v][0],
                      **ob(self.seq, "lane")),
                Param("Swing", lo=0, hi=1, default=0.0, fmt=lambda v: f"{50 + 25 * v:.0f}%", **ob(self.seq, "swing")),
                Param("Length", choices=LENGTHS, default=16, fmt="{} st", **ob(self.seq, "length")),
                Param("Kit", self._kit_setter, choices=list(range(len(self.kits))), default=0,
                      fmt=lambda v: self.kits[v][0], get=lambda: self.kit_index),
                Param("Seq Vol", lo=0, hi=1.25, default=0.8, fmt=_db, curve=2.0, **ob(self.seq, "vol")),
                Param("Seq Pan", lo=-1, hi=1, default=0.0, fmt=_pan, **ob(self.seq, "pan")),
                Param("Seq Delay", lo=0, hi=1, default=0.0, fmt="{:.0%}", **ob(self.seq, "dsend")),
                Param("Seq Reverb", lo=0, hi=1, default=0.1, fmt="{:.0%}", **ob(self.seq, "rsend")),
            ]),
            ("SAMPLER", [
                Param("Pitch", lambda v: setattr(Q, "pitch", float(round(v))), -24, 24, 0, "{:+.0f}st", ticks=48,
                      get=lambda: Q.pitch),
                Param("Start", lo=0, hi=1, default=0.0, fmt="{:.0%}", **ob(Q, "start")),
                Param("Length", lo=0, hi=1, default=1.0, fmt="{:.0%}", **ob(Q, "length")),
                Param("Attack", lo=0.001, hi=2.0, default=0.002, fmt="{:.3f}s", curve=3.0, **ob(Q, "attack")),
                Param("Release", lo=0.01, hi=4.0, default=0.25, fmt="{:.2f}s", curve=3.0, **ob(Q, "release")),
                Param("Smp Vol", lo=0, hi=1.25, default=0.8, fmt=_db, curve=2.0, **ob(Q, "vol")),
                Param("Smp Filter", lo=200, hi=18000, default=18000, fmt="{:.0f}Hz", curve=3.0, **ob(Q, "cutoff")),
                Param("Reverse", choices=[False, True], default=False, fmt=lambda v: "On" if v else "Off",
                      **ob(Q, "reverse")),
            ]),
        ]
        return pages

    def tb(self, k):
        """Pad / key index 0-7 -> track index in the current track bank."""
        return k + 8 * self.track_bank if 0 <= k < 8 else k

    def visible_params(self, page=None):
        """The 8 params the knobs control right now (track pages follow the track bank)."""
        page = self.page if page is None else page
        params = self.pages[page][1]
        return params[8 * self.track_bank:8 * self.track_bank + 8] if page in TRACK_PAGES else params[:8]

    def page_title(self, page=None):
        page = self.page if page is None else page
        title = self.pages[page][0]
        return f"{title} {8 * self.track_bank + 1}-{8 * self.track_bank + 8}" if page in TRACK_PAGES else title

    def _kit_setter(self, v):
        if v != self.kit_index:
            self.kit_index = v
            self.say(f"Drum kit: {self.kits[v][0]}")

    def reverb_size(self, v):
        if hasattr(self, "reverb"):
            self.reverb.set_size(v)

    def _rate_setter(self, i):
        def f(v):
            t = self.tracks[i]
            if v != 1.0 and t.rate == 1.0 and t.length:
                t.phase = float((self.pos - t.anchor) % t.length)
            if t.state == "odub" and v != 1.0:
                t.state = "play"
            t.rate = v
        return f

    def set_tempo(self, bpm):
        self.bar = int(round(60.0 / bpm * self.beats * self.sr))
        self.tempo = 60.0 * self.beats * self.sr / self.bar

    @property
    def beat_len(self):
        return self.bar / self.beats

    def sync_param_values(self):
        """Re-read values that changed outside the params (patch change, load, scene)."""
        for _, params in self.pages:
            for p in params:
                if p.get:
                    p.set_value(p.get(), apply=False)

    def say(self, msg):
        self.message, self.message_t = msg, time.time()
        self.log.append((self.message_t, msg))

    # ------------------------------------------------------------ events (any thread)

    def post(self, *ev):
        self.events.append(ev)

    def _handle(self, ev):
        kind = ev[0]
        if kind == "note_on":
            (self.sampler if self.key_inst == "Sampler" else self.synth).note_on(ev[1], ev[2])
            self._log("on", ev[1], ev[2], self._key_tag())
        elif kind == "note_off":
            self.synth.note_off(ev[1])
            self.sampler.note_off(ev[1])
            self._log("off", ev[1], 0, self._key_tag())
        elif kind == "drum":
            self.play_drum(ev[1], ev[2])
        elif kind == "padb":
            self.padb(ev[1], ev[2])
        elif kind == "padb_off":
            self.padb_off(ev[1])
        elif kind == "padb_mode":
            self.padb_mode = PADB_MODES[(PADB_MODES.index(self.padb_mode) + 1) % len(PADB_MODES)]
            self.say(f"Bank B pads: {self.padb_mode}")
        elif kind == "tap":
            self.tap(ev[1])
        elif kind == "clear":
            self.clear(ev[1])
        elif kind == "mute":
            self.queue_mute(self.tracks[ev[1]])
        elif kind == "solo":
            t = self.tracks[ev[1]]
            t.solo = not t.solo
            self.say(f"T{t.i + 1}: solo {'on' if t.solo else 'off'}" if any(x.solo for x in self.tracks)
                     else f"T{t.i + 1}: solo off - all tracks play")
        elif kind == "unsolo":
            for t in self.tracks:
                t.solo = False
            self.say("Solo cleared")
        elif kind == "track_bank":
            self.track_bank = (ev[1] if len(ev) > 1 else 1 - self.track_bank) % (NTRACKS // 8)
            self.pickup = [False] * 8
            self.say(f"Pads and keys 1-8 now address tracks {8 * self.track_bank + 1}-{8 * self.track_bank + 8}")
            self.sync_param_values()
            if self.on_page_change:
                self.on_page_change()
        elif kind == "copy":
            self.copy_track(ev[1], ev[2])
        elif kind == "double":
            self.resize_track(ev[1], 2.0)
        elif kind == "halve":
            self.resize_track(ev[1], 0.5)
        elif kind == "label":
            self.tracks[ev[1]].label = ev[2][:12]
            self.changed = True
        elif kind == "undo":
            self.undo(ev[1])
        elif kind == "page":
            self.set_page(ev[1])
        elif kind == "patch":
            self.set_patch(ev[1])
        elif kind == "category":
            # tap a category pad: first (or last used) sound in it; tap again: next one
            cat = CATEGORIES[ev[1] % len(CATEGORIES)]
            members = self.lib.members(cat)   # favorites first
            cur = self.synth.patch_index
            if not members:
                self.say(f"No sounds in {cat}")
            elif cur in members:
                self.set_patch(members[(members.index(cur) + 1) % len(members)])
            else:
                self.set_patch(self.cat_memory.get(cat, members[0]))
        elif kind == "kit":
            self.kit_index = (self.kit_index + ev[1]) % len(self.kits)
            names = ", ".join(n for n, _ in self.kits[self.kit_index][1])
            self.say(f"Drum kit: {self.kits[self.kit_index][0]}  ({names})")
            self.sync_param_values()
        elif kind == "knob_rel":
            self.visible_params()[ev[1]].nudge(ev[2])
        # ---- sound library
        elif kind == "kit_set":
            self._kit_setter(ev[1] % len(self.kits))
            self.sync_param_values()
        elif kind == "lib_reload":
            self.reload_library(ev[1] if len(ev) > 1 else None)
        elif kind == "knob_abs":
            self.knob_abs(ev[1], ev[2])
        elif kind == "bend":
            self.synth.bend = self.sampler.bend = ev[1]
        elif kind == "mod":
            self.synth.mod = ev[1]
        elif kind == "sustain":
            self.synth.set_sustain(ev[1])
            self.sampler.set_sustain(ev[1])
        elif kind == "pressure":
            self.pressure = ev[1]
        elif kind == "transport":
            self.stop_transport() if self.running else self.start_transport()
        elif kind == "clear_all":
            for i in range(NTRACKS):
                self.clear(i, quiet=True)
            self.seq.on = False
            self.stop_transport()
            self.say("All tracks cleared")
        elif kind == "panic":
            self.synth.all_off()
            self.sampler.all_off()
        elif kind == "load":
            self._load(ev[1])
        # ---- step sequencer
        elif kind == "seq_toggle":
            self.seq.on = not self.seq.on
            if self.seq.on and not self.running:
                self.start_transport()
            elif not self.seq.on and self.running and self._empty_session():
                self.stop_transport()
            self.say(f"Step sequencer {'on' if self.seq.on else 'off'}")
        elif kind == "seq_rec":
            self.seq.rec = not self.seq.rec
            self.say("Seq record: finger drums are written into the pattern" if self.seq.rec else "Seq record off")
        elif kind == "seq_mute":
            self.seq.muted = not self.seq.muted
        elif kind == "seq_set":
            self.seq.pattern[ev[1], ev[2]] = ev[3]
            self.changed = True
        elif kind == "seq_clear_lane":
            self.seq.pattern[ev[1]] = 0
            self.changed = True
        elif kind == "seq_half":
            self.seq.half = 1 - self.seq.half
            self.say(f"Step pads edit steps {'9-16' if self.seq.half else '1-8'}")
        elif kind == "seq_lane":
            self.seq.lane = ev[1] % 8
            self.sync_param_values()
            if len(ev) < 3 or not ev[2]:
                self.say(f"Seq lane: {self.kits[self.kit_index][1][self.seq.lane][0]}")
        elif kind == "seq_print":
            self.print_seq()
        # ---- scenes
        elif kind == "scene_store":
            self.store_scene(ev[1])
        elif kind == "scene_recall":
            self.recall_scene(ev[1])
        # ---- perform FX
        elif kind == "stutter":
            self.perform.stutter(ev[1])
        elif kind == "stutter_cycle":
            self.stutter_i = (self.stutter_i + 1) % len(STUTTER_CYCLE)
            div = STUTTER_CYCLE[self.stutter_i]
            self.perform.stutter(None)
            self.perform.stutter(div)
            self.say("Stutter off" if div is None else f"Stutter 1/{int(4 / div)}")
        elif kind == "tapestop":
            on = (self.tape_target == 1.0) if ev[1] is None else ev[1]
            self.tape_target = 0.0 if on else 1.0
        elif kind == "rev_all":
            self.rev_all = ev[1]
        elif kind == "half_all":
            self.half_all = ev[1]
        elif kind == "mcrush":
            self.perform.crush = ev[1]
        # ---- sampler
        elif kind == "key_inst":
            self.key_inst = "Sampler" if self.key_inst == "Synth" else "Synth"
            if self.key_inst == "Sampler" and self.sampler.buf is None:
                self.say("Keys: Sampler (empty - y+1-8 grabs a loop, Y samples, l loads a WAV)")
            else:
                self.say(f"Keys: {self.key_inst}")
        elif kind == "sample_track":
            t = self.tracks[ev[1]]
            if t.length:
                self.sampler.set_buffer(t.buf.copy(), f"T{ev[1] + 1} loop")
                self.changed = True
                self.say(f"Sampler: took the loop of T{ev[1] + 1} ({t.length / self.bar:.0f} bars, 8 chops)")
            else:
                self.say(f"T{ev[1] + 1} is empty")
        elif kind == "sample_set":
            self.sampler.set_buffer(ev[1], ev[2])
            self.changed = True
            self.say(f"Sampler: loaded {ev[2]} ({len(ev[1]) / self.sr:.1f} s)")
        elif kind == "sample_rec":
            if self.sample_rec is None:
                self.sample_rec = []
                self.say(f"Sampling the input and what you play (max {MAX_REC_SECONDS} s) - Y again to stop")
            else:
                self.finish_sample_rec()

    def _key_tag(self):
        return "sampler" if self.key_inst == "Sampler" else "synth:" + self.synth.patch["name"]

    def _log(self, kind, number, vel, inst):
        """Remember played notes so loops can be exported as MIDI."""
        if not self.running:
            return
        self.note_log.append((self.pos, kind, number, vel, inst))
        for t in self.tracks:
            if t.state == "odub" and t.length:
                t.notes.append([int((self.pos - t.anchor) % t.length), kind, number, vel, inst])

    @staticmethod
    def _drum_group(name):
        return "hat" if name in ("Hat", "Open Hat") else None

    def play_drum(self, k, vel):
        name, sample = self.kits[self.kit_index][1][k]
        self.drums.trigger(sample, (0.15 + 0.85 * vel / 127.0) ** 1.5, group=self._drum_group(name))
        if k == 0:
            self.ducker.trigger(0)
        if self.seq.rec and self.running:
            self.seq.record_hit(self.pos, k, vel, self.beat_len)
        self._log("on", k, vel, "drum:" + self.kits[self.kit_index][0])

    def padb(self, k, vel):
        """Bank B pad in NOTE mode; what it does depends on padb_mode."""
        m = self.padb_mode
        if m == "Drums":
            self.play_drum(k, vel)
        elif m == "Steps":
            col = self.seq.half * 8 + k
            if col < self.seq.length:
                self.seq.toggle(self.seq.lane, col)
                self.changed = True
        elif m == "Chops":
            if self.sampler.buf is None:
                self.say("Sampler is empty - y+1-8 grabs a loop, Y samples, l loads a WAV")
            else:
                self.sampler.chop(k, vel)
                if k == 0:
                    self.ducker.trigger(0)
                self._log("on", k, vel, "chop")
        elif m == "Scenes":
            self.padb_down[k] = time.monotonic()
        elif m == "FX":
            if k < 4:
                self.perform.stutter(None)
                self.perform.stutter([2.0, 1.0, 0.5, 0.25][k])
            elif k == 4:
                self.tape_target = 0.0
            elif k == 5:
                self.rev_all = True
            elif k == 6:
                self.half_all = True
            else:
                self.perform.crush = True

    def padb_off(self, k):
        m = self.padb_mode
        if m == "Scenes":
            t0 = self.padb_down.pop(k, None)
            if t0 is not None:
                if time.monotonic() - t0 >= HOLD_SECONDS:
                    self.store_scene(k)
                else:
                    self.recall_scene(k)
        elif m == "FX":
            if k < 4:
                if self.perform.div == [2.0, 1.0, 0.5, 0.25][k]:
                    self.perform.stutter(None)
            elif k == 4:
                self.tape_target = 1.0
            elif k == 5:
                self.rev_all = False
            elif k == 6:
                self.half_all = False
            else:
                self.perform.crush = False

    # ------------------------------------------------------------ scenes

    def store_scene(self, i):
        self.scenes[i] = dict(tracks=[{f: getattr(t, f) for f in SCENE_FIELDS} for t in self.tracks],
                              seq=dict(vol=self.seq.vol, muted=self.seq.muted))
        self.scene = i
        self.changed = True
        self.say(f"Scene {i + 1} stored")

    def recall_scene(self, i):
        if not self.scenes[i]:
            self.say(f"Scene {i + 1} is empty - store it first (N+{i + 1}, or hold the pad)")
            return
        if self.running:
            self.pending_scene = i
            self.say(f"Scene {i + 1} at the next bar")
        else:
            self._apply_scene(i)

    def _apply_scene(self, i):
        sc = self.scenes[i]
        for t, d in zip(self.tracks, sc["tracks"]):
            for f in SCENE_FIELDS:
                if f in d:
                    setattr(t, f, d[f])
        self.seq.vol = sc.get("seq", {}).get("vol", self.seq.vol)
        self.seq.muted = sc.get("seq", {}).get("muted", self.seq.muted)
        self.scene, self.pending_scene = i, None
        self.sync_param_values()
        self.say(f"Scene {i + 1}")
        if self.on_page_change:
            self.on_page_change()

    # ------------------------------------------------------------ seq / sampler helpers

    def print_seq(self):
        """Render one pattern cycle of the step sequencer into the first empty track."""
        t = next((t for t in self.tracks if t.state == "empty"), None)
        if t is None:
            self.say("No empty track to print the sequencer into")
            return
        if not self.seq.pattern[:, :self.seq.length].any():
            self.say("The step pattern is empty")
            return
        step = self.beat_len / 4.0
        L = int(round(self.seq.length * step))
        buf = np.zeros((L, 2))
        notes = []
        kit = self.kits[self.kit_index]
        for g in range(self.seq.length):
            o = int(round(self.seq.step_time(g, step))) % L
            for lane in np.nonzero(self.seq.pattern[:, g])[0]:
                s = kit[1][lane][1] * LEVELS_SEQ[int(self.seq.pattern[lane, g])]
                k = 0
                while k < len(s):  # wrap the tail around the loop start
                    take = min(len(s) - k, L - (o + k) % L)
                    a = (o + k) % L
                    buf[a:a + take] += s[k:k + take]
                    k += take
                notes.append([o, "on", int(lane), 30 + 32 * int(self.seq.pattern[lane, g]), "drum:" + kit[0]])
        t.buf, t.length, t.anchor, t.state = buf.astype(np.float32), L, 0, "play"
        t.vol, t.pan, t.dsend, t.rsend, t.muted = self.seq.vol, self.seq.pan, self.seq.dsend, self.seq.rsend, False
        t.notes = notes
        self.seq.muted = True
        self.changed = True
        self.sync_param_values()
        if not self.running:
            self.start_transport()
        self.say(f"Sequencer printed to T{t.i + 1} (seq lane muted; ( unmutes it)")

    def finish_sample_rec(self):
        blocks, self.sample_rec = self.sample_rec, None
        if not blocks:
            return
        x = np.concatenate(blocks).astype(np.float32)
        loud = np.nonzero(np.abs(x).max(axis=1) > 0.003)[0]
        if len(loud) == 0:
            self.say("Sampling stopped: nothing was heard (Input Gain is on the Global page)")
            return
        x = x[max(loud[0] - 64, 0):loud[-1] + 1]
        self.sampler.set_buffer(x, "recording")
        self.changed = True
        self.say(f"Sampler: recorded {len(x) / self.sr:.1f} s")

    def set_patch(self, i):
        self.synth.set_patch(i)
        p = self.synth.patch
        self.cat_memory[p["cat"]] = self.synth.patch_index
        self.sync_param_values()
        members = self.lib.members(p["cat"])
        n = members.index(self.synth.patch_index) + 1 if self.synth.patch_index in members else 0
        star = " ★" if self.lib.is_fav(p) else ""
        self.say(f"Sound: {p['cat']} {n}/{len(members)} - {p['name']}{star}")
        if self.on_page_change:
            self.on_page_change()

    def reload_library(self, select=None):
        """After the library changed on disk (new patch, favorite, delete): keep the
        current sound and kit by name, or select the given ("patch"|"kit", name)."""
        cur_patch, cur_kit = self.synth.patch["name"], self.kits[self.kit_index][0]
        self.kits = self.lib.kits
        self.synth.patches = self.lib.patches
        kp = self.pages[11][1][3]                                     # SEQ page: Kit
        kp.choices, kp.ticks = list(range(len(self.kits))), max(3 * (len(self.kits) - 1), 1)
        if select and select[0] == "kit":
            self.kit_index = self.lib.kit_index_of(select[1])
            self.say(f"Drum kit: {self.kits[self.kit_index][0]}")
        else:
            self.kit_index = self.lib.kit_index_of(cur_kit)
        if select and select[0] == "patch":
            self.set_patch(self.lib.index_of(select[1]))
        else:
            self.synth.set_patch(self.lib.index_of(cur_patch))
        self.cat_memory.clear()
        self.sync_param_values()

    def set_page(self, p):
        self.page = p % len(self.pages)
        self.pickup = [False] * 8
        self.say(f"Knob page: {self.page_title()}")
        if self.on_page_change:
            self.on_page_change()

    def knob_abs(self, k, v):
        """Absolute knob with soft takeover: the parameter only follows once the
        knob passes its current value, so switching pages never makes values jump."""
        p = self.visible_params()[k]
        x = v / 127.0
        last = self.knob_last[k]
        self.knob_last[k] = x
        if not self.pickup[k]:
            if abs(x - p.norm) < 0.03 or (last is not None and (last - p.norm) * (x - p.norm) <= 0):
                self.pickup[k] = True
            else:
                return
        p.set_norm(x)

    # ------------------------------------------------------------ transport

    def start_transport(self):
        if self.running:
            return
        for t in self.tracks:
            if t.length:
                t.anchor = 0  # restart every loop from its top
                t.phase = 0.0
                t.on_grid = True
        self.pos = 0
        self.running = True
        self.transport_gen += 1
        self.clock_ref = (0, time.perf_counter())

    def stop_transport(self):
        self.running = False
        self.count_in_end = None
        self.perform.seg = None
        if self.pending_scene is not None:
            self._apply_scene(self.pending_scene)
        for t in self.tracks:
            if t.state in ("armed", "rec", "closing"):
                t.reset()
            elif t.state == "odub":
                t.state = "play"
        self.pos = 0

    # ------------------------------------------------------------ track actions

    def _fixed_bars(self):
        return {"1 bar": 1, "2 bars": 2, "4 bars": 4, "8 bars": 8}.get(self.rec_mode)

    def _empty_session(self):
        return all(t.state == "empty" for t in self.tracks)

    def _idle(self):
        """Nothing left that needs the transport running."""
        return self._empty_session() and not self.seq.on

    def queue_mute(self, t):
        """Mute / unmute on the next beat while playing (so it lands in time), at once otherwise."""
        if self.running and t.state in ("play", "odub"):
            if t.mute_at is not None:
                t.mute_at = None            # pressed twice: cancel
                return
            t.mute_at = int((self.pos // self.beat_len + 1) * self.beat_len)
        else:
            t.muted = not t.muted

    def _audible(self, t):
        solo = any(x.solo for x in self.tracks)
        return not t.muted and (t.solo or not solo)

    def copy_track(self, src, dst):
        a, b = self.tracks[src], self.tracks[dst]
        if not a.length:
            self.say(f"T{src + 1} is empty - nothing to copy")
            return
        if b.state != "empty":
            self.say(f"T{dst + 1} is not empty - clear it first")
            return
        b.buf, b.length, b.notes = a.buf.copy(), a.length, [list(x) for x in a.notes]
        b.anchor, b.phase, b.on_grid, b.state = a.anchor, a.phase, a.on_grid, "play"
        for f in ("vol", "pan", "filt", "rate", "dsend", "rsend", "fx", "fxamt", "duck", "label"):
            setattr(b, f, getattr(a, f))
        b.muted, b.solo, b.undo = False, False, []
        self.changed = True
        self.sync_param_values()
        self.say(f"T{src + 1} copied to T{dst + 1}")

    def resize_track(self, i, factor):
        t = self.tracks[i]
        if not t.length or t.state not in ("play", "odub"):
            self.say(f"T{i + 1} has no loop to resize")
            return
        if factor > 1 and t.length * 2 > RING_SECONDS * self.sr // 2:
            self.say(f"T{i + 1}: too long to double")
            return
        if factor < 1 and t.length // 2 < self.beat_len:
            self.say(f"T{i + 1}: too short to halve")
            return
        t.undo = (t.undo + [(t.buf, list(t.notes))])[-UNDO_DEPTH:]
        if factor > 1:
            t.buf = np.concatenate([t.buf, t.buf])
            t.notes = t.notes + [[n[0] + t.length] + list(n[1:]) for n in t.notes]
            t.length *= 2
        else:
            t.length //= 2
            t.buf = t.buf[:t.length].copy()
            t.notes = [n for n in t.notes if n[0] < t.length]
        self.changed = True
        bars = t.length / self.bar
        self.say(f"T{i + 1}: loop is now {bars:g} bar{'s' if bars != 1 else ''} (undo restores)")

    def tap(self, i):
        t = self.tracks[i]
        if t.state == "empty":
            self.arm(t)
        elif t.state == "armed":
            t.reset()
            if self._idle():
                self.stop_transport()
        elif t.state == "rec":
            self.close_rec(t)
        elif t.state == "play":
            if not self.running:
                self.start_transport()
                return
            t.undo = (t.undo + [(t.buf.copy(), list(t.notes))])[-UNDO_DEPTH:]
            self.changed = True
            if t.rate != 1.0:
                self.pages[3][1][i].set_value(1.0)
            t.state = "odub"
        elif t.state == "odub":
            t.state = "play"

    def arm(self, t):
        bar = self.bar
        late = min(bar // 8, int(0.25 * self.sr))
        if not self.running:
            if self._empty_session() and self.rec_mode == "Free→Tempo":
                self.start_transport()
                t.S, t.free, t.state = 0, True, "rec"
                self.say(f"T{t.i + 1}: recording (free) - tap again to close loop & set tempo")
                return
            self.start_transport()
            start = bar if self.count_in else 0
            self.count_in_end = start if self.count_in else None
        else:
            prev = (self.pos // bar) * bar
            if self.pos - prev <= late and self.count_in_end is None:
                start = prev  # pressed just after the downbeat: start there (ring has it)
            else:
                start = prev + bar
            if self.count_in_end is not None:
                start = max(start, self.count_in_end)
        t.S, t.free, t.state = start, False, "armed"
        n = self._fixed_bars()
        t.E, t.fixed_end = (start + n * bar, True) if n else (None, False)
        self.say(f"T{t.i + 1}: armed")

    def close_rec(self, t):
        if t.free:
            L = self.pos - t.S
            if L < self.sr // 4:
                return
            nb = next((nb for nb in (1, 2, 4, 8, 16) if 60.0 * self.beats * nb * self.sr / L >= 75), 16)
            self.bar = L // nb
            self.tempo = 60.0 * self.beats * self.sr / self.bar
            self.pages[7][1][0].set_value(self.tempo, apply=False)
            t.E = t.S + self.bar * nb
            self.say(f"Tempo set from loop: {self.tempo:.1f} BPM ({nb} bars)")
        else:
            bar = self.bar
            rel = self.pos - t.S
            prev = t.S + (rel // bar) * bar
            late = min(bar // 8, int(0.25 * self.sr))
            if rel < bar:
                t.E = t.S + bar
            elif self.pos - prev <= late:
                t.E = prev
            else:
                t.E = prev + bar
        t.state = "closing"

    def clear(self, i, quiet=False):
        t = self.tracks[i]
        was = t.state
        if was in ("play", "odub"):
            self.changed = True
        t.reset()
        if not quiet:
            self.say(f"T{i + 1}: cleared" if was != "empty" else f"T{i + 1}: cancelled")
        if self._idle() and self.running:
            self.stop_transport()

    def undo(self, i):
        t = self.tracks[i]
        if t.undo:
            t.buf, t.notes = t.undo.pop()
            self.changed = True
            if t.state == "odub":
                t.state = "play"
            self.say(f"T{i + 1}: undo ({len(t.undo)} left)")
        else:
            self.say(f"T{i + 1}: nothing to undo")

    def _finalize(self, t, n):
        L = t.E - t.S
        idx = (t.S + np.arange(L)) % self.ring_len
        t.buf = self.ring[idx].copy()
        t.length, t.anchor = L, t.S
        t.notes = [[p - t.S, k, a, b, inst] for p, k, a, b, inst in self.note_log if t.S <= p < t.E]
        t.start_offset = min(max(t.E - self.pos, 0), n)
        t.state = "play"
        self.changed = True
        t.dsend, t.rsend = self.live_dsend, self.live_rsend
        self.pages[4][1][t.i].set_value(t.dsend, apply=False)
        self.pages[5][1][t.i].set_value(t.rsend, apply=False)
        bars = L / self.bar
        self.say(f"T{t.i + 1}: loop {bars:.0f} bar{'s' if bars != 1 else ''}")

    # ------------------------------------------------------------ session load

    def _load(self, data):
        self.stop_transport()
        self.bar = data["bar"]
        self.tempo = 60.0 * self.beats * self.sr / self.bar
        for t in self.tracks:
            t.reset()
            t.muted = t.solo = False
            t.mute_at, t.label = None, ""
        for t, td in zip(self.tracks, data["tracks"]):
            for k in ("vol", "pan", "filt", "rate", "dsend", "rsend", "muted"):
                setattr(t, k, td[k])
            t.fx, t.fxamt, t.duck = td.get("fx", "Off"), td.get("fxamt", 0.5), td.get("duck", 0.0)
            t.label = td.get("label") or ""
            if td.get("buf") is not None:
                t.buf, t.length, t.state = td["buf"], len(td["buf"]), "play"
                t.notes = [list(x) for x in td.get("notes", [])]
        self.seq.load(data.get("seq"))
        self.scenes = list(data.get("scenes") or [None] * 8)
        self.scene = self.pending_scene = None
        # sessions store sounds by name; older ones only had the index into the original lists
        kit_name = data.get("kit_name") or OLD_KITS[data.get("kit", 0) % len(OLD_KITS)]
        self.kit_index = self.lib.kit_index_of(kit_name)
        patch_name = data.get("patch_name") or dsp.PATCHES[data.get("patch", 0) % len(dsp.PATCHES)]["name"]
        self.synth.set_patch(self.lib.index_of(patch_name))
        if data.get("sampler"):
            self.sampler.load(data["sampler"], data["sampler"].get("buf"))
        self.sync_param_values()
        self.changed = False
        self.session_name = data.get("name", "")
        self.session_demo = bool(data.get("demo"))
        if any(t.length for t in self.tracks) or self.seq.on:
            self.start_transport()
        self.say(f"Loaded '{self.session_name or 'session'}' ({self.tempo:.0f} BPM) - playing")

    def state(self):
        """Everything a session stores (buffers included), for saving and export."""
        return dict(
            name=self.session_name, sr=self.sr, bar=self.bar, tempo=self.tempo,
            kit=self.kit_index, patch=self.synth.patch_index,
            kit_name=self.kits[self.kit_index][0], patch_name=self.synth.patch["name"],
            tracks=[dict(vol=t.vol, pan=t.pan, filt=t.filt, rate=t.rate, dsend=t.dsend, rsend=t.rsend,
                         muted=t.muted, fx=t.fx, fxamt=t.fxamt, duck=t.duck, label=t.label,
                         notes=[list(x) for x in t.notes] if t.length else [],
                         buf=t.buf if t.state in ("play", "odub") else None) for t in self.tracks],
            seq=self.seq.state(), scenes=list(self.scenes),
            sampler=dict(self.sampler.state(), buf=self.sampler.buf) if self.sampler.buf is not None else None,
        )

    # ------------------------------------------------------------ audio

    def _render_track(self, t, n, mult=None):
        """mult: None, or a per-sample rate multiplier (tape stop, reverse/half all)."""
        if t.rate == 1.0 and mult is None:
            t.on_grid = True
            idx = (self.pos - t.anchor + np.arange(n)) % t.length
            return t.buf[idx]
        if t.on_grid:  # leaving the grid: continue from where the loop is now
            t.phase = float((self.pos - t.anchor) % t.length)
            t.on_grid = False
        r = np.full(n, t.rate) if mult is None else t.rate * mult
        ph = t.phase + np.concatenate(([0.0], np.cumsum(r[:-1])))
        i0 = np.floor(ph).astype(np.int64)
        frac = (ph - i0)[:, None]
        a = t.buf[i0 % t.length]
        b = t.buf[(i0 + 1) % t.length]
        t.phase = float((ph[-1] + r[-1]) % t.length)
        return a + (b - a) * frac

    def _rate_mult(self, n):
        """Per-sample speed multiplier from tape stop / reverse all / half speed, or None."""
        tr, target = self.tape_rate, self.tape_target
        if tr == target == 1.0 and not self.rev_all and not self.half_all:
            return None
        k = np.arange(1, n + 1)
        if target < tr:
            r = np.maximum(tr - k / self.beat_len, target)        # stop over one beat
        elif target > tr:
            r = np.minimum(tr + 4 * k / self.beat_len, target)    # spin up in a quarter beat
        else:
            r = np.full(n, tr)
        self.tape_rate = float(r[-1])
        if self.half_all:
            r = r * 0.5
        if self.rev_all:
            r = -r
        return r

    @staticmethod
    def _gains(pan, g):
        a = (pan + 1) * np.pi / 4
        return np.array([np.cos(a), np.sin(a)]) * g * 1.4142

    def process(self, inp, n):
        """Render one block. inp: (n,2) input or None. Returns (n,2) float32."""
        t0 = time.perf_counter()
        while self.events:
            self._handle(self.events.popleft())

        pos = self.pos
        # ---- live sources (these get recorded)
        syn = self.synth.render(n) * self.synth_vol
        live = self.drums.render(n) * self.drum_vol
        live[:, 0] += syn
        live[:, 1] += syn
        ins = None
        if inp is not None and self.input_gain > 0.001:
            ins = inp.astype(np.float64) * self.input_gain
        if self.sample_rec is not None:
            self.sample_rec.append(live + ins if ins is not None else live.copy())
            if len(self.sample_rec) * n >= MAX_REC_SECONDS * self.sr:
                self.finish_sample_rec()
        if self.sampler.buf is not None or self.sampler.chops.v:
            live += self.sampler.render(n)

        if self.running:
            ridx = (pos + np.arange(n)) % self.ring_len
            self.ring[ridx] = live
            if ins is not None:
                self.ring[(ridx - self.input_latency) % self.ring_len] += ins

        # ---- track state transitions (ring now holds data up to pos+n)
        lat = self.input_latency if self.input_gain > 0.001 else 0
        if self.running:
            if self.count_in_end is not None and pos + n > self.count_in_end:
                self.count_in_end = None
            for t in self.tracks:
                if t.state == "armed" and pos + n > t.S:
                    t.state = "rec"
                    self.say(f"T{t.i + 1}: recording")
                if t.state == "rec":
                    if t.fixed_end:
                        t.state = "closing"
                    elif pos - t.S > self.ring_len - 2 * self.sr:
                        self.close_rec(t)
                if t.state == "closing" and pos + n >= t.E + lat:
                    self._finalize(t, n)
            if self.pending_scene is not None and (pos % self.bar == 0 or pos // self.bar != (pos + n) // self.bar):
                self._apply_scene(self.pending_scene)

        # ---- step sequencer hits (before the loops: its kick drives the ducker)
        if self.seq.on and self.running:
            kit = self.kits[self.kit_index][1]
            for off, lane, lvl in self.seq.hits(pos, n, self.beat_len):
                name, sample = kit[lane]
                self.seq_drums.trigger(sample, lvl, off, group=self._drum_group(name))
                if lane == 0:
                    self.ducker.trigger(off)
        duck = self.ducker.block(n)

        # ---- loops + seq lane into a 6-channel bus: dry L/R, delay send L/R, reverb send L/R
        bus = np.zeros((n, 6))
        ramp = (np.arange(1, n + 1) / n)[:, None]
        mult = self._rate_mult(n) if self.running else None
        solo = any(t.solo for t in self.tracks)
        for t in self.tracks:
            if t.mute_at is not None and self.running and self.pos + n > t.mute_at:
                t.muted, t.mute_at = not t.muted, None
            if t.length == 0 or t.state not in ("play", "odub") or not self.running:
                t.level *= 0.8
                t.gains[:] = 0
                continue
            y = self._render_track(t, n, mult)
            if t.start_offset:
                y = y.copy()
                y[: t.start_offset] = 0
                t.start_offset = 0
            if abs(t.filt) >= 0.03:
                if t.filt < 0:
                    y = t.filter.process(y, "lp", max(20000 * 2 ** (10 * t.filt), 60), 1.1, self.sr)
                else:
                    y = t.filter.process(y, "hp", min(20 * 2 ** (10 * t.filt), 12000), 1.1, self.sr)
            y = t.insert.process(y, t.fx, t.fxamt)
            if t.duck > 0.001:
                y = y * (1.0 - t.duck * duck)[:, None]
            target = self._gains(t.pan, t.vol if not t.muted and (t.solo or not solo) else 0.0)
            y = y * (t.gains + (target - t.gains) * ramp)
            t.gains = target
            t.level = max(float(np.abs(y).max()), t.level * 0.85)
            bus[:, 0:2] += y
            bus[:, 2:4] += y * t.dsend
            bus[:, 4:6] += y * t.rsend
            if t.state == "odub":
                widx = (pos - t.anchor + np.arange(n)) % t.length
                t.buf[widx] += live
                if ins is not None:
                    t.buf[(widx - lat) % t.length] += ins

        sq = self.seq
        if self.seq_drums.v:
            y = self.seq_drums.render(n)
            target = self._gains(sq.pan, 0.0 if sq.muted else sq.vol * self.drum_vol)
            y = y * (sq.gains + (target - sq.gains) * ramp)
            sq.gains = target
            sq.level = max(float(np.abs(y).max()), sq.level * 0.85)
            bus[:, 0:2] += y
            bus[:, 2:4] += y * sq.dsend
            bus[:, 4:6] += y * sq.rsend
        else:
            sq.level *= 0.8

        bus = self.perform.process(bus, pos, self.beat_len, self.running)
        loops = bus[:, 0:2]
        dbus = live * self.live_dsend + bus[:, 2:4]
        rbus = live * self.live_rsend + bus[:, 4:6]
        if ins is not None:
            dbus += ins * self.live_dsend
            rbus += ins * self.live_rsend

        # ---- metronome (not recorded, no fx)
        counting = self.count_in_end is not None
        free_rec = any(t.free and t.state == "rec" for t in self.tracks)
        if self.running and not free_rec and (self.metro_level > 0.001 or counting):
            bl = self.beat_len
            k = math.ceil(pos / bl)
            while True:
                b = int(round(k * bl))
                if b >= pos + n:
                    break
                if b >= pos:
                    lvl = max(self.metro_level, 0.6 if counting else 0)
                    down = k % self.beats == 0
                    self.metro.trigger(self.click_hi if down else self.click_lo, lvl, b - pos)
                k += 1
        click = self.metro.render(n)

        # ---- mix
        wet = self.delay.process(dbus, self.beat_len * self.delay_div / self.sr, self.delay_fb)
        wet += self.reverb.process(rbus)
        out = loops + live + wet
        if ins is not None:
            out += ins
        self.pressure_smooth += (self.pressure - self.pressure_smooth) * 0.3
        if self.pressure_smooth > 0.02:
            fc = 18000 * 2 ** (-self.pressure_smooth * 7)
            out = self.master_filter.process(out, "lp", fc, 1.6, self.sr)
        else:
            self.master_filter.reset()
        out = (np.tanh(out * self.master) if self.clip else out * self.master) + click
        self.levels = np.maximum(np.abs(out).max(axis=0), self.levels * 0.85)

        if self.running:
            self.pos += n
            self.clock_ref = (self.pos, time.perf_counter())
        out = out.astype(np.float32)
        if self.bounce:
            self.bounce(out)
        dt = time.perf_counter() - t0
        self.cpu = self.cpu * 0.95 + 0.05 * dt / (n / self.sr)
        return out
