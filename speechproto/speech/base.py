# SPDX-License-Identifier: Apache-2.0
"""
Layer 1 — the speech engine interface.

The contract is deliberately tiny. That is the architectural argument this
prototype is making: once a machine-readable description of what is on screen
exists, *speaking it is nearly free*, and the speaking part is replaceable.
A Braille display or a remote editor would implement a comparably small
interface against the same state.

Everything hard lives above this line, in the announcement logic. Everything
below it is plumbing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SpeechEngine(ABC):
    """
    A thing that can say a string, and — far more importantly — stop saying it.

    Implementations must honour one rule above all others:

        `speak()` must cancel whatever is currently being spoken, immediately,
        and must not block the caller waiting for audio.

    No queueing. No "finish the sentence first". If the user presses a key
    while the previous announcement is still playing, the previous announcement
    is wrong by definition — it describes a state they have already left.
    """

    #: Human-readable name, announced when engines are switched.
    name: str = "unnamed"

    @abstractmethod
    def speak(self, text: str) -> None:
        """Interrupt any speech in progress and begin speaking `text`."""

    @abstractmethod
    def stop(self) -> None:
        """Silence immediately. Says nothing in response."""

    @abstractmethod
    def is_speaking(self) -> bool:
        """True while audio is still being produced."""

    # -- rate ---------------------------------------------------------- #
    # Blind users run screen readers far faster than sighted people expect.
    # 400 wpm is ordinary; sighted demo audiences find it startling, which is
    # itself worth showing in the room.

    @property
    @abstractmethod
    def rate_wpm(self) -> int:
        """Current speech rate in words per minute."""

    @abstractmethod
    def set_rate(self, wpm: int) -> None:
        """Set speech rate. Takes effect on the next utterance."""

    # -- routing ------------------------------------------------------- #

    @abstractmethod
    def set_output_device(self, device) -> None:
        """
        Point this engine at an `OutputDevice`.

        Engines differ wildly in how well they can honour this, and the
        prototype does not paper over that — see each implementation.
        """

    @property
    def routing_note(self) -> str:
        """One short sentence on how (and how well) this engine can be routed."""
        return ""

    # -- voice --------------------------------------------------------- #
    #
    # Choice of voice matters more than it looks. A voice you find grating is
    # one you stop using, and "which voice" is deeply personal — so an
    # instrument that ships exactly one has effectively shipped none for some
    # of its users.

    def available_voices(self) -> list[str]:
        """Friendly voice names this engine can offer, in menu order."""
        return []

    def set_voice(self, name: str) -> None:
        """Select a voice by its friendly name. Takes effect next utterance."""

    @property
    def voice(self) -> str:
        return ""

    @abstractmethod
    def close(self) -> None:
        """Release processes, streams, threads."""

    @staticmethod
    def is_available() -> bool:
        """Whether this engine can run on this machine at all."""
        return False
