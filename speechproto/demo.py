# SPDX-License-Identifier: Apache-2.0
"""
The `--demo` flag — the whole argument, by ear, in about two minutes.

Run it, sit back, listen. It walks one realistic path through a Combi — find
a timbre, raise its volume, hit the top of the range, jump to the same
parameter in the next timbre — three times over, once at each verbosity
level, then finishes with a held-key burst.

Two things make this a demonstration rather than a recording:

* **Nothing is scripted speech.** Every announcement is produced by feeding
  synthetic keystrokes through `App.handle()` — the same code path a human's
  keys take — so what you hear is `build_announcement()` reading a live
  `Change`, exactly as it would mid-performance. If the announcement rules
  change, the demo changes with them, and it can never drift into describing
  behaviour the prototype does not have.
* **The path is identical at all three levels.** The navigator is rebuilt
  between passes so position memory cannot make pass two walk differently
  from pass one. The only variable left is verbosity, which is the point:
  what you are comparing is the announcement builder, not the walk.

The narration between segments goes through the same speech engine as the
announcements. That is deliberate too — a demo whose narrator sounds better
than its subject is making a promise the subject cannot keep.

This is the flag `audition.py` was an early slice of: that one compares
speech *engines*, this one demonstrates the announcement *design*. They are
separate because they answer different questions from different audiences —
"can it interrupt fast enough" is for an engineer, "what should it say" is
for whoever owns the product.
"""

from __future__ import annotations

import time

from . import audio_out, keys
from .announce import Verbosity
from .instrument import build_instrument
from .keys import Key
from .navigation import Navigator
from .strings import available_languages

# Breathing room after an announcement finishes, before the next keypress.
# Long enough that consecutive announcements read as separate events, short
# enough that the walk still feels like hands moving with intent.
GAP = 0.30

# Pace of a held arrow key — the same unflattering middle audition.py uses.
HELD_KEY_INTERVAL = 0.08

# The walk, as (key, callout) pairs. A callout is spoken *before* the key is
# pressed, and only on the first pass — by the second pass you know the path,
# and hearing the tour guide twice is exactly the repetition this design
# exists to remove.
#
# What the path is chosen to show, in order: a mode change, plain movement,
# the submenu earcon on a node, descending, the container-and-value
# announcement on entering a timbre, a value change, the limit behaviour at
# the top of a range, the one-keystroke sibling jump (the signature
# announcement: container changed, parameter did not), and the where-am-I
# key that always speaks.
WALK: list[tuple[Key, str]] = [
    (Key(keys.TAB, None), "Switching mode."),
    (Key(keys.DOWN, None), ""),
    (Key(keys.DOWN, None), ""),
    (Key(keys.DOWN, None),
     "That rising figure means there is more inside this one."),
    (Key(keys.ENTER, None), "Going in."),
    (Key(keys.DOWN, None), ""),
    (Key(keys.DOWN, None), ""),
    (Key(keys.ENTER, None), "Into this timbre."),
    (Key(keys.DOWN, None), ""),
    (Key(keys.RIGHT, None), "Raising the value."),
    (Key(keys.RIGHT, None), ""),
    (Key(keys.END, None), "Straight to the top."),
    (Key(keys.RIGHT, None),
     "And past it. The value is pinned, and that is said once, not repeated."),
    (Key(keys.PAGE_DOWN, None),
     "Now one keystroke to the same parameter in the next timbre. "
     "The timbre changed, the parameter did not — listen to what is left out."),
    (Key(None, "w"), "The where am I key, which always answers in full."),
]

PASSES: list[tuple[Verbosity, str]] = [
    (Verbosity.NORMAL,
     "First, Normal. The everyday setting."),
    (Verbosity.TERSE,
     "The same walk, Terse. For the player who knows the instrument: "
     "what changed, and almost nothing else."),
    (Verbosity.VERBOSE,
     "The same walk once more, Verbose. For the first week with the "
     "instrument: positions, ranges, and what is around you."),
]

INTRO = (
    "Speech interaction prototype. Two minutes. "
    "You will hear one walk through a Combi, three times, at three "
    "verbosity levels. Nothing in this demo is scripted speech: every "
    "announcement is generated live, from one rule. Announce what changed, "
    "not everything that is true. Control C stops the demo."
)

BURST = (
    "Last, speed. Holding an arrow key. Each keypress cancels the speech "
    "before it, so you hear clipped words tracking the hand — never a "
    "backlog draining after the hand has stopped."
)

CLOSE = (
    "All three levels came from a single announcement builder, reading what "
    "changed. That is the shape of the argument: the expensive part is "
    "exposing the instrument's state — the speech on top of it is nearly "
    "free. End of demo."
)


def _wait_quiet(app, timeout: float = 8.0) -> None:
    """Block until speech stops, or give up on it — never hang the demo."""
    deadline = time.monotonic() + timeout
    # Let the engine actually start before believing it is idle.
    time.sleep(0.12)
    while app.engine.is_speaking() and time.monotonic() < deadline:
        time.sleep(0.02)


def _narrate(app, text: str) -> None:
    print(f"    {text}", flush=True)
    app.say(text, force=True)
    _wait_quiet(app)
    time.sleep(0.4)


def _fresh_navigator(app) -> None:
    """
    Rebuild the tree, exactly as App's constructor does.

    Between passes the navigator must forget everything — remembered mode
    positions, submenu memory, the sibling hint — or pass two would descend
    straight to where pass one left off and the three walks would no longer
    be the same walk.
    """
    app.nav = Navigator(build_instrument(
        app.device_names,
        app.engine.available_voices(),
        audio_out.channel_options(app.speech_device, True),
        available_languages(app.show_unreviewed_languages),
    ))
    app._sync_settings()


def _walk(app, callouts: bool) -> None:
    for key, callout in WALK:
        if callouts and callout:
            _narrate(app, callout)
        app.handle(key)
        _wait_quiet(app)
        time.sleep(GAP)


def run_demo(app) -> None:
    """
    Play the whole demonstration. Ctrl+C stops it; the caller owns cleanup.

    State the demo touches — verbosity and the navigator — is restored on the
    way out, so `--demo` can be pointed at a saved setup without rearranging
    it. The one exception is deliberate: whatever the End key pushed to
    maximum lives in a navigator that is thrown away afterwards.
    """
    saved_verbosity = app.verbosity

    print("\n=== Demo — listen, no keys needed ===", flush=True)
    try:
        _narrate(app, INTRO)

        for i, (verbosity, heading) in enumerate(PASSES):
            _fresh_navigator(app)
            app.verbosity = verbosity
            print(f"\n--- {verbosity.label} ---", flush=True)
            _narrate(app, heading)
            # Callouts on the first pass only: after that you know the path,
            # and the comparison is cleaner without a narrator over it.
            _walk(app, callouts=(i == 0))
            time.sleep(0.6)

        # The burst runs at Normal, on a fresh tree, standing on a volume
        # (the walk's own final position is on the same parameter, but a
        # clean descent keeps the burst independent of the walk's shape).
        app.verbosity = Verbosity.NORMAL
        _fresh_navigator(app)
        print("\n--- Held key ---", flush=True)
        _narrate(app, BURST)
        for key, _ in WALK[:9]:                    # back down to the volume
            app.handle(key)
            time.sleep(0.05)
        app.engine.stop()
        time.sleep(0.3)
        for _ in range(12):
            app.handle(Key(keys.RIGHT, None))
            time.sleep(HELD_KEY_INTERVAL)
        _wait_quiet(app)
        time.sleep(0.6)

        _narrate(app, CLOSE)
    finally:
        app.verbosity = saved_verbosity
        _fresh_navigator(app)
    print("\n=== End of demo ===\n", flush=True)
