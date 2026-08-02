# SPDX-License-Identifier: Apache-2.0
"""
Layer 2 — audio output routing.

Why this layer exists at all
----------------------------
On stage, speech goes to in-ear monitors and must never reach the house PA.
A speech implementation that can only talk out of the main outputs is useless
in performance, and that single mistake would be enough to kill adoption of a
real product. So device selection is a first-class feature here, not a setting
buried three menus deep.

Three things in this file are load-bearing:

**Tracks, not a queue.** A sink carries several independent tracks — `speech`
and `earcon` — which are *summed* in the audio callback. If they shared one
queue, an earcon would have to finish before the speech behind it could start,
and the spec is explicit that earcons must never delay the speech that follows.
Mixing also means interruption can throw away speech without touching a tone
that is still sounding.

**Buses, so speech and earcons route independently.** Each is a named group of
sinks, and a group can hold more than one device. Speech to your in-ears and
the earcons somewhere else is a real request; so is the same signal to two
places at once.

**Stereo throughout.** Earcons carry information in their stereo position, so
the path from synthesis to device has to preserve it. Speech is mono and gets
duplicated.

Two engines, two routing stories — and the difference is the point
------------------------------------------------------------------
espeak-ng writes raw PCM to stdout, so we own the samples and can play them
anywhere. macOS `say` insists on owning its own audio and is routed with its
own `-a` flag instead. `resolve_say_device()` bridges the two ID spaces by
name. Note that `say` cannot reach every device CoreAudio exposes — on this
machine it cannot see the StudioLive at all.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

SPEECH = "speech"
EARCON = "earcon"
#: The instrument playing. Kept as its own track so it is structurally
#: impossible for speech or an earcon to delay a note — interruption
#: clears the speech track and cannot touch this one.
NOTE = "note"

TRACKS = (SPEECH, EARCON, NOTE)


@dataclass(frozen=True)
class OutputDevice:
    """One selectable output, as presented to the user."""

    index: int          # sounddevice / PortAudio index
    name: str
    channels: int
    samplerate: float

    def describe(self) -> str:
        """Spoken and printed form. No columns, no alignment — this is read aloud."""
        return f"{self.index}, {self.name}, {self.channels} channels"


def list_output_devices() -> list[OutputDevice]:
    out: list[OutputDevice] = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            out.append(OutputDevice(i, str(d["name"]),
                                    int(d["max_output_channels"]),
                                    float(d["default_samplerate"])))
    return out


def default_output_device() -> OutputDevice | None:
    try:
        idx = sd.default.device[1]
        for dev in list_output_devices():
            if dev.index == idx:
                return dev
    except Exception:
        pass
    devices = list_output_devices()
    return devices[0] if devices else None


def find_device(spec: str) -> OutputDevice | None:
    """
    Resolve a device by name, falling back to a numeric index.

    Name first, deliberately. PortAudio indices are positional and **shift when
    devices appear or disappear** — during one session here, index 5 meant
    three different devices over twenty minutes with no hardware change. A
    saved index therefore points somewhere else after a reboot, and speech
    silently comes out of the wrong output. On stage that means monitoring goes
    to the house. Real hardware should persist the name for the same reason.
    """
    devices = list_output_devices()
    spec = spec.strip()
    lowered = spec.lower()
    for d in devices:
        if d.name.lower() == lowered:
            return d
    matches = [d for d in devices if lowered in d.name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None
    if spec.isdigit():
        return next((d for d in devices if d.index == int(spec)), None)
    return None


def resolve_say_device(name: str) -> str | None:
    """Map a sounddevice device *name* to the numeric ID `say -a` expects."""
    try:
        proc = subprocess.run(["say", "-a", "?"], capture_output=True,
                              text=True, timeout=5)
    except Exception:
        return None
    for line in proc.stdout.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*\S)\s*$", line)
        if m and m.group(2).strip() == name.strip():
            return m.group(1)
    return None


def resample_linear(samples: np.ndarray, src_rate: float, dst_rate: float) -> np.ndarray:
    """
    Linear resample. Handles mono (N,) and stereo (N,2).

    Linear interpolation is not hi-fi, but this is speech and short tones on a
    monitor feed, and the alternative is a dependency. A typical announcement
    costs a few hundred microseconds — far below anything audible as delay.
    """
    if src_rate == dst_rate or samples.size == 0:
        return samples
    n_in = samples.shape[0]
    n_out = int(round(n_in * (dst_rate / src_rate)))
    if n_out <= 0:
        return np.zeros((0,) + samples.shape[1:], dtype=np.float32)
    x_out = np.linspace(0.0, n_in - 1, n_out, dtype=np.float64)
    x_in = np.arange(n_in)
    if samples.ndim == 1:
        return np.interp(x_out, x_in, samples).astype(np.float32)
    cols = [np.interp(x_out, x_in, samples[:, c]) for c in range(samples.shape[1])]
    return np.stack(cols, axis=1).astype(np.float32)


def channel_options(device: OutputDevice, stereo: bool = True) -> list[str]:
    """
    Selectable outputs on a device, as spoken labels.

    Stereo gives pairs — "1-2", "3-4". Mono gives single outputs — "1", "2",
    "3". Mono is not a lesser option: on a stage box or a crowded patchbay
    there may be exactly one spare send, and a feature that insists on two
    channels is a feature that cannot be used that night.

    One-based, because that is what is printed on the back of every interface
    ever made. Nobody patches "output 0".
    """
    if stereo:
        return [f"{i + 1}-{i + 2}" for i in range(0, device.channels - 1, 2)]
    return [str(i + 1) for i in range(device.channels)]


def channels_from_label(label: str) -> tuple[int, ...]:
    """"3-4" -> (2, 3). "3" -> (2,). Zero-based, as the audio layer works."""
    try:
        parts = [int(x) - 1 for x in label.split("-")]
        return tuple(parts[:2]) if len(parts) > 1 else (parts[0],)
    except Exception:
        return (0, 1)


def label_from_channels(chans: tuple[int, ...]) -> str:
    return "-".join(str(c + 1) for c in chans)


def as_stereo(samples: np.ndarray) -> np.ndarray:
    """Mono (N,) becomes (N,2) by duplication; stereo passes through."""
    if samples.ndim == 1:
        return np.repeat(samples[:, None], 2, axis=1)
    return samples


class AudioSink:
    """
    One open output stream, carrying several independently-cleared tracks.

    The stream stays open for the life of the program. Opening a CoreAudio
    device costs real time, and paying that on every utterance is exactly the
    latency this prototype exists to argue against.
    """

    def __init__(self, device: OutputDevice, blocksize: int = 256):
        self.device = device
        self.samplerate = float(device.samplerate)
        self.blocksize = blocksize

        # Which physical outputs each track lands on: two for stereo, one for
        # mono. This is the setting that makes "speech to my in-ears, never the
        # house" actually true — naming the *device* is not enough on an
        # interface with 64 outputs, where 1-2 is the main mix going to the PA.
        self._outs: dict[str, tuple[int, ...]] = {t: (0, 1) for t in TRACKS}
        self.channels = self._needed_channels()

        self._lock = threading.Lock()
        self._tracks: dict[str, deque[np.ndarray]] = {t: deque() for t in TRACKS}
        self._pending: dict[str, int] = {t: 0 for t in TRACKS}

        # Latency probe: `mark_start()` stamps the keypress, the callback
        # stamps the first sample handed to CoreAudio. The gap between them is
        # the number that decides whether this design is any good.
        self._t_start: float | None = None
        self._t_first: float | None = None

        self._stream = None
        self._open_stream()

    # ------------------------------------------------------------------ #
    def _needed_channels(self) -> int:
        """
        How many channels the stream must open to reach the highest pair in use.

        PortAudio has no portable way to open *only* channels 17 and 18, so we
        open 1..18 and write silence to the rest. Slightly wasteful, entirely
        portable — and portability matters here, because the target this design
        is arguing for is embedded Linux, not CoreAudio.
        """
        highest = max(max(chans) for chans in self._outs.values())
        return max(1, min(highest + 1, self.device.channels))

    def _open_stream(self) -> None:
        self.channels = self._needed_channels()
        self._stream = sd.OutputStream(
            device=self.device.index,
            channels=self.channels,
            samplerate=self.samplerate,
            dtype="float32",
            blocksize=self.blocksize,
            latency="low",
            callback=self._callback,
        )
        self._stream.start()

    def set_channels(self, track: str, chans: tuple[int, ...]) -> None:
        """
        Send a track to one output (mono) or two (stereo).

        Reopens the stream only when the new choice needs channels the current
        one does not have — moving speech from 1-2 to 3-4 on an already-wide
        stream costs nothing and interrupts nothing.
        """
        limit = self.device.channels - 1
        if len(chans) >= 2:
            # Clamp the PAIR, not each index on its own. Clamping independently
            # turns 17-18 on a stereo device into (1, 1) — both sides landing
            # on the right speaker, silently mono AND hard-panned.
            left = max(0, min(chans[0], max(0, self.device.channels - 2)))
            chans = (left, min(left + 1, limit))
        else:
            chans = (max(0, min(chans[0], limit)),)
        with self._lock:
            if self._outs.get(track) == chans:
                return
            self._outs[track] = chans
            grow = self._needed_channels() > self.channels
        if grow:
            # Stop the old stream first. Bound-checking in the callback already
            # makes an overlap harmless, but not producing the overlap at all
            # is better than surviving it.
            old = self._stream
            try:
                old.stop()
            except Exception:
                pass
            self._open_stream()
            try:
                old.close()
            except Exception:
                pass

    def channels_for(self, track: str) -> tuple[int, ...]:
        return self._outs[track]

    # ------------------------------------------------------------------ #
    def _drain(self, track: str, frames: int) -> np.ndarray:
        """Pull up to `frames` stereo frames off one track. Caller holds the lock."""
        buf = np.zeros((frames, 2), dtype=np.float32)
        q = self._tracks[track]
        filled = 0
        while filled < frames and q:
            chunk = q[0]
            take = min(len(chunk), frames - filled)
            buf[filled:filled + take] = chunk[:take]
            filled += take
            if take == len(chunk):
                q.popleft()
            else:
                q[0] = chunk[take:]
            self._pending[track] -= take
        return buf

    def _callback(self, outdata, frames, time_info, status):
        outdata.fill(0.0)
        # Bound against the buffer we were actually handed, NOT self.channels.
        # During a stream reopen the two disagree for a moment, and the old
        # stream's callback can fire with a pair index the old buffer is too
        # narrow to hold. PortAudio swallows the exception, so the symptom is a
        # dropout rather than a crash — the worst kind of bug to chase.
        width = outdata.shape[1]
        with self._lock:
            if self._tracks[SPEECH] and self._t_first is None and self._t_start is not None:
                self._t_first = time.perf_counter()
            # Each track is ADDED into its own pair, not queued behind the
            # other. An earcon and the announcement it introduces overlap by
            # design; and when the two tracks are on different pairs they never
            # meet at all, which is the point of separate outputs.
            for track in TRACKS:
                buf = self._drain(track, frames)
                chans = self._outs[track]
                if len(chans) == 1 or width == 1:
                    # Mono fold-down: average, not sum. Summing two correlated
                    # channels adds 6 dB and clips the loud parts of speech,
                    # which sounds like a broken voice rather than a level.
                    target = chans[0] if chans[0] < width else 0
                    outdata[:, target] += buf.mean(axis=1)
                    continue
                left, right = chans
                if left < width:
                    outdata[:, left] += buf[:, 0]
                if right < width:
                    outdata[:, right] += buf[:, 1]
        np.clip(outdata, -1.0, 1.0, out=outdata)

    # ------------------------------------------------------------------ #
    def write(self, track: str, samples: np.ndarray, src_rate: float | None = None) -> None:
        """Queue samples on a track. Mono or stereo; resampled if needed."""
        if samples.size == 0:
            return
        if src_rate is not None and src_rate != self.samplerate:
            samples = resample_linear(samples, src_rate, self.samplerate)
        stereo = np.ascontiguousarray(as_stereo(samples), dtype=np.float32)
        with self._lock:
            self._tracks[track].append(stereo)
            self._pending[track] += len(stereo)

    def clear(self, track: str | None = None) -> None:
        """
        Drop everything not yet played on a track. This IS interruption.

        Clearing `speech` deliberately leaves a sounding earcon alone: the tone
        is already telling the truth about the new state.
        """
        with self._lock:
            for name in ([track] if track else list(self._tracks)):
                self._tracks[name].clear()
                self._pending[name] = 0

    def pending(self, track: str = SPEECH) -> int:
        with self._lock:
            return self._pending[track]

    def mark_start(self) -> None:
        with self._lock:
            self._t_start = time.perf_counter()
            self._t_first = None

    @property
    def last_latency_ms(self) -> float | None:
        with self._lock:
            if self._t_start is None or self._t_first is None:
                return None
            return (self._t_first - self._t_start) * 1000.0

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


class Bus:
    """
    A named destination that can span several devices.

    Speech and earcons each own one. Both can point at the same device (the
    ordinary case, where they share a sink), at different devices, or at
    several at once — speech into in-ears *and* a desk monitor, say.
    """

    def __init__(self, track: str, sinks: list[AudioSink], gain: float = 1.0):
        self.track = track
        self.sinks = sinks
        #: Level for this destination, 0.0 to 1.0. Speech and earcons carry
        #: their own, because the right balance is personal and situational:
        #: on stage you may want the tones barely there under the band, while
        #: learning a menu you may want them level with the voice.
        self.gain = gain

    @property
    def primary(self) -> AudioSink | None:
        return self.sinks[0] if self.sinks else None

    @property
    def samplerate(self) -> float:
        return self.primary.samplerate if self.primary else 48000.0

    @property
    def device_names(self) -> list[str]:
        return [s.device.name for s in self.sinks]

    def write(self, samples: np.ndarray, src_rate: float | None = None) -> None:
        if self.gain <= 0.0:
            return          # muted: do not even queue it
        if self.gain != 1.0:
            samples = samples * np.float32(self.gain)
        for sink in self.sinks:
            sink.write(self.track, samples, src_rate)

    def clear(self) -> None:
        for sink in self.sinks:
            sink.clear(self.track)

    def mark_start(self) -> None:
        for sink in self.sinks:
            sink.mark_start()

    def pending(self) -> int:
        return max((s.pending(self.track) for s in self.sinks), default=0)

    @property
    def last_latency_ms(self) -> float | None:
        p = self.primary
        return p.last_latency_ms if p else None


class Router:
    """
    Owns every open sink, one per device, and hands out buses.

    Sinks are shared: pointing speech and earcons at the same device opens that
    device once. Devices with nothing routed to them are closed, so a stray
    stream is never left running on an interface you have stopped using.
    """

    def __init__(self):
        self._sinks: dict[int, AudioSink] = {}
        self._assign: dict[str, list[int]] = {t: [] for t in TRACKS}
        # Gains live on the router, not on the Bus objects, because a bus is
        # rebuilt every time it is asked for. Keeping level here means changing
        # output device does not silently reset your volume.
        self._gain: dict[str, float] = {t: 1.0 for t in TRACKS}
        # Which physical outputs each track uses, remembered here so the choice
        # survives a device change rather than silently snapping back to the
        # mains.
        self._outs: dict[str, tuple[int, ...]] = {t: (0, 1) for t in TRACKS}

    def _sink_for(self, device: OutputDevice) -> AudioSink:
        if device.index not in self._sinks:
            self._sinks[device.index] = AudioSink(device)
        return self._sinks[device.index]

    def set_targets(self, track: str, devices: list[OutputDevice],
                    chans: tuple[int, ...] | None = None) -> None:
        for d in devices:
            sink = self._sink_for(d)
            sink.set_channels(track, chans or self._outs.get(track, (0, 1)))
        if chans is not None:
            self._outs[track] = chans
        self._assign[track] = [d.index for d in devices]
        self._prune()

    def set_channels(self, track: str, chans: tuple[int, ...]) -> None:
        self._outs[track] = chans
        for idx in self._assign[track]:
            if idx in self._sinks:
                self._sinks[idx].set_channels(track, chans)
        # Ask a sink what it settled on, so a clamped request is reflected back
        # rather than the router believing something the hardware refused.
        for idx in self._assign[track]:
            if idx in self._sinks:
                self._outs[track] = self._sinks[idx].channels_for(track)
                break

    def channels_for(self, track: str) -> tuple[int, ...]:
        return self._outs.get(track, (0, 1))

    def _prune(self) -> None:
        live = {i for ids in self._assign.values() for i in ids}
        for idx in [i for i in self._sinks if i not in live]:
            self._sinks.pop(idx).close()

    def bus(self, track: str) -> Bus:
        return Bus(track,
                   [self._sinks[i] for i in self._assign[track] if i in self._sinks],
                   gain=self._gain[track])

    def set_gain(self, track: str, gain: float) -> None:
        self._gain[track] = max(0.0, min(1.0, float(gain)))

    def gain(self, track: str) -> float:
        return self._gain[track]

    def close(self) -> None:
        for sink in self._sinks.values():
            sink.close()
        self._sinks.clear()
