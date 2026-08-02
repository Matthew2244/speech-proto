"""
Hands-free audition — hear step 1 without knowing a single keystroke.

Run it, sit back, listen. It walks the same three behaviours on each available
engine, narrating itself as it goes, so the comparison lands by ear rather than
by memory:

    1. Ordinary navigation, at the pace a hand actually moves.
    2. A held key — twelve announcements at auto-repeat speed. This is the one
       that matters. You should hear clipped partial words tracking the burst,
       not a queue draining behind it.
    3. Interrupting a long sentence mid-word.

This is an early slice of the `--demo` flag promised in step 7. That one will
walk a navigation path at all three verbosity levels; this one only has speech
and interruption to show, because that is all step 1 built.
"""

from __future__ import annotations

import time

# Pace of a held arrow key. macOS auto-repeat is roughly 30 ms at the fastest
# setting and ~90 ms at the default; 80 ms is a fair, unflattering middle.
HELD_KEY_INTERVAL = 0.08

NAV = [
    "Cutoff, 64",
    "Resonance, 32",
    "EG Intensity, 12",
    "Type, Low Pass",
    "Level, 100",
]

LONG = (
    "This is a deliberately long announcement, the kind a badly designed "
    "screen reader would insist on finishing while you are already three "
    "parameters further down the list."
)


def _wait_quiet(engine, timeout: float = 8.0) -> None:
    """Block until the engine stops making sound, or we give up on it."""
    deadline = time.monotonic() + timeout
    # Give the engine a moment to actually start before believing it is idle.
    time.sleep(0.12)
    while engine.is_speaking() and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.15)


def _narrate(engine, text: str) -> None:
    """Speak a section heading and wait for it to finish before demonstrating."""
    engine.speak(text)
    _wait_quiet(engine)


def audition_engine(app, engine_key: str) -> None:
    """Run the three demonstrations on one engine."""
    app.engine_key = engine_key
    engine = app.engine
    engine.set_rate(app.rate)

    print(f"\n--- {engine.name} at {app.rate} wpm ---", flush=True)
    print(f"    {engine.routing_note}", flush=True)

    _narrate(engine, f"{engine.name}, {app.rate} words per minute.")

    # 1 ------------------------------------------------------------------
    _narrate(engine, "One. Ordinary navigation.")
    for text in NAV:
        engine.speak(text)
        _wait_quiet(engine)
        time.sleep(0.25)

    # 2 ------------------------------------------------------------------
    _narrate(engine, "Two. Holding the down arrow.")
    latencies = []
    t_start = time.perf_counter()
    for value in range(64, 76):
        engine.speak(str(value))
        time.sleep(HELD_KEY_INTERVAL)
        ms = app.speech_bus.last_latency_ms
        if ms is not None and engine_key == "espeak":
            latencies.append(ms)
    burst = time.perf_counter() - t_start
    _wait_quiet(engine)

    print(f"    12 announcements dispatched in {burst:.2f}s", flush=True)
    if latencies:
        print(
            f"    time to first audio: min {min(latencies):.1f} ms, "
            f"max {max(latencies):.1f} ms",
            flush=True,
        )
    else:
        # `say` plays through CoreAudio directly, so we never see its samples
        # and cannot time them from here. Worth stating rather than omitting.
        print("    time to first audio: not measurable for this engine", flush=True)

    time.sleep(0.4)

    # 3 ------------------------------------------------------------------
    _narrate(engine, "Three. Interrupting a long sentence.")
    engine.speak(LONG)
    time.sleep(1.2)
    buffered = app.speech_bus.pending()
    engine.speak("Sixty five.")
    if engine_key == "espeak":
        print(
            f"    discarded {buffered} frames "
            f"({buffered / app.speech_bus.samplerate:.2f}s) of stale speech",
            flush=True,
        )
    _wait_quiet(engine)
    time.sleep(0.5)


def run_audition(app) -> None:
    """
    Play the whole audition on every available engine.

    Engine order is deliberate: espeak-ng first, so the responsive one sets the
    reference and the slower one is heard against it rather than the other way
    round. Hearing them in the opposite order makes `say` sound acceptable.
    """
    order = [k for k in ("espeak", "say") if k in app.engines]
    original = app.engine_key

    print("\n=== Audition — listen, no keys needed ===", flush=True)
    for i, key in enumerate(order):
        audition_engine(app, key)
        if i + 1 < len(order):
            time.sleep(0.8)

    app.engine_key = original
    engine = app.engine
    engine.speak("End of audition.")
    _wait_quiet(engine)
    print("\n=== End of audition ===\n", flush=True)
