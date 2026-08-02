"""
Layer 3 — earcons.

Short non-speech tones, synthesised in numpy, played on their own mixing track
so they can never delay the speech that follows them.

Why bother, when there is already a voice
------------------------------------------
Because speech is slow and a tone is not. "Sixty-four" takes about 600 ms to
say at a normal rate. A tone whose pitch encodes the same position takes 60,
and you can hear it *while* the value is still moving. When you sweep a filter,
you do not want the numbers read to you — you want to hear where you are in the
range, continuously, the way a sighted player watches a knob.

This is the layer everyone forgets, and it is the one that makes fast editing
possible at all.

What each earcon says
---------------------
    value      pitch rises with the value's position in its range
    limit      a distinct low double-pulse at either end
    level      a rising pair entering a submenu, falling leaving it
    toggle     rising fifth for on, falling fifth for off
    busy       a soft repeating tick, one voice per kind of operation
    done       a resolving pair when a long operation finishes
    power      a three-note rise at startup, fall at shutdown

Everything navigational is under 100 ms and quiet relative to speech.

Stereo position carries a second layer of meaning
--------------------------------------------------
Pitch is already spent on "where in the range". Stereo position is therefore
free to carry something else, and what it carries depends on context:

* **A pan parameter pans to the value it is setting.** Edit Pan to L20 and the
  tone arrives from the left. You hear the stereo field you are building.
* **Any other continuous parameter reinforces the pitch** — low sounds low and
  left, high sounds high and right. Redundant on purpose: two cues for one
  fact is how something becomes learnable without being taught.
* **Entering and leaving submenus pans by depth.** Top level is centred and
  each level inward sits further right, so the hierarchy has a shape you can
  feel rather than count.

Three renderings, because rooms differ
---------------------------------------
    MONO      centred, no positional information at all
    STEREO    constant-power amplitude panning; works on speakers
    BINAURAL  interaural time and level differences plus head-shadow filtering

Binaural here is honest but modest: real ITD and ILD, no HRTF dataset, because
that would mean a dependency and a licence. On in-ear monitors it reads as
genuinely outside the head; on speakers it collapses toward ordinary stereo,
which is why all three are switchable rather than one being chosen for you.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np

# Navigational earcons stay under 100 ms and well below speech level.
DEFAULT_LEVEL = 0.18
HEAD_RADIUS_M = 0.0875   # average human head
SPEED_OF_SOUND = 343.0


class Spatial(IntEnum):
    MONO = 1
    STEREO = 2
    BINAURAL = 3

    @classmethod
    def from_name(cls, name: str) -> "Spatial":
        return {"mono": cls.MONO, "stereo": cls.STEREO,
                "binaural": cls.BINAURAL}.get(name.strip().lower(), cls.STEREO)

    @property
    def label(self) -> str:
        return {1: "Mono", 2: "Stereo", 3: "Binaural"}[int(self)]


# --------------------------------------------------------------------- #
# Tone synthesis
# --------------------------------------------------------------------- #

def _envelope(n: int, sr: float, attack_ms: float = 4.0, release_ms: float = 12.0) -> np.ndarray:
    """
    Attack and release ramps, because a tone that starts instantly clicks.

    Four milliseconds is short enough to still feel immediate and long enough
    to remove the click entirely. The release is longer so the tone gets out of
    the way politely rather than being chopped.
    """
    env = np.ones(n, dtype=np.float32)
    a = min(int(sr * attack_ms / 1000.0), n // 2)
    r = min(int(sr * release_ms / 1000.0), n // 2)
    if a > 0:
        env[:a] = np.linspace(0.0, 1.0, a, dtype=np.float32)
    if r > 0:
        env[-r:] = np.linspace(1.0, 0.0, r, dtype=np.float32)
    return env


def _decay_envelope(n: int, sr: float, tau_ms: float = 90.0) -> np.ndarray:
    """Instant attack, exponential decay — a struck sound rather than a held one."""
    t = np.arange(n, dtype=np.float32) / sr
    env = np.exp(-t / (tau_ms / 1000.0)).astype(np.float32)
    a = min(int(sr * 0.002), n // 2)      # 2 ms, just enough to kill the click
    if a > 0:
        env[:a] *= np.linspace(0.0, 1.0, a, dtype=np.float32)
    return env


# --------------------------------------------------------------------- #
# Earcon packs — the same vocabulary in different voices.
#
# A pack changes **timbre only, never meaning**. Value is always pitch-mapped
# position, a limit is always a low double-pulse, entering a submenu is always
# a rising pair. Swap packs and nothing you have learned stops being true —
# only the colour changes.
#
# That constraint is the whole reason packs are safe to offer. A "pack" that
# reassigned which sound meant what would be a different instrument wearing the
# same name, and the point of an earcon is that you stop having to think about
# it. Screen reader sound schemes work the same way and for the same reason.
#
# Beyond taste, packs solve a real problem: a set that reads beautifully in a
# quiet studio can vanish entirely under a loud band, and one that cuts through
# a stage can be fatiguing to sit with for eight hours of programming.
# --------------------------------------------------------------------- #

def _wave_sine(freq: float, n: int, sr: float) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / sr
    return np.sin(2 * np.pi * freq * t, dtype=np.float32)


def _wave_marimba(freq: float, n: int, sr: float) -> np.ndarray:
    # A marimba's strongest overtone is the fourth, which is what gives it that
    # hollow wooden character rather than a plain tone.
    t = np.arange(n, dtype=np.float32) / sr
    return (np.sin(2 * np.pi * freq * t)
            + 0.35 * np.sin(8 * np.pi * freq * t)).astype(np.float32)


def _wave_glass(freq: float, n: int, sr: float) -> np.ndarray:
    # Inharmonic partials: bells are not built from whole-number multiples,
    # and that is exactly why they sound like bells.
    t = np.arange(n, dtype=np.float32) / sr
    return (np.sin(2 * np.pi * freq * t)
            + 0.55 * np.sin(2 * np.pi * freq * 2.76 * t)
            + 0.25 * np.sin(2 * np.pi * freq * 5.40 * t)).astype(np.float32)


def _wave_pulse(freq: float, n: int, sr: float) -> np.ndarray:
    # A few odd harmonics rather than a hard square, so it cuts without the
    # aliasing fizz a raw square gives at these pitches.
    t = np.arange(n, dtype=np.float32) / sr
    sig = np.zeros(n, dtype=np.float32)
    for k in (1, 3, 5, 7):
        sig += (1.0 / k) * np.sin(2 * np.pi * freq * k * t)
    return (sig * 0.6).astype(np.float32)


def _wave_air(freq: float, n: int, sr: float) -> np.ndarray:
    # Noise pushed through a resonator. Soft and breathy — the pack for when
    # you want to know something happened without being told about it.
    rng = np.random.default_rng(int(freq) & 0xFFFF)   # stable per pitch
    noise = rng.standard_normal(n).astype(np.float32)
    out = np.empty(n, dtype=np.float32)
    y1 = y2 = 0.0
    w = 2 * np.pi * freq / sr
    r = 0.985
    a1, a2 = 2 * r * np.cos(w), -(r * r)
    for i in range(n):
        y = noise[i] + a1 * y1 + a2 * y2
        out[i] = y
        y2, y1 = y1, y
    peak = float(np.abs(out).max()) or 1.0
    return (out / peak).astype(np.float32)


def _wave_woodblock(freq: float, n: int, sr: float) -> np.ndarray:
    # Almost pure transient: two inharmonic partials plus a noise tick that is
    # gone in four milliseconds. The pack for when you want confirmation and
    # nothing else — it takes up almost no time at all.
    t = np.arange(n, dtype=np.float32) / sr
    body = (np.sin(2 * np.pi * freq * 2.2 * t)
            + 0.5 * np.sin(2 * np.pi * freq * 3.7 * t))
    rng = np.random.default_rng(int(freq) & 0xFFFF)
    tick = rng.standard_normal(n).astype(np.float32)
    click = min(int(sr * 0.004), n)
    body[:click] += tick[:click] * 0.8
    return (body * 0.55).astype(np.float32)


def _wave_fm(freq: float, n: int, sr: float) -> np.ndarray:
    # Two-operator FM with a decaying modulation index — the DX7 electric piano
    # and bell trick. Bright at the attack, pure by the tail, which is exactly
    # the shape an alert wants: arrive clearly, leave quietly.
    t = np.arange(n, dtype=np.float32) / sr
    index = 3.2 * np.exp(-t / 0.045)
    mod = np.sin(2 * np.pi * freq * 3.5 * t)
    return np.sin(2 * np.pi * freq * t + index * mod).astype(np.float32)


def _wave_analog(freq: float, n: int, sr: float) -> np.ndarray:
    # Band-limited sawtooth swept by a decaying low-pass: the Moog gesture.
    # Familiar to anyone who has touched a synth, which is the entire audience.
    t = np.arange(n, dtype=np.float32) / sr
    saw = np.zeros(n, dtype=np.float32)
    for k in range(1, 9):
        if freq * k < sr * 0.45:
            saw += (1.0 / k) * np.sin(2 * np.pi * freq * k * t)
    out = np.empty(n, dtype=np.float32)
    acc = 0.0
    for i in range(n):
        # Filter opens fast, closes over the tail.
        a = 0.82 * float(np.exp(-t[i] / 0.05))
        acc = (1.0 - a) * saw[i] + a * acc
        out[i] = acc
    peak = float(np.abs(out).max()) or 1.0
    return (out / peak * 0.8).astype(np.float32)


class Pack:
    """One earcon flavour: a waveform, an envelope, and a level trim."""

    def __init__(self, name: str, wave, percussive: bool = False,
                 tau_ms: float = 90.0, trim: float = 1.0, blurb: str = ""):
        self.name = name
        self.wave = wave
        self.percussive = percussive
        self.tau_ms = tau_ms
        self.trim = trim
        self.blurb = blurb

    def render(self, freq: float, ms: float, sr: float,
               level: float = DEFAULT_LEVEL) -> np.ndarray:
        n = max(1, int(sr * ms / 1000.0))
        sig = self.wave(freq, n, sr)
        env = (_decay_envelope(n, sr, self.tau_ms) if self.percussive
               else _envelope(n, sr))
        return (sig * env * level * self.trim).astype(np.float32)


PACKS: dict[str, Pack] = {
    "Sine": Pack("Sine", _wave_sine, blurb="Clean and neutral. The default."),
    "Marimba": Pack("Marimba", _wave_marimba, percussive=True, tau_ms=110,
                    trim=1.15, blurb="Wooden and musical. Easy to live with."),
    "Glass": Pack("Glass", _wave_glass, percussive=True, tau_ms=260, trim=0.75,
                  blurb="Bell-like and bright. Carries over a quiet room."),
    "Pulse": Pack("Pulse", _wave_pulse, trim=0.85,
                  blurb="Hard and synthetic. Cuts through a loud stage."),
    "Air": Pack("Air", _wave_air, percussive=True, tau_ms=70, trim=1.6,
                blurb="Breathy and soft. Nearly subliminal."),
    "Woodblock": Pack("Woodblock", _wave_woodblock, percussive=True, tau_ms=28,
                      trim=0.80,
                      blurb="Dry and instant. The least time a sound can take."),
    "Vintage FM": Pack("Vintage FM", _wave_fm, percussive=True, tau_ms=150,
                       trim=1.05,
                       blurb="Two-operator FM. Bright attack, pure tail."),
    "Analog": Pack("Analog", _wave_analog, percussive=True, tau_ms=130,
                   trim=1.1,
                   blurb="Filtered saw with a closing sweep. Familiar to any synth player."),
}

PACK_NAMES = list(PACKS)


def tone(freq: float, ms: float, sr: float, level: float = DEFAULT_LEVEL,
         harmonic: float = 0.0, pack: Pack | None = None) -> np.ndarray:
    """
    One tone in the current pack's voice.

    `harmonic` survives from the original sine-only version and still adds a
    little second harmonic to the plain sine — a pure sine is hard to localise
    and easy to miss under a band.
    """
    if pack is not None and pack.name != "Sine":
        return pack.render(freq, ms, sr, level)
    n = max(1, int(sr * ms / 1000.0))
    t = np.arange(n, dtype=np.float32) / sr
    sig = np.sin(2 * np.pi * freq * t, dtype=np.float32)
    if harmonic:
        sig += harmonic * np.sin(4 * np.pi * freq * t, dtype=np.float32)
    return (sig * _envelope(n, sr) * level).astype(np.float32)


def silence(ms: float, sr: float) -> np.ndarray:
    return np.zeros(max(1, int(sr * ms / 1000.0)), dtype=np.float32)


def pitch_for_position(position: float, low_hz: float = 320.0,
                       high_hz: float = 1900.0) -> float:
    """
    Map 0..1 to a frequency, **logarithmically**.

    Pitch perception is logarithmic, so a linear map would bunch the whole
    bottom half of a parameter's range into a narrow, indistinguishable band.
    Two and a half octaves is enough to hear position clearly without the top
    end becoming shrill on in-ears.
    """
    p = 0.0 if position is None else max(0.0, min(1.0, position))
    return float(low_hz * (high_hz / low_hz) ** p)


# --------------------------------------------------------------------- #
# Spatialisation
# --------------------------------------------------------------------- #

def spatialise(mono: np.ndarray, pan: float, mode: Spatial, sr: float) -> np.ndarray:
    """
    Place a mono tone in the stereo field. `pan` is -1 (left) to +1 (right).
    """
    pan = max(-1.0, min(1.0, float(pan)))

    if mode is Spatial.MONO:
        return np.repeat(mono[:, None], 2, axis=1)

    if mode is Spatial.STEREO:
        # Constant power: sin/cos law, so the tone does not dip in loudness as
        # it crosses the centre. Linear panning has an audible hole in the
        # middle, which on a positional cue reads as a wrong value.
        angle = (pan + 1.0) * 0.25 * np.pi
        left, right = float(np.cos(angle)), float(np.sin(angle))
        return np.stack([mono * left, mono * right], axis=1)

    # BINAURAL: time difference, level difference, and head shadow.
    #
    # ITD is the dominant cue below about 1.5 kHz and is what makes a sound
    # seem to come from outside the head rather than from one side of it.
    # Woodworth's approximation, good enough and cheap: the far ear hears the
    # sound later by (r/c)(θ + sin θ).
    theta = pan * (np.pi / 2.0)
    itd_s = (HEAD_RADIUS_M / SPEED_OF_SOUND) * (abs(theta) + np.sin(abs(theta)))
    delay = int(round(itd_s * sr))                    # ~31 samples at 48 kHz

    near = mono
    far = _head_shadow(mono, abs(pan))                # far ear loses treble
    far = far * (1.0 - 0.35 * abs(pan))               # and a little level
    if delay > 0:
        far = np.concatenate([np.zeros(delay, dtype=np.float32), far])
        near = np.concatenate([near, np.zeros(delay, dtype=np.float32)])

    if pan >= 0:
        left, right = far, near
    else:
        left, right = near, far
    return np.stack([left, right], axis=1).astype(np.float32)


def _head_shadow(sig: np.ndarray, amount: float) -> np.ndarray:
    """
    One-pole low-pass standing in for the head blocking high frequencies.

    The skull attenuates treble on the far side far more than bass. Without
    this, binaural panning sounds like plain stereo with a delay — the timbre
    difference between the ears is a large part of what sells the illusion.
    """
    if amount <= 0.001:
        return sig.copy()
    # More pan -> more filtering. a=0 passes everything, a->1 filters hard.
    a = 0.72 * amount
    out = np.empty_like(sig)
    acc = 0.0
    for i in range(len(sig)):          # short buffers; a loop is fine here
        acc = (1.0 - a) * sig[i] + a * acc
        out[i] = acc
    return out


# --------------------------------------------------------------------- #
class Earcons:
    """
    Builds and plays the tones. Owns no policy about *when* — that is the
    interaction layer's job — only about what each one sounds like.
    """

    def __init__(self, bus, spatial: Spatial = Spatial.STEREO,
                 enabled: bool = True, pack: str = "Sine"):
        self.bus = bus
        self.spatial = spatial
        self.enabled = enabled
        self.pack = PACKS.get(pack, PACKS["Sine"])

    def set_pack(self, name: str) -> None:
        self.pack = PACKS.get(name, self.pack)

    def signature(self) -> list:
        """
        A short phrase that shows off the current pack: a value sweep, a limit,
        and a toggle. Played when the pack changes, because the name of a
        sound tells you nothing about the sound.
        """
        return [
            lambda: [self.value(p / 4.0, self.value_pan(p / 4.0, "pan")) for p in range(5)],
            lambda: self.limit(True),
            lambda: self.toggle(True),
        ]

    @property
    def sr(self) -> float:
        return self.bus.samplerate

    def _play(self, mono: np.ndarray, pan: float = 0.0) -> None:
        if not self.enabled or mono.size == 0:
            return
        self.bus.write(spatialise(mono, pan, self.spatial, self.sr))

    # -- the navigational set ------------------------------------------- #
    def value(self, position: float | None, pan: float = 0.0) -> None:
        """Pitch tracks the value's position in its range. The workhorse."""
        self._play(tone(pitch_for_position(position or 0.0), 55, self.sr,
                        harmonic=0.12, pack=self.pack), pan)

    def limit(self, at_max: bool) -> None:
        """
        A distinct double-pulse at either end of a range.

        Deliberately low and a little rough, so it can never be mistaken for a
        value tone — which is the mistake that matters, since a limit means the
        knob stopped moving and the value tone would imply it had not.
        """
        f = 220.0 if at_max else 165.0
        pulse = tone(f, 34, self.sr, level=DEFAULT_LEVEL * 1.15, harmonic=0.45, pack=self.pack)
        gap = silence(22, self.sr)
        self._play(np.concatenate([pulse, gap, pulse]), 0.0)

    def level(self, entering: bool, depth: int = 1) -> None:
        """
        Rising pair going in, falling pair coming out; panned by how deep you are.
        """
        lo, hi = 520.0, 780.0
        first, second = (lo, hi) if entering else (hi, lo)
        pan = self.depth_pan(depth)
        self._play(np.concatenate([
            tone(first, 38, self.sr, level=DEFAULT_LEVEL * 0.9, pack=self.pack),
            tone(second, 44, self.sr, level=DEFAULT_LEVEL * 0.9, pack=self.pack),
        ]), pan)

    def submenu(self) -> None:
        """
        Landing on something you can go *into*.

        Two identical short pulses, deliberately unlike the rising pair that
        means you *have* gone in. Arriving at a door and walking through it are
        different events and must not share a sound.

        Very short and quiet, because this fires on ordinary up-and-down
        movement — the most frequent thing you do. An obtrusive marker here
        would be the first thing anyone switched off.
        """
        pip = tone(1180.0, 16, self.sr, level=DEFAULT_LEVEL * 0.55, pack=self.pack)
        gap = silence(26, self.sr)
        self._play(np.concatenate([pip, gap, pip]), 0.0)

    def toggle(self, on: bool) -> None:
        """A rising fifth for on, a falling fifth for off. Musically obvious."""
        lo, hi = 440.0, 660.0
        first, second = (lo, hi) if on else (hi, lo)
        self._play(np.concatenate([
            tone(first, 36, self.sr, harmonic=0.2, pack=self.pack),
            tone(second, 46, self.sr, harmonic=0.2, pack=self.pack),
        ]), 0.0)

    # -- long operations ------------------------------------------------ #
    #
    # A blind player has no progress bar. Silence during a save is
    # indistinguishable from a crash, so anything with a wait has to keep
    # speaking for itself until it is done.

    #: One voice per kind of operation, so you know what is taking its time
    #: without being told again every second.
    BUSY_VOICES = {
        "save":   (587.0, 0.10),
        "load":   (494.0, 0.10),
        "backup": (392.0, 0.14),
        "update": (330.0, 0.14),
        "scan":   (659.0, 0.10),
    }

    def busy_tick(self, kind: str = "save", phase: int = 0) -> None:
        """
        One tick of a long operation. Called repeatedly by the busy loop.

        The tick drifts slightly upward as it repeats, which is what makes a
        wait feel like progress rather than a stuck machine — even when no real
        percentage is available to report.
        """
        base, level = self.BUSY_VOICES.get(kind, self.BUSY_VOICES["save"])
        freq = base * (1.0 + 0.012 * (phase % 8))
        self._play(tone(freq, 46, self.sr, level=level, pack=self.pack), 0.0)

    def done(self, kind: str = "save", ok: bool = True) -> None:
        """A resolving pair when it finishes; a falling one when it did not."""
        base, _ = self.BUSY_VOICES.get(kind, self.BUSY_VOICES["save"])
        pair = (base, base * 1.5) if ok else (base, base * 0.66)
        self._play(np.concatenate([
            tone(pair[0], 60, self.sr, level=DEFAULT_LEVEL, harmonic=0.2, pack=self.pack),
            tone(pair[1], 110, self.sr, level=DEFAULT_LEVEL, harmonic=0.2, pack=self.pack),
        ]), 0.0)

    # -- routing safety -------------------------------------------------- #
    #
    # These two deliberately **ignore the earcons-off switch**. They are not
    # decoration; they are the mechanism by which you find out whether an
    # output works at all. Someone who has turned earcons off has said they do
    # not want to be told about navigation — not that they want a routing
    # change to happen in silence with no way to tell if it worked.

    def route_confirm(self) -> None:
        """
        A tone that sweeps across the stereo field: the sound literally moving.

        Played on whichever output was just selected, so hearing it *is* the
        proof that the output works. That is the whole safety mechanism — no
        separate test, no dialog you cannot verify.
        """
        n = max(1, int(self.sr * 0.42))
        t = np.arange(n, dtype=np.float32) / self.sr
        # A rising glide, so it reads as "moving to" rather than "moving away".
        freq = 380.0 + 320.0 * (t / t[-1] if n > 1 else 0.0)
        mono = (np.sin(2 * np.pi * np.cumsum(freq) / self.sr, dtype=np.float32)
                * _envelope(n, self.sr, attack_ms=12, release_ms=90)
                * DEFAULT_LEVEL * 1.2)
        # Pan ramp, constant power, left to right across the whole tone.
        pan = np.linspace(-0.9, 0.9, n, dtype=np.float32)
        angle = (pan + 1.0) * 0.25 * np.pi
        stereo = np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1)
        self.bus.write(stereo.astype(np.float32))

    def tick(self) -> None:
        """One second of a confirmation countdown, made audible."""
        self.bus.write(spatialise(
            tone(880.0, 18, self.sr, level=DEFAULT_LEVEL * 0.5, pack=self.pack),
            0.0, self.spatial, self.sr))

    def power(self, on: bool) -> None:
        """
        Three notes rising at startup, falling at shutdown.

        Longer and louder than anything else here on purpose: you need to know
        the instrument is ready from across a stage, before you have touched
        it, and you need to know it actually shut down rather than froze.
        """
        notes = [392.0, 523.0, 659.0]
        if not on:
            notes.reverse()
        parts = [tone(f, 90, self.sr, level=DEFAULT_LEVEL * 1.3, harmonic=0.25, pack=self.pack)
                 for f in notes]
        self._play(np.concatenate(parts), 0.0)

    # -- how pan is decided --------------------------------------------- #
    @staticmethod
    def depth_pan(depth: int) -> float:
        """
        Submenu depth as stereo position: top centred, deeper further right.

        Capped at four levels because past that the steps stop being tellable
        apart, and a cue you cannot resolve is worse than no cue — it implies a
        precision that is not there.
        """
        return min(0.85, max(0, depth - 1) * 0.3)

    @staticmethod
    def value_pan(position: float | None, role: str = "") -> float:
        """
        Where a value tone sits in the field.

        A pan-like parameter pans to the value it is setting — the one case
        where the stereo position is not a metaphor but the actual thing being
        edited. Everything else reinforces pitch.
        """
        if position is None:
            return 0.0
        centred = (max(0.0, min(1.0, position)) * 2.0) - 1.0
        if role == "pan":
            return centred          # literally where you are putting the sound
        return centred * 0.6        # reinforcement, deliberately less extreme
