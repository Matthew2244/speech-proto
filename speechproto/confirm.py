"""
Layer 5c — provisional changes that undo themselves.

For the one setting that can make the instrument unusable: **where the sound
goes.**

The problem
-----------
Every other setting in this tree is safe to apply the instant you arrow onto
it, because if you dislike it you arrow back. Output routing is not like that.
Send speech to an output that is muted, unplugged, or feeding the house PA, and
you have just lost the interface you would need in order to undo it. A blind
player is now navigating a silent instrument by memory, on stage.

An "are you sure?" prompt does not fix this. It asks the question *before* the
consequence is knowable — you cannot tell whether an output works until you
have heard something come out of it.

The pattern that does fix it
-----------------------------
The same one every operating system uses for changing screen resolution, and
for exactly the same reason: **apply provisionally, and revert unless
confirmed.**

    1. Arrow to a new output. Nothing happens yet. You hear
       "StudioLive 64S. Press Enter to apply."
    2. Press Enter. The route changes, and a confirmation plays
       **on the new output**: a sweep tone, then "Speech now on
       StudioLive 64S. Press Enter to keep."
    3. Press Enter again to keep it.
       Press Escape, or do nothing for ten seconds, and it goes back.

The elegance is that **the proof is the sound itself.** If you hear the
confirmation, the output works — no separate test needed. If you hear nothing,
you do nothing, and the instrument returns to a state you know works. Silence,
which is the failure mode that strands you, is exactly what triggers recovery.

A soft tick marks each remaining second on the new output. It is the countdown
made audible, and it costs no words.

The revert announcement goes to the **old** output, because by then that is the
one you can hear.
"""

from __future__ import annotations

import threading
import time


class PendingChange:
    """
    A change that has been applied and will undo itself unless confirmed.

    Runs its countdown on a background thread so the interface stays live —
    you can keep navigating while it ticks, and any keypress still interrupts
    speech normally.
    """

    def __init__(self, app, label: str, apply_fn, revert_fn,
                 seconds: float = 10.0, back_label: str = ""):
        self.app = app
        self.label = label
        #: What to say once it has gone back. Passed in rather than read off
        #: the app, because a reverted *earcon* route must not announce the
        #: speech device — naming the wrong one is worse than naming none.
        self.back_label = back_label
        self._apply = apply_fn
        self._revert = revert_fn
        self.seconds = seconds
        self._resolved = threading.Event()
        self._thread: threading.Thread | None = None
        self.active = False

    # ------------------------------------------------------------------ #
    def arm(self) -> None:
        """Apply the change and start the countdown."""
        self._apply()
        self.active = True

        # Both of these land on the NEW destination, which is the point: they
        # are the test, not a description of one.
        self.app.earcons.route_confirm()
        self.app.say(f"{self.label}. Press Enter to keep.", force=True)

        self._thread = threading.Thread(target=self._countdown, daemon=True)
        self._thread.start()

    def _countdown(self) -> None:
        deadline = time.monotonic() + self.seconds
        next_tick = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if self._resolved.wait(timeout=0.05):
                return
            if time.monotonic() >= next_tick:
                # One soft tick per remaining second, on the new output. A
                # silent countdown would be no countdown at all to someone who
                # cannot see it.
                self.app.earcons.tick()
                next_tick += 1.0
        if not self._resolved.is_set():
            self.revert(timed_out=True)

    # ------------------------------------------------------------------ #
    def confirm(self) -> None:
        if not self.active:
            return
        self._resolved.set()
        self.active = False
        self.app.earcons.done("save", ok=True)
        self.app.say("Kept.", force=True)

    def revert(self, timed_out: bool = False) -> None:
        if not self.active:
            return
        self._resolved.set()
        self.active = False
        self._revert()
        # This one goes to the OLD output — by now, the one you can hear.
        self.app.earcons.route_confirm()
        lead = "Timed out. " if timed_out else ""
        self.app.say(f"{lead}{self.back_label}.", force=True)
