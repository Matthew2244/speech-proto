# Speech feedback on a hardware workstation — a specification

This document states the interaction rules explicitly enough to implement from.
It is the deliverable. The code in this repository is a working reference for
it, not the point of it.

It assumes you have already decided to add speech. It is about the part that
decides whether anyone keeps it switched on.

---

## 0. The problem this solves

When a blind musician asks for speech, engineers hear *"read the screen aloud"*.
That produces something that technically works and is practically unusable: too
slow, too talkative, interrupting itself, useless in performance. It ships, the
community reviews it badly, and it gets quietly abandoned.

The difference between speech blind musicians use for years and speech they
disable on the first afternoon is **entirely in the interaction design** — how
much it says, when it says it, how fast it gets out of the way, and whether it
ever makes you wait.

None of that is expensive. All of it has to be decided deliberately.

---

## 1. The governing principle

> **Announce what changed, not everything that is true.**

Almost every rule below follows from this sentence.

The obvious implementation describes the current state on every keypress. It
re-reads the submenu you never left. It repeats the parameter name you are
holding in your head. It says *"Filter, Cutoff, 64"* when the only thing that
happened is that 63 became 64.

You cannot fix that with a faster voice. You fix it by knowing what was true a
moment ago — which means **focus must be tracked and snapshotted**, and the
announcement must be computed from a *pair* of states, not from one.

---

## 2. The state layer

Build this once. Everything else consumes it.

Every control exposes, as plain data with no speech vocabulary in it:

| Field | Purpose |
|---|---|
| `name` | e.g. `Cutoff` |
| `kind` | `continuous` \| `stepped` \| `toggle` \| `text` \| `node` |
| `value` | the display value — `C064`, not `64` |
| `minimum`, `maximum` | rendered through the same formatter as the value |
| `index`, `count` | position among siblings, for "item 2 of 4" |
| `children`, `child_label` | for containers: how many, and of what |
| `position` | 0.0–1.0 within range — drives earcon pitch |
| `at_min`, `at_max` | at a limit |
| `role` | *semantic* tag, e.g. `pan` — see §7.3 |
| `path` | ancestry, for Braille and for context |
| `bounds` | screen rectangle — required for touch, see §12 |

Two rules about this layer:

1. **Nothing in it knows speech exists.** No engine, no verbosity, no wording.
2. **It must serialise.** If the whole instrument state cannot be dumped as
   JSON, you have coupled it to your renderer and you will pay for it when you
   add Braille, a remote editor, or a community tool.

This is the expensive half, and it is the half that pays for everything else.
Ableton had already built it for Move's web-based screen reader; that is why
one developer outside the company could later put a screen reader *on the
device* — the structured data already existed, and he routed it somewhere new.

---

## 3. What must be tracked

Every navigation action produces a **change**: the focus before, the focus
after, and a tag for what kind of movement it was.

| Event | Meaning |
|---|---|
| `MOVED` | to a sibling |
| `DESCENDED` | into a submenu |
| `ASCENDED` | out of one |
| `VALUE` | a value changed |
| `MODE` | switched top-level mode |
| `VALUE_LIMIT` | asked to push a value past its bound |
| `LIST_EDGE` | asked to move past the first or last sibling |
| `READ_ONLY` | asked to change something that cannot change |
| `NONE` | nothing happened |

**`VALUE_LIMIT` and `LIST_EDGE` must be distinct events.** Collapsing them is
the easy mistake and it produces a screen reader that repeats itself at every
list boundary. See §4.4.

The before-state must be an immutable **snapshot**, not a reference. Controls
are mutable; if "before" points at the live cutoff object, changing the value
rewrites history and every diff comes out empty.

---

## 4. The announcement rules

Implement as a **single function** taking `(previous, current, event, verbosity)`
and returning a string. One function, so the whole design can be read in one
place. Returning `""` — silence — is a valid and frequent answer.

### 4.1 Three verbosity levels

| | Terse | Normal (default) | Verbose |
|---|---|---|---|
| Move to a parameter | `Cutoff, 64` | `Cutoff, 64` | `Filter, item 2 of 4, Cutoff, value 64, range 0 to 127` |
| Change its value | `65` | `65` | `65 of 127` |
| Enter a submenu | `Filter` | `Filter, 4 parameters, Type` | `Filter, submenu, 4 parameters, item 1 of 4, Type, Low Pass 24` |
| Leave a submenu | `Filter` | `Filter` | `Program, item 5 of 7, Filter` |
| Land on a submenu | `Filter` | `Filter, 4 parameters` | `Program, item 5 of 7, Filter, submenu, 4 parameters` |
| Push past a limit | `127` | `127, maximum` | `127 of 127, maximum` |
| Run off a list end | *(silence)* | *(silence)* | *(silence)* |
| Toggle | `on` | `Mute, on` | `Mute, on` |
| Change mode | `Combi` | `Combi, Name, Piano Pad Split` | `Combi, item 1 of 4, Name, …` |
| Free-text field | *(silence)* | `Press Enter to edit` | `Press Enter to edit` |

**Terse and Normal are identical for the two most frequent actions.** This is
deliberate and is the heart of the verbosity model:

> Verbosity is not a volume knob applied evenly. It is a judgement about
> *which* actions deserve more words.

Moving and nudging happen constantly and are already unambiguous. Entering a
submenu happens rarely and is where you get lost. Spend terseness where it is
not needed; spend detail where it is.

### 4.2 Crossing into a new container

Moving from Timbre 3's Volume to Timbre 4's Volume announces:

```
Timbre 4, 110
```

The container changed, so name it. The parameter did **not** change, so drop
it. This is the strictest reading of §1 and it is the rule that makes editing
sixteen timbres bearable.

### 4.3 Landing on a submenu

You must be able to tell a container from a parameter **without pressing a key
to find out.** Guessing is not navigation.

Two cues, both required:

- **A distinct earcon** on arrival — see §7.1.
- **Words**: Normal says `Filter, 4 parameters`. The count tells you it is a
  container *and* how big, in two words, so you can decide whether to scan or
  jump before you start.

### 4.4 The two kinds of "you cannot go further"

**Value limit** — the value is pinned at 127 and you asked for more. Something
*is* true and worth hearing: `127, maximum`, plus the limit earcon. Never the
parameter name; you are holding the knob.

**List edge** — you are on the first item and pressed Up. **Nothing changed.**
Under §1 the correct amount of speech is **none**. The limit earcon carries it.

Speaking here means repeating the item you never left, at every boundary,
forever. It is the single most irritating thing a screen reader does.

Lists **do not wrap.** Wrapping silently past the boundary of a sixteen-timbre
list means you no longer know where you are, and finding out by muting the
wrong timbre is not an acceptable way to find out.

### 4.5 Where am I

A dedicated key reports the current position without moving, at full context,
**always speaking regardless of every other setting**. It is the way back when
speech has been switched off, and the first thing anyone reaches for when lost.

---

## 5. Interruption — non-negotiable

> Any keypress cancels speech in progress immediately and begins the new
> announcement. No queueing. No finishing the sentence.

Holding a key must produce a rapid stream of clipped partial words tracking the
hand in real time — not a backlog playing out three seconds behind.

If the previous announcement is still playing when the user acts, it is wrong
by definition: it describes a state they have already left.

**This one behaviour is the difference between speech blind musicians use and
speech they disable on day one.** If it is not right, nothing built on top of
it will feel right.

Implementation requirement: interruption must be **discarding buffered audio**,
not asking a synthesiser to stop. Own the samples. See §11.

A dedicated **silence key** stops speech instantly and says nothing in reply. A
silence key that announces itself is not a silence key.

---

## 6. Latency

Measured on the reference implementation:

| Engine | Time to first audio | Licence |
|---|---|---|
| espeak-ng | ~13 ms, flat regardless of length | GPL-3.0-or-later |
| Piper | 20 ms short, 35 ms typical, 107 ms verbose | **MIT** |
| macOS `say` | ~1000 ms warm, ~2400 ms cold | proprietary |

Under about 100 ms reads as instantaneous. Around a second is unusable no
matter how good the voice is.

**Piper's latency scales with text length; espeak's does not.** At Verbose,
where announcements get long, Piper is several times slower. Verbosity and
engine choice are therefore *not* independent settings, which is not obvious
and should be stated in the manual.

### 6.1 Speech must never delay a note

Notes belong on their **own mixing track**, summed with speech and earcons, not
queued behind them. This makes the guarantee structural: cancelling an
announcement clears the speech track and there is no code path by which it can
disturb a note already scheduled.

Reference measurement, clicks at 120 bpm while announcements were being fired
and cancelled every 90 ms:

```
while speaking : mean 6.68 ms, max 10.06 ms
while quiet    : mean 7.04 ms, max 10.06 ms
```

Identical. Speech made no measurable difference.

---

## 7. Earcons

Short non-speech tones. **This is the layer everyone forgets, and it is the one
that makes fast editing possible at all.**

"Sixty-four" takes about 600 ms to say. A tone encoding the same position takes
60, and you can hear it *while* the value is still moving. Sweeping a filter,
you do not want the numbers read to you.

### 7.1 The vocabulary

| Earcon | Meaning |
|---|---|
| value | pitch rises with position in range |
| submenu | you have landed on something you can enter |
| level | rising pair entering a submenu, falling leaving |
| limit | low double-pulse at either end of a range |
| toggle | rising fifth for on, falling for off |
| busy | soft repeating tick, one voice per operation type |
| done | resolving pair on success, falling on failure |
| route | a sweep across the stereo field — the sound moving |
| power | three notes rising at startup, falling at shutdown |

Keep it small. An alphabet nobody can learn in an afternoon is one nobody
learns. Deliberately **no earcon for a mode change** — speech names the mode
unambiguously and the vocabulary is better spent elsewhere.

Navigational earcons stay **under 100 ms** and well below speech level, and
must **never delay the speech that follows.** That requires mixing, not
queueing.

Pitch maps to position **logarithmically**. A linear map bunches the entire
bottom half of a range into an indistinguishable band.

### 7.2 Packs

Offer several timbral sets — but **a pack changes timbre only, never meaning.**
Value is always pitch-mapped position; a limit is always a low double-pulse.
Swap packs and nothing learned stops being true.

This is not only taste. A set that reads beautifully in a quiet studio can
vanish under a loud band; one that cuts through a stage is fatiguing across
eight hours of programming.

### 7.3 Stereo position carries a second meaning

Pitch is already spent on "where in the range", so stereo position is free to
carry something else. What it carries depends on context:

- **A pan parameter pans to the value it is setting.** Editing Pan to L20, the
  tone arrives from the left. You hear the field you are building. This is why
  the state layer needs a `role` tag: matching on the parameter's *name* works
  until someone renames or translates it.
- **Other continuous parameters reinforce the pitch** — low sounds low and
  left. Redundant on purpose; two cues for one fact is how something becomes
  learnable without being taught.
- **Submenu movement pans by depth**, so the hierarchy has a shape you can feel
  rather than count.

Offer **mono, stereo, and binaural** renderings, switchable. Binaural needs
interaural time difference, level difference, **and head-shadow filtering** —
without the filtering it is just stereo with a delay, and the timbre difference
between the ears is most of what sells it.

---

## 8. Output routing

On stage, speech goes to in-ear monitors and **must never reach the house PA.**
A speech implementation that can only talk out of the main outputs is useless
in performance, and that one mistake is enough to kill adoption.

Requirements:

1. **Speech and earcons route independently**, and either may target more than
   one destination.
2. **Naming the device is not enough.** On a 64-output interface, outputs 1–2
   are the main mix. The user must choose the **specific outputs**.
3. **Mono must be selectable.** A stage box or crowded patchbay may have
   exactly one spare send. A feature that insists on two channels is a feature
   that cannot be used that night. Fold down by **averaging, not summing** —
   summing correlated channels adds 6 dB and clips speech.
4. **Persist the device by name, never by index.** Index-based enumeration
   renumbers when anything is plugged in or removed. In one test session here,
   index 5 meant three different devices over twenty minutes with no hardware
   change. A saved index silently sends speech to the wrong output.

### 8.1 Changing the output safely

Routing is the one setting that can remove the interface you need in order to
undo it. An "are you sure?" prompt does not help — it asks before the answer is
knowable, because you cannot tell whether an output works until something has
come out of it.

Use the pattern every OS uses for changing screen resolution:

1. Arrowing to a new output **changes nothing**. It says the name, plus
   *"Press Enter to apply."*
2. Enter applies it and plays a confirmation **on the new output**: a sweep
   tone, then *"Speech now on ⟨device⟩. Press Enter to keep."* A soft tick
   marks each remaining second.
3. Enter keeps it. Escape, or ten seconds of nothing, puts it back — and the
   revert announces on the **old** output, because by then that is the one you
   can hear.

**The proof is the sound itself.** Hearing the confirmation proves the output
works. Hearing nothing means you do nothing, and it returns to a state known to
work. Silence — the failure that strands you — is exactly what triggers
recovery.

The confirmation earcons must **ignore the earcons-off switch.** Turning
earcons off says you do not want to be told about navigation, not that you want
routing changes to happen silently with no way to tell if they worked.

### 8.2 When an output disappears

Mixers get powered off; interfaces get unplugged. From inside a silent
instrument this is **indistinguishable from a crash** — nothing happens when
you press a key, and there is no way to discover why.

Watch for it. Fall back to a working output and say so, on the new output.

### 8.3 When an engine cannot reach an output

Some engines address devices through their own namespace and cannot see
everything the system can. Do not switch silently and fall back to the default;
**refuse and say why.** Anything else is discovered during a show.

---

## 9. Long operations

Saving a patch. Backing up sounds. Loading. Updating.

A sighted player gets a progress bar. A blind player gets silence — and
**silence during a save is indistinguishable from a crash.** That ambiguity is
what makes people pull the power on a machine mid-write.

Apply §1's logic to waiting:

- **A repeating tick carries continuity**, at zero verbal cost, and proves the
  machine is alive. Let it drift slightly upward in pitch so a long wait feels
  like progress even when no real percentage exists.
- **Speech carries milestones only**, and how many depends on verbosity:
  Terse gets none, Normal gets halfway, Verbose gets quarters.
- **One tick voice per kind of operation**, so you know what is taking its time
  without being told twice.
- Announce completion, and announce failure differently.

Reading a percentage every second is unusable. Saying nothing is frightening.

---

## 10. Settings, language, and learning

### 10.1 Accessibility settings are ordinary parameters

They live in the same tree, navigated and announced by the same code as filter
cutoff. That means they are reachable by the same muscle memory — including
before speech has been switched on.

**Speech and earcons switch off independently.** Every combination must work,
including both off: that is the Braille-only case, and it is not a broken
configuration. Which creates one trap worth naming — speech off with no earcons
and no Braille strands the user with no way back to the setting that did it.
The "where am I" key (§4.5) is the answer, and it must speak regardless.

Any setting whose value the user cannot judge without hearing it — earcon pack,
spatial mode — should also be **arrow to select, Enter to preview**. Previewing
as you scan means hearing a demonstration before you have heard the name, which
is backwards.

**Do not offer choices that cannot take effect.** Route earcons to a single
output and there is no stereo field, so Stereo and Binaural are not merely
ineffective — they are not choices. Remove them from the list rather than
leaving the setting to lie. Options that do nothing cost navigation time and
teach the user that this instrument's menus do not mean what they say, which is
expensive far beyond the one setting.

Two details make this work rather than annoy:

- **Keep the setting in place, at the same position.** Collapse its options,
  do not remove the item. A menu that changes length under you is its own
  problem, and muscle memory is most of how a blind user moves quickly.
- **Give the choice back.** If the user had picked Binaural before a mono
  output forced Mono, restore Binaural when they return to a stereo output.
  Silently costing someone a setting they chose deliberately is a small theft
  they will notice and resent.

### 10.2 Language is two things, not one

Shipping a Spanish *voice* gives you English words mangled by Spanish
pronunciation rules. That is worse than useless.

Real support is:

1. **A voice for that language** — nearly free; espeak-ng ships over a hundred.
2. **The words themselves** — every framing word: maximum, item, of, submenu,
   parameters, read only.

Enforce it structurally: **no user-facing string literal anywhere in the
announcement builder.** Every word comes from a table keyed by language. Free
on day one, near-impossible to retrofit.

Choosing a language must change **both halves at once.**

**Parameter names do not translate.** `Cutoff`, `Resonance`, `IFX 1` are
international vocabulary among musicians and are what is printed on the panel.
Translating them would leave a Spanish player unable to match what they hear to
any manual or forum post in existence. Only the framing words translate.

### 10.3 Learning mode

The problem with an earcon vocabulary is the first hour. Solve it with **fading
scaffolding**: name each sound the first three times it plays, then stop.

```
limit tone …  "limit"
limit tone …  "limit"
limit tone …  "limit"
limit tone …          ← from here on, just the tone
```

You are taught in the exact situation the sound means something — the only
context in which it is learnable — and the teaching removes itself before it
becomes the nagging that makes people switch it off.

Key hints work the same way: "Right to enter" on a submenu, three times, gone.

Offer a **drill** as well, playing the whole vocabulary named, end to end. Both
routes exist because both kinds of learner do.

### 10.4 First run

The hardest five minutes is the first five, because everything you would
normally lean on is what has not been configured yet.

**The first question is not "what language?" It is "can you hear me?"**

Everything else is downstream. Ask about language first and you have asked a
question the user may not have heard, in a voice going to an output they are
not listening to — and they cannot tell you, because the only channel you have
is the broken one.

Walk the outputs, speaking on each: *"Can you hear this? Enter to use it, Space
to try the next."* **Silence is the answer that makes progress.** There must be
no state in which being unable to hear leaves the user stuck.

Then language, voice, rate, verbosity, earcons. Preview the rate *at* the rate —
a number means nothing until you hear it. Escape must skip the whole thing; a
wizard you cannot escape is a trap.

### 10.5 Speech rate

Support at least **400 words per minute.** Blind users run screen readers far
faster than sighted people expect, and a ceiling of 200 makes the feature
useless to exactly the people who most need it. This reliably surprises sighted
audiences in a demo, which is itself worth showing.

---

## 10.6 Text entry without a screen

Naming a program is the one place the rules in §4 stop helping, because there
is no "next value" to arrow to.

A sighted user sees the whole string, the cursor within it, and every change as
it happens. Take the screen away and all three vanish at once, so each has to
be handed back deliberately:

- **Echo every character as it is inserted.** Otherwise you are typing into a
  void and find out about the mistake at the end.
- **Say the character you land on when moving**, and say `end` when there is
  nothing there. Position is otherwise unknowable.
- **Backspace announces what was deleted**, not what is now adjacent. This is
  the one everybody gets backwards. You pressed a key to remove a character;
  the useful information is which character went.
- **Speak punctuation and whitespace by name.** A space is silence, and silence
  is indistinguishable from nothing having happened. `space`, `dash`, `period`.
  Announce capitals as `cap b` — most voices do not distinguish case.
- **Offer spell-back.** A wrong letter inside a name that still sounds right —
  `Grand` against `Grnad` — is invisible to any amount of reading aloud. One
  key that spells the buffer out catches it.
- **Escape restores the original exactly.** Losing a patch name you have used
  for years to a mistyped character, with no way back, is how people learn
  never to edit anything again.

**Committing reads the whole string back.** It is the only moment where reading
everything is correct, because it is the moment you are checking your work —
the exception that proves §1 rather than breaking it.

Entry is **modal**: while editing, letter keys insert letters and cannot also
be shortcuts. Anything else gives you an editor that changes settings at random
while you type a name.

---

## 11. What the speech engine must provide

The interface is deliberately tiny:

```
speak(text)            cancel anything in progress, begin immediately, do not block
stop()                 silence now
is_speaking()          still producing audio
set_rate(wpm)          up to at least 400
set_voice(name)        offer several — a voice you find grating is one you stop using
```

That is the whole contract. Everything hard lives above it.

**The engine must hand you PCM**, not play audio itself. If it owns its own
output you cannot route it, cannot mix it against earcons, and cannot interrupt
it precisely. Every routing requirement in §8 depends on owning the samples.

### 11.1 Licensing

**espeak-ng is GPL-3.0-or-later.** Its anti-tivoization clause requires that
users be able to run modified versions on the device — a condition many
hardware makers will refuse. That is a property of one swappable component, not
of this design.

**Piper is MIT** and sounds dramatically better. **Flite** is BSD. Commercial
engines license per unit. The interface above is small precisely so this is a
procurement decision, not an architectural one.

---

## 12. Touch and gestures

A touchscreen needs **one addition to the state layer**: a `bounds` rectangle
per control. That is all.

Touch exploration is then a spatial query over the same tree, and every rule in
§4 applies unchanged:

| Gesture | Action |
|---|---|
| drag a finger | speak whatever is under it |
| double tap | activate |
| swipe left / right | previous / next |
| two-finger tap | silence |
| rotor equivalent | verbosity, or navigation granularity |

The touchscreen is not a second project.

---

## 13. Two ways to ship, and they share everything

**On-device** — the instrument speaks for itself. Standalone, ~20 ms, works on
a dark stage with no phone in sight. This is the flagship.

**Host screen reader** — the instrument exposes state and a connected computer
or phone speaks it through the user's own screen reader. Far cheaper to build,
and it has one real advantage: the user's own voice, rate, and Braille display,
already configured and already loved.

But it tethers you, and a dependency on a second device that can sleep,
disconnect, or run flat is a genuine failure mode on stage.

**Ship both. Never ship only the second.** They are two consumers of the same
state layer, which is the entire argument of this document.

---

## 14. Mistakes to expect

Every one of these was made and caught while building the reference
implementation. They are cheap to avoid and expensive to find.

1. **Speaking a hint as a separate utterance.** Every keypress cancels speech —
   including yours. A hint spoken after an announcement *interrupts it*, so the
   user hears only the hint. Hints join the same utterance.
2. **One queue for speech and earcons.** The earcon then delays the speech it
   was meant to introduce.
3. **Collapsing the two limit events.** Produces a reader that repeats itself
   at every list boundary.
4. **A settings screen showing something other than the truth.** Worse than
   showing nothing: it invites the user to "change" to what they already have,
   and to trust it about everything else.
5. **A setting that silently does nothing.** Spatial earcons on a mono output,
   for instance. Say so; it costs one sentence and it reads as broken otherwise.
6. **Clamping a channel pair index-wise.** Asking for outputs 17–18 on a stereo
   device gives (1, 1) — silently mono and hard-panned. Clamp the pair.
7. **Persisting devices by index.** They renumber. Speech ends up somewhere
   else and nothing tells you.
8. **Silence as a response to an impossible action.** Pressing Right on a
   read-only field must not be indistinguishable from a broken key.
9. **Assuming the failure is visible.** A sighted developer sees the mixer's
   lights go out, the dialog, the spinner. Test with the screen off. Every bug
   that survives that is the only kind that matters here.

---

## 15. Prior art worth knowing

Ableton shipped **Move** with an official screen reader accessed through a
browser at `move.local`. It works well. Its limitation, as blind musician Andre
Louis put it, is that it does not let blind users be as untethered as sighted
ones — you need a phone or computer nearby.

Charles Vestal then built an unofficial framework (**Schwung**, originally
*Move Everything*) that runs alongside Move's stock firmware in what he calls
shadow mode, and put a screen reader **directly on the device** using Flite or
eSpeak-NG. He also made the WiFi PIN speak on-device, which the web version
could not. The result was the first genuinely standalone groovebox a blind
musician can operate with no other device present.

The crucial detail: **he reused Ableton's own screen-reader data.** The
structured accessibility metadata already existed for the web reader; he routed
it to a local speech engine.

Three lessons:

1. **The expensive part is exposing structured UI state. Speaking it is nearly
   free.** Once a machine-readable representation exists, speech is one consumer
   of it. So is Braille. So is a remote editor.
2. **Run alongside, do not replace.** Shadow mode meant the device still worked
   normally, which is why people were willing to try it.
3. **If one person outside the company managed this, a team with the source
   code is not looking at a moonshot.**
