"""Original 'club bounce' loop: ~90 BPM West Coast/East Coast club feel (not a transcription)."""
from pathlib import Path
from mpkloop.demos import grid, notes, render_track, write_session, D, _track
from mpkloop.engine import Engine

SR, BPM = 48000, 90

drums = _track("Drums", 2,
    grid(D["kick"],  "x..x..x...x..x..x..x......x.x...", 118, 127)
    + grid(D["clap"], "....X.......X.......X.......X..x", 110, 124)
    + grid(D["snare"],"....x.......x.......x.......x...", 70)
    + grid(D["hat"],  "x.xxx.x.x.xxx.x.x.xxx.x.x.xxx.xx", 62, 88)
    + grid(D["ohat"], "..............x...............x.", 55),
    kit="808", vol=0.95)

# sub follows the kick; F# minor root movement F# - D - E
bass = _track("808 Bass", 2, notes([
    (0, "F#1", 0.7), (0.75, "F#1", 0.5), (1.5, "F#1", 0.4), (2.5, "A1", 0.4), (3.25, "F#1", 0.6),
    (4, "D1", 0.7), (4.75, "D1", 0.5), (6.5, "E1", 0.4), (7.0, "E1", 0.4), (7.5, "C#1", 0.4)], 112),
    patch="Sub Bass", vol=0.9)

# original staccato minor riff (16th stabs) on a reedy lead
riff_seq = []
cells = [(0, "F#4"), (0.5, "F#4"), (0.75, "A4"), (1.25, "G#4"), (1.75, "F#4"), (2.5, "C#4"), (3, "E4"), (3.5, "F#4"),
         (4, "D4"), (4.5, "D4"), (4.75, "F#4"), (5.25, "E4"), (5.75, "D4"), (6.5, "C#4"), (7, "E4"), (7.5, "C#4")]
for b, nm in cells:
    riff_seq.append((b, nm, 0.18, 100 if b % 1 == 0 else 84))
riff = _track("Riff", 2, notes(riff_seq), patch="Pulse Lead", vol=0.55, pan=0.15, dsend=0.15, rsend=0.15)

strings = _track("Strings", 4, notes([
    (0, ("F#3", "A3", "C#4"), 3.9, 72), (4, ("F#3", "A3", "C#4"), 3.9, 68),
    (8, ("D3", "F#3", "A3"), 3.9, 72), (12, ("E3", "G#3", "B3"), 3.9, 70)]),
    patch="Strings", vol=0.45, pan=-0.25, rsend=0.4)

bell = _track("Bell", 4, notes([(3.5, "C#5", 0.4, 70), (11.5, "A4", 0.4, 66), (15.5, "G#4", 0.4, 64)]),
    patch="Bell", vol=0.4, pan=0.35, dsend=0.4, rsend=0.4)

probe = Engine(SR, 128); probe.set_tempo(BPM)
tracks = []
for t in [drums, bass, riff, strings, bell]:
    t["buf"], t["notes"] = render_track(SR, BPM, t["bars"], t["events"], t["patch"], t["kit"])
    tracks.append(t)
while len(tracks) < 8:
    tracks.append(dict(name="", vol=0.8, pan=0.0, dsend=0.0, rsend=0.15, buf=None))
tracks[0]["duck"] = 0.0
tracks[1]["duck"] = 0.0
tracks[3]["duck"] = 0.35   # strings breathe with the kick
p = write_session(Path.home() / "Music/mpkloop/sessions/club-bounce", "Club Bounce", SR, probe.bar, probe.tempo,
                  tracks, extra=dict(kit=1))
print(p)
