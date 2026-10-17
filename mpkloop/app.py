"""Entry point: audio stream, terminal UI, sessions and bouncing."""
import argparse
import curses
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from fractions import Fraction

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly

from . import dsp
from .demos import make_demos, slug, write_session
from .engine import FX_PADS, Engine
from .export import export
from .clockfollow import ClockFollower
from .midi_io import MPK
from .sampler import to_stereo

HOME = Path.home() / "Music" / "mpkloop"
SESSIONS = HOME / "sessions"
BOUNCES = HOME / "bounces"
EXPORTS = HOME / "exports"
SAMPLES = HOME / "samples"
SAMPLE_EXT = (".wav", ".flac", ".ogg", ".aiff", ".aif")

PAGE_SHORT = ["VOLUME", "PAN", "FILTER", "SPEED", "DELAY", "REVERB", "SOUND", "GLOBAL"]
FX_SHORT = {"Crush": "crs", "Drive": "drv", "Chorus": "cho", "Tape": "tap", "Comb": "cmb"}
VEL_CELL = {0: "·", 1: "▫", 2: "▪", 3: "█"}

HELP = """\
MPK MINI 3  →  MPKLOOP                                       (h or Esc closes this)
───────────────────────────────────────────────────────────────────────────────
PADS, normal mode (CC and PROG CHANGE both off)
  Bank A pads 1-8   loop tracks 1-8.  Tap: record → play → overdub → play
                    Hold ≥0.7 s: clear the track (or cancel an armed record)
  Bank B pads 1-8   drums of the current kit (bottom row pads 1-4, top row 5-8)
                    velocity sensitive; NOTE REPEAT rolls lock to the loop tempo
  Pad pressure      squeeze a pad: low-pass filter sweep over the whole mix
PADS, CC mode (press CC)
  Bank A pads 1-8   mute / unmute track 1-8
  Bank B pads 1-8   undo last overdub on track 1-8 (3 levels)
PADS, PROG CHANGE mode (press PROG CHANGE)
  Bank A pads 1-8   knob page: Volume Pan Filter Speed Delay Reverb Sound Global
  Bank B pads 1-7   sound category: Pads Keys Bass Leads Plucks Bells Organ+
                    tap the same pad again for the next sound in that category
  Bank B pad 8      next drum kit: Classic 808 Electro Lo-Fi Percussion
KNOBS 1-8           parameters of the current page (names show on the MPK screen)
KEYS                play the synth.  OCTAVE buttons work as usual
JOYSTICK            ← → pitch bend ±2   ↑ vibrato + opens the filter
ARP / SUSTAIN       arp follows the loop tempo; sustain pedal holds synth notes
───────────────────────────────────────────────────────────────────────────────
Recording: with a loop playing, recording starts and stops on the next bar line
(a press just after a downbeat counts for that downbeat).  Rec Mode is on the
Global page, knob 2: Free→Tempo (first loop sets the tempo; off while following a clock), Quantize, or a
fixed 1/2/4/8 bars.  Everything you play live is captured; loops never record
each other.  The PADS panel on the right shows what the pads do right now.
───────────────────────────────────────────────────────────────────────────────
COMPUTER KEYS  space start/stop    1-8 tap track    !@#$%^&* mute track
               ←/→ knob page       [ ] sound        k next drum kit
               o open session      s save session   b bounce to WAV on/off
               u sound library (browse, favorite, save tweaks as a new sound)
16 TRACKS      B switches pads/keys 1-8 between tracks 1-8 and 9-16 (knob pages
               follow).  Shift+1-8 mute lands on the next beat.  z+N solo, Z unsolo
               c+N+M copy track N to empty track M   D+N double a loop   H+N halve it
               a+N name a track (shown in the table and in exports)
               C clear all (twice) p stuck notes off q quit
───────────────────────────────────────────────────────────────────────────────
MORE PAGES (← →, after GLOBAL)  Track FX · FX Amount · Duck · Seq · Sampler
  Track FX: one effect per track (Crush Drive Chorus Tape Comb), FX Amount sets
  how much.  Duck: the track dips on every kick (live, sequencer or chop 1).
BANK B PADS  m cycles what bank B pads do in NOTE mode:
  Drums   as before                 Steps   toggle steps 1-8 (Tab: 9-16) of the
  Chops   sampler slices 1-8                selected seq lane (Shift-Tab: lane)
  Scenes  tap: recall at next bar, hold ≥0.7 s: store
  FX      hold: 1-4 beat repeat 1/2 1/4 1/8 1/16 · 5 tape stop · 6 reverse
          7 half speed · 8 crush   (computer: x stutter, X tape stop)
STEP SEQ   T on/off · t edit grid · r record finger drums into steps
           ( mute seq lane · P print the pattern to an empty track
SCENES     n + 1-8 recall (at the next bar) · N + 1-8 store
SAMPLER    i keys play Synth/Sampler · y + 1-8 take a loop · Y sample the
           input + live playing · l load a file from ~/Music/mpkloop/samples
EXPORT     e  stems (WAV per track + mix) and/or MIDI of the recorded notes
"""


class Bouncer:
    def __init__(self, sr):
        self.sr = sr
        self.q = queue.Queue()
        self.path = None
        self.active = False

    def start(self):
        BOUNCES.mkdir(parents=True, exist_ok=True)
        self.path = BOUNCES / f"bounce-{datetime.now():%Y%m%d-%H%M%S}.wav"
        self.active = True
        threading.Thread(target=self._writer, args=(self.path,), daemon=True).start()

    def stop(self):
        self.active = False
        self.q.put(None)

    def push(self, block):
        if self.active:
            self.q.put(block.copy())

    def _writer(self, path):
        with sf.SoundFile(path, "w", self.sr, 2, "PCM_24") as f:
            while True:
                b = self.q.get()
                if b is None:
                    break
                f.write(b)


# ---------------------------------------------------------------- sessions

def save_session(e, name=""):
    name = name.strip() or datetime.now().strftime("%Y-%m-%d %H:%M")
    folder = SESSIONS / f"{datetime.now():%Y%m%d-%H%M%S}-{slug(name)}"
    st = e.state()
    smp = st["sampler"]
    extra = dict(seq=st["seq"], scenes=st["scenes"], kit=st["kit"], patch=st["patch"],
                 sampler={k: v for k, v in smp.items() if k != "buf"} if smp else None)
    write_session(folder, name, e.sr, e.bar, e.tempo, st["tracks"], extra=extra,
                  sampler_buf=smp["buf"] if smp else None)
    e.changed = False
    e.session_name = name
    e.session_demo = False
    return folder


def list_sessions():
    out = []
    if not SESSIONS.exists():
        return out
    for js in SESSIONS.glob("*/session.json"):
        try:
            m = json.loads(js.read_text())
        except Exception:
            continue
        n_tracks = sum(1 for t in m["tracks"] if t.get("file"))
        out.append(dict(path=js.parent, name=m.get("name") or js.parent.name, demo=bool(m.get("demo")),
                        tempo=m.get("tempo", 0), tracks=n_tracks, mtime=js.stat().st_mtime))
    out.sort(key=lambda s: (not s["demo"], -s["mtime"] if not s["demo"] else s["name"]))
    return out


def load_session(e, path):
    meta = json.loads((path / "session.json").read_text())
    if meta["sr"] != e.sr:
        raise ValueError(f"session is {meta['sr']} Hz, engine runs at {e.sr} Hz")
    for td in meta["tracks"]:
        td["buf"] = sf.read(path / td["file"], dtype="float32", always_2d=True)[0] if td["file"] else None
    smp = meta.get("sampler")
    if smp and smp.get("file"):
        smp["buf"] = sf.read(path / smp["file"], dtype="float32", always_2d=True)[0]
    e.post("load", meta)


def list_samples():
    if not SAMPLES.exists():
        return []
    return sorted(p for p in SAMPLES.rglob("*") if p.suffix.lower() in SAMPLE_EXT)


def read_sample(path, sr, max_seconds=60):
    x, fsr = sf.read(path, dtype="float32", always_2d=True)
    x = to_stereo(x[: int(max_seconds * fsr)])
    if fsr != sr:
        f = Fraction(sr, fsr).limit_denominator(1000)
        x = resample_poly(x, f.numerator, f.denominator, axis=0).astype(np.float32)
    return x


# ---------------------------------------------------------------- UI helpers

STATE = {"empty": ("· empty", 0, "tap: record"), "armed": ("◌ ARMED", 3, "tap: cancel"),
         "rec": ("● REC", 1, "tap: close loop"), "closing": ("● REC→", 1, "closing at bar"),
         "play": ("▶ PLAY", 2, "tap: overdub"), "odub": ("◉ ODUB", 4, "tap: stop odub")}
C_RED, C_GREEN, C_YELLOW, C_MAGENTA, C_CYAN = 1, 2, 3, 4, 5


def meter(v, width):
    k = int(min(v, 1.0) * width)
    return "█" * k + "░" * (width - k)


def pad_panel(e, mpk):
    """Title and 8 labels for the pad grid, from the last pad press seen."""
    bank, mode = mpk.pad_bank, mpk.pad_mode
    if mode == "note":
        if bank == "A":
            b = 8 * e.track_bank
            return f"LOOP TRACKS {b + 1}-{b + 8}", [f"LOOP {b + i + 1}" for i in range(8)]
        kit = e.kits[e.kit_index]
        m = e.padb_mode
        if m == "Steps":
            q, h = e.seq, e.seq.half * 8
            return (f"STEPS · {kit[1][q.lane][0]} · {h + 1}-{h + 8}",
                    [f"{h + k + 1:>2} {VEL_CELL[int(q.pattern[q.lane, h + k])]}" if h + k < q.length else "--"
                     for k in range(8)])
        if m == "Chops":
            return f"CHOPS · {e.sampler.name or 'empty'}", [f"CHOP {k + 1}" for k in range(8)]
        if m == "Scenes":
            return "SCENES · tap recall, hold store", [f"SCN {k + 1} {'●' if e.scenes[k] else '·'}" for k in range(8)]
        if m == "FX":
            return "PERFORM FX · hold", [x.replace("Rep 1/16", "Rep1/16").replace("TapeStop", "TapStop")
                                         for x in FX_PADS]
        return f"DRUMS · {kit[0]}", [name for name, _ in kit[1]]
    if mode == "cc":
        if bank == "A":
            return "CC · MUTE TRACK", [f"MUTE {8 * e.track_bank + i + 1}" for i in range(8)]
        return "CC · UNDO TRACK", [f"UNDO {8 * e.track_bank + i + 1}" for i in range(8)]
    if bank == "A":
        return "PROG CHANGE · KNOB PAGE", PAGE_SHORT
    return "PROG CHANGE · SOUNDS", [c.upper() for c in dsp.CATEGORIES] + ["KIT →"]


class UI:
    def __init__(self, stdscr, e, mpk, bouncer, stream_info):
        self.scr, self.e, self.mpk, self.bouncer, self.stream_info = stdscr, e, mpk, bouncer, stream_info
        self.overlay = None          # None / help / open / save / quit
        self.sessions = []
        self.sel = 0
        self.text = ""
        self.confirm_clear = 0.0
        self.busy = ""               # background job description
        self.after_save_quit = False
        self.prefix = None           # (key, time) for two-key commands: n#, N#, y#
        self.cur = [0, 0]            # seq editor cursor: lane, step
        self.samples = []
        self.help_top = 0
        self.H = self.W = 0

    # ------------------------------------------------------------ drawing primitives

    def put(self, y, x, s, attr=0):
        if 0 <= y < self.H and 0 <= x < self.W:
            try:
                self.scr.addnstr(y, x, s, max(self.W - x - 1, 0), attr)
            except curses.error:
                pass

    def box(self, y, x, h, w, title=None, attr=0):
        self.put(y, x, "┌" + "─" * (w - 2) + "┐", attr)
        for r in range(1, h - 1):
            self.put(y + r, x, "│", attr)
            self.put(y + r, x + w - 1, "│", attr)
        self.put(y + h - 1, x, "└" + "─" * (w - 2) + "┘", attr)
        if title:
            self.put(y, x + 2, f" {title} ", attr | curses.A_BOLD)

    def clear_area(self, y, x, h, w):
        for r in range(h):
            self.put(y + r, x, " " * w)

    # ------------------------------------------------------------ input

    def handle_key(self, ch):
        e = self.e
        if ch == -1:
            return True
        if self.overlay:
            return self.handle_overlay_key(ch)
        if self.prefix:
            key, t0 = self.prefix
            self.prefix = None
            if ord("1") <= ch <= ord("8") and time.time() - t0 < 2:
                i = ch - ord("1")
                e.post({"n": "scene_recall", "N": "scene_store", "y": "sample_track"}[key], i)
                return True
        if ch < 256 and chr(ch) in "nNy":
            self.prefix = (chr(ch), time.time())
            return True
        if ch == ord("q"):
            if e.changed and any(t.length for t in e.tracks):
                self.overlay = "quit"
            else:
                return False
        elif ch == ord(" "):
            e.post("transport")
        elif ord("1") <= ch <= ord("8"):
            e.post("tap", e.tb(ch - ord("1")))
        elif ch < 256 and chr(ch) in "!@#$%^&*":
            e.post("mute", e.tb("!@#$%^&*".index(chr(ch))))
        elif ch == ord("B"):
            e.post("track_bank")
        elif ch == curses.KEY_RIGHT:
            e.post("page", e.page + 1)
        elif ch == curses.KEY_LEFT:
            e.post("page", e.page - 1)
        elif ch == ord("]"):
            e.post("patch", e.synth.patch_index + 1)
        elif ch == ord("["):
            e.post("patch", e.synth.patch_index - 1)
        elif ch == ord("k"):
            e.post("kit", 1)
        elif ch == ord("h"):
            self.overlay = "help"
        elif ch == ord("p"):
            e.post("panic")
            e.say("All synth notes stopped")
        elif ch == ord("C"):
            if time.time() - self.confirm_clear < 2:
                e.post("clear_all")
                self.confirm_clear = 0
            else:
                self.confirm_clear = time.time()
                e.say("Clear ALL tracks? Press C again within 2 s")
        elif ch == ord("s"):
            if not any(t.length for t in e.tracks):
                e.say("Nothing to save yet - record a loop first")
            else:
                self.text = "" if e.session_demo else e.session_name
                self.overlay = "save"
        elif ch == ord("o"):
            self.sessions = list_sessions()
            self.sel = 0
            self.overlay = "open"
        elif ch == ord("m"):
            e.post("padb_mode")
        elif ch == ord("t"):
            self.cur = [e.seq.lane, self.cur[1]]
            self.overlay = "seq"
        elif ch == ord("T"):
            e.post("seq_toggle")
        elif ch == ord("r"):
            e.post("seq_rec")
        elif ch == ord("("):
            e.post("seq_mute")
        elif ch == 9:
            e.post("seq_half")
        elif ch == curses.KEY_BTAB:
            e.post("seq_lane", e.seq.lane + 1)
        elif ch == ord("P"):
            e.post("seq_print")
        elif ch == ord("x"):
            e.post("stutter_cycle")
        elif ch == ord("X"):
            e.post("tapestop", None)
            e.say("Tape stop" if e.tape_target == 1.0 else "Tape start")
        elif ch == ord("i"):
            e.post("key_inst")
        elif ch == ord("Y"):
            e.post("sample_rec")
        elif ch == ord("l"):
            self.samples = list_samples()
            self.sel = 0
            self.overlay = "samples"
        elif ch == ord("e"):
            if self.busy:
                e.say("Busy: " + self.busy)
            elif not any(t.length for t in e.tracks) and not e.seq.on:
                e.say("Nothing to export yet")
            else:
                self.overlay = "export"
        elif ch == ord("b"):
            if self.bouncer.active:
                self.bouncer.stop()
                e.say(f"Bounce saved: {self.bouncer.path.name}")
            else:
                self.bouncer.start()
                e.say(f"Bouncing everything you hear to {self.bouncer.path.name}")
        return True

    def handle_overlay_key(self, ch):
        e = self.e
        esc = ch in (27, ord("q")) and self.overlay != "save"
        if self.overlay == "help":
            if esc or ch == ord("h"):
                self.overlay = None
            elif ch in (curses.KEY_DOWN, ord("j"), ord(" ")):
                self.help_top += 1 if ch != ord(" ") else 10
            elif ch in (curses.KEY_UP, ord("k")):
                self.help_top = max(self.help_top - 1, 0)
        elif self.overlay == "seq":
            q = e.seq
            lane, col = self.cur
            if esc or ch == ord("t"):
                self.overlay = None
            elif ch in (curses.KEY_UP, curses.KEY_DOWN):
                self.cur[0] = (lane + (1 if ch == curses.KEY_DOWN else -1)) % 8
                e.post("seq_lane", self.cur[0], True)
            elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
                self.cur[1] = (col + (1 if ch == curses.KEY_RIGHT else -1)) % q.length
            elif ch in (ord(" "), 10, 13, curses.KEY_ENTER):
                e.post("seq_set", lane, col, 0 if q.pattern[lane, col] else 2)
            elif ch == ord("v"):
                e.post("seq_set", lane, col, int(q.pattern[lane, col]) % 3 + 1)
            elif ch == ord("c"):
                e.post("seq_clear_lane", lane)
            elif ch == ord("T"):
                e.post("seq_toggle")
            elif ch == ord("r"):
                e.post("seq_rec")
            elif ch == ord("k"):
                e.post("kit", 1)
        elif self.overlay == "samples":
            if esc or ch == ord("l"):
                self.overlay = None
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.sel = min(self.sel + 1, max(len(self.samples) - 1, 0))
            elif ch in (curses.KEY_UP, ord("k")):
                self.sel = max(self.sel - 1, 0)
            elif ch in (10, 13, curses.KEY_ENTER) and self.samples:
                p = self.samples[self.sel]
                try:
                    e.post("sample_set", read_sample(p, e.sr), p.stem)
                except Exception as ex:
                    e.say(f"Could not load {p.name}: {ex}")
                self.overlay = None
        elif self.overlay == "export":
            if esc or ch == ord("e"):
                self.overlay = None
            elif ch in (ord("1"), ord("2"), ord("3")):
                self.overlay = None
                self.run_export(stems=ch != ord("2"), midi=ch != ord("1"))
        elif self.overlay == "quit":
            if ch == ord("q"):
                return False
            if ch == ord("s"):
                self.text, self.overlay = "", "save"
                self.after_save_quit = True
            elif ch == 27:
                self.overlay = None
        elif self.overlay == "open":
            if esc or ch == ord("o"):
                self.overlay = None
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.sel = min(self.sel + 1, max(len(self.sessions) - 1, 0))
            elif ch in (curses.KEY_UP, ord("k")):
                self.sel = max(self.sel - 1, 0)
            elif ch == ord("g") and not self.busy:
                self.make_demos()
            elif ch in (10, 13, curses.KEY_ENTER) and self.sessions:
                s = self.sessions[self.sel]
                try:
                    load_session(e, s["path"])
                except Exception as ex:
                    e.say(f"Load failed: {ex}")
                self.overlay = None
        elif self.overlay == "save":
            if ch == 27:
                self.overlay = None
                self.after_save_quit = False
            elif ch in (10, 13, curses.KEY_ENTER):
                try:
                    folder = save_session(e, self.text)
                    e.say(f"Saved '{e.session_name}' to {folder.name}")
                except Exception as ex:
                    e.say(f"Save failed: {ex}")
                self.overlay = None
                if getattr(self, "after_save_quit", False):
                    return False
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                self.text = self.text[:-1]
            elif 32 <= ch < 127 and len(self.text) < 40:
                self.text += chr(ch)
        return True

    def run_export(self, stems, midi):
        self.busy = "Exporting…"

        def job():
            try:
                folder, summary = export(self.e, stems, midi, EXPORTS,
                                         progress=lambda s: setattr(self, "busy", f"Exporting {s}…"))
                self.e.say(f"Exported to {folder} ({summary})")
            except Exception as ex:
                self.e.say(f"Export failed: {ex}")
            self.busy = ""
        threading.Thread(target=job, daemon=True).start()

    def make_demos(self):
        self.busy = "Rendering demo loops (about half a minute)…"

        def job():
            try:
                make_demos(SESSIONS, self.e.sr, progress=lambda n: setattr(self, "busy", f"Rendering demo: {n}…"))
                self.e.say("Demo sessions ready")
            except Exception as ex:
                self.e.say(f"Demo render failed: {ex}")
            self.busy = ""
            self.sessions = list_sessions()
        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------ main screen

    def draw(self):
        e, mpk = self.e, self.mpk
        self.scr.erase()
        self.H, self.W = self.scr.getmaxyx()
        H, W = self.H, self.W
        if H < 23 or W < 72:
            self.put(0, 0, f"Terminal too small: {W}x{H}, need at least 72x23", curses.A_BOLD)
            self.scr.refresh()
            return
        wide = W >= 100

        # header
        bar_no = e.pos // e.bar + 1 if e.running else 0
        beat = int((e.pos % e.bar) / e.beat_len) + 1 if e.running else 0
        if e.count_in_end is not None:
            tstate, tcol = "◌ COUNT-IN", C_YELLOW
        elif e.running:
            tstate, tcol = "▶ PLAYING", C_GREEN
        else:
            tstate, tcol = "■ STOPPED", 0
        self.put(0, 0, " MPKLOOP ", curses.A_REVERSE | curses.A_BOLD)
        self.put(0, 10, f"{tstate}", curses.color_pair(tcol) | curses.A_BOLD)
        beats_vis = " ".join("●" if (i + 1) == beat else "○" for i in range(e.beats))
        clk = f" {e.clock_label}" if e.clock_label else ""
        self.put(0, 22, f"{e.tempo:5.1f} BPM{clk}  bar {bar_no:>2}  {beats_vis}", curses.A_BOLD)
        self.put(0, 50, f"rec mode: {e.rec_mode}", curses.color_pair(C_CYAN))
        if e.session_name:
            self.put(0, 74, f"session: {e.session_name}{'*' if e.changed else ''}", curses.A_DIM)
        if self.bouncer.active:
            self.put(0, W - 12, "● BOUNCING", curses.color_pair(C_RED) | curses.A_BOLD)
        dev = mpk.connected_name.split(":")[0] if mpk.connected_name else "NO MPK FOUND - computer keys only"
        knobs = "knobs: relative" if mpk.knob_rel else "knobs: absolute"
        self.put(1, 1, f"{dev} · {knobs} · audio {self.stream_info} · cpu {e.cpu:3.0%} · xruns {e.xruns}",
                 curses.A_DIM)
        if self.busy and self.overlay != "open":
            self.put(1, max(W - len(self.busy) - 2, 60), self.busy, curses.color_pair(C_YELLOW) | curses.A_BOLD)

        # tracks
        y0 = 3
        self.put(y0, 1, "TRACKS", curses.A_BOLD)
        self.put(y0, 9, "#  state    len  position              vol   fx    next", curses.A_DIM)
        for r, (i, t) in enumerate(list(enumerate(e.tracks))[8 * e.track_bank:8 * e.track_bank + 8]):  # one bank
            y = y0 + 1 + r
            label, col, hint = STATE[t.state]
            attr = curses.color_pair(col) | (curses.A_BOLD if t.state != "empty" else curses.A_DIM)
            if t.muted and t.state in ("play", "odub"):
                label, attr, hint = "▷ MUTED", curses.A_DIM, "CC pad: unmute"
            self.put(y, 0, f"{i + 1:>2}", curses.A_BOLD)
            self.put(y, 3, label, attr)
            if t.length:
                bars = t.length / e.bar
                self.put(y, 12, f"{bars:>3.0f}b" if abs(bars - round(bars)) < 0.01 else f"{bars:4.1f}")
                frac = ((e.pos - t.anchor) % t.length) / t.length if t.rate == 1.0 else t.phase / t.length
                w = 20
                k = int(frac * w)
                self.put(y, 17, "▕" + "█" * k + "▌" + " " * (w - k - 1) + "▏", curses.color_pair(col))
                lvl = "▂▃▄▅▆▇█"[min(int(t.level * 7), 6)] if t.level > 0.02 and not t.muted else " "
                self.put(y, 39, lvl, curses.color_pair(C_GREEN if t.level < 0.9 else C_RED))
            elif t.state == "armed" and t.S is not None:
                beats_left = max(t.S - e.pos, 0) / e.beat_len
                self.put(y, 17, f"starts in {beats_left:3.1f} beats", curses.color_pair(C_YELLOW))
            elif t.state in ("rec", "closing") and t.S is not None:
                self.put(y, 17, f"{max(e.pos - t.S, 0) / e.bar:5.2f} bars…", curses.color_pair(C_RED))
            if t.state != "empty":
                self.put(y, 41, f"{e.pages[0][1][i].text():>5}")
                tags = []
                if t.fx != "Off":
                    tags.append(FX_SHORT[t.fx])
                if t.duck > 0.001:
                    tags.append("d")
                if t.rate != 1.0:
                    tags.append(e.pages[3][1][i].text())
                if abs(t.filt) >= 0.03:
                    tags.append(e.pages[2][1][i].text())
                if t.undo:
                    tags.append(f"u{len(t.undo)}")
                self.put(y, 47, " ".join(tags)[:5], curses.A_DIM)
            self.put(y, 53, hint, curses.A_DIM if t.state in ("empty", "closing") else curses.color_pair(col))

        # step sequencer lane
        y = y0 + 9
        q = e.seq
        if q.on and q.muted:
            label, col, hint = "▷ MUTED", 0, "( unmute"
        elif q.on:
            label, col, hint = "▶ SEQ", C_CYAN, "t edit · T stop"
        else:
            label, col, hint = "· seq", 0, "T start · t edit"
        self.put(y, 1, "S", curses.A_BOLD)
        self.put(y, 3, label, curses.color_pair(col) | (curses.A_BOLD if q.on else curses.A_DIM))
        self.put(y, 12, f"{q.length:>3}s")
        strip = q.strip()
        self.put(y, 17, "▕" + strip + "▏", curses.color_pair(C_CYAN) if q.on else curses.A_DIM)
        if q.on and e.running:
            st = int(e.pos // (e.beat_len / 4)) % q.length
            self.put(y, 18 + st, strip[st], curses.A_REVERSE)
        lvl = "▂▃▄▅▆▇█"[min(int(q.level * 7), 6)] if q.level > 0.02 else " "
        self.put(y, 39, lvl, curses.color_pair(C_GREEN))
        self.put(y, 41, f"{e.pages[11][1][4].text():>5}")
        self.put(y, 47, ("rec " if q.rec else "") + (f"sw{50 + 25 * q.swing:.0f}" if q.swing > 0.01 else ""),
                 curses.color_pair(C_RED) if q.rec else curses.A_DIM)
        self.put(y, 53, hint, curses.A_DIM)

        # first steps / status line under the tracks
        y = y0 + 10
        if not any(t.state != "empty" for t in e.tracks) and not q.on:
            self.put(y, 1, "Start: tap bank A pad 1 (or key 1) and play. "
                           "Or press o to open a demo session, h for help.", curses.color_pair(C_YELLOW))
        else:
            parts = [f"pad B: {e.padb_mode}", f"keys: {e.key_inst}" + (
                f" ({e.sampler.name})" if e.key_inst == "Sampler" and e.sampler.name else "")]
            if e.scene is not None or e.pending_scene is not None:
                sc = f"scene {e.scene + 1}" if e.scene is not None else "scene -"
                parts.append(sc + (f" → {e.pending_scene + 1} at bar" if e.pending_scene is not None else ""))
            fx = []
            if e.perform.div is not None:
                fx.append(f"repeat 1/{int(4 / e.perform.div)}")
            if e.tape_target < 1.0 or e.tape_rate < 1.0:
                fx.append("tape stop")
            fx += [n for n, on in (("reverse", e.rev_all), ("half", e.half_all), ("crush", e.perform.crush)) if on]
            if fx:
                parts.append("FX: " + " ".join(fx))
            self.put(y, 1, " · ".join(parts), curses.A_DIM)
            if e.sample_rec is not None:
                self.put(y, 62, "● SAMPLING (Y stops)", curses.color_pair(C_RED) | curses.A_BOLD)
            elif self.prefix:
                self.put(y, 62, {"n": "scene 1-8?", "N": "store scene 1-8?", "y": "sample track 1-8?"}[self.prefix[0]],
                         curses.color_pair(C_YELLOW) | curses.A_BOLD)

        # pad panel
        if wide:
            px = 70
            title, labels = pad_panel(e, mpk)
            self.put(y0, px, "PADS", curses.A_BOLD)
            bank_col = C_RED if mpk.pad_bank == "A" else C_GREEN
            self.put(y0, px + 5, f"bank {mpk.pad_bank}", curses.color_pair(bank_col) | curses.A_BOLD)
            self.put(y0, px + 12, title[:W - px - 13], curses.A_DIM)
            cw = 7
            for row, pads in enumerate(((4, 5, 6, 7), (0, 1, 2, 3))):
                yy = y0 + 1 + row * 3
                self.put(yy, px, "┌" + "┬".join(["─" * cw] * 4) + "┐" if row == 0 else "├" + "┼".join(["─" * cw] * 4) + "┤")
                for c, p in enumerate(pads):
                    x = px + 1 + c * (cw + 1)
                    attr = 0
                    if mpk.pad_mode == "note" and mpk.pad_bank == "A":
                        attr = curses.color_pair(STATE[e.tracks[p].state][1]) | (curses.A_BOLD if e.tracks[p].state != "empty" else curses.A_DIM)
                    elif mpk.pad_mode == "pc" and mpk.pad_bank == "A" and p == e.page:
                        attr = curses.A_REVERSE
                    elif mpk.pad_mode == "cc" and mpk.pad_bank == "A" and e.tracks[p].muted:
                        attr = curses.A_REVERSE
                    elif mpk.pad_mode == "note" and mpk.pad_bank == "B":
                        h = e.seq.half * 8 + p
                        if (e.padb_mode == "Steps" and h < e.seq.length and e.seq.pattern[e.seq.lane, h]) or \
                                (e.padb_mode == "Scenes" and e.scene == p):
                            attr = curses.A_REVERSE
                    self.put(yy + 1, x, f"{p + 1}".ljust(cw), curses.A_DIM)
                    self.put(yy + 2, x, labels[p][:cw].center(cw), attr)
                for c in range(5):
                    self.put(yy + 1, px + c * (cw + 1), "│")
                    self.put(yy + 2, px + c * (cw + 1), "│")
            self.put(y0 + 7, px, "└" + "┴".join(["─" * cw] * 4) + "┘")
            self.put(y0 + 8, px, "shows the last pad press seen", curses.A_DIM)

        # knobs
        y = y0 + 12
        title, params = e.page_title(), e.visible_params()
        self.put(y, 1, f" KNOBS: {title} ", curses.A_REVERSE | curses.A_BOLD)
        self.put(y, 12 + len(title), "←/→ or PROG CHANGE + bank A pad" if e.page < 8 else "←/→ (page "
                 f"{e.page + 1}/{len(e.pages)}, computer only)", curses.A_DIM)
        per_row = 4 if W >= 98 else 2
        for k, p in enumerate(params):
            r, c = divmod(k, per_row)
            pick = "" if mpk.knob_rel or e.pickup[k] else "~"
            self.put(y + 1 + r, 1 + c * 24, f"K{k + 1} {p.label[:11]:<11} {pick}{p.text():>7}",
                     curses.A_BOLD if not pick else curses.A_DIM)
        y += 1 + (8 + per_row - 1) // per_row

        # sound + output
        kit = e.kits[e.kit_index][0]
        self.put(y, 1, f"SOUND {e.synth.patch['cat']}: {e.synth.patch['name']}", curses.A_BOLD)
        self.put(y, 36, f"KIT {kit}", curses.A_BOLD)
        if e.key_inst == "Sampler":
            self.put(y, 1, f"SAMPLER: {e.sampler.name or 'empty'}"[:34].ljust(34), curses.A_BOLD | curses.color_pair(C_MAGENTA))
        self.put(y, 52, f"voices {len(e.synth.voices):>2}  bend {e.synth.bend:+.1f}  mod {e.synth.mod:.1f}"
                        f"  {'SUS ' if e.synth.sustain else ''}{'press ' + format(e.pressure, '.1f') if e.pressure > 0.02 else ''}",
                 curses.A_DIM)
        lv = max(e.levels)
        self.put(y + 1, 1, "OUT " + meter(lv, 30), curses.color_pair(C_GREEN if lv < 0.95 else C_RED))
        if e.input_gain > 0.001:
            self.put(y + 1, 36, f"INPUT on ({e.input_gain:.2f}) - use headphones", curses.color_pair(C_YELLOW))
        else:
            self.put(y + 1, 36, "input off (Global page, knob 4)", curses.A_DIM)
        self.put(y + 1, 70, f"midi: {mpk.last_event[:40]}", curses.A_DIM)

        # log
        y += 3
        lines = max(0, H - 1 - y)
        if lines:
            self.put(y - 1, 1, "LOG", curses.A_BOLD)
            for j, (t, msg) in enumerate(list(e.log)[-lines:]):
                age = time.time() - t
                attr = curses.color_pair(C_YELLOW) | curses.A_BOLD if age < 3 else (0 if age < 30 else curses.A_DIM)
                self.put(y + j, 1, f"{datetime.fromtimestamp(t):%H:%M:%S}  {msg}", attr)

        # footer
        self.put(H - 1, 0, (" space play · 1-8 tap · ←/→ page · m pad B · t/T seq · n/N scene · x/X fx"
                            " · i/y/Y/l sampler · e export · o open · s save · h help · q quit").ljust(W - 1),
                 curses.A_REVERSE)

        if self.overlay:
            self.draw_overlay()
        self.scr.refresh()

    # ------------------------------------------------------------ overlays

    def draw_overlay(self):
        H, W = self.H, self.W
        if self.overlay == "help":
            lines = HELP.splitlines()
            h, w = min(len(lines) + 2, H), min(max(len(l) for l in lines) + 4, W)
            y, x = max((H - h) // 2, 0), max((W - w) // 2, 0)
            self.help_top = min(self.help_top, max(len(lines) - (h - 2), 0))
            self.clear_area(y, x, h, w)
            self.box(y, x, h, w, "↑/↓ scroll" if len(lines) > h - 2 else None)
            for i, l in enumerate(lines[self.help_top: self.help_top + h - 2]):
                self.put(y + 1 + i, x + 2, l)
            return
        if self.overlay == "seq":
            self.draw_seq()
            return
        if self.overlay == "export":
            h, w = 9, 62
            y, x = (H - h) // 2, (W - w) // 2
            self.clear_area(y, x, h, w)
            self.box(y, x, h, w, "Export", curses.color_pair(C_GREEN))
            self.put(y + 2, x + 3, "1  stems: one WAV per audible track + seq + mix", curses.A_BOLD)
            self.put(y + 3, x + 3, "2  MIDI: notes you played into each loop", curses.A_BOLD)
            self.put(y + 4, x + 3, "3  both", curses.A_BOLD)
            self.put(y + 6, x + 3, f"→ {EXPORTS}/…   Esc cancel"[: w - 6], curses.A_DIM)
            return
        if self.overlay == "samples":
            rows = max(len(self.samples), 1)
            h, w = min(rows + 6, H - 2), min(70, W - 2)
            y, x = (H - h) // 2, (W - w) // 2
            self.clear_area(y, x, h, w)
            self.box(y, x, h, w, "Load sample", curses.color_pair(C_MAGENTA))
            if not self.samples:
                self.put(y + 2, x + 3, f"No audio files in {SAMPLES}"[: w - 6])
                self.put(y + 3, x + 3, "Put WAV/FLAC/OGG files there and press l again."[: w - 6], curses.A_DIM)
            vis = h - 5
            top = max(0, min(self.sel - vis + 1, len(self.samples) - vis))
            for j, p in enumerate(self.samples[top: top + vis]):
                i = top + j
                name = str(p.relative_to(SAMPLES))
                attr = curses.A_REVERSE if i == self.sel else 0
                self.put(y + 2 + j, x + 1, (("▸ " if i == self.sel else "  ") + name)[: w - 3].ljust(w - 3), attr)
            self.put(y + h - 2, x + 3, "↑/↓ choose   Enter load into the sampler   Esc close"[: w - 6], curses.A_DIM)
            return
        if self.overlay == "quit":
            h, w = 7, 56
            y, x = (H - h) // 2, (W - w) // 2
            self.clear_area(y, x, h, w)
            self.box(y, x, h, w, "Quit?", curses.color_pair(C_YELLOW))
            self.put(y + 2, x + 3, "You have loops that are not saved.", curses.A_BOLD)
            self.put(y + 4, x + 3, "s  save first      q  quit anyway      Esc  back")
            return
        if self.overlay == "save":
            h, w = 7, 60
            y, x = (H - h) // 2, (W - w) // 2
            self.clear_area(y, x, h, w)
            self.box(y, x, h, w, "Save session", curses.color_pair(C_GREEN))
            self.put(y + 2, x + 3, "Name:  " + self.text + "▏", curses.A_BOLD)
            self.put(y + 4, x + 3, "Enter  save        Esc  cancel        (empty name = date)", curses.A_DIM)
            return
        if self.overlay == "open":
            rows = max(len(self.sessions), 1)
            h = min(rows + 7, H - 2)
            w = min(78, W - 2)
            y, x = (H - h) // 2, (W - w) // 2
            self.clear_area(y, x, h, w)
            self.box(y, x, h, w, "Open session", curses.color_pair(C_CYAN))
            self.put(y + 1, x + 3, "name".ljust(28) + "tempo   tracks   type / date", curses.A_DIM)
            if not self.sessions:
                self.put(y + 3, x + 3, "No sessions yet.  Press g to render the demo loops, or record and press s.")
            vis = h - 6
            top = max(0, min(self.sel - vis + 1, len(self.sessions) - vis))
            for j, s in enumerate(self.sessions[top: top + vis]):
                i = top + j
                kind = "demo" if s["demo"] else datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
                line = f"{s['name'][:27]:<28}{s['tempo']:5.0f}   {s['tracks']:>3}      {kind}"
                attr = curses.A_REVERSE if i == self.sel else 0
                self.put(y + 2 + j, x + 1, ("▸ " if i == self.sel else "  ") + line.ljust(w - 4), attr)
            foot = self.busy or "↑/↓ choose   Enter open (plays right away)   g render demos   Esc close"
            self.put(y + h - 2, x + 3, foot[: w - 6], curses.color_pair(C_YELLOW) if self.busy else curses.A_DIM)

    def draw_seq(self):
        """8 x 16 step grid editor."""
        e, q = self.e, self.e.seq
        H, W = self.H, self.W
        h, w = 15, 66
        y, x = (H - h) // 2, (W - w) // 2
        self.clear_area(y, x, h, w)
        run = ("▶ running" if q.on else "■ off") + ("  ● rec" if q.rec else "")
        self.box(y, x, h, w, f"Step sequencer · {e.kits[e.kit_index][0]} · {run}", curses.color_pair(C_CYAN))
        self.put(y + 1, x + 14, " ".join(f"{c + 1:<2}" if c % 4 == 0 else "  " for c in range(16))[:48], curses.A_DIM)
        play = int(e.pos // (e.beat_len / 4)) % q.length if q.on and e.running else -1
        for lane in range(8):
            yy = y + 2 + lane
            name = e.kits[e.kit_index][1][lane][0]
            self.put(yy, x + 2, f"{name[:10]:<10}", curses.A_BOLD if lane == self.cur[0] else curses.A_DIM)
            for c in range(16):
                cx = x + 14 + c * 3
                if c >= q.length:
                    self.put(yy, cx, "  ", curses.A_DIM)
                    continue
                v = int(q.pattern[lane, c])
                attr = curses.color_pair(C_CYAN) | curses.A_BOLD if v else (curses.A_DIM if c % 4 else 0)
                if c == play:
                    attr = curses.color_pair(C_YELLOW) | curses.A_BOLD
                if [lane, c] == self.cur:
                    attr |= curses.A_REVERSE
                self.put(yy, cx, f" {VEL_CELL[v]}", attr)
        self.put(y + 11, x + 2, f"swing {50 + 25 * q.swing:.0f}%   length {q.length}   vol {e.pages[11][1][4].text()}"
                                "   (knobs: SEQ page)", curses.A_DIM)
        self.put(y + 12, x + 2, "arrows move · space toggle · v soft/normal/accent · c clear", curses.A_DIM)
        self.put(y + 13, x + 2, "T run/stop · r record pads · k kit · Esc close", curses.A_DIM)


def run_ui(stdscr, e, mpk, bouncer, stream_info):
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()
    for i, c in enumerate((curses.COLOR_RED, curses.COLOR_GREEN, curses.COLOR_YELLOW,
                           curses.COLOR_MAGENTA, curses.COLOR_CYAN), start=1):
        curses.init_pair(i, c, -1)
    ui = UI(stdscr, e, mpk, bouncer, stream_info)
    while True:
        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            break
        if not ui.handle_key(ch):
            break
        ui.draw()
        time.sleep(0.04)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(prog="mpkloop", description="8-track looper for the Akai MPK mini 3")
    ap.add_argument("--block", type=int, default=512, help="audio block size (256 = lower latency, 1024 = safer)")
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--audio", default=None, help="audio device name/index (see --list)")
    ap.add_argument("--no-input", action="store_true", help="don't open an audio input")
    ap.add_argument("--midi", default="MPK", help="MIDI port name, or \"in,out\" when they differ (Switchbox on Windows: mpkloop,mpkloop-ret)")
    ap.add_argument("--no-device-sync", action="store_true",
                    help="don't write the page/knob names to the MPK (knobs stay absolute)")
    ap.add_argument("--clock", choices=["follow", "master"], default=None,
                    help="follow: lock to the incoming MIDI clock/start/stop (Switchbox) and send none; "
                         "master: tempo from the first loop, send clock to the MPK "
                         "(default: follow when --midi names mpkloop, else master)")
    ap.add_argument("--clock-offset", type=float, default=0.0, metavar="MS",
                    help="follow mode: shift the loops against the clock (+ = play earlier) to trim audio latency")
    ap.add_argument("--no-ext-clock", action="store_true", help="leave the MPK arpeggiator on its own clock")
    ap.add_argument("--list", action="store_true", help="list audio and MIDI devices")
    ap.add_argument("--monitor", action="store_true", help="print incoming MIDI and exit with Ctrl-C")
    ap.add_argument("--make-demos", action="store_true", help="(re)render the demo sessions and exit")
    ap.add_argument("--classic", action="store_true", help="use the classic curses screen instead of the Textual UI")
    a = ap.parse_args()

    if a.list:
        import mido
        print(sd.query_devices())
        print("\nMIDI in:", mido.get_input_names())
        return
    if a.make_demos:
        for p in make_demos(SESSIONS, a.sr, progress=lambda n: print("rendering", n, flush=True)):
            print("wrote", p)
        return
    if a.block > 1024:
        sys.exit("--block must be ≤ 1024")

    # hand the GIL to the audio thread quickly: the default 5 ms is half an audio block
    sys.setswitchinterval(0.0005)
    e = Engine(a.sr, a.block)

    if a.monitor:
        mpk = MPK(e, a.midi, device_sync=False, ext_clock=False, send_clock=False, monitor=lambda m: print(m, flush=True))
        if not mpk.connected_name:
            sys.exit("No MPK found")
        print(f"Listening on {mpk.connected_name}, preset {mpk.map}\nCtrl-C to quit")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            mpk.close()
        return

    bouncer = Bouncer(a.sr)
    e.bounce = bouncer.push

    def callback(indata, outdata, frames, t, status):
        if status:
            e.xruns += 1
        outdata[:] = e.process(indata if indata is not None else None, frames)

    def out_callback(outdata, frames, t, status):
        if status:
            e.xruns += 1
        outdata[:] = e.process(None, frames)

    stream = None
    if not a.no_input:
        try:
            stream = sd.Stream(samplerate=a.sr, blocksize=a.block, channels=2, dtype="float32",
                               device=a.audio, callback=callback, latency="low")
        except Exception as ex:
            print(f"Duplex audio failed ({ex}); output only", file=sys.stderr)
    if stream is None:
        stream = sd.OutputStream(samplerate=a.sr, blocksize=a.block, channels=2, dtype="float32",
                                 device=a.audio, callback=out_callback, latency="low")
        lat = (0.0, stream.latency)
    else:
        lat = stream.latency
    e.input_latency = int(round((lat[0] + lat[1]) * a.sr))
    info = f"{a.sr // 1000}k/{a.block} ({1000 * a.block / a.sr:.0f} ms)"

    follow = (a.clock or ("follow" if "mpkloop" in a.midi.lower() else "master")) == "follow"
    if follow:
        e.follower = ClockFollower(e.post)
        e.ext_ahead = a.clock_offset / 1000.0
    mpk = MPK(e, a.midi, device_sync=not a.no_device_sync, ext_clock=not a.no_ext_clock, send_clock=not follow)
    if not mpk.connected_name:
        e.say("MPK mini not found - use the computer keys, or plug it in and restart")
    else:
        e.say(f"Connected to {mpk.connected_name.split(':')[0]} - press h for help, o for demo sessions")

    os.environ.setdefault("ESCDELAY", "25")   # Esc closes overlays without a 1 s wait
    try:
        if a.classic:
            with stream:
                curses.wrapper(run_ui, e, mpk, bouncer, info)
        else:
            from .tui import run_tui
            run_tui(e, mpk, bouncer, info, stream)   # the UI starts the stream once it has drawn
            stream.close()
    finally:
        if bouncer.active:
            bouncer.stop()
            time.sleep(0.2)
            print(f"Bounce written: {bouncer.path}")
        mpk.close()


if __name__ == "__main__":
    main()
