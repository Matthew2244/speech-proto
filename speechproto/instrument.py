# SPDX-License-Identifier: Apache-2.0
"""
Layer 4b — the instrument, as data.

Everything here is a plain declaration. There is no logic worth reading, which
is the intention: **this file is meant to be edited, not studied.** Change a
range, rename a parameter, add a section, and the navigation, the announcements
and the earcons all follow with no other edits.

The shape is roughly Korg Kronos: Program, Combi, Set List and Global, with
Program carrying an edit tree beneath it and Combi carrying sixteen timbres.
It is close enough to be recognisable to anyone who has used a workstation, and
it is deliberately not an attempt at firmware-exact fidelity — the point is the
*shape* of the state, not the contents.

One thing worth noticing while reading: the Accessibility submenu at the bottom
of Global is made of the same four parameter types as everything else. Speech
settings are not a special case bolted on the side. They are parameters, they
live in the tree, and they are navigated and announced by exactly the same code
as filter cutoff. On a real instrument that matters — it means the
accessibility settings are reachable by the same muscle memory as everything
else, including before speech is switched on.
"""

from __future__ import annotations

from .strings import available_languages
from .params import (
    Continuous,
    Node,
    Stepped,
    Text,
    Toggle,
    cents,
    note_name,
    pan_display,
    signed,
)

# --------------------------------------------------------------------- #
# Shared option lists
# --------------------------------------------------------------------- #

BANKS = ["INT-A", "INT-B", "INT-C", "INT-D", "INT-E", "INT-F", "USER-A", "USER-B"]

CATEGORIES = [
    "Keyboard", "Organ", "Bell/Mallet", "Strings", "Vocal/Airy", "Brass",
    "Woodwind/Reed", "Guitar/Plucked", "Bass", "Slow Synth", "Fast Synth",
    "Lead Synth", "Motion Synth", "Drums", "SFX",
]

WAVEFORMS = [
    "Stereo Grand", "Upright Piano", "Electric Piano", "Clav", "Drawbar Organ",
    "Nylon Guitar", "Fingered Bass", "Saw Wave", "Square Wave", "Triangle Wave",
    "Digital Bell", "Vocal Pad",
]

FILTER_TYPES = ["Low Pass 12", "Low Pass 24", "High Pass", "Band Pass", "Band Reject"]

EFFECT_TYPES = [
    "Off", "Stereo Compressor", "Stereo Limiter", "Overdrive/Hi-Gain",
    "Stereo Chorus", "Stereo Flanger", "Stereo Phaser", "Stereo Delay",
    "Reverb Room", "Reverb Hall",
]

PROGRAMS = [
    "Full Grand", "Berlin D Piano", "Suitcase EP", "Tine EP Bright",
    "Jazz Organ 1", "Rock Organ", "Warm Strings", "Solo Cello",
    "Big Band Brass", "Muted Trumpet", "Fretless Bass", "Upright Bass",
    "Analog Lead", "Wide Pad", "Bell Motion", "Studio Kit",
]

VELOCITY_CURVES = [
    "1 — very light touch", "2", "3", "4 — normal", "5", "6",
    "7", "8", "9 — very heavy touch",
]

VERBOSITY_LEVELS = ["Terse", "Normal", "Verbose"]

SPATIAL_MODES = ["Mono", "Stereo", "Binaural"]

#: How many physical outputs a track uses. Mono is not a lesser option:
#: on a stage box or a crowded patchbay there may be exactly one spare
#: send, and a feature needing two channels is one you cannot use that night.
OUTPUT_WIDTHS = ["Stereo", "Mono"]

#: Earcon flavours. Timbre only — the meaning of each sound is identical
#: across every pack, so switching never costs you what you have learned.
EARCON_PACKS = ["Sine", "Marimba", "Glass", "Pulse", "Air",
                "Woodblock", "Vintage FM", "Analog"]


# --------------------------------------------------------------------- #
# Program mode
# --------------------------------------------------------------------- #

def _oscillator() -> Node:
    return Node("Oscillator", [
        Stepped("Waveform", WAVEFORMS, index=0),
        Continuous("Octave", 0, -2, 2, unit="", formatter=signed),
        Continuous("Level", 100, 0, 127),
        Continuous("Pan", 64, 0, 127, formatter=pan_display, role="pan"),
    ])


def _filter() -> Node:
    return Node("Filter", [
        Stepped("Type", FILTER_TYPES, index=1),
        Continuous("Cutoff", 64, 0, 127),
        Continuous("Resonance", 32, 0, 127),
        Continuous("EG Intensity", 12, -99, 99, formatter=signed),
    ])


def _amp() -> Node:
    return Node("Amp", [
        Continuous("Level", 110, 0, 127),
        Continuous("Pan", 64, 0, 127, formatter=pan_display, role="pan"),
        Node("Amp EG", [
            Continuous("Attack", 0, 0, 99),
            Continuous("Decay", 43, 0, 99),
            Continuous("Sustain", 90, 0, 99),
            Continuous("Release", 25, 0, 99),
        ]),
    ])


def _insert_effects() -> Node:
    """
    Three insert slots. Each carries a type and its own two or three controls.

    The controls differ per slot rather than being generic, because that is
    what a real effects section looks like and because it gives the
    announcement builder genuinely varied material — a compressor's Attack in
    milliseconds and a reverb's Wet/Dry percentage should not sound the same.
    """
    return Node("Insert Effects", [
        Node("IFX 1", [
            Stepped("Type", EFFECT_TYPES, index=1),          # Stereo Compressor
            Continuous("Sensitivity", 42, 1, 127),
            Continuous("Attack", 8, 1, 100, unit="milliseconds"),
            Continuous("Output Level", 64, 0, 127),
        ]),
        Node("IFX 2", [
            Stepped("Type", EFFECT_TYPES, index=4),          # Stereo Chorus
            Continuous("Depth", 28, 0, 100),
            Continuous("Speed", 35, 1, 200, unit="hundredths of a hertz"),
            Continuous("Wet Dry", 30, 0, 100, unit="percent wet"),
        ]),
        Node("IFX 3", [
            Stepped("Type", EFFECT_TYPES, index=9),          # Reverb Hall
            Continuous("Reverb Time", 21, 1, 100, unit="tenths of a second"),
            Continuous("Pre Delay", 24, 0, 200, unit="milliseconds"),
            Continuous("Wet Dry", 35, 0, 100, unit="percent wet"),
        ]),
    ])


def program_mode() -> Node:
    return Node("Program", [
        Text("Name", "Full Grand"),
        Stepped("Bank", BANKS, index=0),
        Stepped("Category", CATEGORIES, index=0),
        _oscillator(),
        _filter(),
        _amp(),
        _insert_effects(),
    ])


# --------------------------------------------------------------------- #
# Combi mode — sixteen timbres
# --------------------------------------------------------------------- #

# Defaults per timbre: (program index, volume, pan, channel, low, high, mute)
# Timbres 1-4 are a realistic split-and-layer; the rest are switched off, the
# way a working combi usually is.
_TIMBRE_DEFAULTS = [
    (0, 110, 64, 1, 36, 108, False),   # Full Grand, full range
    (13, 72, 54, 1, 60, 108, False),   # Wide Pad layered above middle C
    (10, 100, 74, 2, 24, 59, False),   # Fretless Bass in the left hand
    (4, 88, 64, 3, 36, 108, True),     # Jazz Organ, muted, ready to bring in
]


def _timbre(number: int) -> Node:
    if number - 1 < len(_TIMBRE_DEFAULTS):
        prog, vol, pan, chan, low, high, mute = _TIMBRE_DEFAULTS[number - 1]
    else:
        prog, vol, pan, chan, low, high, mute = (0, 0, 64, number, 0, 127, True)

    return Node(f"Timbre {number}", [
        Stepped("Program", PROGRAMS, index=prog),
        Continuous("Volume", vol, 0, 127),
        Continuous("Pan", pan, 0, 127, formatter=pan_display, role="pan"),
        Continuous("MIDI Channel", chan, 1, 16),
        Continuous("Key Low", low, 0, 127, formatter=note_name),
        Continuous("Key High", high, 0, 127, formatter=note_name),
        Continuous("Velocity Low", 1, 1, 127),
        Continuous("Velocity High", 127, 1, 127),
        Toggle("Mute", mute),
        Toggle("Solo", False),
    ])


def combi_mode() -> Node:
    return Node("Combi", [
        Text("Name", "Piano Pad Split"),
        Stepped("Bank", BANKS, index=0),
        Stepped("Category", CATEGORIES, index=0),
        Node("Timbres", [_timbre(n) for n in range(1, 17)]),
    ])


# --------------------------------------------------------------------- #
# Set List
# --------------------------------------------------------------------- #

_SONGS = [
    ("Opener", "Full Grand", "Straight in, no count."),
    ("Second Line", "Jazz Organ 1", "Watch for the tempo push in bar 9."),
    ("Ballad", "Suitcase EP", "Rubato intro, band enters on the turnaround."),
    ("Up Tempo Swing", "Full Grand", "Trading fours after the head."),
    ("Feature", "Berlin D Piano", "Solo piano. House lights down."),
    ("Latin", "Piano Pad Split", "Bass in the left hand, pad above middle C."),
    ("Closer", "Big Band Brass", "Full ensemble, big finish."),
    ("Encore", "Warm Strings", "Only if they ask twice."),
]


def set_list_mode() -> Node:
    slots = []
    for i, (title, sound, comment) in enumerate(_SONGS, start=1):
        slots.append(Node(f"Slot {i}", [
            Text("Title", title),
            Stepped("Sound", PROGRAMS + ["Piano Pad Split"],
                    index=(PROGRAMS + ["Piano Pad Split"]).index(sound)),
            Text("Comment", comment),
        ]))
    return Node("Set List", [
        Text("Name", "Friday Trio"),
        Node("Slots", slots),
    ])


# --------------------------------------------------------------------- #
# Global, including Accessibility
# --------------------------------------------------------------------- #

def accessibility_menu(device_names: list[str] | None = None,
                       voices: list[str] | None = None,
                       pairs: list[str] | None = None,
                       languages: list[str] | None = None) -> Node:
    """
    The speech settings, as ordinary parameters in the ordinary tree.

    Output device is a `Stepped` filled from the real devices found on the
    machine, so changing it here actually moves the speech. That is the whole
    routing argument made operable from inside the instrument rather than from
    a command-line flag.

    Speech and earcons switch off **independently**, and that is a design
    statement rather than a convenience. They are two separate consumers of the
    same state, so any combination has to work: speech only, earcons only,
    both, or neither. "Neither" is not a broken configuration — it is what a
    Braille-only user runs, with the announcement text going to a display
    instead of a voice.

    Note the trap this creates: switch speech off with no earcons and no
    Braille and you are stranded, unable to hear your way back to the setting
    that turned it off. The interaction layer answers that with a dedicated
    "where am I" key that speaks regardless of this toggle — see step 3.
    """
    devices = device_names or ["System Default"]
    return Node("Accessibility", [
        Stepped("Language", languages or available_languages(), index=0),
        Toggle("Speech", True),
        Stepped("Verbosity", VERBOSITY_LEVELS, index=1),            # Normal
        Continuous("Speech Rate", 300, 80, 450, step=10, unit="words per minute"),
        Continuous("Speech Volume", 85, 0, 100, step=5, unit="percent"),
        Stepped("Speech Engine", ["espeak-ng", "Piper", "macOS say"], index=0),
        Stepped("Voice", voices or ["Default"], index=0),
        Stepped("Speech Output", devices, index=0),
        Stepped("Speech Width", OUTPUT_WIDTHS, index=0),
        Stepped("Speech Channels", pairs or ["1-2"], index=0),
        Toggle("Earcons", True),
        Continuous("Earcon Volume", 60, 0, 100, step=5, unit="percent"),
        Stepped("Earcon Pack", EARCON_PACKS, index=0),
        Stepped("Earcon Space", SPATIAL_MODES, index=1),            # Stereo
        Stepped("Earcon Output", devices, index=0),
        Stepped("Earcon Width", OUTPUT_WIDTHS, index=0),
        Stepped("Earcon Channels", pairs or ["1-2"], index=0),
        Toggle("Learning Mode", False),
    ])


def global_mode(device_names: list[str] | None = None,
                voices: list[str] | None = None,
                pairs: list[str] | None = None,
                languages: list[str] | None = None) -> Node:
    return Node("Global", [
        Continuous("Master Tune", 0, -50, 50, formatter=cents),
        Continuous("Transpose", 0, -12, 12, unit="semitones", formatter=signed),
        Stepped("Velocity Curve", VELOCITY_CURVES, index=3),        # 4 — normal
        accessibility_menu(device_names, voices, pairs, languages),
    ])


# --------------------------------------------------------------------- #

def build_instrument(device_names: list[str] | None = None,
                     voices: list[str] | None = None,
                     pairs: list[str] | None = None,
                     languages: list[str] | None = None) -> list[Node]:
    """
    The four top-level modes, in the order Tab cycles them.

    Returns a list rather than a wrapping Node because these are *modes*, not
    siblings in a menu — you switch between them, you do not scroll through
    them. Modelling that distinction here keeps the interaction layer honest.
    """
    return [
        program_mode(),
        combi_mode(),
        set_list_mode(),
        global_mode(device_names, voices, pairs, languages),
    ]
