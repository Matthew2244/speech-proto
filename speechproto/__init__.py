# SPDX-License-Identifier: Apache-2.0
"""
Speech Interaction Prototype — a demonstration of what speech feedback should
feel like on a hardware music workstation.

Layers, deliberately separate:

    audio_out.py    device enumeration, routing, and the shared audio sink
    speech/         engine interface + espeak-ng and macOS say implementations
    keys.py         raw keyboard input

Still to come, in build order: the parameter tree (data), navigation and focus
tracking, the announcement builder, earcons, and the latency demonstration.
"""

__version__ = "0.1.0"
