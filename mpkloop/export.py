"""Stem and MIDI export. Stems are rendered offline through a headless Engine
built from the session state, so they sound exactly like the live mix."""
import math
from datetime import datetime

import mido
import numpy as np
import soundfile as sf

from .engine import Engine

TAIL_SECONDS = 2.0
MAX_QUARTERS = 128   # export length cap: 32 bars
PPQ = 480
# kit voice (bank B pad order) -> General MIDI drum note
_STD = [36, 38, 42, 46, 39, 45, 37, 56]
GM_DRUMS = {"Classic": _STD, "808": _STD, "Lo-Fi": _STD, "Dub": [36, 38, 42, 46, 37, 45, 60, 70],
            "909": [36, 38, 42, 46, 39, 45, 37, 51], "Trap": [36, 38, 42, 46, 39, 45, 37, 49],
            "Electro": [36, 38, 42, 46, 39, 50, 76, 55], "Techno": [36, 38, 42, 46, 39, 41, 76, 55],
            "Breaks": [36, 38, 42, 46, 40, 45, 50, 51], "Glitch": [36, 38, 42, 44, 75, 76, 77, 80],
            "Jazz": [36, 38, 42, 51, 40, 45, 37, 44], "Percussion": [64, 63, 70, 54, 61, 76, 75, 81]}


def snapshot(e):
    """Engine state with private buffer copies (overdubs keep writing into the live ones)."""
    st = e.state()
    for td in st["tracks"]:
        if td["buf"] is not None:
            td["buf"] = td["buf"].copy()
    if st["sampler"]:
        st["sampler"]["buf"] = st["sampler"]["buf"].copy()
    st["mix"] = dict(master=e.master, delay_div=e.delay_div, delay_fb=e.delay_fb, drum_vol=e.drum_vol,
                     reverb=e.pages[7][1][6].value)
    return st


def _seq_active(st):
    s = st["seq"]
    return s["on"] and not s["muted"] and np.any(np.array(s["pattern"])[:, :s["length"]])


def export_length(st):
    """Samples: LCM of the audible loop lengths (in quarter bars), capped, whole bars."""
    bar = st["bar"]
    qs = [max(1, round(4 * len(td["buf"]) / bar / abs(td["rate"])))
          for td in st["tracks"] if td["buf"] is not None and not td["muted"]]
    if _seq_active(st):
        qs.append(max(1, st["seq"]["length"] // 4))
    if not qs:
        return 0
    q = 1
    for x in qs:
        q = q * x // math.gcd(q, x)
    if q > MAX_QUARTERS:
        q = min(max(qs), MAX_QUARTERS)
    return math.ceil(q / 4) * bar


def _headless(st, block):
    h = Engine(st["sr"], block)
    h.say = lambda msg: None
    h.metro_level, h.count_in = 0.0, False
    h._load(st)
    m = st.get("mix", {})
    h.master, h.delay_div, h.delay_fb = m.get("master", 0.85), m.get("delay_div", 0.75), m.get("delay_fb", 0.4)
    h.drum_vol = m.get("drum_vol", 0.8)
    h.reverb_size(m.get("reverb", 0.5))
    return h


def render(st, length, solo=None, clip=False, block=1024):
    """Render `length` samples plus the FX tail. solo: track index, "seq" or None (= full mix)."""
    h = _headless(st, block)
    h.clip = clip
    for i, t in enumerate(h.tracks):
        if solo is not None and solo != i:
            t.muted = True
        t.gains = h._gains(t.pan, 0.0 if t.muted else t.vol)
    if solo is not None and solo != "seq":
        h.seq.muted = True
    h.seq.gains = h._gains(h.seq.pan, 0.0 if h.seq.muted else h.seq.vol * h.drum_vol)
    total = length + int(TAIL_SECONDS * h.sr)
    out = np.zeros((total, 2), np.float32)
    p = 0
    while p < total:
        if p == length:   # loops stop, delay and reverb ring out
            for t in h.tracks:
                t.muted, t.gains = True, np.zeros(2)
            h.seq.muted, h.seq.gains = True, np.zeros(2)
        n = min(block, (length if p < length else total) - p)
        out[p:p + n] = h.process(None, n)
        p += n
    return out


def export_stems(st, folder, progress=None):
    length = export_length(st)
    if not length:
        raise ValueError("nothing audible to export")
    sr = st["sr"]
    jobs = [(f"T{i + 1}", i) for i, td in enumerate(st["tracks"]) if td["buf"] is not None and not td["muted"]]
    if _seq_active(st):
        jobs.append(("seq", "seq"))
    for name, solo in jobs:
        if progress:
            progress(f"stem {name}")
        sf.write(folder / f"{name}.wav", render(st, length, solo), sr, "FLOAT")
    if progress:
        progress("mix")
    sf.write(folder / "mix.wav", render(st, length, None, clip=True), sr, "PCM_24")
    return length


# ---------------------------------------------------------------- MIDI

def _map(inst, num):
    """(channel, note) for a logged note."""
    if inst.startswith("drum:"):
        return 9, GM_DRUMS.get(inst[5:], _STD)[num % 8]
    if inst == "chop":
        return 3, 36 + num
    if inst == "sampler":
        return 2, num
    return 0, num


def _one_shot(inst):
    return inst.startswith("drum:") or inst == "chop"


def _track_events(notes, loop_len, length, beat):
    """Absolute-sample (time, order, msg) events for a loop repeated to `length`."""
    evs = []
    short = int(beat / 4)
    for base in range(0, length, loop_len):
        held = {}
        for off, kind, num, vel, inst in sorted(notes, key=lambda x: x[0]):
            t = base + off
            if t >= length:
                continue
            ch, note = _map(inst, num)
            end = min(base + loop_len, length) - 1
            if _one_shot(inst):
                if kind == "on":
                    evs.append((t, 1, mido.Message("note_on", channel=ch, note=note, velocity=max(1, min(vel, 127)))))
                    evs.append((min(t + short, end), 0, mido.Message("note_off", channel=ch, note=note)))
            elif kind == "on":
                if (ch, note) in held:
                    evs.append((t, 0, mido.Message("note_off", channel=ch, note=note)))
                held[(ch, note)] = t
                evs.append((t, 1, mido.Message("note_on", channel=ch, note=note, velocity=max(1, min(vel, 127)))))
            elif (ch, note) in held:
                del held[(ch, note)]
                evs.append((t, 0, mido.Message("note_off", channel=ch, note=note)))
        for ch, note in held:   # notes still down at the loop end
            evs.append((min(base + loop_len, length) - 1, 0, mido.Message("note_off", channel=ch, note=note)))
    return evs


def _midi_track(name, evs, beat):
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name=name, time=0))
    last = 0
    for t, _, msg in sorted(evs, key=lambda x: (x[0], x[1])):
        tick = int(round(t / beat * PPQ))
        tr.append(msg.copy(time=tick - last))
        last = tick
    return tr


def seq_notes(st, beat):
    s = st["seq"]
    pat = np.array(s["pattern"])
    step = beat / 4.0
    out = []
    for g in range(s["length"]):
        t = int(round(g * step + (s["swing"] * step * 0.5 if g % 2 else 0)))
        for lane in np.nonzero(pat[:, g])[0]:
            out.append([t, "on", int(lane), 30 + 32 * int(pat[lane, g]), "drum:" + st.get("kit_name", "Classic")])
    return out, int(round(s["length"] * step))


def export_midi(st, path, length=None):
    length = length or export_length(st)
    if not length:
        raise ValueError("nothing audible to export")
    beat = st["bar"] / 4.0
    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name=st.get("name") or "mpkloop", time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(st["tempo"]), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    mid.tracks.append(meta)
    for i, td in enumerate(st["tracks"]):
        if td["buf"] is None or td["muted"] or not td.get("notes"):
            continue
        patches = [n[4][6:] for n in td["notes"] if n[4].startswith("synth:")]
        label = patches[0] if patches else ("drums" if any(n[4].startswith("drum:") for n in td["notes"]) else "sampler")
        evs = _track_events(td["notes"], len(td["buf"]), length, beat)
        mid.tracks.append(_midi_track(f"T{i + 1} {label}", evs, beat))
    if _seq_active(st):
        notes, L = seq_notes(st, beat)
        mid.tracks.append(_midi_track("Step seq", _track_events(notes, L, length, beat), beat))
    if len(mid.tracks) == 1:
        raise ValueError("no recorded notes to export (audio-only loops have no MIDI)")
    mid.save(path)
    return len(mid.tracks) - 1


def export(e, stems=True, midi=True, folder_root=None, progress=None):
    """Export into folder_root/<date>-<name>/. Returns (folder, summary)."""
    from .demos import slug
    st = snapshot(e)
    st["kit_name"] = e.kits[e.kit_index][0]
    name = st.get("name") or "session"
    folder = folder_root / f"{datetime.now():%Y%m%d-%H%M%S}-{slug(name)}"
    folder.mkdir(parents=True, exist_ok=True)
    done = []
    if midi:
        try:
            done.append(f"{export_midi(st, folder / 'loops.mid')} MIDI tracks")
        except ValueError as ex:
            if not stems:
                raise
            done.append(f"no MIDI ({ex})")
    if stems:
        length = export_stems(st, folder, progress)
        done.append(f"stems {length / st['bar']:.0f} bars")
    return folder, ", ".join(done)
