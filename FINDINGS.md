# Findings

Measurements taken while building, and space for notes from testing.

Everything below was measured on a Mac Studio (M-series), macOS, August 2026.
Numbers on Raspberry Pi-class hardware — a fair stand-in for what is inside a
keyboard — will be several times slower for Piper and roughly similar for
espeak-ng. The architecture does not change; the numbers do.

---

## Speech engines

| | espeak-ng | Piper | macOS `say` |
|---|---|---|---|
| First audio, short (`"65"`) | **13 ms** | **20 ms** | ~1000 ms warm |
| First audio, typical | 13 ms | 35 ms | ~1000 ms warm |
| First audio, verbose announcement | 13 ms | 107 ms | ~1000 ms warm |
| Cold start | n/a | 583 ms model load, once | **2400 ms, every time** |
| Scales with text length | no | **yes** | no |
| Licence | GPL-3.0-or-later | **MIT** | proprietary |
| Reaches every CoreAudio device | yes | yes | **no** |

**Piper's latency scaling is a real design consequence.** At Verbose, where
announcements are long, Piper is roughly 8× slower than at Terse. Verbosity and
engine choice are therefore not independent settings.

### Why `say` is so slow here

This Mac has **442 voices installed**, and `say` rescans the voice catalogue on
every launch. The cost is identical for every voice, every output device, and
even for an empty string.

Three things that do **not** fix it, all tested:

- `say -o /dev/stdout` fails (`Opening output file failed: -54`). A named pipe
  fails too. It wants a real seekable file, so synthesising to PCM and playing
  it ourselves adds ~1.9 s — worse, not better.
- `say -f -` fed line by line **buffers until stdin closes.** It will not speak
  incrementally, so one long-lived process cannot serve successive utterances.
- Pinning a single voice does not help. The catalogue scan happens regardless.

What does work is a pool of pre-warmed processes: **kill the speaker and hand
text to a warm spare in 1.7 ms.** Warm overhead is still ~1000 ms to first
audio, which is why `say` is kept only as a contrast.

### Why Piper runs in-process

The `piper` CLI works, but a cold spawn costs **783 ms** loading the model.
Worse, interrupting a subprocess mid-sentence means either killing it and
paying that again, or reading and discarding an unknown number of bytes from a
raw stream with no utterance boundaries.

Loading the model once in-process solves both. `synthesize()` yields one chunk
per sentence, so interruption is simply **stopping consuming the generator.**

---

## Interruption

- **2.96 seconds** of queued speech discarded in **under 10 ms**.
- Twelve announcements at 80 ms apart (typical key auto-repeat) left **no
  backlog** — only the final utterance was still playing.
- Peak buffered audio during a held-key burst equalled **one utterance**, which
  is what tracking looks like as opposed to queueing.

---

## Note timing under speech load

Clicks at 120 bpm on their own mixing track, while announcements were fired and
cancelled every 90 ms:

```
while speaking : mean 6.68 ms, max 10.06 ms   (23 clicks)
while quiet    : mean 7.04 ms, max 10.06 ms   (20 clicks)
```

**Identical.** Speech made no measurable difference.

What is measured is when each click was handed to the audio buffer versus when
it was due — a Python thread's scheduling accuracy, not sample-accurate audio
jitter. But it is the thing actually in doubt: whether synthesising speech
starves the thread producing notes. On real hardware the audio path would be
higher priority and *more* isolated, not less. This is the pessimistic case.

---

## Audio routing

**Device indices are not stable.** PortAudio numbers outputs positionally, and
during one session `--device 5` selected three different devices over twenty
minutes with no hardware change. A saved index silently sends speech somewhere
else. Selection and persistence are **by name**.

**`say` cannot reach every device.** `say -a`'s list is a smaller set than
CoreAudio exposes — on this machine it omits the StudioLive 64S and the DELL
entirely. The interface a musician would actually take in-ear monitors from is
unroutable by the macOS engine.

**Channel routing verified** on a 64-output device: speech mono on output 7,
earcons stereo on 3–4, mains 1–2 completely silent. Widening from 3–4 to 17–18
reopens the stream automatically.

> **Not yet verified on real multi-channel hardware.** The StudioLive was
> powered down before outputs 17–18 could be confirmed to physically carry
> audio. Worth doing next time the studio is up.

---

## Bugs found while building

Kept because they are the useful part — each one is in `DESIGN.md §14`.

1. **A hint spoken as a separate utterance interrupted the announcement it
   belonged to.** Every keypress cancels speech, including ours, so the user
   heard only "Press Enter to apply" and never the device name.
2. **`step1.py` silently produced no audio** after the engine moved onto buses.
   The espeak reader thread swallows exceptions, so it failed with no error and
   no sound — exactly the failure mode this project exists to argue against,
   sitting in its own repository.
3. **A race on stream reopen.** Moving to a wider channel pair briefly left the
   old callback writing to a column that did not exist. PortAudio swallows the
   exception, so it would have appeared as a random dropout.
4. **Clamping a channel pair index-wise** turned outputs 17–18 on a stereo
   device into (1, 1) — silently mono and hard-panned right.
5. **The settings menu opened out of sync with reality**, showing a device that
   was not the one playing.
6. **The "where am I" key said `Combi, Combi, item 4 of 4`** at the top of a
   mode, where the container *is* the mode.
7. **`Transpose` read `0` instead of `0 semitones`** — the value formatter was
   swallowing the unit.
8. **A note-name docstring claimed middle C was C3 while the code produced C4.**
   The code was right. Getting it backwards shifts every split point by an
   octave while looking entirely plausible.
9. **A watchdog thread started before the object it watched finished
   constructing**, and died on the first attribute it read.

---

## My notes

_(fill in as you test)_

- Does holding Down feel like it tracks your hand, or lag behind it?
-
- Which earcon pack is actually pleasant after an hour?
-
- Does binaural read as outside your head on in-ears? On speakers?
-
- Is 300 wpm the right default, or should it start higher?
-
- Is `say` merely worse than Piper, or actually unusable?
-
- Does the silence at a list edge feel right, or does it feel like a dropout?
-
- Anything that made you want to switch it off?
-
