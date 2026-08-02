"""
Layer 8 — text entry without a screen.

Naming a program is the one place where the rules in `DESIGN.md §4` stop
helping, because there is no "next value" to arrow to. It is its own
interaction with its own failure modes, and it is where a lot of otherwise
decent accessible products fall over.

What sighted text entry gives you for free
-------------------------------------------
A sighted user sees the whole string, the cursor position within it, and every
change as it happens. Take the screen away and all three vanish at once. Each
has to be handed back deliberately:

**Echo every character as it is typed.** Without this you are typing blind into
a void and will only discover a mistake when you finish. The echo must be the
character *actually inserted*, not the key pressed.

**Say the character you land on when moving.** Arrow keys announce what is now
under the cursor, and say `end` when there is nothing there. Position is
otherwise unknowable.

**Backspace announces what it deleted, not what is now under the cursor.**
This is the one everybody gets backwards. You pressed a key to remove a
character; the useful information is *which character went*. Reporting the new
neighbour tells you nothing about whether you deleted the right thing.

**Speak punctuation and whitespace by name.** A space is silence, and silence
is indistinguishable from "nothing happened". `space`, `dash`, `period`.

**Escape must restore the original exactly.** Editing a patch name you have
used for years, then losing it to a mistyped character with no way back, is the
kind of thing that stops people editing anything ever again.

On reading the whole thing back
--------------------------------
Committing reads the finished string. It is the only moment where reading
everything is right, because it is the moment you are checking your work —
which is the exception that proves §1's rule rather than breaking it.
"""

from __future__ import annotations

from . import keys

#: Characters whose names must be spoken, because hearing them is otherwise
#: impossible. Everything else is announced as itself.
SPOKEN = {
    " ": "space",
    "-": "dash",
    "_": "underscore",
    ".": "period",
    ",": "comma",
    "/": "slash",
    "'": "apostrophe",
    "(": "open bracket",
    ")": "close bracket",
    "+": "plus",
    "&": "and",
    "#": "hash",
    "!": "exclamation",
    "?": "question mark",
    ":": "colon",
}


def speak_char(ch: str) -> str:
    """How a single character should be said aloud."""
    if ch in SPOKEN:
        return SPOKEN[ch]
    if ch.isupper():
        # "cap B" rather than "B", which is otherwise indistinguishable from
        # lower case in most voices.
        return f"cap {ch.lower()}"
    return ch


class TextEditor:
    """
    A modal, character-by-character editor for one string.

    Modal on purpose. While editing, letter keys must insert letters — they
    cannot also be shortcuts, and pretending otherwise produces an editor that
    randomly changes settings while you type a patch name.
    """

    def __init__(self, app, param):
        self.app = app
        self.param = param
        self.original = param.value
        self.buffer = list(param.value)
        self.cursor = len(self.buffer)

    # ------------------------------------------------------------------ #
    def _at_cursor(self) -> str:
        if self.cursor >= len(self.buffer):
            return "end"
        return speak_char(self.buffer[self.cursor])

    def run(self, reader) -> bool:
        """
        Edit until committed or cancelled. Returns True if the value changed.

        Takes the reader rather than owning one, so it shares the same terminal
        state as everything else and cannot leave it in a strange mode.
        """
        app = self.app
        app.earcons.level(True, depth=2)
        app.say(f"Editing {self.param.name}. {self.param.value or 'empty'}. "
                f"Type to change it. Enter to accept, escape to cancel.", force=True)

        while True:
            k = reader.read()
            if k is None:
                continue

            if k.name == keys.SILENCE:
                app.engine.stop()

            elif k.name in (keys.ESCAPE, keys.INTERRUPT):
                # Put it back exactly. Losing a name you have used for years to
                # a mistyped character is how people learn never to edit.
                self.param.value = self.original
                app.earcons.level(False, depth=2)
                app.say(f"Cancelled. {self.original or 'empty'}.", force=True)
                return False

            elif k.name == keys.ENTER:
                new = "".join(self.buffer)
                self.param.value = new
                app.earcons.done("save", ok=True)
                # Reading the whole string back is right here, and only here:
                # this is the moment you are checking your work.
                app.say(f"{self.param.name}, {new or 'empty'}.", force=True)
                return new != self.original

            elif k.name == keys.LEFT:
                if self.cursor > 0:
                    self.cursor -= 1
                    app.say(self._at_cursor(), force=True)
                else:
                    app.earcons.limit(False)

            elif k.name == keys.RIGHT:
                if self.cursor < len(self.buffer):
                    self.cursor += 1
                    app.say(self._at_cursor(), force=True)
                else:
                    app.earcons.limit(True)

            elif k.name == keys.HOME:
                self.cursor = 0
                app.say(f"Start. {self._at_cursor()}", force=True)

            elif k.name == keys.END:
                self.cursor = len(self.buffer)
                app.say("End.", force=True)

            elif k.name == keys.UP:
                # Read the whole thing back on demand, without committing.
                app.say("".join(self.buffer) or "empty", force=True)

            elif k.name == keys.DOWN:
                # Spell it. The only way to catch a wrong letter in a name that
                # sounds right — "Grand" versus "Grnad" read identically fast.
                text = "".join(self.buffer)
                app.say(", ".join(speak_char(c) for c in text) or "empty", force=True)

            elif k.char == "\x7f":                       # backspace
                if self.cursor > 0:
                    gone = self.buffer.pop(self.cursor - 1)
                    self.cursor -= 1
                    # What was DELETED, not what is now adjacent.
                    app.say(f"{speak_char(gone)} deleted", force=True)
                else:
                    app.earcons.limit(False)

            elif k.char and k.char.isprintable():
                self.buffer.insert(self.cursor, k.char)
                self.cursor += 1
                app.say(speak_char(k.char), force=True)
