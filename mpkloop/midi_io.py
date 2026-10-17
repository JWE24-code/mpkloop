"""MPK mini 3 connection: preset readout (SysEx), live mapping, OLED/knob sync,
and MIDI clock out so the device's arpeggiator / note repeat lock to the loops. In clock-follow
mode (Switchbox) the clock comes in instead: it is handed to the engine's ClockFollower."""
import queue
import re
import threading
import time

import mido

# Offsets inside the preset SysEx payload (after F0, without F7).
# 47 00 49 67 01 76 <prog> <name x16> <20 settings bytes> <16 pads x3> <8 knobs x20> <transpose>
NAME = 7
SET = NAME + 16
PADCH, AFTERTOUCH, KEYCH, OCTAVE, ARP_ON, ARP_MODE, ARP_DIV, ARP_CLOCK = range(SET, SET + 8)
JOY_X_MODE, JOY_X_POS, JOY_X_NEG, JOY_Y_MODE, JOY_Y_POS, JOY_Y_NEG = range(SET + 14, SET + 20)
PADS = SET + 20
KNOBS = PADS + 48
KNOB_SIZE = 20
PRESET_LEN = KNOBS + 8 * KNOB_SIZE + 1

DEFAULT_MAP = dict(
    name="(defaults)", pad_ch=9, key_ch=0,
    pad_notes=list(range(36, 52)), pad_pcs=list(range(16)), pad_ccs=list(range(16, 32)),
    knob_ccs=list(range(70, 78)), joy_y_cc=1, aftertouch=1,
)


def parse_preset(d):
    pads = [d[PADS + 3 * i: PADS + 3 * i + 3] for i in range(16)]
    knobs = [d[KNOBS + KNOB_SIZE * i: KNOBS + KNOB_SIZE * (i + 1)] for i in range(8)]
    return dict(
        name=bytes(d[NAME:NAME + 16]).rstrip(b"\0").decode("ascii", "replace"),
        pad_ch=d[PADCH], key_ch=d[KEYCH], aftertouch=d[AFTERTOUCH],
        pad_notes=[p[0] for p in pads], pad_pcs=[p[1] for p in pads], pad_ccs=[p[2] for p in pads],
        knob_ccs=[k[1] for k in knobs], knob_modes=[k[0] for k in knobs],
        joy_y_cc=d[JOY_Y_POS] if d[JOY_Y_MODE] != 0 else None,
        arp_clock_ext=bool(d[ARP_CLOCK]),
    )


def _text(s, n=16):
    return list(s.encode("ascii", "replace")[:n].ljust(n, b"\0"))


def _pick(names, hint):
    """Port called `hint` (tolerating 'Client:' prefixes and ' N' / ' N:M' suffixes), else the first
    one containing it. Exact first so 'mpkloop' never lands on 'mpkloop-ret'."""
    rx = re.compile(r"^(?:.*:)?" + re.escape(hint) + r"(?:\s+\d+(?::\d+)?)?$", re.I)
    exact = [n for n in names if rx.match(n)]
    if exact:
        return exact[0]
    sub = [n for n in names if hint.lower() in n.lower()]
    return sub[0] if sub else None


def find_ports(hint="MPK"):
    """hint is 'name' for both directions or 'in_name,out_name' (Windows loopMIDI: 'mpkloop,mpkloop-ret')."""
    in_hint, _, out_hint = hint.partition(",")
    return _pick(mido.get_input_names(), in_hint), _pick(mido.get_output_names(), out_hint or in_hint)


class MPK:
    def __init__(self, engine, port_hint="MPK", device_sync=True, ext_clock=True, monitor=None,
                 send_clock=True):
        self.engine = engine
        self.device_sync = device_sync
        self.ext_clock = ext_clock
        self.send_clock = send_clock    # False when following an external clock (Switchbox feeds the MPK)
        self.monitor = monitor          # optional callable(msg) for --monitor
        self.inp = self.out = None
        self.map = dict(DEFAULT_MAP)
        self.original = None            # preset in device RAM before we touched it
        self.sysex_replies = queue.Queue()
        self.send_lock = threading.Lock()
        self.pad_down = {}
        self.knob_rel = False
        self.last_event = ""
        self.pad_bank = "A"      # inferred from the last pad press
        self.pad_mode = "note"   # note / cc / pc
        self.connected_name = None
        self._sync_req = threading.Event()
        self._alive = True

        in_name, out_name = find_ports(port_hint)
        if not in_name:
            return
        self.inp = mido.open_input(in_name, callback=self._on_msg)
        if out_name:
            self.out = mido.open_output(out_name)
        self.connected_name = in_name

        self.original = self.read_preset()
        if self.original:
            self.map.update(parse_preset(self.original))
            self.knob_rel = device_sync
        else:
            self.device_sync = False
        if self.out and self.send_clock:
            threading.Thread(target=self._clock_thread, daemon=True).start()
        if self.device_sync:
            engine.on_page_change = self._sync_req.set
            threading.Thread(target=self._sync_thread, daemon=True).start()
            self._sync_req.set()

    # ------------------------------------------------------------ sysex

    def send(self, msg):
        if self.out:
            with self.send_lock:
                self.out.send(msg)

    def read_preset(self, timeout=1.0):
        if not self.out:
            return None
        while not self.sysex_replies.empty():
            self.sysex_replies.get_nowait()
        self.send(mido.Message("sysex", data=[0x47, 0x7F, 0x49, 0x66, 0x00, 0x01, 0x00]))
        try:
            d = list(self.sysex_replies.get(timeout=timeout))
        except queue.Empty:
            return None
        return d if len(d) == PRESET_LEN else None

    def write_preset(self, d):
        self.send(mido.Message("sysex", data=[0x47, 0x7F, 0x49, 0x64] + list(d[4:])))

    def _sync_thread(self):
        """Push the current knob page to the device RAM preset: OLED shows the page
        and parameter names, knobs go relative, arp follows our clock."""
        while self._alive:
            self._sync_req.wait()
            self._sync_req.clear()
            time.sleep(0.03)  # coalesce bursts
            if not self._alive:
                break
            cur = self.read_preset(0.5) or self.original
            d = list(cur)
            e = self.engine
            title, params = e.page_title(), e.visible_params()
            d[NAME:NAME + 16] = _text(f"{title[:7]}|{e.synth.patch['name']}")
            for k, p in enumerate(params):
                base = KNOBS + KNOB_SIZE * k
                d[base] = 1                       # relative mode
                d[base + 1] = self.map["knob_ccs"][k]
                d[base + 2], d[base + 3] = 0, 127
                d[base + 4: base + 20] = _text(p.label)
            if self.ext_clock:
                d[ARP_CLOCK] = 1
            self.write_preset(d)

    def restore(self):
        """Put back what we changed (name, knobs, arp clock), keep the rest
        (octave etc.) as the user left it."""
        self._alive = False
        self._sync_req.set()
        if not (self.device_sync and self.original):
            return
        cur = self.read_preset(0.5)
        d = list(cur) if cur else list(self.original)
        o = self.original
        d[NAME:NAME + 16] = o[NAME:NAME + 16]
        d[KNOBS:KNOBS + 8 * KNOB_SIZE] = o[KNOBS:KNOBS + 8 * KNOB_SIZE]
        d[ARP_CLOCK] = o[ARP_CLOCK]
        self.write_preset(d)
        time.sleep(0.1)

    def close(self):
        self.restore()
        if self.out and self.send_clock:
            self.send(mido.Message("stop"))
        for p in (self.inp, self.out):
            if p:
                p.close()

    # ------------------------------------------------------------ clock

    def _clock_thread(self):
        """24 ppqn MIDI clock, phase-locked to the audio transport. Ticks are sent
        one audio block early so arp notes coming back land on the grid."""
        e = self.engine
        gen = e.transport_gen
        was_running = False
        tick = 0
        free_t = time.perf_counter()
        while self._alive:
            if e.running:
                if not was_running or gen != e.transport_gen:
                    gen = e.transport_gen
                    self.send(mido.Message("start"))
                    tick = 0
                    was_running = True
                ref_pos, ref_t = e.clock_ref
                tick_pos = tick * e.beat_len / 24.0
                when = ref_t + (tick_pos - ref_pos) / e.sr
                now = time.perf_counter()
                if when > now:
                    time.sleep(min(when - now, 0.01))
                    continue
                if when - now > -0.05:  # skip ticks we are hopelessly late for
                    self.send(mido.Message("clock"))
                tick += 1
            else:
                if was_running:
                    self.send(mido.Message("stop"))
                    was_running = False
                # free-run so the arp keeps going while the transport is stopped
                period = 60.0 / e.tempo / 24.0
                now = time.perf_counter()
                if now < free_t:
                    time.sleep(min(free_t - now, 0.01))
                    continue
                self.send(mido.Message("clock"))
                free_t = max(free_t + period, now - period)

    # ------------------------------------------------------------ input mapping

    def _decode_rel(self, v):
        if 48 <= v <= 80:           # offset-64 encoding
            return v - 64
        return v if v < 64 else v - 128  # two's complement

    def _on_msg(self, msg):
        if msg.type == "sysex":
            d = msg.data
            if len(d) > 4 and d[0] == 0x47 and d[2] == 0x49 and d[3] == 0x67:
                self.sysex_replies.put(d)
            return
        if msg.type in ("clock", "start", "stop", "continue"):
            f = self.engine.follower
            if f is not None:
                f.on_message(msg.type)      # timestamp taken here, as close to the port as we can get
            return
        if msg.type == "active_sensing":
            return
        if self.monitor:
            self.monitor(msg)
        m, e = self.map, self.engine
        ch = getattr(msg, "channel", None)
        self.last_event = str(msg)
        on_pads = ch == m["pad_ch"]
        t = msg.type
        if t == "note_on" and msg.velocity == 0:
            t = "note_off"

        if t == "note_on":
            if on_pads and msg.note in m["pad_notes"]:
                k = m["pad_notes"].index(msg.note)
                self.pad_bank, self.pad_mode = ("A" if k < 8 else "B"), "note"
                if k < 8:
                    self.pad_down[k] = time.monotonic()
                    e.post("tap", e.tb(k))
                else:
                    e.post("padb", k - 8, msg.velocity)
            else:
                e.post("note_on", msg.note, msg.velocity)
        elif t == "note_off":
            if on_pads and msg.note in m["pad_notes"]:
                k = m["pad_notes"].index(msg.note)
                t0 = self.pad_down.pop(k, None)
                if k < 8 and t0 is not None and time.monotonic() - t0 >= 0.7:
                    e.post("clear", e.tb(k))
                elif k >= 8:
                    e.post("padb_off", k - 8)
            else:
                e.post("note_off", msg.note)
        elif t == "control_change":
            c, v = msg.control, msg.value
            if c in m["knob_ccs"] and not (on_pads and c in m["pad_ccs"]):
                k = m["knob_ccs"].index(c)
                if self.knob_rel:
                    e.post("knob_rel", k, self._decode_rel(v))
                else:
                    e.post("knob_abs", k, v)
            elif on_pads and c in m["pad_ccs"]:
                k = m["pad_ccs"].index(c)
                self.pad_bank, self.pad_mode = ("A" if k < 8 else "B"), "cc"
                if v > 0:
                    e.post("mute", e.tb(k)) if k < 8 else e.post("undo", e.tb(k - 8))
            elif c == 64:
                e.post("sustain", v >= 64)
            elif c == (m["joy_y_cc"] or 1):
                e.post("mod", v / 127.0)
            elif c == 123 or c == 120:
                e.post("panic")
        elif t == "pitchwheel":
            e.post("bend", msg.pitch / 8192.0)
        elif t == "program_change" and msg.program in m["pad_pcs"]:
            k = m["pad_pcs"].index(msg.program)
            self.pad_bank, self.pad_mode = ("A" if k < 8 else "B"), "pc"
            if k < 8:
                e.post("page", k)
            elif k < 15:
                e.post("category", k - 8)
            else:
                e.post("kit", 1)
        elif t in ("aftertouch", "polytouch"):
            e.post("pressure", msg.value / 127.0)
