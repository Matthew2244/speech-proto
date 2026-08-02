# SPDX-License-Identifier: Apache-2.0
"""
Raw keyboard input.

The terminal is put into cbreak mode so keys arrive the instant they are
pressed, with no line buffering and no echo. Two consequences matter:

* **Auto-repeat comes free.** Holding Down arrow produces a stream of events at
  the OS repeat rate, which is exactly the stress test this prototype needs.
* **Nothing is echoed.** The screen stays quiet; speech is the interface.

On the silence key
------------------
The spec asked for Control. A bare Control keypress **sends no bytes to a
terminal at all** — modifier state is simply not visible to a program reading
stdin, so it cannot be detected without macOS Input Monitoring permission and a
native API. Ctrl+Space is used instead: it sends NUL (0x00), it is detectable,
and it keeps the muscle memory close to the Control key that NVDA and JAWS use
for silence.
"""

from __future__ import annotations

import os
import select
import sys
import termios
import tty
from dataclasses import dataclass


# Symbolic key names, so the interaction layer never deals in escape sequences.
UP = "UP"
DOWN = "DOWN"
LEFT = "LEFT"
RIGHT = "RIGHT"
ENTER = "ENTER"
ESCAPE = "ESCAPE"
TAB = "TAB"
HOME = "HOME"
END = "END"
PAGE_UP = "PAGE_UP"
PAGE_DOWN = "PAGE_DOWN"
SILENCE = "SILENCE"      # Ctrl+Space (NUL)
INTERRUPT = "INTERRUPT"  # Ctrl+C

# Tilde-terminated sequences: CSI <n> ~ . Page Up and Page Down drive the
# jump between sibling submenus, which is the fastest way to compare one
# parameter across sixteen timbres.
_CSI_TILDE = {"5": PAGE_UP, "6": PAGE_DOWN, "1": HOME, "4": END, "7": HOME, "8": END}

_CSI = {
    "A": UP,
    "B": DOWN,
    "C": RIGHT,
    "D": LEFT,
    "H": HOME,
    "F": END,
}


@dataclass(frozen=True)
class Key:
    """One keypress. `name` is symbolic for special keys, else None."""

    name: str | None
    char: str | None
    shift: bool = False

    def __str__(self) -> str:
        return self.name or (self.char or "?")


class KeyReader:
    """Context manager putting stdin in cbreak mode and yielding Key objects."""

    def __init__(self, stream=None):
        self._fd = (stream or sys.stdin).fileno()
        self._saved = None

    def __enter__(self) -> "KeyReader":
        self._saved = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc) -> None:
        if self._saved is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

    # ------------------------------------------------------------------ #
    def _read_byte(self, timeout: float | None = None) -> int | None:
        if timeout is not None:
            r, _, _ = select.select([self._fd], [], [], timeout)
            if not r:
                return None
        data = os.read(self._fd, 1)
        return data[0] if data else None

    def read(self) -> Key | None:
        """Block for one keypress and return it."""
        b = self._read_byte()
        if b is None:
            return None

        if b == 0x00:
            return Key(SILENCE, None)
        if b == 0x03:
            return Key(INTERRUPT, None)
        if b in (0x0D, 0x0A):
            return Key(ENTER, None)
        if b == 0x09:
            return Key(TAB, None)

        if b == 0x1B:
            # Escape, or the start of an escape sequence. Distinguishing them
            # is a timing judgement: a real arrow key delivers its remaining
            # bytes immediately, a lone Escape does not. 40 ms is comfortably
            # longer than the gap within a sequence and short enough that
            # Escape still feels instant.
            nxt = self._read_byte(timeout=0.04)
            if nxt is None:
                return Key(ESCAPE, None)
            if nxt == 0x5B:  # '['
                params = ""
                while True:
                    c = self._read_byte(timeout=0.04)
                    if c is None:
                        return Key(ESCAPE, None)
                    ch = chr(c)
                    if ch.isalpha() or ch == "~":
                        # xterm encodes Shift+arrow as CSI 1;2A
                        shift = ";2" in params
                        if ch == "~":
                            name = _CSI_TILDE.get(params.split(";")[0])
                            return Key(name, None, shift=shift) if name else Key(None, None)
                        name = _CSI.get(ch)
                        if name:
                            return Key(name, None, shift=shift)
                        return Key(None, None)
                    params += ch
            return Key(ESCAPE, None)

        if 0x20 <= b < 0x7F:
            return Key(None, chr(b))
        if b == 0x7F:
            return Key(None, "\x7f")
        return Key(None, None)
