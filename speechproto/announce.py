"""
Layer 5b — the announcement builder.

**If you read one file in this project, read this one.**

Everything else is plumbing: an engine that makes sound, a tree that holds
values, a cursor that moves. This file is the design. It decides how much you
are told, and it is the entire difference between speech a blind musician uses
for years and speech they switch off on the first afternoon.

The governing rule
------------------

    Announce what CHANGED, not everything that is true.

That single sentence is most of the design. The obvious implementation — take
the current state and describe it — is what engineers build when told "add
speech", and it produces something that technically works and is practically
unusable. It re-reads the submenu you never left. It repeats the parameter name
you are holding in your head. It says "Filter, Cutoff, 64" when the only thing
that happened is that 63 became 64.

You cannot fix that with a faster voice. You fix it by knowing what was true a
moment ago, which is why this function takes *two* states and not one.

Verbosity
---------

Screen readers have had verbosity settings for decades — NVDA, JAWS and
VoiceOver all let you control how much you are told per action. No musical
instrument has ever applied the idea. Three levels here:

    TERSE    You know this instrument. It is a gig. Get out of the way.
    NORMAL   The default. Enough to work without counting menu items.
    VERBOSE  Learning an unfamiliar instrument, or new to screen readers.

The same navigation, at all three levels:

    move to a parameter   TERSE    Cutoff, 64
                          NORMAL   Cutoff, 64
                          VERBOSE  Filter, item 2 of 4, Cutoff, value 64,
                                   range 0 to 127

    change its value      TERSE    65
                          NORMAL   65
                          VERBOSE  65 of 127

    enter a submenu       TERSE    Filter
                          NORMAL   Filter, 4 parameters, Type
                          VERBOSE  Filter, submenu, 4 parameters,
                                   item 1 of 4, Type, Low Pass 24

    push past a limit     TERSE    127                  (plus the limit earcon)
                          NORMAL   127, maximum
                          VERBOSE  127 of 127, maximum

Notice that TERSE and NORMAL are identical for the two most frequent actions.
That is deliberate. Verbosity is not a volume knob applied evenly — it is a
judgement about *which* actions deserve more words. Moving and nudging happen
constantly and are already unambiguous; entering a submenu happens rarely and
is where you get lost. So terseness is spent where it is not needed, and detail
is spent where it is.

Two rules that come from watching real use
-------------------------------------------

**Crossing into a new container names the container and drops the parameter
name.** Going from Timbre 3's Volume to Timbre 4's Volume says `Timbre 4, 110`.
The container changed, so you need it. The parameter did not, so you do not.

**Running off the end of a list says nothing at all.** You pressed Up on the
first item; nothing changed; there is nothing to announce. The limit earcon
carries it. Speaking here would mean repeating the item you never left, at
every boundary, forever — which is the single most irritating thing a screen
reader does.

Braille is not speech
---------------------

`braille_line()` at the bottom renders the *same* `Focus` snapshot completely
differently, and that contrast is the architectural argument made visible.
Speech is transient, so it says only what changed. Braille can be re-read under
the fingers at will, so it shows the full path and context every time. Same
state layer, two consumers, two presentations — because the media have
different properties, not because anyone wrote the feature twice.
"""

from __future__ import annotations

from enum import IntEnum

from .navigation import Change, Event, Focus
from .strings import Strings


class Verbosity(IntEnum):
    TERSE = 1
    NORMAL = 2
    VERBOSE = 3

    @classmethod
    def from_name(cls, name: str) -> "Verbosity":
        return {"terse": cls.TERSE, "normal": cls.NORMAL, "verbose": cls.VERBOSE}.get(
            name.strip().lower(), cls.NORMAL
        )

    @property
    def label(self) -> str:
        return {1: "Terse", 2: "Normal", 3: "Verbose"}[int(self)]


# --------------------------------------------------------------------- #
# Small phrase builders. Kept separate so the decision tree below reads as
# rules rather than as string formatting.
# --------------------------------------------------------------------- #

#: Used when no language is supplied. Every entry point takes an explicit
#: `Strings`; this exists so a caller testing the builder in isolation does not
#: have to construct one.
_EN = Strings("English")


def _label(word: str, s: Strings) -> str:
    """Translate the container words the model produced in English."""
    return s(word) if word in ("parameters", "items") else word


def _value_phrase(f: Focus, v: Verbosity, s: Strings = _EN) -> str:
    """Just the value, as it should be spoken on its own."""
    if v is Verbosity.VERBOSE:
        if f.kind == "continuous" and f.maximum:
            # "65 of 127" gives the ear a sense of scale that a bare number
            # cannot. Only worth the extra syllables when you are learning.
            return f"{f.value} {s('of')} {f.maximum}"
        if f.kind == "stepped" and f.count:
            return f"{f.value}, {s('item')} {f.index + 1} {s('of')} {f.count}"
    return f.value


def _named_value(f: Focus, v: Verbosity, s: Strings = _EN) -> str:
    """Name plus value: what you hear when you arrive somewhere new."""
    if f.is_node:
        # Say that it *is* a submenu, and how big. Without this you cannot tell
        # "Filter" (a door) from a parameter whose value simply was not read —
        # and the only way to find out is to press Right and see what happens,
        # which is guessing. The submenu earcon carries the same fact faster;
        # this is the words for anyone who has not learned the tone yet.
        if v is Verbosity.TERSE or not f.children:
            return f.name
        label = _label(f.child_label or "items", s)
        if v is Verbosity.VERBOSE:
            return f"{f.name}, {s('submenu')}, {f.children} {label}"
        return f"{f.name}, {f.children} {label}"
    if not f.value:
        return f.name
    if v is Verbosity.VERBOSE:
        parts = [f.name]
        if f.kind == "continuous":
            parts.append(f"{s('value')} {f.value}")
            if f.minimum and f.maximum:
                parts.append(f"{s('range')} {f.minimum} {s('to')} {f.maximum}")
        else:
            parts.append(f.value)
        return ", ".join(parts)
    return f"{f.name}, {f.value}"


def _container_summary(f: Focus, v: Verbosity, s: Strings = _EN) -> str:
    """
    How a submenu introduces itself when you enter it.

    The child count matters more than it looks: knowing "4 parameters" before
    you start arrowing means you can decide whether to scan or to jump, without
    walking the list to find out how long it is.
    """
    # `count` counts the siblings, so the word must describe *them* — the
    # container's children, not the focused item's.
    label = _label(f.container_label or "items", s)
    if v is Verbosity.VERBOSE:
        return f"{f.container}, {s('submenu')}, {f.count} {label}"
    return f"{f.container}, {f.count} {label}"


def _position_phrase(f: Focus, s: Strings = _EN) -> str:
    return f"{s('item')} {f.index + 1} {s('of')} {f.count}"


# --------------------------------------------------------------------- #
def build_announcement(change: Change, verbosity: Verbosity,
                       s: Strings | None = None) -> str:
    """
    Turn (previous state, new state, what happened) into words.

    `change` is exactly that triple: `change.before`, `change.after`, and
    `change.event`. The event tag is needed because two of the cases —
    pushing a value past its limit, and running off the end of a list — leave
    the state identical, and no amount of comparing snapshots will tell you
    that the user asked for something and was refused.

    Returns "" when the correct response is silence. Silence is a real answer
    here, not a failure to produce one.
    """
    s = s or _EN
    ev, before, after = change.event, change.before, change.after

    # ---------------------------------------------------------------- #
    # Nothing happened, or nothing changed. Say nothing.
    #
    # LIST_EDGE lands here on purpose: you pressed Up on the first item, the
    # cursor did not move, and there is no news. The limit earcon reports it
    # without spending a word.
    # ---------------------------------------------------------------- #
    if after is None or ev in (Event.NONE, Event.LIST_EDGE):
        return ""

    # A free-text field: arrows cannot change it, but Enter opens an editor.
    # Say what WILL work rather than only what will not — at TERSE the refusal
    # tone alone is the answer, which is what TERSE is for.
    if ev is Event.READ_ONLY:
        return "" if verbosity is Verbosity.TERSE else s("edit_hint")

    # ---------------------------------------------------------------- #
    # A value was pushed against its limit. Unlike a list edge, something IS
    # worth knowing — the value is pinned. Say the value, and which end.
    # Never the parameter name: you are holding the knob, you know what it is.
    # ---------------------------------------------------------------- #
    if ev is Event.VALUE_LIMIT:
        end = s("maximum") if after.at_max else s("minimum")
        if verbosity is Verbosity.TERSE:
            # The earcon already says "limit". The word would be redundant.
            return after.value
        return f"{_value_phrase(after, verbosity, s)}, {end}"

    # ---------------------------------------------------------------- #
    # A value changed. This is the most frequent event by a wide margin —
    # every step of every knob — so it is the one that must be shortest.
    # The parameter name is deliberately absent: you just moved to it, or you
    # are holding the key down, and either way you know.
    # ---------------------------------------------------------------- #
    if ev is Event.VALUE:
        # Toggles are the exception. "on" alone is ambiguous when Mute and Solo
        # sit next to each other, and toggling is rare enough to afford a word.
        if after.kind == "toggle" and verbosity is not Verbosity.TERSE:
            return f"{after.name}, {after.value}"
        return _value_phrase(after, verbosity, s)

    # ---------------------------------------------------------------- #
    # Entering a submenu. Rare, and the place people get lost, so this is
    # where the extra words are spent even at NORMAL.
    # ---------------------------------------------------------------- #
    if ev is Event.DESCENDED:
        if verbosity is Verbosity.TERSE:
            return after.container
        if verbosity is Verbosity.NORMAL:
            # "Filter, 4 parameters, Type" — where you are, how big it is,
            # what you are on. Not the first item's *value*: you have not
            # asked about it yet, and Down will tell you soon enough.
            return f"{_container_summary(after, verbosity, s)}, {after.name}"
        return (
            f"{_container_summary(after, verbosity, s)}, "
            f"{_position_phrase(after, s)}, {_named_value(after, verbosity, s)}"
        )

    # ---------------------------------------------------------------- #
    # Leaving a submenu. You are landing on the submenu you were inside, which
    # you already know the name of — so this stays short at every level. The
    # falling level-change earcon does most of the work.
    # ---------------------------------------------------------------- #
    if ev is Event.ASCENDED:
        if verbosity is Verbosity.VERBOSE:
            return f"{after.container}, {_position_phrase(after, s)}, {after.name}"
        return after.name

    # ---------------------------------------------------------------- #
    # Switching mode. Always name the mode — it is the largest context there
    # is, and getting it wrong means editing the wrong thing entirely.
    # ---------------------------------------------------------------- #
    if ev is Event.MODE:
        if verbosity is Verbosity.TERSE:
            return after.mode
        if verbosity is Verbosity.NORMAL:
            return f"{after.mode}, {_named_value(after, verbosity, s)}"
        return (
            f"{after.mode}, {_position_phrase(after, s)}, "
            f"{_named_value(after, verbosity, s)}"
        )

    # ---------------------------------------------------------------- #
    # Moving between siblings — the other very frequent event.
    # ---------------------------------------------------------------- #
    if ev is Event.MOVED:
        # Arriving from nowhere (the "where am I" key). Nothing changed, so
        # the rule cannot apply; give full context instead, because the only
        # reason to press that key is that you have lost it.
        if before is None:
            # At the top level of a mode the container IS the mode, and naming
            # it twice ("Combi, Combi, item 4 of 4") sounds like a stutter
            # rather than a location.
            where = (after.mode if after.container == after.mode
                     else f"{after.mode}, {after.container}")
            return (f"{where}, {_position_phrase(after, s)}, "
                    f"{_named_value(after, Verbosity.VERBOSE, s)}")

        # The container changed under us. Name it — and drop the parameter
        # name if that did not change, because it did not.
        if before.container != after.container:
            if before.name == after.name and after.value:
                return f"{after.container}, {_value_phrase(after, verbosity, s)}"
            return f"{after.container}, {_named_value(after, verbosity, s)}"

        if verbosity is Verbosity.VERBOSE:
            return (
                f"{after.container}, {_position_phrase(after, s)}, "
                f"{_named_value(after, verbosity, s)}"
            )
        return _named_value(after, verbosity, s)

    return ""


# --------------------------------------------------------------------- #
def braille_line(focus: Focus | None) -> str:
    """
    The same state, rendered for fingers instead of ears.

    A Braille display is **re-readable**. You can move back along the line, or
    read it again in a second, which speech does not allow. So the "announce
    what changed" rule — which exists entirely because speech is transient —
    does not apply here, and this shows the full path and position every time.

    That is the point worth making to a manufacturer: this function and
    `build_announcement()` read the same `Focus` snapshot and share no logic.
    Neither is a special case of the other. Build the state layer once, and
    each output medium presents it the way that medium actually works.

        Program > Filter > Cutoff: 64  [2/4]
    """
    if focus is None:
        return ""
    path = " > ".join(focus.path)
    head = f"{path} > {focus.name}" if focus.name else path
    body = f"{head}: {focus.value}" if focus.value else head
    return f"{body}  [{focus.index + 1}/{focus.count}]"
