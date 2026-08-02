"""
Layer 6b — learning mode.

The problem with an earcon vocabulary is the first hour. A tone is faster than
a word forever after, but on the first day it is just a noise you have to look
up. Most products solve this with a manual nobody reads, or by never using
tones at all.

Fading scaffolding
------------------
Learning mode names each sound **the first few times it plays**, then stops.

    limit tone …  "limit"
    limit tone …  "limit"
    limit tone …  "limit"
    limit tone …          <- from here on, just the tone

Three repetitions, counted per sound, then silence. You are taught in exactly
the situation the sound means something, which is the only context in which it
is learnable, and the teaching removes itself before it becomes the nagging
that made you switch it off.

This is deliberately not a tutorial mode you sit through. It runs during real
work, on real edits, and it expires on its own. Nothing has to be completed and
nothing has to be dismissed.

Key hints work the same way
----------------------------
Landing on a submenu for the first few times adds "Right to enter". Landing on
a value adds "Left and Right to change". Same counter, same fade. A blind user
arriving at an unfamiliar instrument does not know which keys do what *here*,
and that is not something a tone can tell them.

The drill
---------
`drill()` plays the whole vocabulary end to end with each sound named, for
anyone who would rather learn it in one sitting than pick it up in passing.
Both routes exist because both kinds of learner exist.
"""

from __future__ import annotations

import time

from .navigation import Event

#: How many times a sound is named before the scaffolding is removed.
REPEATS = 3


class Learning:
    """
    Names sounds and keys while they are still unfamiliar, then gets out of
    the way. Consulted by the app; owns no sound of its own.
    """

    def __init__(self, app, repeats: int = REPEATS):
        self.app = app
        self.enabled = False
        self.repeats = repeats
        self._heard: dict[str, int] = {}

    def reset(self) -> None:
        """Start the counters over — for demonstrating this to someone else."""
        self._heard.clear()

    def _still_teaching(self, key: str) -> bool:
        """True while this cue has not yet been named `repeats` times."""
        if not self.enabled:
            return False
        seen = self._heard.get(key, 0)
        if seen >= self.repeats:
            return False
        self._heard[key] = seen + 1
        return True

    # ------------------------------------------------------------------ #
    def annotation(self, change) -> str:
        """
        Extra words to append to an announcement, or "" once learned.

        Returns a *suffix* rather than speaking anything itself, because a
        separate utterance would interrupt the announcement it is explaining —
        every keypress cancels speech in progress, including ours.
        """
        if not self.enabled or change.after is None:
            return ""
        ev, after = change.event, change.after
        s = self.app.strings

        # What the sound you just heard was called.
        sound = {
            Event.VALUE_LIMIT: "limit",
            Event.LIST_EDGE: "end of list",
            Event.DESCENDED: "entering",
            Event.ASCENDED: "leaving",
            Event.READ_ONLY: "not editable",
        }.get(ev)
        if ev is Event.VALUE and after.kind == "toggle":
            sound = "toggle"
        if sound and self._still_teaching(f"sound:{sound}"):
            return sound

        # What the keys do from where you are now.
        if ev in (Event.MOVED, Event.DESCENDED, Event.ASCENDED, Event.MODE):
            if after.is_node and self._still_teaching("key:node"):
                return "Right to enter"
            if after.kind == "toggle" and self._still_teaching("key:toggle"):
                return "Right to switch"
            if after.kind == "text" and self._still_teaching("key:text"):
                return s("read_only")
            if after.kind in ("continuous", "stepped") and self._still_teaching("key:value"):
                return "Left and Right to change"
        return ""

    # ------------------------------------------------------------------ #
    def drill(self) -> None:
        """
        The whole vocabulary, once, with names. For learning it deliberately
        rather than by accident.
        """
        app, ec = self.app, self.app.earcons
        was = ec.enabled
        ec.enabled = True                      # a silent drill teaches nothing

        def demo(label: str, play) -> None:
            app.say(label, force=True)
            deadline = time.monotonic() + 3.0
            time.sleep(0.1)
            while app.engine.is_speaking() and time.monotonic() < deadline:
                time.sleep(0.02)
            play()
            time.sleep(0.7)

        app.say("Sound vocabulary.", force=True)
        time.sleep(1.2)
        demo("Value, low.", lambda: ec.value(0.05, -0.5))
        demo("Value, middle.", lambda: ec.value(0.5, 0.0))
        demo("Value, high.", lambda: ec.value(0.95, 0.5))
        demo("Maximum reached.", lambda: ec.limit(True))
        demo("Minimum reached.", lambda: ec.limit(False))
        demo("This one has a submenu.", ec.submenu)
        demo("Entering a submenu.", lambda: ec.level(True, 2))
        demo("Leaving a submenu.", lambda: ec.level(False, 2))
        demo("Switched on.", lambda: ec.toggle(True))
        demo("Switched off.", lambda: ec.toggle(False))
        demo("Working. Please wait.", lambda: [ec.busy_tick("save", i) or time.sleep(0.3)
                                               for i in range(3)])
        demo("Finished.", lambda: ec.done("save", True))
        demo("Failed.", lambda: ec.done("save", False))
        demo("Output changed.", ec.route_confirm)
        demo("Powering on.", lambda: ec.power(True))

        ec.enabled = was
        app.say("End of vocabulary.", force=True)
