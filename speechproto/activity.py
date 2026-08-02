# SPDX-License-Identifier: Apache-2.0
"""
Layer 3b — long operations.

Saving a patch. Backing up sounds. Loading a large program. Running an update.
Anything the instrument does that takes longer than an instant.

Why this needs designing at all
--------------------------------
A sighted player gets a progress bar for free. A blind player gets **silence** —
and silence during a save is indistinguishable from a crash. That ambiguity is
the entire problem: not knowing how long is annoying, but not knowing whether
it is still working is the thing that makes you pull the power on a machine
mid-write.

So every long operation has to keep speaking for itself until it is done.

How much it should say
----------------------
The same verbosity principle as everywhere else, applied to a new problem.
Speech is expensive and a tone is cheap, so **the tone carries the continuity
and speech carries the milestones**:

    TERSE     tick, tick, tick … then "Saved."
    NORMAL    "Saving." … tick, tick … "Half way." … tick … "Saved."
    VERBOSE   "Saving." … "25 percent." … "50 percent." … "75 percent." …
              "Saved."

Reading a percentage every second would be unusable, and saying nothing at all
would be frightening. The ticking earcon resolves both: it proves the machine
is alive continuously, at zero verbal cost, and it drifts slowly upward in
pitch so a long wait *feels* like progress even when no real percentage is
available to report.

Each kind of operation gets its own tick voice, so you know what is taking its
time without being told twice.
"""

from __future__ import annotations

import threading
import time


class Activity:
    """
    A simulated long operation with progress feedback.

    Runs on a background thread so the interface stays live throughout — you
    can keep navigating, and any keypress still interrupts speech instantly.
    On real hardware the operation would be genuine work; here it is a timer,
    because what is being demonstrated is the *feedback*, not the file I/O.
    """

    TICK_SECONDS = 0.7

    def __init__(self, app):
        self.app = app
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, kind: str, gerund: str, past: str, seconds: float = 4.0) -> bool:
        """
        Begin an operation. `gerund` opens it ("Saving"), `past` closes it
        ("Saved"). Returns False if one is already running.
        """
        if self.running:
            return False
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, args=(kind, gerund, past, seconds), daemon=True
        )
        self._thread.start()
        return True

    def cancel(self) -> None:
        self._cancel.set()

    # ------------------------------------------------------------------ #
    def _run(self, kind: str, gerund: str, past: str, seconds: float) -> None:
        from .announce import Verbosity

        app = self.app
        verbosity = app.verbosity

        if verbosity is not Verbosity.TERSE:
            app.say(f"{gerund}.")

        # Milestones worth interrupting for. Terse gets none: the tick already
        # says "still working", and that is all a terse user asked for.
        milestones: dict[int, str] = {}
        if verbosity is Verbosity.NORMAL:
            milestones = {50: "Half way."}
        elif verbosity is Verbosity.VERBOSE:
            milestones = {25: "25 percent.", 50: "50 percent.", 75: "75 percent."}

        start = time.monotonic()
        phase = 0
        spoken: set[int] = set()

        while not self._cancel.is_set():
            elapsed = time.monotonic() - start
            if elapsed >= seconds:
                break
            percent = int(100 * elapsed / seconds)
            for mark, words in milestones.items():
                if percent >= mark and mark not in spoken:
                    spoken.add(mark)
                    app.say(words)
            app.earcons.busy_tick(kind, phase)
            phase += 1
            # Sleep in slices so a cancel is felt immediately rather than at
            # the end of a tick.
            deadline = time.monotonic() + self.TICK_SECONDS
            while time.monotonic() < deadline and not self._cancel.is_set():
                time.sleep(0.02)

        if self._cancel.is_set():
            app.earcons.done(kind, ok=False)
            app.say("Cancelled.")
            return

        app.earcons.done(kind, ok=True)
        app.say(f"{past}.")


#: The operations the demo can run, keyed by the key that starts them.
#: `kind` selects the tick voice — one per operation, so a backup and a save
#: never sound alike.
OPERATIONS = {
    "1": ("save",   "Saving program",  "Program saved",   3.5),
    "2": ("load",   "Loading program", "Program loaded",  2.5),
    "3": ("backup", "Backing up all sounds", "Backup complete", 6.0),
    "4": ("update", "Updating system software", "Update complete", 8.0),
}
