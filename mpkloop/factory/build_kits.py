"""Writes kits.json: the factory drum kits as drumsynth recipes.
Run:  python -m mpkloop.factory.build_kits"""
import json
from pathlib import Path


def v(name, gen, pan=0.0, post=None, **args):
    d = dict(name=name, gen=gen, args=args, pan=pan)
    if post:
        d["post"] = post
    return d


# pad order: bottom row 1-4 (kick snare hat ohat), top row 5-8 (clap tom rim bell)
classic = [
    v("Kick", "kick", 0.0, f_hi=155, f_lo=45, sweep=0.045, decay=0.22),
    v("Snare", "snare", 0.05, tone=185, tone_decay=0.06, hp=1200, noise_decay=0.09),
    v("Hat", "hat", 0.3, hp=7000, decay=0.018, length=0.08),
    v("Open Hat", "hat", 0.3, hp=7000, decay=0.16, length=0.6, level=0.7),
    v("Clap", "clap", -0.15, bp=1300, tail=0.11),
    v("Tom", "tone", -0.35, f_hi=155, f_lo=95, sweep=0.07, decay=0.17),
    v("Rim", "ping", 0.25, freqs=[[1750, 1.0], [520, 0.5]], decay=0.01, length=0.06),
    v("Cowbell", "cowbell", 0.4),
]
k808 = [
    v("Kick", "kick", 0.0, f_hi=110, f_lo=48, sweep=0.08, decay=0.55, length=1.4, click=0.15, drive=1.2),
    v("Snare", "snare", 0.05, tone=238, tone_decay=0.08, hp=1800, noise_decay=0.12, mix=0.6),
    v("Hat", "hat", 0.3, hp=8000, decay=0.02, length=0.1, level=1.2, metallic=True),
    v("Open Hat", "hat", 0.3, hp=8000, decay=0.2, length=0.8, level=1.0, metallic=True),
    v("Clap", "clap", -0.15, bp=1100, tail=0.16, level=2.6),
    v("Tom", "tone", -0.35, f_hi=130, f_lo=80, sweep=0.12, decay=0.3, length=0.9),
    v("Rim", "ping", 0.25, freqs=[[1700, 1.0], [450, 0.6]], decay=0.008, length=0.05, level=1.2),
    v("Cowbell", "cowbell", 0.4),
]
k909 = [
    v("Kick", "kick", 0.0, f_hi=200, f_lo=52, sweep=0.03, decay=0.3, length=0.7, click=0.7, drive=2.0),
    v("Snare", "snare", 0.05, tone=180, tone_decay=0.05, hp=900, noise_decay=0.16, mix=1.0, tone2=330),
    v("Hat", "hat", 0.3, hp=8500, decay=0.025, length=0.1, level=1.0, bp=9000),
    v("Open Hat", "hat", 0.3, hp=8000, decay=0.25, length=0.9, level=0.8, bp=8500),
    v("Clap", "clap", -0.15, bp=1500, tail=0.14, level=2.4, spread=0.009),
    v("Tom", "tone", -0.35, f_hi=200, f_lo=110, sweep=0.05, decay=0.25, length=0.6, drive=1.5),
    v("Rim", "ping", 0.25, freqs=[[1900, 1.0], [600, 0.4]], decay=0.012, length=0.06),
    v("Ride", "ride", 0.45),
]
electro = [
    v("Kick", "kick", 0.0, f_hi=260, f_lo=52, sweep=0.02, decay=0.18, length=0.4, click=0.9, drive=2.5),
    v("Snare", "snare", 0.05, tone=200, tone_decay=0.04, hp=2500, noise_decay=0.15, mix=1.0),
    v("Hat", "hat", 0.3, hp=9500, decay=0.012, length=0.06, level=1.0),
    v("Open Hat", "hat", 0.3, hp=9000, decay=0.1, length=0.4, level=0.8),
    v("Clap", "clap", -0.15, bp=1600, tail=0.08, level=2.4),
    v("Zap", "zap", -0.35, f_hi=2400, f_lo=90, sweep=0.025, decay=0.12, length=0.3, level=0.6),
    v("Blip", "ping", 0.25, freqs=[[2200, 1.0]], decay=0.03, length=0.12, level=0.6),
    v("Noise Hit", "noise_hit", 0.4, bp=3000, q=0.8, decay=0.12, length=0.5),
]
lofi = [dict(x, post=[["crush", {"hold": 4, "bits": 6}]]) for x in classic]
trap = [
    v("Kick", "kick", 0.0, f_hi=120, f_lo=42, sweep=0.06, decay=0.7, length=1.6, click=0.3, drive=1.4, sub=0.5),
    v("Snare", "snare", 0.05, tone=210, tone_decay=0.05, hp=1500, noise_decay=0.2, mix=1.1, tone2=165),
    v("Hat", "hat", 0.3, hp=9000, decay=0.012, length=0.05, level=1.1, metallic=True),
    v("Open Hat", "hat", 0.3, hp=8500, decay=0.15, length=0.6, level=0.9, metallic=True),
    v("Clap", "clap", -0.15, bp=1200, tail=0.2, level=2.6, spread=0.013),
    v("Tom 808", "tone", -0.35, f_hi=95, f_lo=60, sweep=0.1, decay=0.5, length=1.2, drive=1.3),
    v("Rim", "ping", 0.25, freqs=[[1800, 1.0], [700, 0.5]], decay=0.01, length=0.06),
    v("Rev Cymbal", "reverse_cymbal", 0.4, length=0.5),
]
techno = [
    v("Kick", "kick", 0.0, f_hi=180, f_lo=50, sweep=0.025, decay=0.26, length=0.6, click=0.6, drive=3.0),
    v("Snare", "noise_hit", 0.05, bp=1800, q=0.6, decay=0.1, length=0.35, level=1.3),
    v("Hat", "hat", 0.3, hp=9000, decay=0.02, length=0.08, level=1.0, bp=10000),
    v("Open Hat", "hat", 0.3, hp=8500, decay=0.18, length=0.7, level=0.8),
    v("Clap", "clap", -0.15, bp=1400, tail=0.12, level=2.4),
    v("Rumble", "tone", -0.35, f_hi=70, f_lo=55, sweep=0.1, decay=0.9, length=1.6, level=0.8, drive=2.0),
    v("Blip", "ping", 0.25, freqs=[[3000, 1.0], [1500, 0.3]], decay=0.02, length=0.08, level=0.6),
    v("Zap Noise", "noise_hit", 0.4, bp=900, q=1.5, decay=0.2, length=0.6, sweep=1.0),
]
breaks = [
    v("Kick", "kick", 0.0, f_hi=140, f_lo=58, sweep=0.03, decay=0.14, length=0.35, click=0.6, drive=1.8,
      post=[["lowpass", {"f": 4000}]]),
    v("Snare", "snare", 0.05, tone=195, tone_decay=0.05, hp=800, noise_decay=0.13, mix=0.9, tone2=290,
      post=[["drive", {"amount": 2.5}]]),
    v("Hat", "hat", 0.3, hp=6000, decay=0.03, length=0.12, level=0.8),
    v("Open Hat", "hat", 0.3, hp=6000, decay=0.2, length=0.7, level=0.7),
    v("Ghost Snare", "snare", -0.15, tone=190, tone_decay=0.03, hp=1500, noise_decay=0.05, mix=0.5, body=0.3, level=0.5),
    v("Low Tom", "tone", -0.35, f_hi=130, f_lo=85, sweep=0.05, decay=0.22, length=0.5, drive=1.6),
    v("High Tom", "tone", 0.25, f_hi=210, f_lo=150, sweep=0.04, decay=0.18, length=0.4, drive=1.6),
    v("Ride", "ride", 0.4, decay=0.4, length=1.0),
]
dub = [
    v("Kick", "kick", 0.0, f_hi=120, f_lo=46, sweep=0.05, decay=0.35, length=0.9, click=0.25, drive=1.3,
      post=[["lowpass", {"f": 2500}]]),
    v("Snare", "snare", 0.05, tone=175, tone_decay=0.07, hp=700, noise_decay=0.1, mix=0.7, tone2=260),
    v("Hat", "hat", 0.3, hp=7500, decay=0.02, length=0.08, level=0.8),
    v("Open Hat", "hat", 0.3, hp=7000, decay=0.14, length=0.5, level=0.6),
    v("Rim", "ping", -0.15, freqs=[[1600, 1.0], [420, 0.7]], decay=0.015, length=0.08, level=1.1),
    v("Tom", "tone", -0.35, f_hi=120, f_lo=75, sweep=0.08, decay=0.3, length=0.8),
    v("Bongo", "tone", 0.25, f_hi=480, f_lo=420, sweep=0.01, decay=0.07, length=0.25),
    v("Shaker", "shaker", 0.4, length=0.14, hp=5500),
]
glitch = [
    v("Kick", "kick", 0.0, f_hi=300, f_lo=60, sweep=0.012, decay=0.09, length=0.2, click=1.0, drive=3.0,
      post=[["crush", {"hold": 2, "bits": 8}]]),
    v("Snare", "noise_hit", 0.05, bp=2500, q=1.2, decay=0.05, length=0.15, level=1.3,
      post=[["crush", {"hold": 3, "bits": 5}]]),
    v("Tick", "ping", 0.3, freqs=[[5000, 1.0]], decay=0.004, length=0.03, level=0.8),
    v("Click Hat", "hat", 0.3, hp=11000, decay=0.006, length=0.03, level=1.0),
    v("Glitch 1", "glitch", -0.15, length=0.09, rate=3, seed=1),
    v("Glitch 2", "glitch", -0.35, length=0.14, rate=5, seed=2),
    v("Glitch 3", "glitch", 0.25, length=0.2, rate=2, seed=3, post=[["crush", {"hold": 6, "bits": 4}]]),
    v("Bitblip", "ping", 0.4, freqs=[[1200, 1.0], [2400, 0.6], [3600, 0.3]], decay=0.03, length=0.1, level=0.6,
      post=[["crush", {"hold": 8, "bits": 4}]]),
]
jazz = [
    v("Kick", "kick", 0.0, f_hi=120, f_lo=65, sweep=0.03, decay=0.12, length=0.3, click=0.2, drive=1.1,
      post=[["lowpass", {"f": 3000}]]),
    v("Brush Snare", "brush", 0.05, hp=2500, decay=0.12, length=0.35),
    v("Hat", "hat", 0.3, hp=7000, decay=0.03, length=0.1, level=0.7),
    v("Ride", "ride", 0.3, decay=0.8, length=1.8, level=0.5),
    v("Brush Sweep", "brush", -0.15, hp=1800, decay=0.25, length=0.6, swell=0.15, level=0.6),
    v("Low Tom", "tone", -0.35, f_hi=140, f_lo=100, sweep=0.04, decay=0.2, length=0.5),
    v("Rim Click", "ping", 0.25, freqs=[[2100, 1.0], [800, 0.4]], decay=0.008, length=0.05),
    v("Hat Foot", "hat", 0.4, hp=6000, decay=0.01, length=0.05, level=0.5),
]
perc = [
    v("Low Conga", "tone", -0.3, f_hi=240, f_lo=190, sweep=0.02, decay=0.18, length=0.5),
    v("High Conga", "tone", 0.3, f_hi=350, f_lo=290, sweep=0.015, decay=0.12, length=0.4),
    v("Shaker", "shaker", 0.4),
    v("Tambourine", "tambourine", 0.35),
    v("Bongo", "tone", -0.2, f_hi=480, f_lo=420, sweep=0.01, decay=0.07, length=0.25),
    v("Woodblock", "woodblock", -0.4),
    v("Claves", "ping", 0.2, freqs=[[2500, 1.0]], decay=0.025, length=0.12, level=0.8),
    v("Triangle", "ping", 0.5, freqs=[[4200, 1.0], [6100, 0.4]], decay=0.6, length=1.5, level=0.35),
]

KITS = [
    ("Classic", classic, "Punchy all-round kit"),
    ("808", k808, "Long boomy kick, metallic hats"),
    ("909", k909, "Clicky house kick, big snare, ride"),
    ("Electro", electro, "Hard, bright, zaps and blips"),
    ("Lo-Fi", lofi, "The Classic kit, bit-crushed"),
    ("Trap", trap, "808 sub kick, tight hats, reverse cymbal"),
    ("Techno", techno, "Driven kick, noise snare, rumble"),
    ("Breaks", breaks, "Dusty breakbeat kit with ghost snare and toms"),
    ("Dub", dub, "Soft kick, woody rim, bongo and shaker"),
    ("Glitch", glitch, "Clicks, bursts and bit-crushed hits"),
    ("Jazz", jazz, "Brushes, ride and a soft kick"),
    ("Percussion", perc, "Congas, bongo, shaker and bells"),
]

out = [dict(name=n, info=i, voices=vs) for n, vs, i in KITS]
Path(__file__).with_name("kits.json").write_text(json.dumps(out, indent=1))
print(f"{len(out)} kits written")
