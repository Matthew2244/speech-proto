#!/usr/bin/env python3
"""
Step 1 harness — speech engine layer, output routing, and interruption.

This exists to answer one question by ear: **does interruption feel right?**

The test that matters: hold the Down arrow. You should hear a rapid stream of
clipped partial words that tracks your hand in real time. If you hear a backlog
playing out behind you, the design is wrong and nothing built on top of it will
feel right.

Nothing here is the real interaction design yet — the parameter names below are
canned strings standing in for a parameter tree that arrives in step 2. The
announcement builder, the verbosity model, and the earcons all come later.

Keys
----
  Down / Up ......... next / previous parameter (hold to stress interruption)
  Right / Left ...... value up / down by 1      (hold to stress interruption)
  Shift+Right/Left .. value by 10
  t ................. speak a long sentence, so there is something to interrupt
  e ................. switch speech engine
  ] / [ ............. speech rate up / down by 25 wpm
  d ................. choose output device
  s ................. speak current status
  a ................. hands-free audition (also: run with --audition)
  ? ................. speak the key list
  Ctrl+Space ........ silence immediately, say nothing
  q / Ctrl+C ........ quit
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from speechproto import audio_out, keys
from speechproto.audio_out import SPEECH, OutputDevice, Router
from speechproto.audition import run_audition
from speechproto.keys import Key, KeyReader
from speechproto.speech import available_engines, create_engine

# Canned announcements standing in for a real parameter tree (step 2).
PARAMS = [
    "Cutoff, 64",
    "Resonance, 32",
    "EG Intensity, 12",
    "Type, Low Pass",
    "Level, 100",
    "Pan, C064",
    "Attack, 0",
    "Decay, 43",
    "Sustain, 90",
    "Release, 25",
]

LONG_SENTENCE = (
    "This is a deliberately long announcement, the kind a badly designed "
    "screen reader would insist on finishing while you are already three "
    "parameters further down the list and wondering why it will not stop "
    "talking over you."
)

HELP = (
    "Down and Up move between parameters. Right and Left change value. "
    "Shift for ten. T speaks a long sentence. E switches engine. "
    "Bracket keys change rate. D chooses output device. S speaks status. "
    "A plays the hands-free audition. Control Space silences. Q quits."
)


class App:
    def __init__(self, device: OutputDevice, engine_key: str, rate: int):
        self.device = device
        self.rate = rate
        # Step 1 predates the router, but it has to share the same plumbing or
        # it rots into a second, silently-broken copy of the app — which is
        # exactly what happened once already.
        self.router = Router()
        self.router.set_targets(SPEECH, [device])

        # Both engines are constructed up front and both stay alive. `say`
        # needs its warm pool filling in the background at all times; tearing
        # it down on every switch would reintroduce the very latency the pool
        # exists to hide.
        self.engines = {}
        for key in available_engines():
            self.engines[key] = create_engine(key, self.speech_bus, rate, device)
        if engine_key not in self.engines:
            engine_key = next(iter(self.engines))
        self.engine_key = engine_key

        self.index = 0
        self.value = 64
        self.running = True

        self._latency_thread = threading.Thread(target=self._watch_latency, daemon=True)
        self._latency_thread.start()

    @property
    def engine(self):
        return self.engines[self.engine_key]

    @property
    def speech_bus(self):
        return self.router.bus(SPEECH)

    @property
    def sink(self):
        """Kept as a name for the audition module, which reads latency off it."""
        return self.speech_bus

    # ------------------------------------------------------------------ #
    def say(self, text: str) -> None:
        """Every announcement in this harness goes through here."""
        self.engine.speak(text)

    def _watch_latency(self) -> None:
        """
        Report keypress-to-first-audio, once per utterance.

        Only meaningful for espeak-ng, because that is the engine whose samples
        we own. `say` plays through CoreAudio directly and cannot be measured
        from here — which is itself part of the story.
        """
        last = None
        while self.running:
            ms = self.speech_bus.last_latency_ms
            if ms is not None and ms != last:
                last = ms
                if self.engine_key == "espeak":
                    print(f"  [{ms:.1f} ms to first audio]", flush=True)
            time.sleep(0.02)

    # ------------------------------------------------------------------ #
    def set_device(self, device: OutputDevice) -> None:
        """Repoint everything at a new output. Speech follows, immediately."""
        self.engine.stop()
        self.router.set_targets(SPEECH, [device])
        self.device = device
        if "espeak" in self.engines:
            self.engines["espeak"].set_bus(self.speech_bus)
        # `say` routes itself and merely needs telling.
        if "say" in self.engines:
            self.engines["say"].set_output_device(device)

    def choose_device(self, reader: KeyReader) -> None:
        """
        Device chooser, arrow-driven.

        Reading a numbered list aloud and asking someone to type a number is
        the sighted way to do this. Arrowing through a list that speaks each
        entry is faster and needs no memory, so both work: arrows browse,
        digits jump, Enter selects, Escape cancels.
        """
        devices = audio_out.list_output_devices()
        if not devices:
            self.say("No output devices found.")
            return
        cur = next((i for i, d in enumerate(devices) if d.index == self.device.index), 0)
        self.say(f"Output device. {devices[cur].describe()}. Up and down to browse, enter to select, escape to cancel.")
        print("Device menu — up/down, Enter select, Esc cancel", flush=True)

        while True:
            k = reader.read()
            if k is None:
                continue
            if k.name in (keys.ESCAPE, keys.INTERRUPT):
                self.say("Cancelled.")
                return
            if k.name == keys.SILENCE:
                self.engine.stop()
                continue
            if k.name == keys.UP:
                cur = (cur - 1) % len(devices)
                self.say(devices[cur].describe())
            elif k.name == keys.DOWN:
                cur = (cur + 1) % len(devices)
                self.say(devices[cur].describe())
            elif k.name == keys.ENTER:
                chosen = devices[cur]
                self.set_device(chosen)
                self.say(f"Speech now going to {chosen.name}.")
                print(f"-> speech routed to [{chosen.index}] {chosen.name}", flush=True)
                return
            elif k.char and k.char.isdigit():
                want = int(k.char)
                match = next((i for i, d in enumerate(devices) if d.index == want), None)
                if match is not None:
                    cur = match
                    self.say(devices[cur].describe())

    # ------------------------------------------------------------------ #
    def switch_engine(self) -> None:
        order = list(self.engines)
        if len(order) < 2:
            self.say("Only one engine available.")
            return
        self.engine.stop()
        self.engine_key = order[(order.index(self.engine_key) + 1) % len(order)]
        eng = self.engine
        eng.set_rate(self.rate)
        self.say(f"{eng.name}. {eng.routing_note}")
        print(f"-> engine: {eng.name}  ({eng.routing_note})", flush=True)

    def change_rate(self, delta: int) -> None:
        self.rate = max(80, min(450, self.rate + delta))
        for eng in self.engines.values():
            eng.set_rate(self.rate)
        self.say(f"{self.rate} words per minute")
        print(f"-> rate: {self.rate} wpm", flush=True)

    def status(self) -> None:
        eng = self.engine
        self.say(
            f"{eng.name}, {self.rate} words per minute, "
            f"output {self.device.name}. {eng.routing_note}"
        )

    # ------------------------------------------------------------------ #
    def handle(self, k: Key, reader: KeyReader) -> None:
        # Silence first, and it says nothing in response. A silence key that
        # announces itself is not a silence key.
        if k.name == keys.SILENCE:
            self.engine.stop()
            return

        if k.name == keys.INTERRUPT or (k.char == "q"):
            self.running = False
            self.engine.stop()
            return

        if k.name == keys.DOWN:
            self.index = (self.index + 1) % len(PARAMS)
            self.say(PARAMS[self.index])
        elif k.name == keys.UP:
            self.index = (self.index - 1) % len(PARAMS)
            self.say(PARAMS[self.index])
        elif k.name == keys.RIGHT:
            self.value = min(127, self.value + (10 if k.shift else 1))
            self.say(str(self.value))
        elif k.name == keys.LEFT:
            self.value = max(0, self.value - (10 if k.shift else 1))
            self.say(str(self.value))
        elif k.char == "t":
            self.say(LONG_SENTENCE)
        elif k.char == "e":
            self.switch_engine()
        elif k.char == "]":
            self.change_rate(25)
        elif k.char == "[":
            self.change_rate(-25)
        elif k.char == "d":
            self.choose_device(reader)
        elif k.char == "s":
            self.status()
        elif k.char == "a":
            run_audition(self)
        elif k.char == "?":
            self.say(HELP)

    def close(self) -> None:
        self.running = False
        for eng in self.engines.values():
            eng.close()
        self.router.close()


def resolve_device(devices: list[OutputDevice], spec: str) -> OutputDevice | None:
    """
    Find an output device by name, falling back to a numeric index.

    Name first, deliberately. PortAudio indices are positional and **shift when
    devices appear or disappear** — plugging in an interface renumbers
    everything after it. A saved index therefore points somewhere different
    after a reboot, and speech silently comes out of the wrong output. On stage
    that means your monitoring goes to the house.

    A real instrument should persist the device *name* for the same reason.
    Numeric selection is kept only because it is convenient to type.
    """
    spec = spec.strip()
    lowered = spec.lower()

    for d in devices:  # exact name wins
        if d.name.lower() == lowered:
            return d
    matches = [d for d in devices if lowered in d.name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(d.name for d in matches)
        print(f"{spec!r} matches several devices: {names}", file=sys.stderr)
        return None
    if spec.isdigit():
        return next((d for d in devices if d.index == int(spec)), None)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 1 — speech, routing, interruption.")
    ap.add_argument("--list-devices", action="store_true", help="print output devices and exit")
    ap.add_argument("--audition", action="store_true", help="play the hands-free audition and exit")
    ap.add_argument(
        "--device",
        default=None,
        help="output device: name or part of a name (preferred), or a numeric index",
    )
    ap.add_argument("--engine", default=None, choices=["espeak", "say"], help="starting engine")
    ap.add_argument("--rate", type=int, default=300, help="speech rate, words per minute")
    args = ap.parse_args()

    devices = audio_out.list_output_devices()
    if args.list_devices:
        for d in devices:
            print(f"{d.index:3d}  {d.name}  ({d.channels}ch)")
        return 0

    engines = available_engines()
    if not engines:
        print("No speech engine available (need espeak-ng or macOS say).", file=sys.stderr)
        return 1

    if args.device is not None:
        device = resolve_device(devices, args.device)
        if device is None:
            print(f"No output device matching {args.device!r}. Try --list-devices.", file=sys.stderr)
            return 1
    else:
        device = audio_out.default_output_device()
        if device is None:
            print("No output devices found.", file=sys.stderr)
            return 1

    engine_key = args.engine or ("espeak" if "espeak" in engines else engines[0])

    print(f"Output: [{device.index}] {device.name}")
    print(f"Engines available: {', '.join(engines)}")
    print("Press ? to hear the keys, q to quit.\n", flush=True)

    app = App(device, engine_key, args.rate)

    if args.audition:
        # Let the `say` warm pool fill before judging it. Auditioning a cold
        # pool would show ~2.4 s and misrepresent the engine at its best —
        # the comparison is only fair if `say` is given every advantage.
        print("Warming the say process pool...", flush=True)
        time.sleep(3.0)
        try:
            run_audition(app)
        finally:
            app.close()
        return 0

    try:
        with KeyReader() as reader:
            eng = app.engine
            app.say(
                f"Ready. {eng.name}, {app.rate} words per minute, "
                f"output {device.name}. Hold down arrow to test interruption."
            )
            while app.running:
                k = reader.read()
                if k is None:
                    continue
                app.handle(k, reader)
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
