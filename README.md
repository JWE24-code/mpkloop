# mpkloop

A 16-track live looper with its own synth, drum kits, step sequencer, sampler and
effects. You play it from an **Akai MPK mini 3** and a few computer keys.

The idea: tap a pad, play something, tap again. That part now repeats. Add another
part on the next pad. Keep going until it's a song. No mouse needed, no menus.

Install: `python -m venv .venv && .venv/bin/pip install -r requirements.txt`, then
`ln -s "$PWD/mpkloop.sh" ~/.local/bin/mpkloop`.

```
mpkloop                 # start (or ./mpkloop.sh)
mpkloop --classic       # the simpler old screen (uses less CPU)
mpkloop --make-demos    # (re)render the four demo sessions
mpkloop --block 256     # lower latency; use 1024 if you hear crackles
mpkloop --list          # show audio + MIDI devices
mpkloop --monitor       # print incoming MIDI (check your preset)
mpkloop --midi Switchbox:mpkloop   # follow the Switchbox clock (see "Clock" below)
```

In the app: `h` shows every key, `L` opens the **lessons** in your browser (English
and Dutch, with three songs to make step by step).

## The MPK, button by button

| On the MPK | What it does |
|---|---|
| **Keys** | Play the current sound. Harder = louder. OCT −/+ move up and down. |
| **Bank A pads** | Your loop tracks. Tap: record → play → overdub → play. Hold about a second: clear. |
| **Bank B pads** | Drums. Bottom row pads 1–4, top row 5–8. Squeeze a pad after the hit: filter sweep over everything. |
| **CC** button | Pads become mix buttons: bank A mutes a track (on the next beat), bank B undoes the last overdub. Press CC again to leave. |
| **PROG CHANGE** button | Pads become choosers: bank A picks the knob page, bank B pads 1–7 pick a sound category (tap again for the next sound) and pad 8 the next drum kit. Press again to leave. |
| **Knobs 1–8** | Whatever the current page says. The MPK's screen shows the name and value. |
| **Joystick** | Left/right bends the pitch. Up adds vibrato and opens the filter. |
| **ARP / NOTE REPEAT** | Work as usual and follow the loop tempo (or the Switchbox clock, see "Clock"). |
| **Sustain pedal** | Holds synth notes. |
| **PROG SELECT** | Leave it alone while mpkloop runs. |

**16 tracks, 8 pads.** The pads and the computer keys 1–8 work on tracks 1–8 or
9–16. `B` switches. The top line of the screen says which ("pads: T9-16"), and
the track table marks the active eight.

## Knob pages

Bank A + PROG CHANGE picks the first eight pages; `←` `→` reach them all.

| Page | Knob N is… |
|---|---|
| Volume, Pan, Filter, Speed, Delay, Reverb | …that setting for track N (of the current 8). Filter: left muffles, right thins. Speed: reverse, half, double. |
| Sound | Cutoff, Resonance, Attack, Release, Synth Vol, Drum Vol, Live Delay, Live Reverb |
| Global | Tempo, Rec Mode, Metronome, Input Gain, Delay Time, Delay Feedback, Reverb Size, Master |
| Track FX, FX Amount, Duck | one effect per track (Crush, Drive, Chorus, Tape, Comb), how much, and how much the track ducks on every kick |
| Seq | Lane, Swing, Length, Kit, Seq Vol, Seq Pan, Seq Delay, Seq Reverb |
| Sampler | Pitch, Start, Length, Attack, Release, Volume, Filter, Reverse |

Tempo locks as soon as a loop exists. Set it first (Global, knob 1), or use rec
mode **Free→Tempo**: then your first loop decides the tempo. (Following an external
clock, the clock decides: the Tempo knob shows `ext`, see "Clock".)

## Computer keys

| Key | Does |
|---|---|
| `space` | start / stop (following a clock: starts/stops mpkloop only, never the shared clock) |
| `1`–`8` | same as tapping a loop pad · `Shift`+`1`–`8` mute on the next beat |
| `B` | pads and keys 1–8 address tracks 9–16 (press again: 1–8) |
| `z`+`1`–`8` solo a track · `Z` | solo off for all |
| `c`+`1`–`8`+`1`–`8` | copy a track to an empty one |
| `D`+`1`–`8` / `H`+`1`–`8` | double / halve a loop (undo restores) |
| `a`+`1`–`8` | name a track (shows in the table and the exports) |
| `←` `→` | knob page · `[` `]` sound · `k` drum kit · `u` sound library |
| `m` | what bank B pads do: Drums → Steps → Chops → Scenes → FX |
| `T` `t` `r` `(` `P` | sequencer on/off · grid editor · live record into steps · mute the lane · print it to a track |
| `Tab` / `Shift-Tab` | step pads edit steps 9–16 / next lane |
| `N`+`1`–`8` / `n`+`1`–`8` | store a scene / recall it on the next bar |
| `x` / `X` | beat repeat off → 1/4 → 1/8 → 1/16 / tape stop |
| `i` `y`+`1`–`8` `Y` `l` | keys play synth↔sampler · take a loop into the sampler · sample the input · load a file |
| `e` | export: `1` stems, `2` MIDI, `3` both |
| `o` `s` `b` | open a session · save · bounce to WAV on/off |
| `C` `C` / `p` / `q` | clear everything (twice) · stuck notes off · quit |
| mouse | click a track row to tap it, its volume to mute; click pads, page tabs and knob bars; scroll over a knob |

## Recording

- Everything you play live (keys, drums, chops, mic if Input Gain is up) goes into
  the track that's recording. Loops never record each other.
- **Quantize** (default): the first loop gets a 1-bar count-in; after that recording
  starts and stops on bar lines. Pressing just after a downbeat still counts.
- **Free→Tempo**: the first loop starts and stops exactly when you tap; the tempo
  comes from its length. (Not available while following a clock: it records like Quantize.)
- **1/2/4/8 bars**: one tap records exactly that many bars.
- Tracks can have different lengths. A 1-bar beat under a 4-bar chord loop is fine.
- Mutes land on the next beat so they stay in time. Solo (`z`) lets you hear one
  track; `Z` brings everything back.

## Sound library

102 synth sounds in 7 categories and 12 drum kits. On the MPK: PROG CHANGE,
bank B, pads 1–7 are the categories (Pads, Keys, Bass, Leads, Plucks, Bells,
Organ+), tap again for the next sound, pad 8 is the next kit. Favorites come first.

Kits: Classic, 808, 909, Electro, Lo-Fi, Trap, Techno, Breaks, Dub, Glitch, Jazz,
Percussion. Bottom row pads 1–4 are kick, snare, hat, open hat in most kits.

**Library screen** (`u`): browse with ↑/↓ while the keys play what you point at.
`Enter` keeps it. `f` favorite ★. `n` saves the synth *as it sounds now* (your knob
tweaks included) as a new sound. `d` deletes a user sound or hides a factory one,
`R` restores everything hidden.

**Add your own.** Everything lives in `~/Music/mpkloop/library/`:

- `patches/<name>.json`: one synth sound, same fields as `mpkloop/factory/patches.json`
  (`osc`: saw2 super saw1 square pulse tri sine bass fm organ; `amp`/`fenv` ADSR;
  `cutoff`, `reso`, `gain`; extras `detune`, `sub`, `pw`, `intervals`, `noise`, `vib`,
  `ratio`/`index`). Copy one, change it, save it.
- `kits/<name>/` with **8 audio files** (WAV/FLAC/OGG, sorted by name = pad order) is a
  kit. Optional `kit.json` with `names` and `pans`.
- `kits/<name>/kit.json` with a `voices` list is a synthesized kit using the generators in
  `mpkloop/drumsynth.py` (`mpkloop/factory/kits.json` has twelve examples).
- A user sound with the same name as a factory one replaces it. Favorites and hidden
  sounds are in `library.json`. Sessions remember sounds by name.

## Step sequencer, scenes, effects, sampler

`m` decides what the **bank B pads** do in normal mode:

| `m` mode | Bank B pads |
|---|---|
| Drums | play the kit (default) |
| Steps | toggle steps 1–8 of the selected lane (`Tab`: 9–16, `Shift-Tab`: next lane) |
| Chops | play the 8 slices of the sample |
| Scenes | tap: recall scene 1–8 on the next bar · hold: store it |
| FX | hold: 1–4 beat repeat 1/2 1/4 1/8 1/16 · 5 tape stop · 6 reverse · 7 half speed · 8 crush |

- **Step sequencer**: row **S** in the track table. 8 lanes (the kit's sounds) × 8/12/16
  sixteenth steps, soft/normal/accent, swing. Its own volume and sends, never recorded
  into loops. `T` on/off, `t` grid (arrows, space, `v` velocity, `c` clear lane), `r` live
  record, `(` mute, `P` prints one cycle onto the first empty track as audio.
- **Scenes**: a snapshot of every track's volume, pan, filter, mute, sends, FX, duck and the
  sequencer's volume/mute. `N`+1–8 stores, `n`+1–8 recalls on the next bar.
- **Track FX**: Crush, Drive, Chorus, Tape, Comb per track; **Duck** dips a track on every
  kick. **Perform FX** (`x`, `X`, or the FX pads) hit everything at once and snap back to the grid.
- **Sampler**: one sample, played from the keys (C4 = original pitch) or as 8 chops on the
  pads. `y`+N grabs a loop, `Y` records the input (up to 10 s), `l` loads a file from
  `~/Music/mpkloop/samples/`. Chops are recorded into loops like drums.

## Saving, exporting, demos

- `s` saves a session to `~/Music/mpkloop/sessions/<date>-<name>/` (a WAV per track plus
  `session.json` with pattern, scenes, FX, sample, notes and names). `o` opens one.
- Four **demo sessions** come along (Lo-Fi Chill, House Groove, Electro Acid, Ambient
  Drift); `g` in the picker re-renders them.
- `b` records everything you hear to `~/Music/mpkloop/bounces/`.
- `e` exports to `~/Music/mpkloop/exports/<date>-<name>/`: one WAV per track plus
  `seq.wav` and `mix.wav` (the stems add up to the mix), and `loops.mid` with the notes
  you played (synth ch 1, sampler ch 3, chops ch 4, drums ch 10, GM numbers).

## Clock: master or follower

`--clock master` (the default unless the MIDI port is Switchbox's): the first loop sets the
tempo and mpkloop sends MIDI clock/start/stop to the MPK, so its arp locks to the loops.

`--clock follow` (default when `--midi` contains `mpkloop`, i.e. `--midi Switchbox:mpkloop`, or
`mpkloop,mpkloop-ret` on Windows) makes mpkloop a slave of the shared 24 ppqn clock that
Switchbox (a MIDI router, not part of this repo) broadcasts to every app. mpkloop then sends **no** clock
to the MPK (Switchbox feeds the arp; the `ARP_CLOCK` external flag is still set by device sync).

- **Tempo**: smoothed from the tick arrival times (least-squares over 4 to 16 beats, outlier
  ticks rejected, a tempo change is picked up within a few seconds, snapped to 0.1 BPM like
  Switchbox's tempos). It goes into the engine while no loop exists; the Tempo knob shows `ext`.
  Loops that already exist keep their length: if the clock tempo moves afterwards you get a
  message, and clearing the loops makes mpkloop follow again.
- **Start/Stop**: MIDI Start starts the transport with loop phase 0 on the start tick (Start while
  playing restarts, Stop stops like `space`). `space` or a loop pad while stopped starts mpkloop
  locally on the nearest earlier bar line of the clock's grid, so it stays in phase. It cannot start
  the global clock. With no ticks for more than 1 s the header shows `waiting for clock` and mpkloop
  runs on its own clock (Free→Tempo works again, loops keep playing).
- **Recording** is quantised to the clock's bars (the Quantize / N bars modes); the clock is the count-in.
- **Timing**: the audio callback owns the sample clock. Tick times only feed the tempo estimate and the
  start alignment (a low-passed callback-time to sample-position map absorbs scheduling jitter), so MIDI
  jitter never moves loop boundaries. After the start the loops run on the audio clock: a sound card
  that is 20 ppm off the clock drifts about 1 ms per 50 s against it; press Start again to re-align.
  `--clock-offset MS` shifts the loops earlier (+) or later (-) to trim audio output latency.

Measured with a synthetic tick stream (2 ms jitter, 0.5 % outlier ticks): tempo within 0.15 BPM
from the first estimate (about 2 s) and within 0.01 BPM once settled, at 90, 120 and 140 BPM; start
alignment within 0.5 ms; loops on the bar grid.

## Device sync

On start mpkloop reads the MPK's active preset over SysEx and writes a temporary
version to the device's **RAM only**: the screen shows page and sound names, knobs go
relative, the arp follows mpkloop's clock (or Switchbox's, when following). Stored programs are never touched; it's
undone on exit. If mpkloop crashes, re-select the program on the MPK. Opt out with
`--no-device-sync` / `--no-ext-clock`.

## Notes

- Input Gain is 0 by default. Laptop mic + speakers will howl: use headphones.
- The Textual screen takes the mouse; `--classic` is the lighter curses screen and shows
  one bank of 8 tracks at a time.
- Built with Python + numpy/scipy, sounddevice (PortAudio → PipeWire), mido/rtmidi, Textual.

## License

MIT, see `LICENSE`.
