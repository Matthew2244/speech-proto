# SPDX-License-Identifier: Apache-2.0
"""
Speech engines, and the one function that picks between them.

Adding a third engine means adding a file and one line here. That is the
architectural claim in miniature: the engine is a detail, and a manufacturer
who exposes structured state can swap the voice — or add a Braille display —
without touching the design work above.
"""

from __future__ import annotations

from .base import SpeechEngine
from .espeak import EspeakEngine
from .macsay import SayEngine
from .piper import PiperEngine

ENGINES = {
    "espeak": EspeakEngine,
    "piper": PiperEngine,
    "say": SayEngine,
}


def available_engines() -> list[str]:
    return [k for k, cls in ENGINES.items() if cls.is_available()]


def create_engine(key: str, bus, rate_wpm: int, device) -> SpeechEngine:
    """
    Build an engine by key.

    The two engines need different things — espeak-ng plays through our shared
    audio bus, `say` routes itself — so construction is not uniform. That
    asymmetry is real and is left visible rather than hidden behind a wrapper.
    """
    if key == "espeak":
        return EspeakEngine(bus, rate_wpm=rate_wpm)
    if key == "piper":
        return PiperEngine(bus, rate_wpm=rate_wpm)
    if key == "say":
        return SayEngine(rate_wpm=rate_wpm, device=device)
    raise ValueError(f"unknown engine: {key}")


__all__ = [
    "SpeechEngine",
    "EspeakEngine",
    "SayEngine",
    "PiperEngine",
    "ENGINES",
    "available_engines",
    "create_engine",
]
