"""Demo sessions: loops rendered offline through the engine's own synth and kits,
saved as ordinary sessions so they show up in the session picker."""
import json
from pathlib import Path

import soundfile as sf

from . import dsp
from .engine import Engine

# bank-B pad order inside a kit
D = dict(kick=0, snare=1, hat=2, ohat=3, clap=4, tom=5, rim=6, bell=7)
NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def n(name):
    """'C3' -> MIDI note (C3 = 48)."""
    return 12 * (int(name[-1]) + 1) + NOTE[name[:-1]]


def grid(pad, pattern, vel=100, accent=118):
    """16th-note pattern string: 'x' hit, 'X' accent, '.' rest. One char = one 16th."""
    return [(k / 4.0, "drum", pad, accent if c == "X" else vel) for k, c in enumerate(pattern) if c in "xX"]


def notes(seq, vel=100):
    """seq: (beat, note_name(s), duration_beats[, vel])"""
    out = []
    for item in seq:
        beat, names, dur = item[:3]
        v = item[3] if len(item) > 3 else vel
        for nm in ([names] if isinstance(names, str) else names):
            out.append((beat, "note_on", n(nm), v))
            out.append((beat + dur - 0.02, "note_off", n(nm)))
    return out


def render_track(sr, bpm, bars, events, patch=None, kit="Classic", block=128):
    """Record one loop of `bars` bars by feeding timed events into a fresh engine."""
    e = Engine(sr, block)
    e.set_tempo(bpm)
    e.count_in = False
    e.metro_level = 0.0
    e.live_rsend = e.live_dsend = 0.0
    e.rec_mode = "1 bar" if bars == 1 else f"{bars} bars"
    e.kit_index = e.lib.kit_index_of(kit)
    if patch:
        e.synth.set_patch(e.lib.index_of(patch))
    e.post("tap", 0)
    evs = sorted(events, key=lambda x: x[0])
    i = 0
    t = e.tracks[0]
    guard = 0
    while t.state != "play":
        end = e.pos + block
        while i < len(evs) and int(evs[i][0] * e.beat_len) < end:
            e.post(*evs[i][1:])
            i += 1
        e.process(None, block)
        guard += 1
        if guard > sr * 60 // block:
            raise RuntimeError("render did not finish")
    return t.buf, t.notes


def _track(name, bars, events, patch=None, kit="Classic", vol=0.8, pan=0.0, dsend=0.0, rsend=0.15):
    return dict(name=name, bars=bars, events=events, patch=patch, kit=kit, vol=vol, pan=pan, dsend=dsend, rsend=rsend)


def lofi_chill():
    return dict(name="Lo-Fi Chill", bpm=84, tracks=[
        _track("Beat", 2, grid(D["kick"], "x.....x...x.....x.....x.......x.", 110)
               + grid(D["snare"], "....x.......x.......x......x.x..", 95)
               + grid(D["hat"], "x.x.x.x.x.x.x.x.x.x.x.x.x.x.x.xx", 70, 90)
               + grid(D["ohat"], "..............x...............x.", 60), kit="Lo-Fi", vol=0.9),
        _track("Bass", 4, notes([(0, "D1", 1.5), (2, "D1", 0.5), (3, "F1", 0.75),
                                 (4, "G1", 1.5), (6, "G1", 0.5), (7, "B1", 0.75),
                                 (8, "C2", 1.5), (10, "C2", 0.5), (11, "E1", 0.75),
                                 (12, "A1", 1.5), (14, "A1", 0.5), (15, "G1", 0.75)], 100),
               patch="Sub Bass", vol=0.85),
        _track("Keys", 4, notes([(0, ("D3", "F3", "A3", "C4"), 3.5, 80), (4, ("G2", "B2", "D3", "F3"), 3.5, 76),
                                 (8, ("C3", "E3", "G3", "B3"), 3.5, 80), (12, ("A2", "C3", "E3", "G3"), 3.5, 76)]),
               patch="E-Piano", vol=0.7, pan=-0.2, rsend=0.3),
        _track("Melody", 4, notes([(0.5, "A4", 1.0, 70), (2, "C5", 0.5, 64), (2.5, "A4", 1.0, 60),
                                   (6, "D5", 1.5, 72), (8.5, "E5", 1.0, 70), (10, "G4", 0.5, 60),
                                   (11, "B4", 2.0, 66), (14, "A4", 1.5, 62)]),
               patch="Vibes", vol=0.6, pan=0.3, dsend=0.35, rsend=0.45),
    ])


def house_groove():
    arp = []
    for bar, chord in enumerate([("A3", "C4", "E4", "G4"), ("F3", "A3", "C4", "E4"),
                                 ("C3", "E3", "G3", "B3"), ("G3", "B3", "D4", "F4")]):
        for k in range(16):
            arp.append((bar * 4 + k / 4.0, chord[k % 4] if k % 8 < 4 else chord[3 - k % 4], 0.22, 72 + (k % 4) * 6))
    return dict(name="House Groove", bpm=124, tracks=[
        _track("Drums", 1, grid(D["kick"], "x...x...x...x...", 115)
               + grid(D["clap"], "....x.......x...", 95)
               + grid(D["hat"], "..x...x...x...x.", 85)
               + grid(D["ohat"], "......x.......x.", 50), kit="Classic", vol=0.9),
        _track("Bass", 2, notes([(0.5, "A1", 0.4), (1.5, "A1", 0.4), (2.5, "A2", 0.3), (3.5, "A1", 0.4),
                                 (4.5, "F1", 0.4), (5.5, "F1", 0.4), (6.5, "F2", 0.3), (7.5, "G1", 0.4)], 105),
               patch="Pluck Bass", vol=0.85),
        _track("Stabs", 2, notes([(1.5, "A3", 0.3, 100), (3.5, "A3", 0.3, 92), (5.5, "F3", 0.3, 100), (7.0, "G3", 0.3, 96)]),
               patch="Chord Stab", vol=0.7, pan=0.25, dsend=0.3, rsend=0.25),
        _track("Arp", 4, notes(arp), patch="Bright Pluck", vol=0.55, pan=-0.3, dsend=0.25, rsend=0.3),
    ])


def electro_acid():
    acid = []
    pat = [("E1", 1), ("E1", 1), ("E2", 0), ("E1", 1), ("G1", 1), ("E1", 0), ("E2", 1), ("D1", 1)]
    for bar in range(2):
        for k, (nm, acc) in enumerate(pat * 2):
            acid.append((bar * 4 + k / 4.0, nm, 0.2, 110 if acc else 80))
    return dict(name="Electro Acid", bpm=128, tracks=[
        _track("Drums", 2, grid(D["kick"], "x...x...x...x...x...x...x..xx...", 120)
               + grid(D["snare"], "....x.......x.......x.......x...", 100)
               + grid(D["hat"], "x.x.x.x.x.x.x.x.x.x.x.x.x.x.x.x.", 75, 95)
               + grid(D["rim"], "......x.......x.......x.......xx", 70), kit="Electro", vol=0.7),
        _track("Acid", 2, notes(acid), patch="Acid", vol=0.6, dsend=0.15),
        _track("Lead", 4, notes([(0, "B3", 0.5, 100), (0.5, "D4", 0.5, 90), (1, "E4", 1.0, 100), (2.5, "D4", 0.5, 85),
                                 (3, "B3", 1.0, 95), (8, "G3", 0.5, 100), (8.5, "B3", 0.5, 90), (9, "D4", 1.0, 100),
                                 (10.5, "E4", 0.5, 85), (11, "G4", 1.0, 95), (12, "F#4", 2.0, 90)]),
               patch="Square Lead", vol=0.6, pan=0.2, dsend=0.4, rsend=0.3),
        _track("Pad", 4, notes([(0, ("E2", "B2", "D3"), 7.8, 70), (8, ("G2", "D3", "F#3"), 7.8, 70)]),
               patch="Dark Pad", vol=0.4, pan=-0.2, rsend=0.5),
    ])


def ambient_drift():
    kal = []
    for bar, nms in enumerate([("F#4", "A4", "C#5", "E5"), ("D4", "F#4", "A4", "C#5"),
                               ("E4", "G#4", "B4", "D5"), ("C#4", "E4", "G#4", "B4")]):
        for k, nm in enumerate(nms):
            kal.append((bar * 4 + k * 0.75, nm, 0.4, 60 + k * 8))
    return dict(name="Ambient Drift", bpm=70, tracks=[
        _track("Shaker", 2, grid(D["hat"], "x.x.x.x.x.x.x.x.x.x.x.x.x.x.x.x.", 60, 85)
               + grid(D["bell"], "x...............x...............", 50)
               + grid(D["kick"], "x.......x.......x.......x.......", 70), kit="Percussion", vol=0.6, pan=0.3, rsend=0.4),
        _track("Strings", 4, notes([(0, ("F#2", "C#3", "F#3", "A3"), 3.9, 70), (4, ("D2", "A2", "D3", "F#3"), 3.9, 70),
                                    (8, ("E2", "B2", "E3", "G#3"), 3.9, 70), (12, ("C#2", "G#2", "C#3", "E3"), 3.9, 70)]),
               patch="Strings", vol=0.65, pan=-0.3, rsend=0.6),
        _track("Glass", 4, notes([(0, ("A4", "E5"), 3.5, 60), (4, ("F#4", "D5"), 3.5, 60),
                                  (8, ("G#4", "E5"), 3.5, 60), (12, ("E4", "C#5"), 3.5, 60)]),
               patch="Glass Pad", vol=0.5, pan=0.3, dsend=0.3, rsend=0.6),
        _track("Kalimba", 4, notes(kal), patch="Kalimba", vol=0.6, dsend=0.45, rsend=0.5),
    ])


DEMOS = [lofi_chill, house_groove, electro_acid, ambient_drift]


def slug(name):
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


def write_session(path, name, sr, bar, tempo, tracks, demo=False, extra=None, sampler_buf=None):
    """tracks: list of dicts with buf (or None) and the mixer fields. extra: more
    top-level keys (seq, scenes, kit, sampler params...)."""
    path.mkdir(parents=True, exist_ok=True)
    meta = dict(name=name, demo=demo, sr=sr, bar=bar, tempo=tempo, tracks=[])
    meta.update(extra or {})
    for i, t in enumerate(tracks):
        td = dict(vol=t["vol"], pan=t["pan"], filt=t.get("filt", 0.0), rate=t.get("rate", 1.0),
                  dsend=t["dsend"], rsend=t["rsend"], muted=t.get("muted", False), file=None,
                  label=t.get("name", ""), fx=t.get("fx", "Off"), fxamt=t.get("fxamt", 0.5),
                  duck=t.get("duck", 0.0), notes=t.get("notes", []))
        if t.get("buf") is not None:
            td["file"] = f"track{i + 1}.wav"
            sf.write(path / td["file"], t["buf"], sr, "FLOAT")
        meta["tracks"].append(td)
    if sampler_buf is not None and meta.get("sampler") is not None:
        meta["sampler"]["file"] = "sampler.wav"
        sf.write(path / "sampler.wav", sampler_buf, sr, "FLOAT")
    (path / "session.json").write_text(json.dumps(meta, indent=2))
    return path


def make_demos(sessions_dir, sr=48000, progress=None):
    """Render all demo sessions into sessions_dir/demo-<slug>. Returns the paths."""
    out = []
    for make in DEMOS:
        d = make()
        if progress:
            progress(d["name"])
        probe = Engine(sr, 128)
        probe.set_tempo(d["bpm"])
        tracks = []
        for t in d["tracks"]:
            t["buf"], t["notes"] = render_track(sr, d["bpm"], t["bars"], t["events"], t["patch"], t["kit"])
            tracks.append(t)
        while len(tracks) < 8:
            tracks.append(dict(name="", vol=0.8, pan=0.0, dsend=0.0, rsend=0.15, buf=None))
        out.append(write_session(Path(sessions_dir) / f"demo-{slug(d['name'])}", d["name"], sr,
                                 probe.bar, probe.tempo, tracks, demo=True))
    return out
