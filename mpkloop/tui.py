"""Textual user interface: the same screen layout as the classic curses UI, with
mouse support (click pads, tracks, knobs and step cells), panels and modal
dialogs. All state lives in the Engine; this module only reads it and posts
events, exactly like the classic UI."""
import os
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static

from .app import (EXPORTS, HELP, SAMPLES, STATE, list_samples, list_sessions, load_session, read_sample,
                  save_session, make_demos, SESSIONS)
from .engine import FX_PADS, HOLD_SECONDS
from .library import CATEGORIES
from .export import export

# palette (GitHub-dark-ish, readable on both dark and light terminals)
GREEN, RED, YELLOW, MAGENTA, CYAN, DIM, FG, ACCENT = ("#56d364", "#ff7b72", "#e3b341", "#d2a8ff", "#79c0ff",
                                                       "#8b949e", "#e6edf3", "#f5b31c")
COL = {0: FG, 1: RED, 2: GREEN, 3: YELLOW, 4: MAGENTA, 5: CYAN}
PAGE_TABS = ["Vol", "Pan", "Filt", "Speed", "Dly", "Rev", "Sound", "Glob", "TrkFX", "FXAmt", "Duck", "Seq", "Smp"]
VEL_CELL = {0: "·", 1: "▫", 2: "▪", 3: "█"}
FX_SHORT = {"Crush": "crs", "Drive": "drv", "Chorus": "cho", "Tape": "tap", "Comb": "cmb"}
LESSONS = Path(__file__).resolve().parent.parent / "lessons.html"


def bar(frac, width, fill="█", empty=" ", head="▌"):
    k = int(max(0.0, min(frac, 1.0)) * width)
    if k >= width:
        return fill * width
    return fill * k + head + empty * (width - k - len(head))


class Panel(Widget):
    """A widget that rebuilds its text from the engine on every tick, but only asks
    Textual to re-render when the text actually changed (rendering is the expensive
    part and competes with the audio thread for the interpreter)."""

    DEFAULT_CSS = "Panel { height: auto; }"

    def __init__(self, ui, **kw):
        super().__init__(**kw)
        self.ui = ui
        self.e = ui.e
        self.mpk = ui.mpk
        self._last = None

    def build(self):
        return Text()

    def tick(self):
        new = self.build()
        if self._last is None or new.plain != self._last.plain or new.spans != self._last.spans:
            self._last = new
            self.refresh()

    def render(self):
        if self._last is None:
            self._last = self.build()
        return self._last


# ---------------------------------------------------------------- panels

class HeaderBar(Panel):
    def build(self):
        e, mpk, ui = self.e, self.mpk, self.ui
        t = Text()
        t.append(" MPKLOOP ", style=f"bold reverse {ACCENT}")
        if e.count_in_end is not None:
            t.append("  ◌ COUNT-IN", style=f"bold {YELLOW}")
        elif e.running:
            t.append("  ▶ PLAYING ", style=f"bold {GREEN}")
        else:
            t.append("  ■ STOPPED ", style="bold")
        bar_no = e.pos // e.bar + 1 if e.running else 0
        beat = int((e.pos % e.bar) / e.beat_len) + 1 if e.running else 0
        beats = " ".join("●" if i + 1 == beat else "○" for i in range(e.beats))
        t.append(f"  {e.tempo:5.1f} BPM  bar {bar_no:>2}  ", style="bold")
        t.append(beats, style=f"bold {ACCENT}")
        t.append(f"   rec mode: {e.rec_mode}", style=CYAN)
        b = 8 * e.track_bank
        t.append(f"   pads: T{b + 1}-{b + 8}", style=f"bold {YELLOW}" if e.track_bank else DIM)
        if any(x.solo for x in e.tracks):
            t.append("   SOLO", style=f"bold {YELLOW}")
        if e.session_name:
            t.append(f"   session: {e.session_name}{'*' if e.changed else ''}", style=DIM)
        if ui.bouncer.active:
            t.append("   ● BOUNCING", style=f"bold {RED}")
        if e.sample_rec is not None:
            t.append("   ● SAMPLING (Y stops)", style=f"bold {RED}")
        t.append("\n")
        dev = mpk.connected_name.split(":")[0] if mpk.connected_name else "NO MPK FOUND - keys and mouse only"
        knobs = "knobs: relative" if mpk.knob_rel else "knobs: absolute"
        t.append(f" {dev} · {knobs} · audio {ui.stream_info} · cpu {e.cpu:3.0%} · xruns {e.xruns}", style=DIM)
        if ui.busy:
            t.append(f"   {ui.busy}", style=f"bold {YELLOW}")
        return t


class TracksPanel(Panel):
    """Click a row to tap it (record / overdub / stop), click the volume to mute."""

    def build(self):
        e = self.e
        t = Text()
        t.append(" TRACKS", style="bold")
        t.append("  #  name    state    len  position              vol   fx    next\n", style=DIM)
        solo = any(x.solo for x in e.tracks)
        b = 8 * e.track_bank
        for i, tr in enumerate(e.tracks):
            label, col, hint = STATE[tr.state]
            style = f"bold {COL[col]}" if tr.state != "empty" else DIM
            if tr.muted and tr.state in ("play", "odub"):
                label, style, hint = "▷ MUTED", DIM, "click vol: unmute"
            if tr.mute_at is not None:
                label, style = ("▷ mute…" if not tr.muted else "▶ play…"), f"{YELLOW}"
            if solo and not tr.solo and tr.state in ("play", "odub") and not tr.muted:
                label, style = "▷ (solo)", DIM
            line = Text()
            line.append(f"{i + 1:>2} ", style="bold" if b <= i < b + 8 else DIM)
            line.append(f"{(('★' if tr.solo else '') + tr.label)[:7]:<7} ", style=f"bold {YELLOW}" if tr.solo else DIM)
            line.append(f"{label:<8}", style=style)
            if tr.length:
                bars = tr.length / e.bar
                line.append(f" {bars:>3.0f}b " if abs(bars - round(bars)) < 0.01 else f" {bars:4.1f} ")
                frac = ((e.pos - tr.anchor) % tr.length) / tr.length if tr.on_grid else tr.phase / tr.length
                line.append("▕", style=DIM)
                line.append(bar(frac, 20), style=COL[col])
                line.append("▏", style=DIM)
                lvl = "▂▃▄▅▆▇█"[min(int(tr.level * 7), 6)] if tr.level > 0.02 and not tr.muted else " "
                line.append(lvl, style=GREEN if tr.level < 0.9 else RED)
            elif tr.state == "armed" and tr.S is not None:
                line.append(f"      starts in {max(tr.S - e.pos, 0) / e.beat_len:3.1f} beats   ", style=YELLOW)
            elif tr.state in ("rec", "closing") and tr.S is not None:
                line.append(f"      {max(e.pos - tr.S, 0) / e.bar:5.2f} bars…            ", style=RED)
            else:
                line.append(" " * 28)
            line.pad_right(49 - len(line))
            if tr.state != "empty":
                line.append(f"{e.pages[0][1][i].text():>5} ", style="bold" if not tr.muted else DIM)
                tags = []
                if tr.fx != "Off":
                    tags.append(FX_SHORT[tr.fx])
                if tr.duck > 0.001:
                    tags.append("d")
                if tr.rate != 1.0:
                    tags.append(e.pages[3][1][i].text())
                if abs(tr.filt) >= 0.03:
                    tags.append(e.pages[2][1][i].text())
                if tr.undo:
                    tags.append(f"u{len(tr.undo)}")
                line.append(f"{' '.join(tags)[:5]:<5} ", style=DIM)
            line.pad_right(61 - len(line))
            line.append(hint, style=DIM if tr.state in ("empty", "closing") else COL[col])
            t.append(line)
            t.append("\n")
        # step sequencer lane
        q = e.seq
        if q.on and q.muted:
            label, col, hint = "▷ MUTED", DIM, "click vol: unmute"
        elif q.on:
            label, col, hint = "▶ SEQ", CYAN, "click: stop · t edit"
        else:
            label, col, hint = "· seq", DIM, "click: start · t edit"
        line = Text()
        line.append(" S ", style="bold")
        line.append(f"{'seq':<7} ", style=DIM)
        line.append(f"{label:<8}", style=f"bold {col}" if q.on else DIM)
        line.append(f" {q.length:>3}s ")
        strip = q.strip()
        line.append("▕", style=DIM)
        if q.on and e.running:
            st = int(e.pos // (e.beat_len / 4)) % q.length
            line.append(strip[:st], style=CYAN)
            line.append(strip[st], style=f"reverse {CYAN}")
            line.append(strip[st + 1:], style=CYAN)
        else:
            line.append(strip, style=CYAN if q.on else DIM)
        line.append("▏    ", style=DIM)
        lvl = "▂▃▄▅▆▇█"[min(int(q.level * 7), 6)] if q.level > 0.02 else " "
        line.append(lvl, style=GREEN)
        line.pad_right(49 - len(line))
        line.append(f"{e.pages[11][1][4].text():>5} ")
        extra = ("rec " if q.rec else "") + (f"sw{50 + 25 * q.swing:.0f}" if q.swing > 0.01 else "")
        line.append(f"{extra:<6}", style=RED if q.rec else DIM)
        line.pad_right(61 - len(line))
        line.append(hint, style=DIM)
        t.append(line)
        return t

    def on_click(self, ev: events.Click):
        row = ev.y - 1
        n = len(self.e.tracks)
        if 0 <= row < n:
            self.e.post("mute" if 49 <= ev.x <= 54 else "tap", row)
        elif row == n:
            self.e.post("seq_mute" if 49 <= ev.x <= 54 else "seq_toggle")


class PadsPanel(Panel):
    """The 8 pads as on the device. Click a pad to press it; the bank and mode
    chips above switch what the drawing (and your clicks) do."""

    CW = 7

    def labels(self):
        from .app import pad_panel
        return pad_panel(self.e, self.mpk)

    def build(self):
        e, mpk = self.e, self.mpk
        title, labels = self.labels()
        t = Text()
        t.append(" PADS ", style="bold")
        for b in "AB":
            on = mpk.pad_bank == b
            t.append(f" {b} ", style=f"bold reverse {RED if b == 'A' else GREEN}" if on else DIM)
        t.append(" ")
        for m, name in (("note", "NOTE"), ("cc", "CC"), ("pc", "PROG")):
            on = mpk.pad_mode == m
            t.append(f" {name} ", style=f"bold reverse {FG}" if on else DIM)
        t.append("\n")
        t.append(" " + title[:32] + "\n", style=DIM)
        cw = self.CW
        for row, pads in enumerate(((4, 5, 6, 7), (0, 1, 2, 3))):
            t.append(" " + ("┌" + "┬".join(["─" * cw] * 4) + "┐" if row == 0 else "├" + "┼".join(["─" * cw] * 4) + "┤")
                     + "\n", style=DIM)
            num, lab = Text(" "), Text(" ")
            for p in pads:
                style = ""
                pressed = p in self.ui.pad_down
                if mpk.pad_mode == "note" and mpk.pad_bank == "A":
                    s = e.tracks[p].state
                    style = f"bold {COL[STATE[s][1]]}" if s != "empty" else DIM
                elif mpk.pad_mode == "pc" and mpk.pad_bank == "A" and p == e.page:
                    style = "reverse"
                elif mpk.pad_mode == "cc" and mpk.pad_bank == "A" and e.tracks[p].muted:
                    style = "reverse"
                elif mpk.pad_mode == "note" and mpk.pad_bank == "B":
                    h = e.seq.half * 8 + p
                    if (e.padb_mode == "Steps" and h < e.seq.length and e.seq.pattern[e.seq.lane, h]) or \
                            (e.padb_mode == "Scenes" and e.scene == p):
                        style = "reverse"
                if pressed:
                    style = f"reverse {ACCENT}"
                num.append("│", style=DIM)
                num.append(f"{p + 1}".ljust(cw), style=DIM if not pressed else style)
                lab.append("│", style=DIM)
                lab.append(labels[p][:cw].center(cw), style=style)
            num.append("│\n", style=DIM)
            lab.append("│\n", style=DIM)
            t.append(num)
            t.append(lab)
        t.append(" └" + "┴".join(["─" * cw] * 4) + "┘\n", style=DIM)
        t.append(" click pads · bank B mode: m", style=DIM)
        return t

    def _pad_at(self, x, y):
        if y < 3 or y > 8:
            return None
        row = 0 if y <= 5 else 1
        if (y - 3) % 3 == 0:
            return None  # border line
        c = (x - 2) // (self.CW + 1)
        if not 0 <= c <= 3:
            return None
        return (4, 5, 6, 7)[c] if row == 0 else (0, 1, 2, 3)[c]

    def on_click(self, ev: events.Click):
        if ev.y == 0:  # bank / mode chips
            mpk = self.mpk
            if 6 <= ev.x <= 8:
                mpk.pad_bank = "A"
            elif 9 <= ev.x <= 11:
                mpk.pad_bank = "B"
            elif 13 <= ev.x <= 18:
                mpk.pad_mode = "note"
            elif 19 <= ev.x <= 22:
                mpk.pad_mode = "cc"
            elif 23 <= ev.x <= 28:
                mpk.pad_mode = "pc"

    def on_mouse_down(self, ev: events.MouseDown):
        p = self._pad_at(ev.x, ev.y)
        if p is None:
            return
        e, mpk = self.e, self.mpk
        k = p if mpk.pad_bank == "A" else p + 8
        self.ui.pad_down[p] = time.monotonic()
        if mpk.pad_mode == "note":
            e.post("tap", e.tb(k)) if k < 8 else e.post("padb", k - 8, 110)
        elif mpk.pad_mode == "cc":
            e.post("mute", e.tb(k)) if k < 8 else e.post("undo", e.tb(k - 8))
        else:
            if k < 8:
                e.post("page", k)
            elif k < 15:
                e.post("category", k - 8)
            else:
                e.post("kit", 1)

    def on_mouse_up(self, ev: events.MouseUp):
        for p, t0 in list(self.ui.pad_down.items()):
            del self.ui.pad_down[p]
            if self.mpk.pad_mode != "note":
                continue
            if self.mpk.pad_bank == "A":
                if time.monotonic() - t0 >= HOLD_SECONDS:
                    self.e.post("clear", p)
            else:
                self.e.post("padb_off", p)


class KnobsPanel(Panel):
    """Page tabs (click to switch) and the 8 knobs: click in a bar to set it,
    scroll over a knob to nudge it."""

    KW = 31  # columns per knob cell

    def per_row(self):
        return 4 if self.size.width >= 4 * self.KW + 1 else 2

    def build(self):
        e, mpk = self.e, self.mpk
        t = Text(" ")
        for i, name in enumerate(PAGE_TABS):
            t.append(f" {name} ", style=f"bold reverse {ACCENT}" if i == e.page else DIM)
        t.append("\n")
        title, params = e.page_title(), e.visible_params()
        t.append(f" {title}", style="bold")
        t.append("  ←/→ · click a tab · PROG CHANGE + bank A pad" if e.page < 8 else "  ←/→ · click a tab (computer only)",
                 style=DIM)
        t.append("\n")
        pr = self.per_row()
        for r in range(8 // pr):
            line = Text(" ")
            for c in range(pr):
                k = r * pr + c
                p = params[k]
                pick = "" if mpk.knob_rel or e.pickup[k] else "~"
                cell = Text()
                cell.append(f"K{k + 1} ", style=DIM)
                cell.append(f"{p.label[:9]:<9} ", style="bold" if not pick else DIM)
                cell.append(bar(p.norm, 8, "▰", "▱", ""), style=ACCENT if not pick else DIM)
                cell.append(f" {pick + p.text():>7}", style="bold" if not pick else DIM)
                cell.pad_right(self.KW - len(cell))
                line.append(cell)
            t.append(line)
            if r < 8 // pr - 1:
                t.append("\n")
        return t

    def _knob_at(self, x, y):
        pr = self.per_row()
        if not 2 <= y < 2 + 8 // pr:
            return None, None
        c = (x - 1) // self.KW
        if not 0 <= c < pr:
            return None, None
        k = (y - 2) * pr + c
        off = (x - 1) % self.KW
        return k, off

    def on_click(self, ev: events.Click):
        if ev.y == 0:
            x = 1
            for i, name in enumerate(PAGE_TABS):
                w = len(name) + 2
                if x <= ev.x < x + w:
                    self.e.post("page", i)
                    return
                x += w
            return
        k, off = self._knob_at(ev.x, ev.y)
        if k is None:
            return
        p = self.e.visible_params()[k]
        if 13 <= off <= 20:  # the bar
            p.set_norm((off - 13 + 0.5) / 8)
            self.e.pickup[k] = True
        if self.e.on_page_change:
            self.e.on_page_change()

    def _scroll(self, ev, d):
        k, _ = self._knob_at(ev.x, ev.y)
        if k is not None:
            self.e.visible_params()[k].nudge(d)
            self.e.pickup[k] = True
            ev.stop()

    def on_mouse_scroll_up(self, ev):
        self._scroll(ev, 2)

    def on_mouse_scroll_down(self, ev):
        self._scroll(ev, -2)


class MixPanel(Panel):
    def build(self):
        e = self.e
        t = Text()
        if e.key_inst == "Sampler":
            t.append(f" SAMPLER: {e.sampler.name or 'empty'}"[:36].ljust(36), style=f"bold {MAGENTA}")
        else:
            t.append(f" SOUND {e.synth.patch['cat']}: {e.synth.patch['name']}"[:36].ljust(36), style="bold")
        t.append(f"KIT {e.kits[e.kit_index][0]:<12}", style="bold")
        t.append(f"voices {len(e.synth.voices) + len(e.sampler.voices):>2}  bend {e.synth.bend:+.1f}  mod {e.synth.mod:.1f}"
                 f"  {'SUS ' if e.synth.sustain else ''}{'press ' + format(e.pressure, '.1f') if e.pressure > 0.02 else ''}",
                 style=DIM)
        t.append("\n OUT ", style="bold")
        lv = max(e.levels)
        t.append(bar(lv, 30, "█", "░", ""), style=GREEN if lv < 0.95 else RED)
        if e.input_gain > 0.001:
            t.append(f"  INPUT on ({e.input_gain:.2f}) - use headphones", style=YELLOW)
        else:
            t.append("  input off (Global page, knob 4)", style=DIM)
        t.append("\n ")
        parts = [f"pad B: {e.padb_mode}", f"keys: {e.key_inst}"]
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
        t.append(" · ".join(parts), style=DIM)
        if self.ui.prefix:
            pk = self.ui.prefix[0]
            names = {"n": "scene 1-8?", "N": "store scene 1-8?", "y": "sample track 1-8?", "z": "solo 1-8?",
                     "c": "copy from 1-8?", "a": "name track 1-8?", "D": "double 1-8?", "H": "halve 1-8?"}
            t.append("   " + (names[pk] if pk in names else f"copy T{int(pk[1]) + 1 + 8 * self.e.track_bank} to 1-8?"),
                     style=f"bold {YELLOW}")
        t.append(f"   midi: {self.mpk.last_event[:40]}", style=DIM)
        return t


class LogPanel(Panel):
    DEFAULT_CSS = "LogPanel { height: 1fr; }"

    def build(self):
        t = Text(" LOG\n", style="bold")
        lines = max(self.size.height - 1, 1)
        now = time.time()
        for ts, msg in list(self.e.log)[-lines:]:
            age = now - ts
            style = f"bold {YELLOW}" if age < 3 else (FG if age < 30 else DIM)
            t.append(f" {datetime.fromtimestamp(ts):%H:%M:%S}  {msg}\n", style=style)
        return t


class FooterBar(Static):
    DEFAULT_CSS = f"FooterBar {{ height: auto; max-height: 3; background: {ACCENT}; color: #1a1405; padding: 0 1; }}"


# ---------------------------------------------------------------- modal dialogs

class Dialog(ModalScreen):
    DEFAULT_CSS = """
    Dialog { align: center middle; }
    Dialog > Vertical { width: auto; height: auto; max-width: 90%; max-height: 90%;
                        border: round $accent; background: $surface; padding: 1 2; }
    Dialog > Vertical > Static { width: auto; }
    Dialog .title { text-style: bold; color: $accent; }
    Dialog .hint { color: $text-muted; }
    Dialog Input { width: 50; margin: 1 0; }
    Dialog OptionList { height: auto; max-height: 20; width: 76; margin: 1 0; }
    """

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.e = ui.e

    def on_mount(self):
        # the name field / session list must own the keyboard, or typing and Enter go nowhere
        for w in self.query("Input, OptionList"):
            w.focus()
            if isinstance(w, OptionList) and w.option_count:
                w.highlighted = 0
            break

    def on_key(self, ev: events.Key):
        # Textual calls on_key for every class in the MRO, so subclasses implement
        # key() instead and this is the only handler. Keys never reach the main screen.
        if ev.key == "escape":
            self.dismiss()
        elif isinstance(self.focused, (Input, OptionList)):
            # Textual runs a field's bindings (Enter, arrows) only once the key has
            # bubbled up to the app, so don't stop it; LooperApp ignores it while a dialog is open
            return
        else:
            self.key(ev)
        ev.stop()
        ev.prevent_default()

    def key(self, ev):
        pass


class HelpDialog(Dialog):
    DEFAULT_CSS = "HelpDialog Static.body { height: auto; max-height: 85vh; overflow-y: auto; }"

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(HELP), classes="body")
            yield Static("Esc or h closes · L opens the lessons page in your browser", classes="hint")

    def key(self, ev):
        if ev.character == "h":
            self.dismiss()
        elif ev.character == "L":
            self.ui.open_lessons()


class QuitDialog(Dialog):
    def compose(self):
        with Vertical():
            yield Static("Quit?", classes="title")
            yield Static("You have loops that are not saved.")
            yield Static("s  save first      q  quit anyway      Esc  back", classes="hint")

    def key(self, ev):
        if ev.character == "q":
            self.app.exit()
        elif ev.character == "s":
            self.dismiss()
            self.app.push_screen(SaveDialog(self.ui, quit_after=True))


class SaveDialog(Dialog):
    def __init__(self, ui, quit_after=False):
        super().__init__(ui)
        self.quit_after = quit_after

    def compose(self):
        with Vertical():
            yield Static("Save session", classes="title")
            yield Input(value="" if self.e.session_demo else self.e.session_name, placeholder="name (empty = date)")
            yield Static("Enter  save        Esc  cancel", classes="hint")

    def on_input_submitted(self, ev: Input.Submitted):
        try:
            folder = save_session(self.e, ev.value)
            self.e.say(f"Saved '{self.e.session_name}' to {folder.name}")
        except Exception as ex:
            self.e.say(f"Save failed: {ex}")
        self.dismiss()
        if self.quit_after:
            self.app.exit()


class OpenDialog(Dialog):
    def compose(self):
        self.sessions = list_sessions()
        with Vertical():
            yield Static("Open session", classes="title")
            yield Static(Text(f"{'name':<28}tempo   tracks   type / date", style=DIM))
            if self.sessions:
                yield OptionList(*[self._row(s) for s in self.sessions])
            else:
                yield Static("No sessions yet.  Press g to render the demo loops, or record and press s.")
            yield Static("↑/↓ choose   Enter open (plays right away)   g render demos   Esc close", classes="hint",
                         id="foot")

    def _row(self, s):
        kind = "demo" if s["demo"] else datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
        return Text(f"{s['name'][:27]:<28}{s['tempo']:5.0f}   {s['tracks']:>3}      {kind}")

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected):
        s = self.sessions[ev.option_index]
        try:
            load_session(self.e, s["path"])
        except Exception as ex:
            self.e.say(f"Load failed: {ex}")
        self.dismiss()

    def key(self, ev):
        if ev.character == "g" and not self.ui.busy:
            self.ui.make_demos()
            self.dismiss()
        elif ev.character == "o":
            self.dismiss()


class SamplesDialog(Dialog):
    def compose(self):
        self.samples = list_samples()
        with Vertical():
            yield Static("Load sample", classes="title")
            if self.samples:
                yield OptionList(*[str(p.relative_to(SAMPLES)) for p in self.samples], markup=False)
            else:
                yield Static(f"No audio files in {SAMPLES}\nPut WAV/FLAC/OGG files there and press l again.")
            yield Static("↑/↓ choose   Enter load into the sampler   Esc close", classes="hint")

    def on_option_list_option_selected(self, ev):
        p = self.samples[ev.option_index]
        try:
            self.e.post("sample_set", read_sample(p, self.e.sr), p.stem)
        except Exception as ex:
            self.e.say(f"Could not load {p.name}: {ex}")
        self.dismiss()


class LibraryDialog(Dialog):
    """Browse synth sounds and drum kits: pick, favorite, save tweaks, delete."""

    DEFAULT_CSS = "LibraryDialog OptionList { width: 70; max-height: 24; }"

    def compose(self):
        self.rows = []
        with Vertical():
            yield Static("Sound library", classes="title", id="libtitle")
            yield OptionList(*self._build_rows(), markup=False)
            yield Static("↑/↓ browse (keys play it)  Enter pick  f favorite  n save knob tweaks as new sound\n"
                         "d delete/hide  R restore hidden  Esc close   · files: ~/Music/mpkloop/library",
                         classes="hint")

    def _build_rows(self):
        e, lib = self.e, self.e.lib
        self.rows, out = [], []
        for cat in CATEGORIES:
            idx = lib.members(cat)
            if not idx:
                continue
            out.append(f"── {cat.upper()} ──")
            self.rows.append(None)
            for i in idx:
                p = lib.patches[i]
                star = "★" if lib.is_fav(p) else " "
                cur = "▶" if i == e.synth.patch_index else " "
                out.append(f"{cur}{star} {p['name']:<22} {p['osc']:<7}{'user' if p['user'] else ''}")
                self.rows.append(("patch", i))
        out.append("── DRUM KITS ──")
        self.rows.append(None)
        for i, (name, sounds) in enumerate(lib.kits):
            m = lib.kit_meta[i]
            star = "★" if lib.is_fav_kit(name) else " "
            cur = "▶" if i == e.kit_index else " "
            out.append(f"{cur}{star} {name:<22} {m['info'][:30]:<30}{' user' if m['user'] else ''}")
            self.rows.append(("kit", i))
        return out

    def on_mount(self):
        self._refresh(("patch", self.e.synth.patch["name"]))

    def _row_of(self, item):
        """Row index of ("patch"|"kit", name)."""
        for i, r in enumerate(self.rows):
            if r and r[0] == item[0]:
                name = self.e.lib.patches[r[1]]["name"] if r[0] == "patch" else self.e.lib.kits[r[1]][0]
                if name == item[1]:
                    return i
        return 1

    def _refresh(self, item=None):
        ol = self.query_one(OptionList)
        ol.clear_options()
        ol.add_options(self._build_rows())
        ol.highlighted = self._row_of(item) if item else 1
        ol.focus()

    def _current(self):
        h = self.query_one(OptionList).highlighted
        return (h, self.rows[h]) if h is not None and self.rows[h] else (h, None)

    def _item(self, row):
        return (row[0], self.e.lib.patches[row[1]]["name"] if row[0] == "patch" else self.e.lib.kits[row[1]][0])

    def on_option_list_option_highlighted(self, ev):
        row = self.rows[ev.option_index] if ev.option_index is not None else None
        if row and row[0] == "patch":
            self.e.post("patch", row[1])          # audition: the keys play it right away
        elif row and row[0] == "kit":
            self.e.post("kit_set", row[1])

    def on_option_list_option_selected(self, ev):
        self.dismiss()

    def key(self, ev):
        pass

    def on_key(self, ev: events.Key):
        ch = ev.character
        h, row = self._current()
        lib = self.e.lib
        if ev.key == "escape":
            self.dismiss()
        elif ch == "f" and row:
            key = ("patch:" + lib.patches[row[1]]["name"]) if row[0] == "patch" else ("kit:" + lib.kits[row[1]][0])
            on = lib.toggle_fav(key)
            self.e.post("lib_reload")
            self.e.say(f"{'★ Favorite' if on else 'Unfavorited'}: {key.split(':', 1)[1]}")
            self._refresh(self._item(row))
        elif ch == "n":
            self.app.push_screen(SavePatchDialog(self.ui), lambda name: self._after_save(name))
        elif ch == "d" and row:
            if row[0] == "patch":
                p = lib.patches[row[1]]
                lib.delete_patch(p)
                self.e.say(f"{'Deleted' if p['user'] else 'Hidden'}: {p['name']}  (R restores hidden sounds)")
            else:
                name = lib.kits[row[1]][0]
                lib.delete_kit(row[1])
                self.e.say(f"Hidden kit: {name}  (R restores)")
            self.e.post("lib_reload")
            self.set_timer(0.15, lambda: self._refresh(None))
        elif ch == "R":
            lib.restore_all()
            self.e.post("lib_reload")
            self.e.say("Restored all hidden sounds and kits")
            self.set_timer(0.15, lambda: self._refresh(row and self._item(row)))
        else:
            return   # Enter / arrows go to the list
        ev.stop()
        ev.prevent_default()

    def _after_save(self, name):
        if name:
            self.e.post("lib_reload", ("patch", name))
            self.e.say(f"Saved sound '{name}' to the library")
            self.set_timer(0.2, lambda: self._refresh(("patch", name)))


class LabelDialog(Dialog):
    def __init__(self, ui, track):
        super().__init__(ui)
        self.track = track

    def compose(self):
        with Vertical():
            yield Static(f"Name for track {self.track + 1}", classes="title")
            yield Input(value=self.e.tracks[self.track].label, placeholder="e.g. Bass, Hook (max 12)")
            yield Static("Enter  set   Esc  cancel", classes="hint")

    def on_input_submitted(self, ev: Input.Submitted):
        self.e.post("label", self.track, ev.value.strip())
        self.dismiss()


class SavePatchDialog(Dialog):
    """Save the synth as it sounds now (patch + knob tweaks) under a new name."""

    def compose(self):
        with Vertical():
            yield Static("Save current sound as", classes="title")
            yield Input(value=self.e.synth.patch["name"] + " 2", placeholder="name")
            yield Static("Enter  save   Esc  cancel", classes="hint")

    def on_input_submitted(self, ev: Input.Submitted):
        name = ev.value.strip()
        if name:
            S = self.e.synth
            p = dict(S.patch)
            a = list(p["amp"])
            a[0], a[3] = S.attack, S.release
            p["amp"], p["cutoff"], p["reso"] = a, S.cutoff, S.reso
            self.e.lib.save_patch(p, name)
        self.dismiss(name)


class ExportDialog(Dialog):
    def compose(self):
        with Vertical():
            yield Static("Export", classes="title")
            yield Static("1  stems: one WAV per audible track + seq + mix\n2  MIDI: notes you played into each loop\n3  both")
            yield Static(f"→ {EXPORTS}/…   Esc cancel", classes="hint")

    def key(self, ev):
        if ev.character in ("1", "2", "3"):
            self.ui.run_export(stems=ev.character != "2", midi=ev.character != "1")
            self.dismiss()


class SeqGrid(Panel):
    """Clickable 8 x 16 step grid."""

    DEFAULT_CSS = "SeqGrid { width: 64; height: auto; }"

    def build(self):
        e, q = self.e, self.e.seq
        t = Text("            " + " ".join(f"{c + 1:<2}" if c % 4 == 0 else "  " for c in range(16)) + "\n", style=DIM)
        play = int(e.pos // (e.beat_len / 4)) % q.length if q.on and e.running else -1
        for lane in range(8):
            name = e.kits[e.kit_index][1][lane][0]
            t.append(f"{name[:10]:<10}  ", style="bold" if lane == self.ui.cur[0] else DIM)
            for c in range(16):
                if c >= q.length:
                    t.append("   ", style=DIM)
                    continue
                v = int(q.pattern[lane, c])
                style = f"bold {CYAN}" if v else (DIM if c % 4 else FG)
                if c == play:
                    style = f"bold {YELLOW}"
                if [lane, c] == self.ui.cur:
                    style += " reverse"
                t.append(f" {VEL_CELL[v]} ", style=style)
            t.append("\n")
        return t

    def cell_at(self, x, y):
        lane, c = y - 1, (x - 12) // 3
        if 0 <= lane < 8 and 0 <= c < self.e.seq.length and x >= 12:
            return lane, c
        return None

    def on_click(self, ev: events.Click):
        cell = self.cell_at(ev.x, ev.y)
        if cell is None:
            return
        lane, c = cell
        self.ui.cur = [lane, c]
        v = int(self.e.seq.pattern[lane, c])
        if ev.button == 3:
            self.e.post("seq_set", lane, c, v % 3 + 1)   # right click: velocity
        else:
            self.e.post("seq_set", lane, c, 0 if v else 2)
        self.e.post("seq_lane", lane, True)


class SeqDialog(Dialog):
    def compose(self):
        with Vertical():
            yield Static("", id="seqtitle", classes="title")
            yield SeqGrid(self.ui)
            yield Static("", id="seqfoot", classes="hint")

    def on_mount(self):
        self.set_interval(1 / 8, self.tick)
        self.tick()

    def tick(self):
        e, q = self.e, self.e.seq
        run = ("▶ running" if q.on else "■ off") + ("  ● rec" if q.rec else "")
        title = f"Step sequencer · {e.kits[e.kit_index][0]} · {run}"
        foot = (f"swing {50 + 25 * q.swing:.0f}%   length {q.length}   vol {e.pages[11][1][4].text()}   (knobs: SEQ page)\n"
                "click: toggle · right-click: soft/normal/accent · arrows move · space toggle · v velocity\n"
                "c clear lane · T run/stop · r record pads · k kit · Esc close")
        if (title, foot) != getattr(self, "_texts", None):
            self._texts = (title, foot)
            self.query_one("#seqtitle", Static).update(title)
            self.query_one("#seqfoot", Static).update(foot)
        self.query_one(SeqGrid).tick()

    def key(self, ev):
        e, q, cur = self.e, self.e.seq, self.ui.cur
        lane, col = cur
        ch = ev.character
        if ev.key in ("up", "down"):
            cur[0] = (lane + (1 if ev.key == "down" else -1)) % 8
            e.post("seq_lane", cur[0], True)
        elif ev.key in ("left", "right"):
            cur[1] = (col + (1 if ev.key == "right" else -1)) % q.length
        elif ev.key in ("space", "enter"):
            e.post("seq_set", lane, col, 0 if q.pattern[lane, col] else 2)
        elif ch == "v":
            e.post("seq_set", lane, col, int(q.pattern[lane, col]) % 3 + 1)
        elif ch == "c":
            e.post("seq_clear_lane", lane)
        elif ch == "T":
            e.post("seq_toggle")
        elif ch == "r":
            e.post("seq_rec")
        elif ch == "k":
            e.post("kit", 1)
        elif ch == "t":
            self.dismiss()


# ---------------------------------------------------------------- the app

class LooperApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS = f"""
    Screen {{ layout: vertical; }}
    #top {{ height: auto; }}
    TracksPanel {{ width: 1fr; min-width: 78; }}
    PadsPanel {{ width: 36; }}
    #tracks, #knobs, #mix {{ border-top: solid $panel; }}
    """
    BINDINGS = []

    def __init__(self, e, mpk, bouncer, stream_info, stream=None):
        super().__init__()
        self.e, self.mpk, self.bouncer, self.stream_info, self.stream = e, mpk, bouncer, stream_info, stream
        self.busy = ""
        self.prefix = None
        self.cur = [0, 0]
        self.pad_down = {}
        self.confirm_clear = 0.0

    def compose(self) -> ComposeResult:
        yield HeaderBar(self, id="header")
        with Horizontal(id="top"):
            yield TracksPanel(self, id="tracks")
            yield PadsPanel(self, id="pads")
        yield KnobsPanel(self, id="knobs")
        yield MixPanel(self, id="mix")
        yield LogPanel(self, id="log")
        yield FooterBar("space play · 1-8 tap · Shift+1-8 mute · B tracks 9-16 · z solo · c copy · a name · D/H double/halve · "
                        "←/→ page · [ ] sound · k kit · u library · m pad B mode · t/T seq · r rec steps · P print · n/N scene · "
                        "x/X fx · i/y/Y/l sampler · e export · o open · s save · b bounce · L lessons · h help · q quit")

    def on_mount(self):
        self.theme = "textual-dark"
        fps = float(os.environ.get("MPKLOOP_FPS", "12"))
        if fps > 0:
            self.set_interval(1 / fps, self.tick)
        if self.stream is not None:
            self.set_timer(0.5, self.stream.start)   # after the first frames: no xruns while mounting
        if LESSONS.exists():
            self.e.say("Press L to open the lessons in your browser, h for help")

    def tick(self):
        if len(self.screen_stack) > 1:
            return  # a dialog is open: it ticks itself; redrawing underneath it costs audio time
        for w in self.screen_stack[0].query(Panel):
            w.tick()
        if self.prefix and time.time() - self.prefix[1] > 4:
            self.prefix = None

    # ------------------------------------------------------------ keys

    def on_key(self, ev: events.Key):
        if isinstance(self.screen, Dialog):
            return
        if self.handle_key(ev):
            ev.stop()
            ev.prevent_default()

    def handle_key(self, ev):
        e = self.e
        ch, key = ev.character, ev.key
        if self.prefix:
            pk, t0 = self.prefix
            self.prefix = None
            if ch and ch in "12345678" and time.time() - t0 < 4:
                k = int(ch) - 1
                if pk in ("n", "N"):
                    e.post({"n": "scene_recall", "N": "scene_store"}[pk], k)
                elif pk == "y":
                    e.post("sample_track", e.tb(k))
                elif pk == "z":
                    e.post("solo", e.tb(k))
                elif pk == "D":
                    e.post("double", e.tb(k))
                elif pk == "H":
                    e.post("halve", e.tb(k))
                elif pk == "c":
                    self.prefix = (f"c{k}", time.time())
                    e.say(f"Copy T{e.tb(k) + 1} to which track? Press 1-8 (empty track)")
                elif pk.startswith("c"):
                    e.post("copy", e.tb(int(pk[1])), e.tb(k))
                elif pk == "a":
                    self.push_screen(LabelDialog(self, e.tb(k)))
                return True
        if ch in ("n", "N", "y", "z", "c", "a", "D", "H"):
            self.prefix = (ch, time.time())
            e.say({"n": "Recall scene: press 1-8", "N": "Store scene: press 1-8", "y": "Sample track: press 1-8",
                   "z": "Solo track: press 1-8", "c": "Copy track: press the source 1-8", "a": "Name track: press 1-8",
                   "D": "Double loop: press 1-8", "H": "Halve loop: press 1-8"}[ch])
        elif ch == "B":
            e.post("track_bank")
        elif ch == "Z":
            e.post("unsolo")
        elif ch == "q":
            if e.changed and any(t.length for t in e.tracks):
                self.push_screen(QuitDialog(self))
            else:
                self.exit()
        elif key == "space":
            e.post("transport")
        elif ch and ch in "12345678":
            e.post("tap", e.tb(int(ch) - 1))
        elif ch and ch in "!@#$%^&*":
            e.post("mute", e.tb("!@#$%^&*".index(ch)))
        elif key == "right":
            e.post("page", e.page + 1)
        elif key == "left":
            e.post("page", e.page - 1)
        elif ch == "]":
            e.post("patch", e.synth.patch_index + 1)
        elif ch == "[":
            e.post("patch", e.synth.patch_index - 1)
        elif ch == "k":
            e.post("kit", 1)
        elif ch == "h":
            self.push_screen(HelpDialog(self))
        elif ch == "L":
            self.open_lessons()
        elif ch == "p":
            e.post("panic")
            e.say("All synth notes stopped")
        elif ch == "C":
            if time.time() - self.confirm_clear < 2:
                e.post("clear_all")
                self.confirm_clear = 0
            else:
                self.confirm_clear = time.time()
                e.say("Clear ALL tracks? Press C again within 2 s")
        elif ch == "s":
            if not any(t.length for t in e.tracks):
                e.say("Nothing to save yet - record a loop first")
            else:
                self.push_screen(SaveDialog(self))
        elif ch == "o":
            self.push_screen(OpenDialog(self))
        elif ch == "m":
            e.post("padb_mode")
        elif ch == "t":
            self.cur = [e.seq.lane, self.cur[1]]
            self.push_screen(SeqDialog(self))
        elif ch == "T":
            e.post("seq_toggle")
        elif ch == "r":
            e.post("seq_rec")
        elif ch == "(":
            e.post("seq_mute")
        elif key == "tab":
            e.post("seq_half")
        elif key == "shift+tab":
            e.post("seq_lane", e.seq.lane + 1)
        elif ch == "P":
            e.post("seq_print")
        elif ch == "x":
            e.post("stutter_cycle")
        elif ch == "X":
            e.post("tapestop", None)
            e.say("Tape stop" if e.tape_target == 1.0 else "Tape start")
        elif ch == "i":
            e.post("key_inst")
        elif ch == "Y":
            e.post("sample_rec")
        elif ch == "l":
            self.push_screen(SamplesDialog(self))
        elif ch == "u":
            self.push_screen(LibraryDialog(self))
        elif ch == "e":
            if self.busy:
                e.say("Busy: " + self.busy)
            elif not any(t.length for t in e.tracks) and not e.seq.on:
                e.say("Nothing to export yet")
            else:
                self.push_screen(ExportDialog(self))
        elif ch == "b":
            if self.bouncer.active:
                self.bouncer.stop()
                e.say(f"Bounce saved: {self.bouncer.path.name}")
            else:
                self.bouncer.start()
                e.say(f"Bouncing everything you hear to {self.bouncer.path.name}")
        else:
            return False
        return True

    # ------------------------------------------------------------ jobs

    def open_lessons(self):
        if LESSONS.exists():
            webbrowser.open(LESSONS.as_uri())
            self.e.say("Lessons opened in your browser (Connect MPK there; mpkloop keeps running)")
        else:
            self.e.say(f"lessons.html not found next to the package ({LESSONS})")

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
        threading.Thread(target=job, daemon=True).start()


def run_tui(e, mpk, bouncer, stream_info, stream=None):
    LooperApp(e, mpk, bouncer, stream_info, stream).run()
    if stream is not None:
        stream.stop()
