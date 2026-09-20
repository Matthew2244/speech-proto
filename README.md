# A flagship keyboard that talks

**Everything needed to make a workstation speak already exists, and in most
cases it is already inside the instrument.**

The Korg Kronos runs a real-time Linux kernel on an x86 processor with an SSD,
with a separate ARM board driving the panel. Yamaha publishes GPL source for
its synthesizers. Speech would be a userspace process on a CPU that already
handles menus and file I/O — the synthesis engines are never touched. The
speech engines themselves are free, tiny, and run comfortably on Raspberry
Pi-class hardware.

Ableton proved the rest of it. They shipped **Move** with a screen reader, and
a developer outside the company later put one *directly on the device* by
routing Ableton's existing accessibility data to a local voice. A $449
groovebox does what no $4,000 flagship does.

So the hardware is not the obstacle, and neither is the software. What has
never existed is an **interaction design** — a written account of how speech on
an instrument should actually behave, precise enough to build from.

That gap has a real cost today. No flagship workstation speaks: not the Kronos,
not the Yamaha Montage, not the Roland Fantom, not the Nord Stage, not the
Kurzweil K2700. A blind professional cannot find a sound on any of them without
a sighted person sitting next to them.

**This repository is that missing design** — written down, and running, so you
can hear it rather than read about it.

---

## Why this exists

When engineers are told "add speech", they hear *"read the screen aloud"*. That
produces something that technically works and is practically unusable: too slow,
too talkative, interrupting itself, useless on stage. It ships, the blind
community reviews it badly, and it gets abandoned.

The gap between speech blind musicians use for years and speech they switch off
within a day is entirely in how it behaves. That can be described in prose.
**Nobody can hear prose.**

So: something your engineers and product managers can sit down with for five
minutes, operate by hand, and come away understanding what *good* feels like.

Success looks like a sighted product manager holding down the arrow key,
hearing the speech keep up with their hands, and saying *"oh — I get it."*

---

## Try it in two minutes

```bash
./run
```

First launch asks whether you can hear it, then a few questions. Escape skips
all of that.

Then, in rough order of how convincing they are:

| Do this | And notice |
|---|---|
| **Hold the Down arrow** | Speech tracks your hand. Clipped partial words, no backlog. This is the whole thing. |
| **Hold Left or Right on a value** | A tone whose pitch is the value's position. Faster than any number could be read. |
| Press **`v`** repeatedly | Terse, Normal, Verbose. Note that two of them are identical for the commonest actions — that is deliberate. |
| Press **`p`** repeatedly | Eight earcon packs. Same meanings, different character. |
| Press **`s`** repeatedly | Mono, stereo, binaural spatial audio. |
| Press **`m`**, hammer the arrows, press **`m`** again | A steady click, and a report showing speech made no measurable difference to its timing. |
| Press **`1`** | A long save operation. Notice you are never left wondering whether it crashed. |
| Press **`l`** then move around | Learning mode names each sound three times, then stops. |
| Go to Global → Accessibility → Speech Output, arrow, press Enter, then **do nothing** | It puts itself back. See below. |

Press **`?`** at any time to hear the keys. **`q`** quits.

---

## Five things worth taking away

**1. Announce what changed, not everything that is true.**
Moving within a submenu does not re-announce the submenu. Changing a value says
the value, not the parameter name you are already holding in your head. This
one sentence is most of the design.

**2. Interruption is not a feature, it is the foundation.**
Any keypress cancels speech instantly. If the previous announcement is still
playing when you act, it is describing a state you have already left. Get this
wrong and nothing built on top of it can feel right.

**3. Tones do what words are too slow for.**
"Sixty-four" takes 600 ms to say. A tone encoding the same position takes 60,
and you can hear it *while* the value is still moving. This is the layer
everyone forgets, and it is what makes fast editing possible at all.

**4. Where the sound goes is a first-class feature.**
On stage, speech goes to in-ear monitors and must never reach the house PA. On
a 64-output interface, naming the *device* is not enough — you need the
specific outputs, and sometimes only one is free. Changing that routing applies
provisionally and **puts itself back** unless you confirm, because you cannot
tell whether an output works until you have heard something come out of it.

**5. Build the state layer once; everything consumes it.**
Speech is one consumer. Braille is another — press **`b`** to see the same
state rendered as a Braille line, which shows full context every time because
Braille is re-readable and speech is not. A touchscreen would be a third,
needing one extra field in the model. A remote editor a fourth.

---

## What it costs

Less than you would guess.

- **Speech engine**: espeak-ng is tiny and free (GPL-3.0), Piper is MIT with
  far better voices, Flite is BSD. All run comfortably on Raspberry Pi-class
  hardware. Reference measurements: **13 ms** to first audio for espeak-ng,
  **20–107 ms** for Piper.
- **Note timing**: unaffected. Measured at 120 bpm while speech was being fired
  and cancelled every 90 ms — worst-case timing error was **identical** with
  speech running and with it silent.
- **The engines are never touched.** This is a userspace process reading state
  the instrument already has.

The expensive part is exposing structured UI state. Ableton had already built
that for Move's web reader, which is exactly why one developer outside the
company could later put a screen reader on the device itself.

---

## The documents

- **[DESIGN.md](DESIGN.md)** — the specification. Every rule stated explicitly
  enough to implement from, including a catalogue of the mistakes we made and
  caught so you do not have to. **This is the real deliverable.**
- **[FINDINGS.md](FINDINGS.md)** — measurements and testing notes.

---

## Running it

Python 3.11+, macOS or Linux. `numpy` and `sounddevice` only.

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./run
```

You also need at least one speech engine. Either or both:

```bash
brew install espeak-ng                       # or: apt install espeak-ng
./.venv/bin/pip install -r requirements-piper.txt
cd voices && ../.venv/bin/python -m piper.download_voices en_US-lessac-medium
```

Useful flags: `--device "name"`, `--engine espeak|piper|say`, `--rate 400`,
`--verbosity terse|normal|verbose`, `--space mono|stereo|binaural`,
`--braille`, `--audition`, `--demo`, `--wizard`.

`--demo` plays the whole argument by ear in about two minutes, hands-free:
one walk through a Combi at all three verbosity levels, then a held-key
burst. Nothing in it is scripted speech — every announcement is generated
live by feeding keystrokes through the same code path real keys take, so the
demo can never drift from what the prototype actually does. Start here when
showing this to someone who owns a product.

`--audition` plays a hands-free comparison of the speech engines. Useful when
the question is latency and interruption rather than what gets said.

---

## Tests

```bash
./.venv/bin/python test_announcements.py
```

These assert the **exact strings printed in the DESIGN.md verbosity table**.
The specification is executable: change an announcement rule without changing
the document and the tests fail. They have already caught one error in the
document and one bad assumption in a test.

## Licence

Code is [Apache 2.0](LICENSE); the documentation is additionally
[CC BY 4.0](LICENSE-DOCS.md). Apache rather than MIT for two reasons: an
explicit patent grant, which removes a reason for a corporate legal department
to say no, and a trademark clause, so contributing code does not convey rights
to the name.

Copy the specification into your internal engineering documents, translate it,
quote it, build commercial products from it. Attribution is the only condition.

See [CONTRIBUTING.md](CONTRIBUTING.md) — the most useful contributions are
usually not code.

## Status

A demonstration prototype for a design conversation. Not a product, and not
trying to be one. The parameter tree is modelled on a Korg Kronos closely
enough to be recognisable and is deliberately not firmware-accurate — the point
is the shape of the state, not the contents.

Non-English translations in `speechproto/strings.py` prove the architecture and
**need a native speaker before being shown to anyone.**
