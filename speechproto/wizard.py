# SPDX-License-Identifier: Apache-2.0
"""
Layer 6 — first-run setup.

The hardest five minutes of any accessible product is the first five, because
every convenience you would normally lean on is exactly what has not been
configured yet. The wizard has to work for someone who has never used this,
cannot see it, and does not yet know whether it can even reach their ears.

So the first question is not "what language?" It is **"can you hear me?"**

Why the hearing check comes first
----------------------------------
Every other setting is downstream of it. Ask about language first and you have
asked a question the user may not have heard, in a voice going to an output
they are not listening to — and they cannot tell you, because the only channel
you have is the broken one.

So step one walks the available outputs, speaking on each in turn:

    "Can you hear this? Press Enter to use this output, or Space to try the
    next one."

**Silence is the answer that makes progress.** If you hear nothing, you press
Space and the next output speaks. There is no state in which being unable to
hear leaves you stuck — which is the property that the rest of the setup, and
frankly the rest of the instrument, depends on.

The rest
--------
Language, voice, speech rate, verbosity, earcons, pack. Every step is arrow to
choose, Enter to accept, Escape to stop and keep the defaults. Nothing is
mandatory; a wizard you cannot escape is a trap, not a help.

Language applies **immediately**, so every prompt after it is spoken in the
language just chosen — in that language's voice, with that language's words.
That is the string table and the voice selection working together, and it is
the most direct way to show that "add Spanish" means both halves.
"""

from __future__ import annotations

import json
import os
import time

from . import audio_out, keys
from .announce import Verbosity
from .keys import Key
from .earcons import PACK_NAMES, PACKS, Spatial
from .strings import LANGUAGES, Strings

SETUP_FILE = os.path.expanduser("~/.speech-proto.json")


def has_run_before() -> bool:
    return os.path.exists(SETUP_FILE)


def save_setup(app) -> None:
    """Remember the answers, so first-run only happens once."""
    data = {
        "language": app.strings.language,
        "engine": app.engine_key,
        "voice": app.engine.voice,
        "rate": app.rate,
        "verbosity": app.verbosity.label,
        "earcons": app.earcons.enabled,
        "pack": app.earcons.pack.name,
        "space": app.earcons.spatial.label,
        # Saved by NAME, never by index — PortAudio renumbers devices when
        # anything is plugged in or removed.
        "speech_output": app.speech_device.name,
        "earcon_output": app.earcon_device.name,
    }
    try:
        with open(SETUP_FILE, "w") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


def load_setup() -> dict:
    try:
        with open(SETUP_FILE) as fh:
            return json.load(fh)
    except Exception:
        return {}


class Wizard:
    def __init__(self, app, reader):
        self.app = app
        self.reader = reader
        self.cancelled = False

    # ------------------------------------------------------------------ #
    def _speak_and_wait(self, text: str, timeout: float = 6.0) -> Key | None:
        """
        Say something and let it finish — unless a key interrupts it.

        Returns the interrupting key, or None if the prompt played out. The
        caller must treat that key as the answer to THIS question. The first
        version of this method read no input until speech ended, so keys
        pressed during a prompt queued up against questions the user had not
        heard yet — every answer landed one question late, and in the hearing
        check that accepted an output the user never chose. Interruption is
        the rule everywhere else in this prototype; the wizard does not get
        an exemption just because it speaks in paragraphs.
        """
        self.app.say(text, force=True)
        deadline = time.monotonic() + timeout
        time.sleep(0.1)
        while self.app.engine.is_speaking() and time.monotonic() < deadline:
            k = self.reader.poll(0.03)
            if k is not None:
                self.app.engine.stop()
                return k
        return None

    def choose(self, prompt: str, options: list[str], current: int,
               preview=None) -> int | None:
        """
        One question. Arrow to change, Enter to accept, Escape to stop.

        `preview` is called with each option as you land on it, for the
        settings where the name means nothing without the sound.
        """
        idx = max(0, min(current, len(options) - 1))
        k = self._speak_and_wait(
            f"{prompt} {options[idx]}. Up and down to choose. Enter to accept.")

        while True:
            if k is None:
                k = self.reader.read()
            if k is None:
                continue
            if k.name == keys.SILENCE:
                self.app.engine.stop()
            elif k.name in (keys.ESCAPE, keys.INTERRUPT):
                self.cancelled = True
                return None
            elif k.name == keys.ENTER:
                return idx
            elif k.name in (keys.UP, keys.DOWN):
                step = -1 if k.name == keys.UP else 1
                new = idx + step
                if 0 <= new < len(options):
                    idx = new
                    self.app.say(options[idx], force=True)
                    if preview:
                        preview(options[idx])
                else:
                    self.app.earcons.limit(idx > 0)
            k = None

    # ------------------------------------------------------------------ #
    def hearing_check(self) -> bool:
        """
        Find an output the user can actually hear. Returns False if they quit.

        This is the only step that cannot assume its own question was heard,
        so it is built the other way round: not hearing it is a valid, useful
        answer that moves things forward.
        """
        devices = audio_out.list_output_devices()
        if not devices:
            return True
        start = next((i for i, d in enumerate(devices)
                      if d.index == self.app.speech_device.index), 0)

        for offset in range(len(devices)):
            device = devices[(start + offset) % len(devices)]
            self.app.route(audio_out.SPEECH, device)
            self.app.route(audio_out.EARCON, device)
            self.app.earcons.power(True)
            k = self._speak_and_wait(
                f"Setup. Can you hear this? This is {device.name}. "
                f"Press Enter to use it, or press the space bar to try the next output.",
                timeout=10.0,
            )
            while True:
                if k is None:
                    k = self.reader.read()
                if k is None:
                    continue
                if k.name == keys.ENTER:
                    return True
                if k.char == " ":
                    break                       # try the next device
                if k.name in (keys.ESCAPE, keys.INTERRUPT):
                    self.cancelled = True
                    return False
                if k.name == keys.SILENCE:
                    self.app.engine.stop()
                k = None
        return True

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        app = self.app
        print("Setup — arrow keys to choose, Enter to accept, Escape to skip.\n",
              flush=True)

        if not self.hearing_check() or self.cancelled:
            return

        # -- language, applied at once so the rest speaks it -------------- #
        pick = self.choose("Language.", LANGUAGES,
                           LANGUAGES.index(app.strings.language))
        if pick is None:
            return
        app.set_language(LANGUAGES[pick])

        # -- voice -------------------------------------------------------- #
        voices = app.engine.available_voices()
        if voices:
            cur = voices.index(app.engine.voice) if app.engine.voice in voices else 0
            pick = self.choose("Voice.", voices, cur,
                               preview=lambda v: app.engine.set_voice(v))
            if pick is None:
                return
            app.engine.set_voice(voices[pick])

        # -- rate. Previewed at the rate itself, which is the only honest -- #
        # -- way to choose one: a number means nothing until you hear it. -- #
        rates = ["180", "240", "300", "350", "400", "450"]
        cur = min(range(len(rates)), key=lambda i: abs(int(rates[i]) - app.rate))
        pick = self.choose("Speech rate, words per minute.", rates, cur,
                           preview=lambda r: app.set_rate(int(r)))
        if pick is None:
            return
        app.set_rate(int(rates[pick]))

        # -- verbosity ---------------------------------------------------- #
        levels = ["Terse", "Normal", "Verbose"]
        pick = self.choose("How much should it tell you?", levels,
                           int(app.verbosity) - 1)
        if pick is None:
            return
        app.verbosity = Verbosity.from_name(levels[pick])

        # -- earcons ------------------------------------------------------ #
        pick = self.choose("Sound effects for navigation?", ["On", "Off"],
                           0 if app.earcons.enabled else 1)
        if pick is None:
            return
        app.earcons.enabled = (pick == 0)

        if app.earcons.enabled:
            pick = self.choose(
                "Sound style.", PACK_NAMES,
                PACK_NAMES.index(app.earcons.pack.name),
                preview=lambda n: (app.earcons.set_pack(n), app.demo_pack()),
            )
            if pick is None:
                return
            app.earcons.set_pack(PACK_NAMES[pick])

        app._sync_settings()
        save_setup(app)
        app.earcons.done("save", ok=True)
        self._speak_and_wait("Setup complete. Press question mark at any time to hear the keys.")
