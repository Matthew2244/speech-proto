# SPDX-License-Identifier: Apache-2.0
"""
Layer 4a — parameter types.

This is the state layer, and it is the load-bearing part of the whole argument.

**Nothing in this file knows that speech exists.** No engine, no verbosity, no
wording. A parameter exposes structured facts about itself — its value, its
range, where it sits in that range, what it looks like on screen, whether it is
at a limit — and that is all. The announcement builder in step 4 reads those
facts and decides what to say.

That separation is the point being made to a manufacturer. Ableton had already
built structured accessibility metadata for their web-based screen reader;
Charles Vestal put a screen reader on the Move itself largely by routing that
existing data to a local speech engine. The expensive half was already done.

So: build this layer once, and speech is one consumer of it. A Braille display
is another. A remote editor is another. `to_dict()` at the bottom of each class
exists to make that concrete — the whole instrument state serialises to plain
JSON with no speech vocabulary anywhere in it.

Four parameter kinds, because four kinds announce differently:

    Continuous  a number in a range      Cutoff, 64
    Stepped     one of a list of names   Type, Low Pass
    Toggle      on or off                Mute, on
    Text        a free string            Name, Full Grand
"""

from __future__ import annotations

from dataclasses import dataclass, field


class Param:
    """Base class. A leaf of the tree — something with a value you can change."""

    #: Short tag the announcement builder branches on.
    kind: str = "param"

    def __init__(self, name: str, role: str = ""):
        self.name = name
        #: Optional semantic tag saying what this value *means*, as opposed to
        #: what type it is. `role="pan"` tells the earcon layer that this
        #: parameter's value is a stereo position, so its tone should come from
        #: where it is being set. Matching on the parameter's *name* would work
        #: today and break the moment someone renames it or translates it, so
        #: the meaning is declared in the state layer instead of guessed at
        #: downstream. This is the small version of the whole argument: the
        #: model publishes facts, consumers read them.
        self.role = role

    # -- what the value looks like ------------------------------------- #
    @property
    def display_value(self) -> str:
        """
        The value as it would be printed on the instrument's screen.

        This belongs to the parameter, not to speech: pan reads "C064" whether
        you see it or hear it. What speech adds on top — the range, the item
        number, the word "maximum" — is the announcement builder's business.
        """
        raise NotImplementedError

    # -- where the value sits, for earcons ------------------------------ #
    @property
    def position(self) -> float | None:
        """
        Normalised position in range, 0.0 to 1.0, or None if the idea does not
        apply. Step 5 maps this to earcon pitch: low value, low tone.
        """
        return None

    @property
    def at_minimum(self) -> bool:
        return False

    @property
    def at_maximum(self) -> bool:
        return False

    # -- changing it ---------------------------------------------------- #
    def nudge(self, steps: int) -> bool:
        """Move by `steps` increments. Returns True if the value changed."""
        return False

    def to_minimum(self) -> bool:
        return False

    def to_maximum(self) -> bool:
        return False

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "name": self.name, "value": self.display_value}
        if self.role:
            d["role"] = self.role
        return d


# --------------------------------------------------------------------- #
class Continuous(Param):
    """
    A number in a range: cutoff, level, tuning, transpose.

    `formatter` exists because the number a synth stores and the number it
    shows are often different — pan is stored 0..127 and shown "L64" to "R63".
    The stored value drives the earcon; the formatted value drives the words.
    """

    kind = "continuous"

    def __init__(
        self,
        name: str,
        value: int,
        minimum: int,
        maximum: int,
        step: int = 1,
        unit: str = "",
        formatter=None,
        role: str = "",
    ):
        super().__init__(name, role)
        self.value = value
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.unit = unit
        self._formatter = formatter

    def format(self, value: int) -> str:
        """
        Render an arbitrary value the way this parameter renders its own.

        Needed so a verbose announcement can say "range L64 to R63" rather than
        "range 0 to 127" — the raw numbers are an implementation detail the
        user never sees. Kept as a method taking a value, rather than something
        that temporarily assigns to `self.value` and puts it back, because the
        latter mutates shared state to answer a read-only question.
        """
        # Formatter and unit compose rather than compete: pan formats to "L12"
        # and carries no unit, while transpose formats to "+2" and still needs
        # "semitones" after it. An earlier version let the formatter swallow
        # the unit, which silently turned "0 semitones" into a bare "0".
        base = self._formatter(value) if self._formatter else str(value)
        return f"{base} {self.unit}" if self.unit else base

    @property
    def display_value(self) -> str:
        return self.format(self.value)

    @property
    def position(self) -> float | None:
        span = self.maximum - self.minimum
        if span <= 0:
            return None
        return (self.value - self.minimum) / span

    @property
    def at_minimum(self) -> bool:
        return self.value <= self.minimum

    @property
    def at_maximum(self) -> bool:
        return self.value >= self.maximum

    def nudge(self, steps: int) -> bool:
        old = self.value
        self.value = max(self.minimum, min(self.maximum, self.value + steps * self.step))
        return self.value != old

    def to_minimum(self) -> bool:
        old, self.value = self.value, self.minimum
        return self.value != old

    def to_maximum(self) -> bool:
        old, self.value = self.value, self.maximum
        return self.value != old

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(raw=self.value, minimum=self.minimum, maximum=self.maximum)
        return d


# --------------------------------------------------------------------- #
class Stepped(Param):
    """One of a fixed list: filter type, waveform, velocity curve, effect type."""

    kind = "stepped"

    def __init__(self, name: str, options: list[str], index: int = 0, role: str = ""):
        super().__init__(name, role)
        self.options = list(options)
        self.index = max(0, min(len(self.options) - 1, index))

    @property
    def display_value(self) -> str:
        return self.options[self.index] if self.options else ""

    @property
    def position(self) -> float | None:
        if len(self.options) < 2:
            return None
        return self.index / (len(self.options) - 1)

    @property
    def at_minimum(self) -> bool:
        return self.index <= 0

    @property
    def at_maximum(self) -> bool:
        return self.index >= len(self.options) - 1

    def nudge(self, steps: int) -> bool:
        old = self.index
        self.index = max(0, min(len(self.options) - 1, self.index + steps))
        return self.index != old

    def to_minimum(self) -> bool:
        old, self.index = self.index, 0
        return self.index != old

    def to_maximum(self) -> bool:
        old, self.index = self.index, len(self.options) - 1
        return self.index != old

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(index=self.index, options=list(self.options))
        return d


# --------------------------------------------------------------------- #
class Toggle(Param):
    """On or off: mute, solo, earcons enabled."""

    kind = "toggle"

    def __init__(self, name: str, value: bool = False, on: str = "on", off: str = "off", role: str = ""):
        super().__init__(name, role)
        self.value = value
        self.on_word = on
        self.off_word = off

    @property
    def display_value(self) -> str:
        return self.on_word if self.value else self.off_word

    def nudge(self, steps: int) -> bool:
        if steps == 0:
            return False
        self.value = not self.value
        return True

    def to_minimum(self) -> bool:
        old, self.value = self.value, False
        return self.value != old

    def to_maximum(self) -> bool:
        old, self.value = self.value, True
        return self.value != old

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(raw=self.value)
        return d


# --------------------------------------------------------------------- #
class Text(Param):
    """
    A free string: program name, set list comment.

    Not editable by arrow keys — there is no "next" string. A real instrument
    would open a text entry screen here; this prototype only reads them.
    """

    kind = "text"

    def __init__(self, name: str, value: str = "", role: str = ""):
        super().__init__(name, role)
        self.value = value

    @property
    def display_value(self) -> str:
        return self.value

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(editable=False)
        return d


# --------------------------------------------------------------------- #
@dataclass
class Node:
    """
    A branch of the tree: a mode, a section, a timbre, a submenu.

    Deliberately dumb. It knows its name and its children and nothing else —
    no focus, no cursor, no history. Focus tracking is the interaction layer's
    job (step 3) and lives entirely outside this file, because focus is a
    property of *a user navigating*, not of the instrument's state.
    """

    name: str
    children: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.children)

    def __iter__(self):
        return iter(self.children)

    def __getitem__(self, i):
        return self.children[i]

    def find(self, name: str):
        """First child with this name, or None. Handy when editing the tree."""
        for c in self.children:
            if getattr(c, "name", None) == name:
                return c
        return None

    def to_dict(self) -> dict:
        return {
            "kind": "node",
            "name": self.name,
            "children": [c.to_dict() for c in self.children],
        }


# --------------------------------------------------------------------- #
# Display helpers. These live here rather than in the data file because they
# are how a synth *writes* a value, and more than one parameter uses each.
# --------------------------------------------------------------------- #

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(midi_note: int) -> str:
    """
    MIDI note number to name, with note 0 as C-1 — so middle C reads "C4".

    Octave numbering is genuinely inconsistent across manufacturers: Yamaha
    calls middle C "C3", Korg and Roland call it "C4". Korg's key-range display
    runs C-1 to G9, which is the C-1-is-zero convention, so that is what this
    follows. Worth stating explicitly because getting it wrong shifts every
    split point by an octave while looking entirely plausible.
    """
    return f"{_NOTE_NAMES[midi_note % 12]}{midi_note // 12 - 1}"


def pan_display(value: int) -> str:
    """
    Korg-style pan: 0 is hard left, 64 is centre, 127 is hard right.

    Written L64 / C064 / R63 rather than as a bare number, which is what makes
    it worth having a formatter at all — "Pan, 64" is ambiguous to the ear in a
    way "Pan, C064" is not.
    """
    if value == 64:
        return "C064"
    if value < 64:
        return f"L{64 - value}"
    return f"R{value - 64}"


def signed(value: int) -> str:
    """Transpose and EG intensity read better with an explicit plus sign."""
    return f"+{value}" if value > 0 else str(value)


def cents(value: int) -> str:
    return f"{signed(value)} cents"
