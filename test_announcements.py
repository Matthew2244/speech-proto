#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
The specification, executable.

Every case below asserts a string that appears verbatim in the verbosity table
in `DESIGN.md §4.1`, or a rule stated in §4.2 to §4.5. If you change an
announcement rule and the document no longer matches, this fails.

That coupling is the point. A specification that drifts from its reference
implementation is worse than no specification, because people implement from it
and get something that does not match what they heard in the demo. Change both
deliberately, or neither.

    ./.venv/bin/python test_announcements.py

No test framework, on purpose — one fewer dependency between a contributor and
running this.
"""

from __future__ import annotations

import sys

from speechproto.announce import Verbosity, braille_line, build_announcement
from speechproto.instrument import build_instrument
from speechproto.navigation import Event, Navigator
from speechproto.strings import Strings

T, N, V = Verbosity.TERSE, Verbosity.NORMAL, Verbosity.VERBOSE

_failures: list[str] = []
_passes = 0


def check(label: str, got, want) -> None:
    global _passes
    if got == want:
        _passes += 1
    else:
        _failures.append(f"{label}\n      got:  {got!r}\n      want: {want!r}")


def nav_at_filter() -> Navigator:
    """A navigator sitting on Program > Filter, the worked example in §4.1."""
    nav = Navigator(build_instrument(["Test Device"]))
    for _ in range(4):
        nav.move(1)                      # Name, Bank, Category, Oscillator, Filter
    return nav


# --------------------------------------------------------------------- #
# DESIGN.md §4.1 — the verbosity table
# --------------------------------------------------------------------- #
def test_verbosity_table() -> None:
    for verbosity, want in (
        (T, "Filter"),
        (N, "Filter, 4 parameters, Type"),
        (V, "Filter, submenu, 4 parameters, item 1 of 4, Type, Low Pass 24"),
    ):
        nav = nav_at_filter()
        check(f"enter a submenu [{verbosity.label}]",
              build_announcement(nav.descend(), verbosity), want)

    for verbosity, want in (
        (T, "Cutoff, 64"),
        (N, "Cutoff, 64"),
        (V, "Filter, item 2 of 4, Cutoff, value 64, range 0 to 127"),
    ):
        nav = nav_at_filter()
        nav.descend()
        check(f"move to a parameter [{verbosity.label}]",
              build_announcement(nav.move(1), verbosity), want)

    for verbosity, want in ((T, "65"), (N, "65"), (V, "65 of 127")):
        nav = nav_at_filter()
        nav.descend(); nav.move(1)
        check(f"change a value [{verbosity.label}]",
              build_announcement(nav.adjust(1), verbosity), want)

    for verbosity, want in ((T, "127"), (N, "127, maximum"), (V, "127 of 127, maximum")):
        nav = nav_at_filter()
        nav.descend(); nav.move(1); nav.value_to_maximum()
        check(f"push past a limit [{verbosity.label}]",
              build_announcement(nav.adjust(1), verbosity), want)

    for verbosity, want in (
        (T, "Filter"), (N, "Filter, 4 parameters"),
        (V, "Program, item 5 of 7, Filter, submenu, 4 parameters"),
    ):
        nav = Navigator(build_instrument(["Test Device"]))
        for _ in range(3):
            nav.move(1)
        check(f"land on a submenu [{verbosity.label}]",
              build_announcement(nav.move(1), verbosity), want)

    for verbosity, want in ((T, "Filter"), (N, "Filter"), (V, "Program, item 5 of 7, Filter")):
        nav = nav_at_filter()
        nav.descend()
        check(f"leave a submenu [{verbosity.label}]",
              build_announcement(nav.ascend(), verbosity), want)

    # Toggles: Terse says the state alone, Normal and Verbose name the control,
    # because "on" is ambiguous with Mute and Solo side by side.
    for verbosity, want in ((T, "on"), (N, "Mute, on"), (V, "Mute, on")):
        nav = Navigator(build_instrument(["Test Device"]))
        nav.cycle_mode(1)                       # Combi
        for _ in range(3):
            nav.move(1)                          # Timbres
        nav.descend(); nav.descend()             # Timbre 1
        for _ in range(8):
            nav.move(1)                          # Mute
        check(f"toggle [{verbosity.label}]",
              build_announcement(nav.adjust(1), verbosity), want)


# --------------------------------------------------------------------- #
# §4.2 — crossing into a new container
# --------------------------------------------------------------------- #
def test_container_crossing() -> None:
    nav = Navigator(build_instrument(["Test Device"]))
    nav.cycle_mode(1)
    for _ in range(3):
        nav.move(1)
    nav.descend(); nav.descend()                 # Timbre 1
    nav.move(1)                                  # Volume
    change = nav.sibling_container(1)            # -> Timbre 2's Volume
    check("§4.2 container changed, parameter did not",
          build_announcement(change, N), "Timbre 2, 72")


# --------------------------------------------------------------------- #
# §4.4 — the two kinds of "cannot go further"
# --------------------------------------------------------------------- #
def test_limits_differ() -> None:
    nav = Navigator(build_instrument(["Test Device"]))
    edge = nav.move(-1)                          # already on the first item
    check("§4.4 list edge is a distinct event", edge.event, Event.LIST_EDGE)
    for verbosity in (T, N, V):
        check(f"§4.4 list edge is silent [{verbosity.label}]",
              build_announcement(edge, verbosity), "")

    nav = nav_at_filter()
    nav.descend(); nav.move(1); nav.value_to_maximum()
    limit = nav.adjust(1)
    check("§4.4 value limit is a distinct event", limit.event, Event.VALUE_LIMIT)
    check("§4.4 value limit speaks", build_announcement(limit, N), "127, maximum")

    # §4.4 lists do not wrap
    nav = Navigator(build_instrument(["Test Device"]))
    before = nav.snapshot().index
    nav.move(-1)
    check("§4.4 lists do not wrap", nav.snapshot().index, before)


# --------------------------------------------------------------------- #
# §4.5 / §10.1 — read-only, and where-am-I
# --------------------------------------------------------------------- #
def test_read_only_and_where_am_i() -> None:
    nav = Navigator(build_instrument(["Test Device"]))
    ro = nav.adjust(1)                           # "Name" is a text field
    check("§14.8 a text field is its own event", ro.event, Event.READ_ONLY)
    check("text field, Terse is the tone alone", build_announcement(ro, T), "")
    check("text field, Normal points at the key that works",
          build_announcement(ro, N), "Press Enter to edit")

    nav = Navigator(build_instrument(["Test Device"]))
    check("§4.5 where-am-I gives full context",
          build_announcement(nav.here(), N),
          "Program, item 1 of 7, Name, Full Grand")

    # §14.6 — at the top of a mode the container IS the mode; do not say it twice
    nav = Navigator(build_instrument(["Test Device"]))
    nav.cycle_mode(1)
    text = build_announcement(nav.here(), N)
    check("§14.6 mode name not doubled", text.startswith("Combi, Combi"), False)


# --------------------------------------------------------------------- #
# §10.2 — language changes the framing words, not the parameter names
# --------------------------------------------------------------------- #
def test_localisation() -> None:
    nav = nav_at_filter()
    nav.descend(); nav.move(1); nav.value_to_maximum()
    limit = nav.adjust(1)
    check("§10.2 Spanish framing word",
          build_announcement(limit, N, Strings("Español")), "127, máximo")

    nav = nav_at_filter()
    got = build_announcement(nav.descend(), N, Strings("Deutsch"))
    check("§10.2 German framing word", got, "Filter, 4 Parameter, Type")
    check("§10.2 parameter names are NOT translated", "Filter" in got and "Type" in got, True)


# --------------------------------------------------------------------- #
# §2 / §13 — the state layer has no speech vocabulary, and Braille differs
# --------------------------------------------------------------------- #
def test_state_layer_is_neutral() -> None:
    import json

    modes = build_instrument(["Test Device"])
    # The Accessibility submenu legitimately contains words like "Verbosity"
    # and "espeak-ng" — they are parameter names and values, which is precisely
    # what §10.1 asks for. What must never appear anywhere is *announcement
    # phrasing*: the wording the builder produces.
    dumped = json.dumps([m.to_dict() for m in modes]).lower()
    for phrase in ("press enter to apply", "read only", "item 1 of",
                   ", maximum", "submenu,", "announce"):
        check(f"§2 no announcement phrasing in the model: {phrase!r}",
              phrase in dumped, False)

    program = json.dumps(modes[0].to_dict()).lower()
    for word in ("verbosity", "espeak", "speech", "earcon"):
        check(f"§2 the instrument proper knows nothing of '{word}'",
              word in program, False)
    check("§2 state layer round-trips",
          json.loads(dumped if False else json.dumps([m.to_dict() for m in modes]))
          == [m.to_dict() for m in modes], True)

    # §13 — Braille shows full context every time; speech shows the diff.
    nav = nav_at_filter()
    nav.descend()
    change = nav.move(1)
    check("§13 Braille renders full context",
          braille_line(change.after), "Program > Filter > Cutoff: 64  [2/4]")
    check("§13 speech renders only the diff",
          build_announcement(change, N), "Cutoff, 64")


# --------------------------------------------------------------------- #
def main() -> int:
    for fn in (test_verbosity_table, test_container_crossing, test_limits_differ,
               test_read_only_and_where_am_i, test_localisation,
               test_state_layer_is_neutral):
        fn()

    print(f"\n  {_passes} passed, {len(_failures)} failed\n")
    for f in _failures:
        print(f"  FAIL  {f}\n")
    if not _failures:
        print("  The implementation matches DESIGN.md.\n")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
