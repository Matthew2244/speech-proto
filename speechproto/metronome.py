# SPDX-License-Identifier: Apache-2.0
"""
Layer 7 — the latency demonstration.

The claim being tested
----------------------
**Speech must never make a note late.**

This is the objection a manufacturer's audio engineer will raise within thirty
seconds of hearing the proposal, and they are right to raise it. If pressing a
key while the instrument is talking can delay a note — even occasionally, even
slightly — the feature gets switched off in the first rehearsal and never
switched back on. No amount of good interaction design survives that.

So this plays a steady click on its own audio track while you hammer the
keyboard and trigger speech, and reports how far each click landed from where
it should have.

What the number actually means
-------------------------------
Being honest about this matters more than the number being small.

What is measured is **when the click was handed to the audio buffer**, against
when it was due. That is a Python thread's scheduling accuracy, not the true
audio-callback jitter — the callback itself is driven by CoreAudio at a fixed
rate, and a sample written early is played at exactly the right moment
regardless of when it was written.

So a small number here does not prove sample-accurate timing. What it proves
is the thing actually in doubt: **that synthesising speech does not starve the
thread producing notes.** On real hardware the audio path would be a
high-priority thread or an interrupt, and would be *more* isolated than this,
not less. This is the pessimistic case.

The design point underneath
----------------------------
Notes go out on their own mixing track, alongside speech and earcons. That is
not a convenience — it is what makes the guarantee structural. Interruption
clears the *speech* track and cannot touch the note track, so there is no code
path in which cancelling an announcement can disturb a note that is already
scheduled. You cannot get that from a single queue no matter how careful you
are.
"""

from __future__ import annotations

import statistics
import threading
import time

import numpy as np

from .audio_out import NOTE


def click(sr: float, freq: float = 1400.0, ms: float = 14.0,
          level: float = 0.25) -> np.ndarray:
    """A short, dry tick — deliberately unlike any earcon in the vocabulary."""
    n = max(1, int(sr * ms / 1000.0))
    t = np.arange(n, dtype=np.float32) / sr
    env = np.exp(-t / 0.004).astype(np.float32)
    return (np.sin(2 * np.pi * freq * t, dtype=np.float32) * env * level).astype(np.float32)


class Metronome:
    """
    A steady click on the note track, with timing kept honest.

    Deliberately simple. This is a demonstration, not a real-time audio system,
    and pretending otherwise would be the wrong claim to make in a meeting.
    """

    def __init__(self, app, bpm: int = 120, subdivision: int = 2):
        self.app = app
        self.bpm = bpm
        self.subdivision = subdivision      # 2 = eighth notes
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        #: (error in ms, was speech active) for every click played.
        self._samples: list[tuple[float, bool]] = []

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def interval(self) -> float:
        return 60.0 / self.bpm / self.subdivision

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        with self._lock:
            self._samples.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        bus = self.app.router.bus(NOTE)
        sound = click(bus.samplerate)
        interval = self.interval
        start = time.perf_counter()
        i = 0
        while not self._stop.is_set():
            # Absolute scheduling, never cumulative sleeps. Sleeping for
            # `interval` each time accumulates every scheduling delay into a
            # permanent drift, which would look like jitter and would be
            # entirely the measurement's own fault.
            due = start + i * interval
            wait = due - time.perf_counter()
            if wait > 0:
                self._stop.wait(timeout=wait)
                if self._stop.is_set():
                    break
            actual = time.perf_counter()
            bus.write(sound)
            speaking = self.app.engine.is_speaking()
            with self._lock:
                self._samples.append(((actual - due) * 1000.0, speaking))
            i += 1

    # ------------------------------------------------------------------ #
    def stats(self) -> dict:
        """Timing error, split by whether speech was running at the time."""
        with self._lock:
            samples = list(self._samples)
        if not samples:
            return {}

        def summarise(rows):
            if not rows:
                return None
            errs = [abs(e) for e, _ in rows]
            return {
                "clicks": len(errs),
                "mean_ms": statistics.mean(errs),
                "max_ms": max(errs),
            }

        return {
            "bpm": self.bpm,
            "interval_ms": self.interval * 1000.0,
            "all": summarise(samples),
            "while_speaking": summarise([r for r in samples if r[1]]),
            "while_quiet": summarise([r for r in samples if not r[1]]),
        }

    def report(self) -> str:
        """A spoken summary — this has to be usable without reading a table."""
        s = self.stats()
        if not s or not s["all"]:
            return "No clicks recorded."
        loud, quiet = s["while_speaking"], s["while_quiet"]
        parts = [f"{s['all']['clicks']} clicks at {s['bpm']} beats per minute."]
        if loud:
            parts.append(f"While speaking, worst error {loud['max_ms']:.1f} milliseconds "
                         f"over {loud['clicks']} clicks.")
        if quiet:
            parts.append(f"While quiet, worst error {quiet['max_ms']:.1f} milliseconds.")
        if loud and quiet:
            diff = loud["max_ms"] - quiet["max_ms"]
            parts.append("Speech made no measurable difference."
                         if abs(diff) < 1.0 else
                         f"Difference, {diff:+.1f} milliseconds.")
        return " ".join(parts)

    def print_report(self) -> None:
        s = self.stats()
        if not s or not s["all"]:
            print("  no clicks recorded")
            return
        print(f"\n  {s['all']['clicks']} clicks at {s['bpm']} bpm "
              f"({s['interval_ms']:.0f} ms apart)")
        for label, key in (("while speaking", "while_speaking"),
                           ("while quiet   ", "while_quiet"),
                           ("overall       ", "all")):
            row = s[key]
            if row:
                print(f"    {label}: mean {row['mean_ms']:6.2f} ms, "
                      f"max {row['max_ms']:6.2f} ms  ({row['clicks']} clicks)")
        print("\n  Measured: when each click was handed to the audio buffer versus")
        print("  when it was due. Not sample-accurate audio jitter — but it is the")
        print("  thing in doubt: whether speech starves the thread making notes.")
