# SPDX-License-Identifier: Apache-2.0
"""
Piper engine — neural voices, MIT licensed, fast enough.

Why this engine matters more than it looks
-------------------------------------------
espeak-ng is fast and free and sounds like 1985. macOS `say` sounds good and is
unusably slow here. Piper is the first option that is **both** good enough to
put in front of a product manager and cheap enough to actually ship.

The licensing is the real argument. espeak-ng is **GPL-3.0-or-later**, and
GPLv3's anti-tivoization clause means a manufacturer shipping it in locked-down
firmware must let users run modified versions on the device. Plenty of hardware
companies will refuse outright, and that refusal has nothing to do with the
design being proposed. **Piper is MIT.** It removes the reason to say no.

Measured here, 2026-08-02, in-process on an M-series Mac:

    model load (once, at startup) ....... 583 ms
    "sixty five" ......................... 20 ms to first audio
    "Cutoff, sixty four" ................. 42 ms
    a full verbose announcement .......... 140 ms

For comparison: espeak-ng is a flat ~13 ms regardless of length, and `say` is
~1000 ms warm. Piper sits between them, close enough to espeak for the frequent
short announcements that dominate real use.

Two honest caveats
------------------
**Latency scales with text length; espeak's does not.** At Verbose, where
announcements get long, Piper is several times slower. That is a genuine
interaction between two settings a manufacturer would otherwise treat as
unrelated, and it belongs in the spec.

**These numbers are from a Mac Studio.** On a Raspberry Pi 4 — a fair stand-in
for what is inside a keyboard — expect several times slower, and drop to a
`low` quality voice if it matters. The architecture does not change; the number
does.

Why in-process, not the CLI
----------------------------
The `piper` command works, but a cold spawn costs **783 ms** loading the model,
which puts it in `say` territory. Worse, interrupting a subprocess mid-sentence
means either killing it (and paying the load again) or reading and discarding
an unknown number of bytes from a raw stream with no utterance boundaries.

Loading the model once in-process solves both. `synthesize()` yields one chunk
per sentence, so interruption is simply **stopping consuming the generator** —
no process to kill, no bytes to discard, nothing to negotiate with.
"""

from __future__ import annotations

import glob
import os
import threading

import numpy as np

from ..audio_out import Bus, OutputDevice
from .base import SpeechEngine

#: Where voice models live. A `.onnx` and a matching `.onnx.json` per voice.
VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "voices")

#: Words per minute the models speak at `length_scale = 1.0`. Approximate and
#: voice-dependent — used only to turn the wpm the user understands into the
#: scale factor Piper wants, so that the rate control means the same thing
#: across all three engines.
NATURAL_WPM = 165.0


def available_models() -> list[tuple[str, str]]:
    """(friendly name, path) for every voice model present."""
    out = []
    for path in sorted(glob.glob(os.path.join(VOICE_DIR, "*.onnx"))):
        stem = os.path.basename(path)[:-5]
        # "en_US-lessac-medium" -> "Lessac (medium)": the raw stem is precise
        # and unspeakable, and this menu is navigated by ear.
        parts = stem.split("-")
        if len(parts) >= 3:
            friendly = f"{parts[1].capitalize()} ({parts[2]})"
        else:
            friendly = stem
        out.append((friendly, path))
    return out


class PiperEngine(SpeechEngine):
    name = "Piper"

    def __init__(self, bus: Bus, rate_wpm: int = 300):
        self._bus = bus
        self._rate = rate_wpm
        self._lock = threading.Lock()
        self._gen = 0
        self._voice = None
        self._speaking = False

        models = available_models()
        self._models = dict(models)
        self._voice_name = models[0][0] if models else ""
        self._model_path = models[0][1] if models else ""

        # Load off the critical path. 583 ms is nothing at startup and
        # everything on a keypress, so the one place it must not happen is
        # inside speak().
        self._ready = threading.Event()
        threading.Thread(target=self._load, daemon=True).start()

    # ------------------------------------------------------------------ #
    @staticmethod
    def is_available() -> bool:
        """Needs both the library and at least one voice model on disk."""
        try:
            import piper  # noqa: F401
        except Exception:
            return False
        return bool(available_models())

    @property
    def routing_note(self) -> str:
        return "Routed exactly: we own the samples and play them ourselves."

    def _load(self) -> None:
        try:
            from piper import PiperVoice

            voice = PiperVoice.load(self._model_path)
            with self._lock:
                self._voice = voice
        except Exception:
            pass
        finally:
            self._ready.set()

    def _syn_config(self):
        from piper import SynthesisConfig

        # Lower length_scale is faster. Clamped so an extreme rate cannot
        # produce something unintelligible or absurdly slow.
        scale = max(0.30, min(2.0, NATURAL_WPM / max(60.0, float(self._rate))))
        return SynthesisConfig(length_scale=scale)

    # ------------------------------------------------------------------ #
    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._gen += 1
            my_gen = self._gen
            voice = self._voice
            # Interruption: discard everything queued before a sample of the
            # new utterance exists. Only the speech track — an earcon still
            # sounding is telling the truth about the new state.
            self._bus.clear()
            self._bus.mark_start()
        if voice is None:
            return                      # still loading; drop it rather than block
        threading.Thread(target=self._synth, args=(voice, text, my_gen),
                         daemon=True).start()

    def _synth(self, voice, text: str, my_gen: int) -> None:
        """
        Iterate the synthesiser, abandoning it the moment we are superseded.

        This is the whole reason for using the library rather than the CLI:
        stopping is *not consuming the next chunk*. There is no process to
        kill and no stale bytes to discard.
        """
        self._speaking = True
        try:
            cfg = self._syn_config()
            for chunk in voice.synthesize(text, cfg):
                if self._gen != my_gen:
                    return
                pcm = (np.frombuffer(chunk.audio_int16_bytes, dtype="<i2")
                       .astype(np.float32) / 32768.0)
                if self._gen != my_gen:
                    return
                self._bus.write(pcm, src_rate=float(chunk.sample_rate))
        except Exception:
            pass
        finally:
            if self._gen == my_gen:
                self._speaking = False

    # ------------------------------------------------------------------ #
    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            self._bus.clear()
        self._speaking = False

    def is_speaking(self) -> bool:
        return self._speaking or self._bus.pending() > 0

    @property
    def rate_wpm(self) -> int:
        return self._rate

    def set_rate(self, wpm: int) -> None:
        self._rate = max(80, min(450, int(wpm)))

    # -- voices --------------------------------------------------------- #
    def available_voices(self) -> list[str]:
        return list(self._models)

    def set_voice(self, name: str) -> None:
        """
        Switch model. Costs another ~600 ms load, so it happens off-thread and
        the old voice keeps speaking until the new one is ready.
        """
        path = self._models.get(name)
        if not path or path == self._model_path:
            return
        self._voice_name, self._model_path = name, path
        self._ready.clear()
        threading.Thread(target=self._load, daemon=True).start()

    @property
    def voice(self) -> str:
        return self._voice_name

    def set_output_device(self, device: OutputDevice) -> None:
        pass                                    # the bus owns the device

    def set_bus(self, bus: Bus) -> None:
        self._bus = bus

    def close(self) -> None:
        self.stop()
