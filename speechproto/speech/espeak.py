# SPDX-License-Identifier: Apache-2.0
"""
espeak-ng engine — PCM to stdout, played through our own audio sink.

This is the realistic target. It is what would actually run on embedded Linux
inside a keyboard, it is what Charles Vestal used to put a screen reader on the
Ableton Move, and it is tiny and open source.

Measured on this machine, 2026-08-01:

    time to FIRST PCM byte ......... ~12 ms
    complete synthesis of a
    3.5-second announcement ........ ~14 ms

For comparison, macOS `say` costs roughly 2400 ms per invocation here. espeak-ng
is about two hundred times faster to first audio. That gap is the entire reason
this engine, not the pretty one, is the honest demonstration of what good feels
like.

Because we own the samples, interruption is exact: kill the synthesiser, throw
away the buffered audio, done. There is no synthesiser to negotiate with.
"""

from __future__ import annotations

import io
import shutil
import struct
import subprocess
import threading

import numpy as np

from ..audio_out import Bus, OutputDevice
from .base import SpeechEngine


def _parse_wav_header(buf: bytes) -> tuple[int, int, int, int] | None:
    """
    Pull (samplerate, channels, bits, data_offset) out of a RIFF/WAVE header.

    espeak-ng emits a canonical 44-byte header, but it is parsed properly here
    rather than assumed, because the sample rate is voice-dependent and getting
    it wrong makes speech play at the wrong pitch — a bug that sounds like a
    broken voice rather than a broken number.

    Returns None if the header has not fully arrived yet.
    """
    if len(buf) < 12 or buf[0:4] != b"RIFF" or buf[8:12] != b"WAVE":
        return None
    pos = 12
    samplerate = channels = bits = None
    while pos + 8 <= len(buf):
        chunk_id = buf[pos : pos + 4]
        (chunk_sz,) = struct.unpack("<I", buf[pos + 4 : pos + 8])
        body = pos + 8
        if chunk_id == b"fmt ":
            if body + 16 > len(buf):
                return None
            _fmt, channels, samplerate, _byte_rate, _align, bits = struct.unpack(
                "<HHIIHH", buf[body : body + 16]
            )
        elif chunk_id == b"data":
            if samplerate is None:
                return None
            return samplerate, channels, bits, body
        pos = body + chunk_sz + (chunk_sz & 1)
    return None


#: Friendly name -> espeak-ng voice spec. espeak's own names ("en-us+m3") are
#: precise and unspeakable; a menu you navigate by ear needs names that survive
#: being read aloud. The list is curated rather than exhaustive — espeak ships
#: about a hundred variants, and a menu nobody can finish is not a choice.
ESPEAK_VOICES: list[tuple[str, str]] = [
    ("American", "en-us"),
    ("British", "en-gb"),
    ("Received Pronunciation", "en-gb-x-rp"),
    ("Scottish", "en-gb-scotland"),
    ("Lancashire", "en-gb-x-gbclan"),
    ("West Midlands", "en-gb-x-gbcwmd"),
    ("Male 1", "en-us+m1"), ("Male 2", "en-us+m2"), ("Male 3", "en-us+m3"),
    ("Male 4", "en-us+m4"), ("Male 5", "en-us+m5"), ("Male 6", "en-us+m6"),
    ("Male 7", "en-us+m7"), ("Male 8", "en-us+m8"),
    ("Female 1", "en-us+f1"), ("Female 2", "en-us+f2"), ("Female 3", "en-us+f3"),
    ("Female 4", "en-us+f4"), ("Female 5", "en-us+f5"),
    ("Announcer", "en-us+announcer"),
    ("Whisper", "en-us+whisper"),
    ("Whisper Female", "en-us+whisperf"),
    ("Croak", "en-us+croak"),
    ("Grandma", "en-us+grandma"),
    ("Grandpa", "en-us+grandpa"),
    ("Robot", "en-us+robosoft"),
    ("Robot 3", "en-us+robosoft3"),
    ("Klatt", "en-us+klatt"),
    ("Klatt 3", "en-us+klatt3"),
    ("Storm", "en-us+Storm"),
    ("Max", "en-us+max"),
    ("Alex", "en-us+Alex"),
    ("Linda", "en-us+linda"),
]


class EspeakEngine(SpeechEngine):
    name = "espeak-ng"

    def __init__(self, bus: Bus, rate_wpm: int = 300):
        self._bus = bus
        self._rate = rate_wpm
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        # Generation counter. Every speak() bumps it. A reader thread that
        # notices its generation is stale stops pushing audio and exits, so a
        # superseded utterance can never leak samples into the sink after the
        # new one has started.
        self._gen = 0
        self._voice_name, self._voice_spec = ESPEAK_VOICES[0]

    @staticmethod
    def is_available() -> bool:
        return shutil.which("espeak-ng") is not None

    def available_voices(self) -> list[str]:
        return [n for n, _ in ESPEAK_VOICES]

    def set_voice(self, name: str) -> None:
        for friendly, spec in ESPEAK_VOICES:
            if friendly == name:
                self._voice_name, self._voice_spec = friendly, spec
                return

    @property
    def voice(self) -> str:
        return self._voice_name

    def set_voice_spec(self, spec: str) -> None:
        """
        Set the espeak voice directly, bypassing the friendly-name table.

        Used when the *language* changes: the language decides the base voice
        ("es", "fr-fr"), and the friendly names in ESPEAK_VOICES are all
        English variants. Choosing Spanish must change the pronunciation rules
        as well as the words, or you get Spanish text read as English.
        """
        self._voice_spec = spec
        self._voice_name = spec

    @property
    def routing_note(self) -> str:
        return "Routed exactly: we own the samples and play them ourselves."

    # ------------------------------------------------------------------ #
    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._gen += 1
            my_gen = self._gen
            self._kill_locked()
            # Discard anything still queued from the previous announcement.
            # This is the interruption. It happens before a single sample of
            # the new utterance is generated. Only the speech track is cleared —
            # an earcon that is still sounding is telling the truth about the
            # new state, so it is left alone.
            self._bus.clear()
            self._bus.mark_start()

            self._proc = subprocess.Popen(
                [
                    "espeak-ng",
                    "-v", self._voice_spec,
                    "-s", str(self._rate),
                    "--stdout",
                    "--", text,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            proc = self._proc

        self._reader = threading.Thread(
            target=self._pump, args=(proc, my_gen), daemon=True
        )
        self._reader.start()

    def _pump(self, proc: subprocess.Popen, my_gen: int) -> None:
        """
        Read PCM from espeak-ng and feed the sink, in chunks, as it arrives.

        espeak-ng produces the whole utterance in a few milliseconds, so this
        is not really streaming for latency's sake — it is so that an interrupt
        arriving mid-read stops the pump instantly instead of after the entire
        utterance has been queued.
        """
        header_buf = bytearray()
        src_rate = None
        bits = 16
        stream = proc.stdout
        assert stream is not None

        try:
            while True:
                if self._gen != my_gen:
                    return  # superseded — drop everything, say nothing more
                data = stream.read(4096)
                if not data:
                    break

                if src_rate is None:
                    header_buf += data
                    parsed = _parse_wav_header(bytes(header_buf))
                    if parsed is None:
                        continue
                    src_rate, _ch, bits, offset = parsed
                    data = bytes(header_buf[offset:])
                    if not data:
                        continue

                if bits != 16:
                    continue
                pcm = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
                if self._gen != my_gen:
                    return
                # Each sink on the bus resamples for itself, so speech can go to
                # two devices running at different rates without duplicating work
                # here or picking a winner.
                self._bus.write(pcm, src_rate=float(src_rate))
        except Exception:
            pass
        finally:
            try:
                proc.wait(timeout=1)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            self._kill_locked()
            self._bus.clear()

    def _kill_locked(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def is_speaking(self) -> bool:
        return self._bus.pending() > 0 or (
            self._proc is not None and self._proc.poll() is None
        )

    @property
    def rate_wpm(self) -> int:
        return self._rate

    def set_rate(self, wpm: int) -> None:
        # espeak-ng accepts roughly 80..450 wpm.
        self._rate = max(80, min(450, int(wpm)))

    def set_output_device(self, device: OutputDevice) -> None:
        # Nothing to do: the bus owns its devices. Re-routing is done by the
        # router in the app layer, and this engine simply keeps writing to the
        # same bus object.
        pass

    def set_bus(self, bus: Bus) -> None:
        self._bus = bus

    def close(self) -> None:
        self.stop()
