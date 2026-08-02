# SPDX-License-Identifier: Apache-2.0
"""
macOS `say` engine — good voice, bad latency, kept honest by a warm pool.

Why this file is more complicated than it looks
------------------------------------------------
The obvious implementation is `subprocess.run(["say", text])`. On this machine
that costs **~2.4 seconds before any sound**, because there are 442 voices
installed and `say` rescans the voice catalogue on every single launch. The
cost is the same for every voice, every output device, and even for an empty
string. Measured 2026-08-01.

That is not a detail — it is the exact failure this whole prototype exists to
argue against, and a naive implementation would demonstrate the opposite of the
intended point while appearing to work.

Three things that do NOT fix it, all tested:

* `say -o /dev/stdout` fails outright (`Opening output file failed: -54`), and
  a named pipe fails too. `say` wants a real seekable file, so synthesising to
  PCM and playing it ourselves adds ~1.9 s. Worse, not better.
* `say -f -` fed line by line **buffers until stdin closes**. It will not speak
  incrementally, so one long-lived process cannot serve successive utterances.
* Pinning a single voice does not help. The catalogue scan happens regardless.

What does work: a pool of pre-warmed processes
-----------------------------------------------
Spawn `say -f -` processes in advance and leave stdin open. Each has already
paid the catalogue cost by the time it is needed. To speak, write the text and
close stdin. To interrupt, kill the speaker and take the next warm process.

    kill speaking process + hand text to a warm spare .... 1.7 ms

A background thread keeps the pool topped up, so the ~2.4 s is always paid off
the critical path. Warm overhead to first audio is still around a second — far
better than 2.4, and still much worse than espeak-ng's 12 ms. Keeping this
engine in the prototype is deliberate: the contrast is informative, and a
manufacturer choosing a heavyweight system voice needs to hear what it costs.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time

from ..audio_out import OutputDevice, resolve_say_device
from .base import SpeechEngine

POOL_SIZE = 3          # spares kept warm and ready
WARMUP_SECONDS = 2.5   # how long a fresh process needs before it is "warm"


class _Warm:
    """One pre-spawned `say -f -` process and the time it became usable."""

    __slots__ = ("proc", "ready_at")

    def __init__(self, proc: subprocess.Popen, ready_at: float):
        self.proc = proc
        self.ready_at = ready_at

    def is_ready(self) -> bool:
        return time.monotonic() >= self.ready_at and self.proc.poll() is None


class SayEngine(SpeechEngine):
    name = "macOS say"

    def __init__(self, rate_wpm: int = 300, device: OutputDevice | None = None):
        self._rate = rate_wpm
        self._say_device: str | None = None
        if device is not None:
            self._say_device = resolve_say_device(device.name)

        self._lock = threading.Lock()
        self._pool: list[_Warm] = []
        self._speaking: subprocess.Popen | None = None
        self._closed = False
        self._voices: list[str] | None = None
        self._voice: str = ""

        self._filler = threading.Thread(target=self._keep_pool_full, daemon=True)
        self._filler.start()

    @staticmethod
    def is_available() -> bool:
        import shutil

        return shutil.which("say") is not None

    def available_voices(self) -> list[str]:
        """
        English voices installed on this Mac.

        Queried once and cached: `say -v ?` is a subprocess, and on this
        machine it returns 442 voices — the same catalogue scan that makes
        every `say` invocation cost two seconds. Filtering to English keeps the
        menu navigable; there are still around 140.
        """
        if self._voices is None:
            names: list[str] = []
            try:
                out = subprocess.run(["say", "-v", "?"], capture_output=True,
                                     text=True, timeout=10).stdout
                for line in out.splitlines():
                    m = re.match(r"^(.+?)\s{2,}(\S+)\s+#", line)
                    if m and m.group(2).startswith("en"):
                        nm = m.group(1).strip()
                        if "(" not in nm and nm not in names:
                            names.append(nm)
            except Exception:
                pass
            self._voices = sorted(names) or ["System Default"]
        return self._voices

    def set_voice(self, name: str) -> None:
        if name and name != self._voice:
            self._voice = name
            self._recycle_pool()      # voice is fixed at spawn time

    @property
    def voice(self) -> str:
        return self._voice or ""

    @property
    def routing_note(self) -> str:
        if self._say_device:
            return f"Routed via say -a {self._say_device} (separate ID space, matched by name)."
        return "Not routed: no matching `say -a` device; using the system default."

    # ------------------------------------------------------------------ #
    def _spawn(self) -> _Warm:
        args = ["say", "-r", str(self._rate), "-f", "-"]
        if self._say_device:
            args = ["say", "-a", self._say_device, "-r", str(self._rate), "-f", "-"]
        if self._voice:
            args += ["-v", self._voice]
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _Warm(proc, time.monotonic() + WARMUP_SECONDS)

    def _keep_pool_full(self) -> None:
        """Background top-up. Every second of catalogue scanning happens here."""
        while not self._closed:
            try:
                with self._lock:
                    # Drop any process that died while waiting.
                    self._pool = [w for w in self._pool if w.proc.poll() is None]
                    need = POOL_SIZE - len(self._pool)
                for _ in range(max(0, need)):
                    w = self._spawn()
                    with self._lock:
                        if self._closed:
                            w.proc.kill()
                            return
                        self._pool.append(w)
            except Exception:
                pass
            time.sleep(0.25)

    def _take_warm(self) -> _Warm | None:
        with self._lock:
            for i, w in enumerate(self._pool):
                if w.is_ready():
                    return self._pool.pop(i)
            # Nothing warm yet. Take the oldest anyway — a slow announcement
            # beats a silent one; silence reads as a crash to a blind user.
            if self._pool:
                return self._pool.pop(0)
        return None

    # ------------------------------------------------------------------ #
    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._kill_speaking()
        w = self._take_warm()
        if w is None:
            w = self._spawn()
        try:
            assert w.proc.stdin is not None
            w.proc.stdin.write(text.encode("utf-8", "replace"))
            w.proc.stdin.close()   # `say -f -` does not speak until EOF
            with self._lock:
                self._speaking = w.proc
        except Exception:
            pass

    def stop(self) -> None:
        self._kill_speaking()

    def _kill_speaking(self) -> None:
        with self._lock:
            proc = self._speaking
            self._speaking = None
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def is_speaking(self) -> bool:
        with self._lock:
            proc = self._speaking
        return proc is not None and proc.poll() is None

    @property
    def rate_wpm(self) -> int:
        return self._rate

    def set_rate(self, wpm: int) -> None:
        self._rate = max(80, min(700, int(wpm)))
        # Rate is fixed at spawn time, so the warm pool is now stale. Discard
        # it and let the filler thread rebuild at the new rate.
        self._recycle_pool()

    def set_output_device(self, device: OutputDevice) -> None:
        self._say_device = resolve_say_device(device.name)
        self._recycle_pool()

    def _recycle_pool(self) -> None:
        with self._lock:
            old, self._pool = self._pool, []
        for w in old:
            try:
                w.proc.kill()
            except Exception:
                pass

    def close(self) -> None:
        self._closed = True
        self._kill_speaking()
        self._recycle_pool()
