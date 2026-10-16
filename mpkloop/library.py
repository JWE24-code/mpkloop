"""Sound library: synth patches and drum kits, factory + user.

    ~/Music/mpkloop/library/
        patches/<name>.json        one synth patch (same fields as factory/patches.json)
        kits/<name>/kit.json       a drumsynth recipe, or a WAV kit:
        kits/<name>/*.wav          8 audio files in pad order (kit.json optional: names/pans)
        library.json               favorites and hidden factory sounds

A user patch or kit with the same name as a factory one replaces it."""
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from . import drumsynth

LIBRARY = Path.home() / "Music" / "mpkloop" / "library"
FACTORY = Path(__file__).parent / "factory"
CATEGORIES = ["Pads", "Keys", "Bass", "Leads", "Plucks", "Bells", "Organ+"]
AUDIO_EXT = {".wav", ".flac", ".ogg", ".aif", ".aiff"}
DEFAULT_PAD_NAMES = ["Kick", "Snare", "Hat", "Open Hat", "Clap", "Tom", "Rim", "Perc"]


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "sound"


def _read_audio(path, sr, max_seconds=4.0):
    x, fsr = sf.read(path, dtype="float32", always_2d=True)
    x = x[: int(max_seconds * fsr)]
    if fsr != sr:
        g = np.gcd(sr, fsr)
        x = resample_poly(x, sr // g, fsr // g, axis=0).astype(np.float32)
    x = np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x[:, :2]
    return x * (0.9 / max(np.abs(x).max(), 1e-6))


class Library:
    def __init__(self, sr):
        self.sr = sr
        self.patches = []   # dicts; extra keys: user (bool), file (Path|None)
        self.kits = []      # (name, [(voice name, stereo buf)]) in load order
        self.kit_meta = []  # dicts: name, info, user, path
        self.favorites = set()
        self.hidden = set()
        self.reload()

    # ------------------------------------------------------------ loading

    def reload(self):
        for d in ("patches", "kits"):
            (LIBRARY / d).mkdir(parents=True, exist_ok=True)
        meta = {}
        if (LIBRARY / "library.json").exists():
            try:
                meta = json.loads((LIBRARY / "library.json").read_text())
            except Exception:
                meta = {}
        self.favorites = set(meta.get("favorites", []))
        self.hidden = set(meta.get("hidden", []))
        self._load_patches()
        self._load_kits()

    def _load_patches(self):
        by_name = {}
        for n, p in enumerate(json.loads((FACTORY / "patches.json").read_text())):
            p["user"], p["file"], p["_pos"] = False, None, n
            by_name[p["name"]] = p
        for f in sorted((LIBRARY / "patches").glob("*.json")):
            try:
                p = json.loads(f.read_text())
                p.setdefault("name", f.stem)
                p.setdefault("cat", "Keys")
                self._check_patch(p)
            except Exception as ex:
                print(f"library: skipped {f.name}: {ex}")
                continue
            p["user"], p["file"], p["_pos"] = True, f, 10 ** 6
            by_name[p["name"]] = p
        order = {c: i for i, c in enumerate(CATEGORIES)}   # factory order, then user sounds A-Z
        self.patches = sorted((p for p in by_name.values() if "patch:" + p["name"] not in self.hidden),
                              key=lambda p: (order.get(p["cat"], 99), p["_pos"], p["name"].lower()))
        if not self.patches:
            self.patches = [json.loads((FACTORY / "patches.json").read_text())[0]]

    @staticmethod
    def _check_patch(p):
        for k in ("osc", "amp"):
            if k not in p:
                raise ValueError(f"missing '{k}'")
        p.setdefault("fenv", [0.01, 0.3, 1.0, 0.3])
        p.setdefault("fenv_amt", 0.0)
        p.setdefault("cutoff", 16000)
        p.setdefault("reso", 0.0)
        p.setdefault("gain", 0.3)
        if p["cat"] not in CATEGORIES:
            p["cat"] = "Keys"
        for k in ("amp", "fenv", "intervals"):
            if k in p:
                p[k] = tuple(p[k])

    def _load_kits(self):
        kits = {}
        for k in json.loads((FACTORY / "kits.json").read_text()):
            kits[k["name"]] = (k, dict(name=k["name"], info=k.get("info", ""), user=False, path=None))
        for d in sorted((LIBRARY / "kits").iterdir()):
            if not d.is_dir():
                continue
            try:
                k = self._read_user_kit(d)
            except Exception as ex:
                print(f"library: skipped kit {d.name}: {ex}")
                continue
            kits[k["name"]] = (k, dict(name=k["name"], info=k.get("info", "user kit"), user=True, path=d))
        self.kits, self.kit_meta = [], []
        for k, m in kits.values():
            if "kit:" + k["name"] in self.hidden:
                continue
            self.kits.append((k["name"], k["sounds"] if "sounds" in k else drumsynth.render_kit(k, self.sr)))
            self.kit_meta.append(m)
        if not self.kits:
            k = json.loads((FACTORY / "kits.json").read_text())[0]
            self.kits, self.kit_meta = [(k["name"], drumsynth.render_kit(k, self.sr))], [dict(name=k["name"], info="", user=False, path=None)]

    def _read_user_kit(self, d):
        meta = json.loads((d / "kit.json").read_text()) if (d / "kit.json").exists() else {}
        meta.setdefault("name", d.name)
        if "voices" in meta:                     # a synthesis recipe
            return meta
        files = sorted(f for f in d.iterdir() if f.suffix.lower() in AUDIO_EXT)[:8]
        if not files:
            raise ValueError("no kit.json recipe and no audio files")
        names = meta.get("names") or [f.stem.replace("_", " ").replace("-", " ").title() for f in files]
        pans = meta.get("pans") or [0.0, 0.05, 0.3, 0.3, -0.15, -0.35, 0.25, 0.4]
        sounds = []
        for i, f in enumerate(files):
            x = _read_audio(f, self.sr)
            if x.shape[1] == 2 and pans[i % len(pans)]:  # pan a (mono-ish) file
                mono = x.mean(axis=1)
                x = drumsynth._pan(mono, pans[i % len(pans)])
            sounds.append((names[i] if i < len(names) else f.stem, x))
        while len(sounds) < 8:                   # pad short kits with silence so pads stay safe
            sounds.append((DEFAULT_PAD_NAMES[len(sounds)], np.zeros((64, 2), np.float32)))
        meta["sounds"] = sounds
        return meta

    # ------------------------------------------------------------ queries

    def index_of(self, name, default=0):
        for i, p in enumerate(self.patches):
            if p["name"] == name:
                return i
        return default

    def kit_index_of(self, name, default=0):
        for i, (n, _) in enumerate(self.kits):
            if n == name:
                return i
        return default

    def members(self, cat):
        """Patch indices of a category, favorites first."""
        idx = [i for i, p in enumerate(self.patches) if p["cat"] == cat]
        return sorted(idx, key=lambda i: not self.is_fav(self.patches[i]))

    def is_fav(self, p):
        return "patch:" + p["name"] in self.favorites

    def is_fav_kit(self, name):
        return "kit:" + name in self.favorites

    # ------------------------------------------------------------ editing

    def _save_meta(self):
        (LIBRARY / "library.json").write_text(json.dumps(
            dict(favorites=sorted(self.favorites), hidden=sorted(self.hidden)), indent=1))

    def toggle_fav(self, key):
        self.favorites ^= {key}
        self._save_meta()
        return key in self.favorites

    def save_patch(self, patch, name, cat=None):
        """Write a patch as a user sound. Returns the new index in self.patches."""
        p = {k: v for k, v in patch.items() if k not in ("user", "file", "_pos")}
        p["name"], p["cat"] = name, cat or p["cat"]
        for k in ("amp", "fenv", "intervals"):
            if k in p:
                p[k] = list(p[k])
        f = LIBRARY / "patches" / f"{slug(name)}.json"
        f.write_text(json.dumps(p, indent=1))
        self.hidden.discard("patch:" + name)
        self._save_meta()
        self._load_patches()
        return self.index_of(name)

    def delete_patch(self, p):
        if p.get("file"):
            Path(p["file"]).unlink(missing_ok=True)
        else:
            self.hidden.add("patch:" + p["name"])
        self._save_meta()
        self._load_patches()

    def delete_kit(self, i):
        m = self.kit_meta[i]
        if not m["user"]:
            self.hidden.add("kit:" + m["name"])
        else:
            self.hidden.add("kit:" + m["name"])   # keep the files; hide only
        self._save_meta()
        self._load_kits()

    def restore_all(self):
        self.hidden.clear()
        self._save_meta()
        self.reload()
