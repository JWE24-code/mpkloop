"""Rewrites the LESSONS object (EN + NL) in lessons.html: one intro lesson and three
songs, each using more of mpkloop. Written for a 12-year-old: short steps, one thing
at a time.  Run:  python -m mpkloop.factory.build_lessons"""
import json
import re
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent.parent / "lessons.html"


def S(t, b, hl=(), st=None, **kw):
    d = dict(t=t, hl=[list(x) for x in hl], b=b)
    if st:
        d["st"] = st
    d.update(kw)
    return d


PC_B = {"mode": "pc", "bank": "B"}
PC_A = {"mode": "pc", "bank": "A"}

EN = [
 {"t": "Meet your MPK", "steps": [
  S("Start mpkloop", "<p>Plug in the MPK with the USB cable. Open a terminal and type <code>mpkloop</code>, then press Enter. "
    "You see a big table with 16 <b>tracks</b>. Each track can hold one loop: a short piece of music that repeats.</p>"
    "<p class=\"tip\">Press <kbd>L</kbd> in mpkloop to open this page. Click <b>Connect MPK</b> at the top and the page will see what you press on the real MPK.</p>",
    comp=True, st={"line": "mpkloop ready"}),
  S("The keys play a sound", "<p>Play some keys. Press harder and the note is louder. Play two or three keys together for a chord.</p>",
    hl=[("keys", "PLAY")], keys=[0, 4, 7]),
  S("OCT − and OCT +", "<p>These two buttons move the keys lower or higher. Low notes are for bass, high notes for melodies. Press both at once to go back to the middle.</p>",
    hl=[("octdn", "PRESS"), ("octup", "PRESS")]),
  S("The joystick", "<p>Push it <b>left</b> or <b>right</b> while you hold a note: the note bends. Push it <b>up</b>: the note wobbles and gets brighter.</p>",
    hl=[("joy", "MOVE")], joy=True),
  S("The pads have two banks", "<p>The <b>BANK A/B</b> button switches the 8 pads between:</p><ul><li><b>Bank A</b> (red light): your <b>loop tracks</b>.</li>"
    "<li><b>Bank B</b> (green light): the <b>drums</b>.</li></ul><p>Pads 1–4 are the bottom row, 5–8 the top row. Press BANK A/B now and tap a pad to see it on the screen.</p>",
    hl=[("bank", "PRESS"), ("pad1", "TAP")], st={"bank": "B"}),
  S("Hit the drums", "<p>On bank B, hit the pads. Pad 1 is the kick, 2 the snare, 3 the hi-hat, 4 the open hi-hat. The top row has a clap and more. Hit softer and harder.</p>",
    hl=[("pad1", "KICK"), ("pad2", "SNARE"), ("pad3", "HAT")], st={"bank": "B"}),
  S("The knobs", "<p>The 8 knobs change settings. Which ones depends on the <b>page</b>. On the Volume page, knob 1 is the volume of track 1, knob 2 of track 2, and so on. Turn one and its name shows on the MPK's little screen.</p>",
    hl=[("k1", "TURN")], st={"page": 0}),
  S("Two special buttons", "<p><b>CC</b> and <b>PROG CHANGE</b> give the pads a different job for a moment. You'll use them in the songs. Press the same button again to get normal pads back.</p>"
    "<p class=\"tip\">Don't press <b>PROG SELECT</b> while mpkloop runs.</p>",
    hl=[("cc", "LOOK"), ("pc", "LOOK")]),
 ]},
 {"t": "Song 1: a beat, a bass and chords", "steps": [
  S("Pick a drum kit", "<p>Press <b>PROG CHANGE</b>, go to <b>bank B</b> and tap <b>pad 8</b>. Every tap gives the next drum kit: Classic, 808, 909, Electro… Pick one you like, then press PROG CHANGE again to leave.</p>",
    hl=[("pc", "PRESS"), ("bank", "BANK B"), ("pad8", "TAP")], st=dict(PC_B, kit=1, line="Drum kit: 808")),
  S("Record your beat on track 1", "<p>Go to <b>bank A</b> and tap <b>pad 1</b>. You hear 4 clicks: that's the count-in. Then switch to <b>bank B</b> and play a beat: kick, hat, snare, hat… Keep it simple.</p>"
    "<p>After 1 bar (4 beats) or 2 bars, switch back to bank A and tap <b>pad 1</b> again. Your beat now repeats. That's a loop!</p>"
    "<p class=\"tip\">Made a mess? Hold pad 1 for a second: the track is cleared and you can try again.</p>",
    hl=[("pad1", "TAP"), ("bank", "BANK B"), ("pad1", "TAP AGAIN")], st={"bank": "A", "line": "T1: loop 1 bar"}, tr={1: "play"}),
  S("Choose a bass sound", "<p>Press <b>PROG CHANGE</b>, bank B, tap <b>pad 3: Bass</b>. Tap it again for the next bass sound. Press PROG CHANGE to leave, then press <b>OCT −</b> once so the keys play low.</p>",
    hl=[("pc", "PRESS"), ("pad3", "TAP"), ("octdn", "PRESS")], st=dict(PC_B, sound="Sub Bass")),
  S("Record the bass on track 2", "<p>Bank A, tap <b>pad 2</b>. Recording starts at the next bar, so you have a moment. Play a few low notes on the keys that fit your beat. Tap pad 2 again to close the loop.</p>"
    "<p class=\"tip\">The loop closes at the end of a bar, so you don't have to tap at the exact moment.</p>",
    hl=[("pad2", "TAP"), ("keys", "PLAY"), ("pad2", "TAP AGAIN")], st={"bank": "A", "sound": "Sub Bass", "line": "T2: loop 1 bar"}, tr={1: "play", 2: "play"}, keys=[0, 7]),
  S("Add chords on track 3", "<p>PROG CHANGE, bank B, tap <b>pad 1: Pads</b> or <b>pad 2: Keys</b> for a chord sound. Leave PROG CHANGE, press <b>OCT +</b> to come back up. Bank A, tap <b>pad 3</b>, play two or three chords, tap pad 3 again.</p>",
    hl=[("pc", "PRESS"), ("pad2", "TAP"), ("octup", "PRESS"), ("pad3", "TAP")], st={"bank": "A", "sound": "E-Piano", "line": "T3: loop 2 bars"}, tr={1: "play", 2: "play", 3: "play"}, keys=[0, 4, 7]),
  S("Take parts out and in", "<p>Press <b>CC</b>. Now bank A pads <b>mute</b> tracks: tap pad 1 and the beat stops at the next beat; tap again and it's back. Try playing with just the chords, then bring the beat in. Press CC again to leave.</p>",
    hl=[("cc", "PRESS"), ("pad1", "TAP"), ("pad1", "TAP AGAIN")], st={"mode": "cc", "bank": "A"}, tr={1: "mute", 2: "play", 3: "play"}),
  S("Make it louder or softer", "<p>Press PROG CHANGE, <b>bank A</b>, tap <b>pad 1: Volume</b>, press PROG CHANGE again. Now knob 1 is the volume of track 1, knob 2 of track 2, knob 3 of track 3. Turn them until the beat, bass and chords sound good together.</p>",
    hl=[("pc", "PRESS"), ("pad1", "TAP"), ("k2", "TURN"), ("k3", "TURN")], st=dict(PC_A, page=0)),
  S("Play over the top", "<p>Pick a sound you like (Leads on pad 4 are good for melodies). Play along with your loops. Nothing is recorded now, so just have fun. Want to keep a melody? Tap <b>pad 4</b>, play it, tap again.</p>",
    hl=[("keys", "PLAY")], st={"bank": "A", "sound": "Saw Lead"}, tr={1: "play", 2: "play", 3: "play"}, keys=[12, 14, 16, 19]),
  S("Save your song", "<p>On the computer press <kbd>s</kbd>, type a name like <i>my first song</i> and press Enter. Press <kbd>o</kbd> any time to open it again. Press <kbd>space</kbd> to stop and start playing.</p>"
    "<p class=\"tip\">Song 1 done! You used: tracks, drum pads, sounds, mute, volume and save.</p>",
    comp=True, st={"line": "Saved 'my first song'"}),
 ]},
 {"t": "Song 2: the step sequencer, effects and scenes", "steps": [
  S("Start empty", "<p>Press <kbd>C</kbd> twice on the computer to clear all tracks (save first if you want to keep Song 1). For this song, the computer makes the beat and you play on top.</p>",
    comp=True, st={"line": "All tracks cleared"}),
  S("Open the step grid", "<p>Press <kbd>t</kbd>. You see a grid: 8 rows (kick, snare, hat…) and 16 steps. One row of 16 steps is one bar. Use the arrow keys to move and <kbd>space</kbd> to turn a step on. Put the kick on steps 1, 5, 9, 13 and the snare on 5 and 13. Press <kbd>T</kbd> to hear it. Press <kbd>t</kbd> to close the grid.</p>"
    "<p class=\"tip\">With the mouse: click a step. Right-click makes a step louder or softer.</p>",
    comp=True, st={"line": "Step sequencer on"}),
  S("Draw steps with the pads", "<p>Press <kbd>m</kbd> until the status line says <b>pad B: Steps</b>. Now the bank B pads turn steps 1–8 on and off for one drum. <kbd>Tab</kbd> switches to steps 9–16, <kbd>Shift-Tab</kbd> picks the next drum. Add some hi-hats. Press <kbd>m</kbd> until it says <b>Drums</b> again when you're done.</p>",
    hl=[("pad1", "TAP"), ("pad3", "TAP"), ("pad5", "TAP")], st={"bank": "B", "padb": "Steps", "line": "Bank B pads: Steps"}),
  S("Swing and a different kit", "<p>Press <kbd>→</kbd> until the knob page says <b>SEQ</b>. Knob 2 is <b>Swing</b>: turn it up and the beat starts to bounce. Knob 4 picks the <b>kit</b>. Knob 5 is the beat's volume.</p>",
    hl=[("k2", "SWING"), ("k4", "KIT")], st={"page": 11, "line": "Knob page: SEQ"}),
  S("Record the bass and chords", "<p>Like in Song 1: pick a bass sound (PROG CHANGE, bank B, pad 3), tap <b>pad 1</b> on bank A, play, tap again. Then chords on <b>pad 2</b>. The sequencer keeps playing underneath and is never recorded into your loops.</p>",
    hl=[("pad1", "TAP"), ("keys", "PLAY"), ("pad2", "TAP")], st={"bank": "A", "sound": "Pluck Bass"}, tr={1: "play", 2: "play"}, keys=[0, 3, 7]),
  S("Give your tracks names", "<p>Press <kbd>a</kbd> then <kbd>1</kbd>, type <i>Bass</i>, Enter. Press <kbd>a</kbd> <kbd>2</kbd>, type <i>Chords</i>. The names show in the table so you always know what's where.</p>",
    comp=True, st={"line": "Name track: press 1-8"}),
  S("Copy a track and make it longer", "<p>Press <kbd>c</kbd> <kbd>2</kbd> <kbd>3</kbd>: the chords are copied to track 3. Press <kbd>D</kbd> <kbd>3</kbd>: track 3 is now twice as long. Now tap <b>pad 3</b> (overdub) and play a second chord part only in the second half. Tap pad 3 again. Mute track 2 with CC to hear just the new one.</p>",
    hl=[("pad3", "TAP")], st={"bank": "A", "line": "T3: loop is now 4 bars"}, tr={1: "play", 2: "play", 3: "odub"}),
  S("An effect on a track", "<p>Press <kbd>→</kbd> to the <b>TRACK FX</b> page. Knob 2 picks an effect for track 2: Crush, Drive, Chorus, Tape or Comb. Then <kbd>→</kbd> to <b>FX AMOUNT</b> and turn knob 2 up. Chorus on chords sounds wide; Crush on a bass sounds like an old video game.</p>",
    hl=[("k2", "EFFECT")], st={"page": 8, "line": "Knob page: TRACK FX"}),
  S("Duck: the pumping sound", "<p><kbd>→</kbd> to the <b>DUCK</b> page. Turn knob 2 halfway. Now the chords dip a little every time the kick hits. That pumping is used in a lot of dance music.</p>",
    hl=[("k2", "DUCK")], st={"page": 10, "line": "Knob page: DUCK"}),
  S("Store two scenes", "<p>A scene remembers all your volumes, mutes and effects. Make a quiet version (mute the bass, turn the chords down) and press <kbd>N</kbd> <kbd>1</kbd>. Make a full version and press <kbd>N</kbd> <kbd>2</kbd>. Now <kbd>n</kbd> <kbd>1</kbd> and <kbd>n</kbd> <kbd>2</kbd> switch between them at the next bar.</p>"
    "<p class=\"tip\">On the MPK: press <kbd>m</kbd> until it says <b>Scenes</b>. Then tapping a bank B pad recalls that scene, and holding it stores one.</p>",
    comp=True, st={"line": "Scene 2 at the next bar"}),
  S("Record a whole performance", "<p>Press <kbd>b</kbd>. Everything you hear is now recorded to a WAV file. Switch between your scenes, mute things, play a melody. Press <kbd>b</kbd> again to stop. The file is in <code>~/Music/mpkloop/bounces/</code>. Press <kbd>s</kbd> to save the session too.</p>"
    "<p class=\"tip\">Song 2 done! New: step sequencer, swing, names, copy, double, effects, duck, scenes, bounce.</p>",
    comp=True, st={"line": "Bounce saved"}),
 ]},
 {"t": "Song 3: your own sounds, the sampler and a live show", "steps": [
  S("Find your favorite sounds", "<p>Press <kbd>u</kbd>. This is the sound library. Move with <kbd>↑</kbd> <kbd>↓</kbd> and play the keys: you hear the sound you're pointing at. Press <kbd>f</kbd> on the ones you love: they get a ★ and come <b>first</b> when you tap that category pad on the MPK. <kbd>Esc</kbd> closes it.</p>",
    comp=True, st={"line": "★ Favorite: Hoover"}),
  S("Make your own sound", "<p>Pick a sound. Go to the <b>SOUND</b> page (PROG CHANGE, bank A, pad 7). Knob 1 makes it darker or brighter, knob 2 makes it squeal, knob 3 makes notes start slowly, knob 4 makes them ring longer. Like it? Press <kbd>u</kbd>, then <kbd>n</kbd>, type a name. It's now in the library with your name on it.</p>",
    hl=[("k1", "CUTOFF"), ("k2", "RESONANCE"), ("k4", "RELEASE")], st={"page": 6, "sound": "Acid", "line": "Saved sound 'My Acid' to the library"}),
  S("Record a beat and chop it up", "<p>Record a beat on track 1 as in Song 1. Then press <kbd>y</kbd> <kbd>1</kbd>: the loop is copied into the <b>sampler</b> and cut into 8 pieces. Press <kbd>m</kbd> until the status line says <b>Chops</b>. Now the bank B pads play the 8 pieces. Play them in a new order!</p>",
    hl=[("pad1", "TAP"), ("pad3", "TAP"), ("pad2", "TAP")], st={"bank": "B", "padb": "Chops", "line": "Sampler: took the loop of T1"}, tr={1: "play"}),
  S("Record the chopped beat", "<p>Mute track 1 (CC + pad 1). Bank A, tap <b>pad 2</b>, play your chops on bank B, tap pad 2 again. Now you have a new beat made from the old one. Try the <b>SAMPLER</b> page (<kbd>→</kbd> to the end): knob 1 changes the pitch, knob 8 plays it backwards.</p>",
    hl=[("pad2", "TAP"), ("bank", "BANK B")], st={"bank": "A", "padb": "Chops"}, tr={1: "mute", 2: "play"}),
  S("Sample your own voice", "<p>Go to the <b>GLOBAL</b> page and turn knob 4 (<b>Input Gain</b>) up a little. Use headphones, or it howls! Press <kbd>Y</kbd>, say or sing something, press <kbd>Y</kbd> again. Press <kbd>i</kbd>: now the keys play your voice, high and low. Chops play pieces of it.</p>",
    hl=[("k4", "INPUT GAIN"), ("keys", "PLAY")], st={"page": 7, "line": "Sampler: recorded 2.3 s"}, keys=[0, 5, 7]),
  S("Arpeggiator and Note Repeat", "<p>Press <b>ARP</b> on the MPK and hold a chord: the notes play one after another, in time with your loops. Hold <b>NOTE REPEAT</b> and hold a drum pad: a fast roll, also in time. Record either one into a track.</p>",
    hl=[("arp", "PRESS"), ("keys", "HOLD CHORD"), ("repeat", "HOLD"), ("pad3", "HOLD")], st={"bank": "B"}, keys=[0, 4, 7]),
  S("More than 8 tracks", "<p>Press <kbd>B</kbd>. The top line now says <b>pads: T9-16</b>: the pads and keys 1–8 work on tracks 9 to 16. Record something on pad 1: it lands on track 9. Press <kbd>B</kbd> again to go back to tracks 1–8.</p>",
    hl=[("pad1", "TAP")], st={"bank": "A", "line": "Pads and keys 1-8 now address tracks 9-16"}, tr={1: "play", 2: "play"}),
  S("Solo", "<p>Press <kbd>z</kbd> <kbd>2</kbd>: you hear only track 2. Good for checking one part. Press <kbd>Z</kbd> and everything comes back.</p>",
    comp=True, st={"line": "T2: solo on"}),
  S("Live effects", "<p>Press <kbd>m</kbd> until it says <b>FX</b>. Now the bank B pads are effects while you <b>hold</b> them: pads 1–4 repeat a small piece (stutter), pad 5 slows everything down like a tape, pad 6 plays everything backwards, pad 8 crushes the sound. Let go and the music snaps back in time.</p>",
    hl=[("pad2", "HOLD"), ("pad5", "HOLD"), ("pad6", "HOLD")], st={"bank": "B", "padb": "FX", "line": "Bank B pads: FX"}),
  S("Free tempo", "<p>Clear everything (<kbd>C</kbd> <kbd>C</kbd>). On the GLOBAL page set knob 2 (<b>Rec Mode</b>) to <b>Free→Tempo</b>. Tap pad 1 and start playing right away, no count-in. Tap pad 1 exactly when your loop should end. mpkloop works out the tempo from your loop.</p>",
    hl=[("k2", "REC MODE"), ("pad1", "TAP"), ("pad1", "TAP AGAIN")], st={"page": 7, "line": "Tempo set from loop: 92.4 BPM (2 bars)"}),
  S("Export your song", "<p>Press <kbd>e</kbd>, then <kbd>3</kbd>. mpkloop writes a WAV file per track, a mix, and a MIDI file with the notes you played, to <code>~/Music/mpkloop/exports/</code>. You can open those in any music program and keep working there.</p>"
    "<p class=\"tip\">Song 3 done! You now know every feature. Make something nobody has heard before.</p>",
    comp=True, st={"line": "Exported: stems 4 bars, 5 MIDI tracks"}),
 ]},
]

NL = [
 {"t": "Maak kennis met je MPK", "steps": [
  S("Start mpkloop", "<p>Sluit de MPK aan met de USB-kabel. Open een terminal, typ <code>mpkloop</code> en druk op Enter. "
    "Je ziet een grote tabel met 16 <b>tracks</b>. Elke track kan één loop bevatten: een kort stukje muziek dat zich herhaalt.</p>"
    "<p class=\"tip\">Druk op <kbd>L</kbd> in mpkloop om deze pagina te openen. Klik bovenaan op <b>MPK verbinden</b> en de pagina ziet wat je op de echte MPK indrukt.</p>",
    comp=True, st={"line": "mpkloop ready"}),
  S("De toetsen spelen een klank", "<p>Speel wat toetsen. Druk harder en de noot is luider. Speel twee of drie toetsen tegelijk voor een akkoord.</p>",
    hl=[("keys", "SPEEL")], keys=[0, 4, 7]),
  S("OCT − en OCT +", "<p>Deze twee knoppen schuiven de toetsen lager of hoger. Lage noten zijn voor bas, hoge noten voor melodieën. Druk beide tegelijk om terug naar het midden te gaan.</p>",
    hl=[("octdn", "DRUK"), ("octup", "DRUK")]),
  S("De joystick", "<p>Duw hem naar <b>links</b> of <b>rechts</b> terwijl je een noot vasthoudt: de noot buigt. Duw hem <b>omhoog</b>: de noot gaat wiebelen en wordt helderder.</p>",
    hl=[("joy", "BEWEEG")], joy=True),
  S("De pads hebben twee banken", "<p>De knop <b>BANK A/B</b> schakelt de 8 pads tussen:</p><ul><li><b>Bank A</b> (rood lampje): je <b>looptracks</b>.</li>"
    "<li><b>Bank B</b> (groen lampje): de <b>drums</b>.</li></ul><p>Pads 1–4 zijn de onderste rij, 5–8 de bovenste. Druk nu op BANK A/B en tik op een pad om het op het scherm te zien.</p>",
    hl=[("bank", "DRUK"), ("pad1", "TIK")], st={"bank": "B"}),
  S("Sla op de drums", "<p>Op bank B sla je op de pads. Pad 1 is de kick, 2 de snare, 3 de hi-hat, 4 de open hi-hat. De bovenste rij heeft een clap en meer. Sla zachter en harder.</p>",
    hl=[("pad1", "KICK"), ("pad2", "SNARE"), ("pad3", "HAT")], st={"bank": "B"}),
  S("De draaiknoppen", "<p>De 8 draaiknoppen veranderen instellingen. Welke, hangt af van de <b>pagina</b>. Op de pagina Volume is knop 1 het volume van track 1, knop 2 van track 2, enzovoort. Draai er een en de naam verschijnt op het schermpje van de MPK.</p>",
    hl=[("k1", "DRAAI")], st={"page": 0}),
  S("Twee speciale knoppen", "<p><b>CC</b> en <b>PROG CHANGE</b> geven de pads even een andere taak. Die gebruik je in de liedjes. Druk nog eens op dezelfde knop om de gewone pads terug te krijgen.</p>"
    "<p class=\"tip\">Druk niet op <b>PROG SELECT</b> terwijl mpkloop draait.</p>",
    hl=[("cc", "KIJK"), ("pc", "KIJK")]),
 ]},
 {"t": "Liedje 1: een beat, een bas en akkoorden", "steps": [
  S("Kies een drumkit", "<p>Druk op <b>PROG CHANGE</b>, ga naar <b>bank B</b> en tik op <b>pad 8</b>. Elke tik geeft de volgende drumkit: Classic, 808, 909, Electro… Kies er een die je mooi vindt en druk dan nog eens op PROG CHANGE om eruit te gaan.</p>",
    hl=[("pc", "DRUK"), ("bank", "BANK B"), ("pad8", "TIK")], st=dict(PC_B, kit=1, line="Drum kit: 808")),
  S("Neem je beat op op track 1", "<p>Ga naar <b>bank A</b> en tik op <b>pad 1</b>. Je hoort 4 tikken: dat is het aftellen. Ga dan naar <b>bank B</b> en speel een beat: kick, hat, snare, hat… Houd het simpel.</p>"
    "<p>Na 1 maat (4 tellen) of 2 maten ga je terug naar bank A en tik je nog eens op <b>pad 1</b>. Je beat herhaalt zich nu. Dat is een loop!</p>"
    "<p class=\"tip\">Mislukt? Houd pad 1 een seconde vast: de track wordt gewist en je kunt opnieuw.</p>",
    hl=[("pad1", "TIK"), ("bank", "BANK B"), ("pad1", "TIK NOG EENS")], st={"bank": "A", "line": "T1: loop 1 bar"}, tr={1: "play"}),
  S("Kies een basklank", "<p>Druk op <b>PROG CHANGE</b>, bank B, tik op <b>pad 3: Bass</b>. Tik nog eens voor de volgende basklank. Druk op PROG CHANGE om eruit te gaan en druk dan één keer op <b>OCT −</b> zodat de toetsen laag spelen.</p>",
    hl=[("pc", "DRUK"), ("pad3", "TIK"), ("octdn", "DRUK")], st=dict(PC_B, sound="Sub Bass")),
  S("Neem de bas op op track 2", "<p>Bank A, tik op <b>pad 2</b>. Het opnemen begint bij de volgende maat, dus je hebt even tijd. Speel een paar lage noten die bij je beat passen. Tik nog eens op pad 2 om de loop te sluiten.</p>"
    "<p class=\"tip\">De loop sluit aan het eind van een maat, dus je hoeft niet precies op het juiste moment te tikken.</p>",
    hl=[("pad2", "TIK"), ("keys", "SPEEL"), ("pad2", "TIK NOG EENS")], st={"bank": "A", "sound": "Sub Bass", "line": "T2: loop 1 bar"}, tr={1: "play", 2: "play"}, keys=[0, 7]),
  S("Akkoorden op track 3", "<p>PROG CHANGE, bank B, tik op <b>pad 1: Pads</b> of <b>pad 2: Keys</b> voor een akkoordklank. Verlaat PROG CHANGE, druk op <b>OCT +</b> om weer omhoog te gaan. Bank A, tik op <b>pad 3</b>, speel twee of drie akkoorden, tik nog eens op pad 3.</p>",
    hl=[("pc", "DRUK"), ("pad2", "TIK"), ("octup", "DRUK"), ("pad3", "TIK")], st={"bank": "A", "sound": "E-Piano", "line": "T3: loop 2 bars"}, tr={1: "play", 2: "play", 3: "play"}, keys=[0, 4, 7]),
  S("Haal partijen weg en terug", "<p>Druk op <b>CC</b>. Nu <b>dempen</b> de bank A-pads tracks: tik op pad 1 en de beat stopt bij de volgende tel; tik nog eens en hij is terug. Speel eens met alleen de akkoorden en laat dan de beat binnenkomen. Druk nog eens op CC om eruit te gaan.</p>",
    hl=[("cc", "DRUK"), ("pad1", "TIK"), ("pad1", "TIK NOG EENS")], st={"mode": "cc", "bank": "A"}, tr={1: "mute", 2: "play", 3: "play"}),
  S("Harder of zachter", "<p>Druk op PROG CHANGE, <b>bank A</b>, tik op <b>pad 1: Volume</b>, druk nog eens op PROG CHANGE. Nu is knop 1 het volume van track 1, knop 2 van track 2, knop 3 van track 3. Draai tot beat, bas en akkoorden goed samen klinken.</p>",
    hl=[("pc", "DRUK"), ("pad1", "TIK"), ("k2", "DRAAI"), ("k3", "DRAAI")], st=dict(PC_A, page=0)),
  S("Speel erbovenop", "<p>Kies een klank die je mooi vindt (Leads op pad 4 zijn goed voor melodieën). Speel mee met je loops. Er wordt nu niets opgenomen, dus gewoon plezier maken. Wil je een melodie bewaren? Tik op <b>pad 4</b>, speel hem, tik nog eens.</p>",
    hl=[("keys", "SPEEL")], st={"bank": "A", "sound": "Saw Lead"}, tr={1: "play", 2: "play", 3: "play"}, keys=[12, 14, 16, 19]),
  S("Sla je liedje op", "<p>Druk op de computer op <kbd>s</kbd>, typ een naam zoals <i>mijn eerste liedje</i> en druk op Enter. Druk op <kbd>o</kbd> om het later weer te openen. <kbd>spatie</kbd> stopt en start het afspelen.</p>"
    "<p class=\"tip\">Liedje 1 klaar! Je gebruikte: tracks, drumpads, klanken, dempen, volume en opslaan.</p>",
    comp=True, st={"line": "Saved 'mijn eerste liedje'"}),
 ]},
 {"t": "Liedje 2: de stepsequencer, effecten en scenes", "steps": [
  S("Begin leeg", "<p>Druk twee keer op <kbd>C</kbd> op de computer om alle tracks te wissen (sla eerst op als je Liedje 1 wilt houden). In dit liedje maakt de computer de beat en speel jij erbovenop.</p>",
    comp=True, st={"line": "All tracks cleared"}),
  S("Open het stepraster", "<p>Druk op <kbd>t</kbd>. Je ziet een raster: 8 rijen (kick, snare, hat…) en 16 stappen. Eén rij van 16 stappen is één maat. Beweeg met de pijltjestoetsen en zet een stap aan met <kbd>spatie</kbd>. Zet de kick op stap 1, 5, 9, 13 en de snare op 5 en 13. Druk op <kbd>T</kbd> om het te horen. Druk op <kbd>t</kbd> om het raster te sluiten.</p>"
    "<p class=\"tip\">Met de muis: klik op een stap. Rechtsklikken maakt een stap luider of zachter.</p>",
    comp=True, st={"line": "Step sequencer on"}),
  S("Teken stappen met de pads", "<p>Druk op <kbd>m</kbd> tot de statusregel <b>pad B: Steps</b> zegt. Nu zetten de bank B-pads stap 1–8 aan en uit voor één drum. <kbd>Tab</kbd> gaat naar stap 9–16, <kbd>Shift-Tab</kbd> kiest de volgende drum. Voeg wat hi-hats toe. Druk op <kbd>m</kbd> tot het weer <b>Drums</b> zegt als je klaar bent.</p>",
    hl=[("pad1", "TIK"), ("pad3", "TIK"), ("pad5", "TIK")], st={"bank": "B", "padb": "Steps", "line": "Bank B pads: Steps"}),
  S("Swing en een andere kit", "<p>Druk op <kbd>→</kbd> tot de knoppenpagina <b>SEQ</b> zegt. Knop 2 is <b>Swing</b>: draai hem open en de beat gaat huppelen. Knop 4 kiest de <b>kit</b>. Knop 5 is het volume van de beat.</p>",
    hl=[("k2", "SWING"), ("k4", "KIT")], st={"page": 11, "line": "Knob page: SEQ"}),
  S("Neem de bas en akkoorden op", "<p>Net als in Liedje 1: kies een basklank (PROG CHANGE, bank B, pad 3), tik op <b>pad 1</b> op bank A, speel, tik nog eens. Dan akkoorden op <b>pad 2</b>. De sequencer speelt eronder door en wordt nooit in je loops opgenomen.</p>",
    hl=[("pad1", "TIK"), ("keys", "SPEEL"), ("pad2", "TIK")], st={"bank": "A", "sound": "Pluck Bass"}, tr={1: "play", 2: "play"}, keys=[0, 3, 7]),
  S("Geef je tracks een naam", "<p>Druk op <kbd>a</kbd> en dan <kbd>1</kbd>, typ <i>Bas</i>, Enter. Druk op <kbd>a</kbd> <kbd>2</kbd>, typ <i>Akkoorden</i>. De namen staan in de tabel, zodat je altijd weet wat waar staat.</p>",
    comp=True, st={"line": "Name track: press 1-8"}),
  S("Kopieer een track en maak hem langer", "<p>Druk op <kbd>c</kbd> <kbd>2</kbd> <kbd>3</kbd>: de akkoorden worden naar track 3 gekopieerd. Druk op <kbd>D</kbd> <kbd>3</kbd>: track 3 is nu twee keer zo lang. Tik nu op <b>pad 3</b> (overdub) en speel alleen in de tweede helft een tweede akkoordpartij. Tik nog eens op pad 3. Demp track 2 met CC om alleen de nieuwe te horen.</p>",
    hl=[("pad3", "TIK")], st={"bank": "A", "line": "T3: loop is now 4 bars"}, tr={1: "play", 2: "play", 3: "odub"}),
  S("Een effect op een track", "<p>Druk op <kbd>→</kbd> naar de pagina <b>TRACK FX</b>. Knop 2 kiest een effect voor track 2: Crush, Drive, Chorus, Tape of Comb. Dan <kbd>→</kbd> naar <b>FX AMOUNT</b> en draai knop 2 open. Chorus op akkoorden klinkt breed; Crush op een bas klinkt als een oude videogame.</p>",
    hl=[("k2", "EFFECT")], st={"page": 8, "line": "Knob page: TRACK FX"}),
  S("Duck: het pompende geluid", "<p><kbd>→</kbd> naar de pagina <b>DUCK</b>. Draai knop 2 half open. Nu duiken de akkoorden een beetje weg elke keer als de kick slaat. Dat pompen hoor je in veel dansmuziek.</p>",
    hl=[("k2", "DUCK")], st={"page": 10, "line": "Knob page: DUCK"}),
  S("Sla twee scenes op", "<p>Een scene onthoudt al je volumes, dempingen en effecten. Maak een rustige versie (demp de bas, draai de akkoorden zachter) en druk op <kbd>N</kbd> <kbd>1</kbd>. Maak een volle versie en druk op <kbd>N</kbd> <kbd>2</kbd>. Nu wisselen <kbd>n</kbd> <kbd>1</kbd> en <kbd>n</kbd> <kbd>2</kbd> ertussen bij de volgende maat.</p>"
    "<p class=\"tip\">Op de MPK: druk op <kbd>m</kbd> tot het <b>Scenes</b> zegt. Dan roept een tik op een bank B-pad die scene op, en vasthouden slaat er een op.</p>",
    comp=True, st={"line": "Scene 2 at the next bar"}),
  S("Neem een hele performance op", "<p>Druk op <kbd>b</kbd>. Alles wat je hoort wordt nu opgenomen in een WAV-bestand. Wissel tussen je scenes, demp dingen, speel een melodie. Druk nog eens op <kbd>b</kbd> om te stoppen. Het bestand staat in <code>~/Music/mpkloop/bounces/</code>. Druk op <kbd>s</kbd> om de sessie ook op te slaan.</p>"
    "<p class=\"tip\">Liedje 2 klaar! Nieuw: stepsequencer, swing, namen, kopiëren, verdubbelen, effecten, duck, scenes, bounce.</p>",
    comp=True, st={"line": "Bounce saved"}),
 ]},
 {"t": "Liedje 3: je eigen klanken, de sampler en een live show", "steps": [
  S("Vind je favoriete klanken", "<p>Druk op <kbd>u</kbd>. Dit is de klankbibliotheek. Beweeg met <kbd>↑</kbd> <kbd>↓</kbd> en speel de toetsen: je hoort de klank die je aanwijst. Druk op <kbd>f</kbd> bij de klanken waar je van houdt: ze krijgen een ★ en komen <b>eerst</b> als je op de MPK op die categoriepad tikt. <kbd>Esc</kbd> sluit het.</p>",
    comp=True, st={"line": "★ Favorite: Hoover"}),
  S("Maak je eigen klank", "<p>Kies een klank. Ga naar de pagina <b>SOUND</b> (PROG CHANGE, bank A, pad 7). Knop 1 maakt hem donkerder of helderder, knop 2 laat hem piepen, knop 3 laat noten langzaam beginnen, knop 4 laat ze langer naklinken. Mooi? Druk op <kbd>u</kbd>, dan <kbd>n</kbd>, typ een naam. Hij staat nu in de bibliotheek met jouw naam erop.</p>",
    hl=[("k1", "CUTOFF"), ("k2", "RESONANCE"), ("k4", "RELEASE")], st={"page": 6, "sound": "Acid", "line": "Saved sound 'Mijn Acid' to the library"}),
  S("Neem een beat op en hak hem in stukken", "<p>Neem een beat op op track 1 zoals in Liedje 1. Druk dan op <kbd>y</kbd> <kbd>1</kbd>: de loop wordt in de <b>sampler</b> gekopieerd en in 8 stukken gehakt. Druk op <kbd>m</kbd> tot de statusregel <b>Chops</b> zegt. Nu spelen de bank B-pads de 8 stukken. Speel ze in een andere volgorde!</p>",
    hl=[("pad1", "TIK"), ("pad3", "TIK"), ("pad2", "TIK")], st={"bank": "B", "padb": "Chops", "line": "Sampler: took the loop of T1"}, tr={1: "play"}),
  S("Neem de gehakte beat op", "<p>Demp track 1 (CC + pad 1). Bank A, tik op <b>pad 2</b>, speel je chops op bank B, tik nog eens op pad 2. Nu heb je een nieuwe beat gemaakt uit de oude. Probeer de pagina <b>SAMPLER</b> (<kbd>→</kbd> tot het eind): knop 1 verandert de toonhoogte, knop 8 speelt hem achterstevoren.</p>",
    hl=[("pad2", "TIK"), ("bank", "BANK B")], st={"bank": "A", "padb": "Chops"}, tr={1: "mute", 2: "play"}),
  S("Sample je eigen stem", "<p>Ga naar de pagina <b>GLOBAL</b> en draai knop 4 (<b>Input Gain</b>) een beetje open. Gebruik een koptelefoon, anders gaat het rondzingen! Druk op <kbd>Y</kbd>, zeg of zing iets, druk nog eens op <kbd>Y</kbd>. Druk op <kbd>i</kbd>: nu spelen de toetsen je stem, hoog en laag. Chops spelen er stukjes van.</p>",
    hl=[("k4", "INPUT GAIN"), ("keys", "SPEEL")], st={"page": 7, "line": "Sampler: recorded 2.3 s"}, keys=[0, 5, 7]),
  S("Arpeggiator en Note Repeat", "<p>Druk op <b>ARP</b> op de MPK en houd een akkoord vast: de noten spelen na elkaar, in de maat van je loops. Houd <b>NOTE REPEAT</b> vast en houd een drumpad vast: een snelle roffel, ook in de maat. Neem een van beide op in een track.</p>",
    hl=[("arp", "DRUK"), ("keys", "HOUD AKKOORD"), ("repeat", "HOUD"), ("pad3", "HOUD")], st={"bank": "B"}, keys=[0, 4, 7]),
  S("Meer dan 8 tracks", "<p>Druk op <kbd>B</kbd>. De bovenste regel zegt nu <b>pads: T9-16</b>: de pads en toetsen 1–8 werken op track 9 tot 16. Neem iets op op pad 1: het komt op track 9. Druk nog eens op <kbd>B</kbd> om terug te gaan naar track 1–8.</p>",
    hl=[("pad1", "TIK")], st={"bank": "A", "line": "Pads and keys 1-8 now address tracks 9-16"}, tr={1: "play", 2: "play"}),
  S("Solo", "<p>Druk op <kbd>z</kbd> <kbd>2</kbd>: je hoort alleen track 2. Handig om één partij te controleren. Druk op <kbd>Z</kbd> en alles komt terug.</p>",
    comp=True, st={"line": "T2: solo on"}),
  S("Live-effecten", "<p>Druk op <kbd>m</kbd> tot het <b>FX</b> zegt. Nu zijn de bank B-pads effecten zolang je ze <b>vasthoudt</b>: pad 1–4 herhalen een klein stukje (stutter), pad 5 vertraagt alles als een cassettebandje, pad 6 speelt alles achterstevoren, pad 8 verbrijzelt het geluid. Laat los en de muziek springt weer in de maat.</p>",
    hl=[("pad2", "HOUD"), ("pad5", "HOUD"), ("pad6", "HOUD")], st={"bank": "B", "padb": "FX", "line": "Bank B pads: FX"}),
  S("Vrij tempo", "<p>Wis alles (<kbd>C</kbd> <kbd>C</kbd>). Zet op de pagina GLOBAL knop 2 (<b>Rec Mode</b>) op <b>Free→Tempo</b>. Tik op pad 1 en begin meteen te spelen, zonder aftellen. Tik precies op pad 1 wanneer je loop moet eindigen. mpkloop berekent het tempo uit je loop.</p>",
    hl=[("k2", "REC MODE"), ("pad1", "TIK"), ("pad1", "TIK NOG EENS")], st={"page": 7, "line": "Tempo set from loop: 92.4 BPM (2 bars)"}),
  S("Exporteer je liedje", "<p>Druk op <kbd>e</kbd> en dan <kbd>3</kbd>. mpkloop schrijft een WAV-bestand per track, een mix, en een MIDI-bestand met de noten die je speelde, naar <code>~/Music/mpkloop/exports/</code>. Die kun je in elk muziekprogramma openen en daar verder werken.</p>"
    "<p class=\"tip\">Liedje 3 klaar! Je kent nu elke functie. Maak iets wat nog niemand heeft gehoord.</p>",
    comp=True, st={"line": "Exported: stems 4 bars, 5 MIDI tracks"}),
 ]},
]

s = HTML.read_text()
a = s.index("const LESSONS = {")
b = s.index("\n};", a) + 3
js = "const LESSONS = {\nen: " + json.dumps(EN, ensure_ascii=False, indent=1) + ",\nnl: " + json.dumps(NL, ensure_ascii=False, indent=1) + "\n};"
s = s[:a] + js + s[b:]

REP = {
 'lede: "Seventeen hands-on lessons. Every step shows exactly what to press on the controller.':
 'lede: "Four lessons: meet the controller, then make three songs. Each song uses more of mpkloop, and every step shows exactly what to press.',
 'lede: "Zeventien praktijklessen. Elke stap laat precies zien wat je op de controller indrukt.':
 'lede: "Vier lessen: eerst de controller leren kennen, dan drie liedjes maken. Elk liedje gebruikt meer van mpkloop, en elke stap laat precies zien wat je indrukt.',
 '    ["1 … 8", "Same as tapping loop pad 1–8"], ["Shift + 1 … 8", "Mute / unmute track 1–8"],':
 '    ["1 … 8", "Same as tapping loop pad 1–8"], ["Shift + 1 … 8", "Mute / unmute track 1–8 (on the next beat)"],\n'
 '    ["B", "Pads and keys 1–8 work on tracks 9–16 (press again: 1–8)"], ["z + 1…8 / Z", "Solo a track / solo off"],\n'
 '    ["c + 1…8 + 1…8", "Copy a track to an empty track"], ["D + 1…8 / H + 1…8", "Double / halve a loop"], ["a + 1…8", "Name a track"],',
 '    ["1 … 8", "Hetzelfde als looppad 1–8 tikken"], ["Shift + 1 … 8", "Track 1–8 dempen / weer aan"],':
 '    ["1 … 8", "Hetzelfde als looppad 1–8 tikken"], ["Shift + 1 … 8", "Track 1–8 dempen / weer aan (bij de volgende tel)"],\n'
 '    ["B", "Pads en toetsen 1–8 werken op track 9–16 (nog eens: 1–8)"], ["z + 1…8 / Z", "Een track solo / solo uit"],\n'
 '    ["c + 1…8 + 1…8", "Een track naar een lege track kopiëren"], ["D + 1…8 / H + 1…8", "Een loop verdubbelen / halveren"], ["a + 1…8", "Een track een naam geven"],',
}
for k, v in REP.items():
    assert k in s, k[:60]
    s = s.replace(k, v)
HTML.write_text(s)
print(f"lessons: {sum(len(l['steps']) for l in EN)} EN steps, {sum(len(l['steps']) for l in NL)} NL steps")
