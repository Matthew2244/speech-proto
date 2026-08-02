#!/usr/bin/env python3
"""
Speech Interaction Prototype — steps 1 to 5.

Speech engine and routing, the parameter tree, navigation with focus tracking,
the three-level announcement builder, and earcons with spatial rendering.

Keys
----
  Up / Down ......... previous / next item at this level (does not wrap)
  Right ............. descend into a submenu, or raise a value
  Left .............. ascend out of a submenu, or lower a value
  Enter ............. descend
  Escape ............ ascend, even when a value is focused
  + / - ............. raise / lower a value
  Shift+Left/Right .. coarse, ten steps at a time
  PageDn / PageUp ... same parameter, next / previous submenu
                      (Timbre 3 Volume -> Timbre 4 Volume, one keystroke)
  Home / End ........ value to minimum / maximum; on a submenu, first / last item
  Tab / Shift+Tab ... next / previous mode
  v ................. cycle verbosity: Terse, Normal, Verbose
  s ................. cycle earcon space: Mono, Stereo, Binaural
  p ................. cycle earcon pack: Sine, Marimba, Glass, Pulse, Air
  w ................. where am I — always speaks, even with speech switched off
  b ................. toggle the simulated braille line
  Enter (on a name) . edit the text, character by character
  1 2 3 4 ........... run a long operation: save, load, backup, update
  x ................. cancel a running operation
  a ................. hands-free audition of the speech engines
  l ................. learning mode: names each sound until you know it
  k ................. drill: play the whole sound vocabulary
  m ................. metronome on/off — proves speech never delays a note
  ? ................. speak the key list
  Ctrl+Space ........ silence immediately, say nothing
  q ................. quit

The Accessibility submenu under Global is live. Speech and earcons have
**separate** output settings, and either can be switched off without the other.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from speechproto import audio_out, keys
from speechproto.activity import OPERATIONS, Activity
from speechproto.announce import Verbosity, braille_line, build_announcement
from speechproto.audio_out import EARCON, NOTE, SPEECH, OutputDevice, Router
from speechproto.audition import run_audition
from speechproto.confirm import PendingChange
from speechproto.earcons import PACK_NAMES, PACKS, Earcons, Spatial
from speechproto.instrument import SPATIAL_MODES, build_instrument
from speechproto.learning import Learning
from speechproto.metronome import Metronome
from speechproto.keys import Key, KeyReader
from speechproto.navigation import Change, Event, Navigator
from speechproto.params import Node
from speechproto.speech import available_engines, create_engine
from speechproto.strings import LANGUAGES, Strings
from speechproto.textentry import TextEditor
from speechproto import wizard as wiz

COARSE = 10  # Shift multiplier for value changes

#: Settings that do NOT take effect the moment you arrow onto them.
#:
#: Two different reasons, one behaviour. Output routing is *dangerous* — it can
#: take away the interface you need to undo it. Earcon pack and space are
#: merely *loud*: previewing each one as you scan past means hearing a
#: demonstration before you have even heard the name, which is backwards.
#:
#: In both cases the answer is the same: arrowing selects, Enter commits. You
#: hear what you are choosing before you hear it happen.
DEFERRED = ("Speech Output", "Speech Width", "Speech Channels",
            "Earcon Output", "Earcon Width", "Earcon Channels",
            "Earcon Pack", "Earcon Space")


class App:
    def __init__(self, device: OutputDevice, engine_key: str, rate: int):
        self.rate = rate
        self.strings = Strings("English")

        # One router owns every open device. Speech and earcons each get a bus,
        # and a bus can point at more than one device. Both start on the same
        # device, which is the ordinary case — the router opens it once.
        self.router = Router()
        self.router.set_targets(SPEECH, [device])
        self.router.set_targets(EARCON, [device])
        self.router.set_targets(NOTE, [device])
        self.speech_device = device
        self.earcon_device = device

        self.earcons = Earcons(self.router.bus(EARCON), Spatial.STEREO)
        # What spatial mode to return to when a mono output stops forcing our
        # hand. Set here, beside the earcons themselves, because _sync_settings()
        # runs later in this constructor and reads it.
        self._spatial_before_mono: Spatial | None = None

        self.engines = {}
        for key in available_engines():
            self.engines[key] = create_engine(
                key, self.router.bus(SPEECH), rate, device
            )
        if engine_key not in self.engines:
            engine_key = next(iter(self.engines))
        self.engine_key = engine_key

        self.device_names = [d.name for d in audio_out.list_output_devices()]
        self.nav = Navigator(build_instrument(
            self.device_names,
            self.engine.available_voices(),
            audio_out.channel_options(device, True),
        ))

        # Start the output settings on the device actually in use. A settings
        # screen that opens showing something other than the truth is worse
        # than one showing nothing: it invites you to "change" to the device you
        # are already on, and to trust it about everything else.
        self._sync_settings()

        self.speech_enabled = True
        self.verbosity = Verbosity.NORMAL
        self.show_braille = False
        self.activity = Activity(self)
        self.pending: PendingChange | None = None
        self.pending_warning: str = ""
        self.learning = Learning(self)
        self.metronome = Metronome(self)
        self.running = True

        # Started last, deliberately: a watchdog that runs while the object it
        # watches is still being built will read half of it.
        self._watchdog = threading.Thread(target=self._watch_devices, daemon=True)
        self._watchdog.start()

    @property
    def engine(self):
        return self.engines[self.engine_key]

    @property
    def speech_bus(self):
        return self.router.bus(SPEECH)

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #
    def announce(self, change: Change, force: bool = False, suffix: str = "") -> None:
        """
        Turn a Change into sound: an earcon, then words.

        Order matters and costs nothing. The earcon goes on its own mixing
        track, so it starts immediately and the speech behind it does not wait
        — you hear the tone and the first syllable almost together, which is
        what makes the tone feel like part of the announcement rather than a
        beep in front of it.
        """
        if change.after is not None:
            self.play_earcon(change)
        if self.show_braille and change.after is not None:
            print(f"[braille] {braille_line(change.after)}", flush=True)
        text = build_announcement(change, self.verbosity, self.strings)
        # Learning-mode wording joins the SAME utterance for the same reason a
        # hint does: a second call would cancel the first.
        note = self.learning.annotation(change)
        if note:
            suffix = f"{note}. {suffix}" if suffix else note
        # A hint has to be part of the SAME utterance. Speaking it separately
        # would interrupt the announcement it is attached to — every keypress
        # cancels speech in progress, including ours — so you would hear only
        # the hint and never the device name it refers to.
        if suffix:
            text = f"{text}. {suffix}" if text else suffix
        if text and (self.speech_enabled or force):
            self.engine.speak(text)

    def say(self, text: str, force: bool = False) -> None:
        if self.show_braille:
            print(f"[braille] {text}", flush=True)
        if text and (self.speech_enabled or force):
            self.engine.speak(text)

    def play_earcon(self, change: Change) -> None:
        """
        Pick the tone for a change.

        The vocabulary is deliberately small — value, limit, level, toggle, and
        the operation sounds. A mode switch gets **no** earcon at all, because
        speech names the mode unambiguously and an alphabet you cannot learn in
        an afternoon is one nobody learns at all.
        """
        ev, after = change.event, change.after
        if after is None:
            return

        if ev is Event.VALUE:
            if after.kind == "toggle":
                self.earcons.toggle(after.value.lower() in ("on", "true"))
            elif after.position is not None:
                self.earcons.value(
                    after.position, Earcons.value_pan(after.position, after.role)
                )
        elif ev is Event.VALUE_LIMIT:
            self.earcons.limit(after.at_max)
        elif ev is Event.LIST_EDGE:
            # Which end you hit is worth knowing, and it is all you get here:
            # speech stays silent because nothing changed.
            self.earcons.limit(after.index > 0)
        elif ev is Event.READ_ONLY:
            # A refusal, not a limit of range — but the same shape of answer:
            # you asked, nothing moved, here is why.
            self.earcons.limit(False)
        elif ev is Event.DESCENDED:
            self.earcons.level(True, depth=len(after.path))
        elif ev is Event.ASCENDED:
            self.earcons.level(False, depth=len(after.path))
            if after.is_node:
                self.earcons.submenu()
        elif ev in (Event.MOVED, Event.MODE) and after.is_node:
            # "There is more inside this one." Without it, the only way to find
            # out whether Right descends or changes a value is to press it and
            # see what happens — which is guessing, and guessing on a stage is
            # how you edit the wrong thing.
            self.earcons.submenu()

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #
    def _watch_devices(self) -> None:
        """
        Notice when a routed output disappears, and go somewhere audible.

        Powering off a mixer, unplugging an interface, a USB hub sleeping —
        all of these silently take the interface away from a blind player, and
        the symptom is identical to a crash: nothing happens when you press a
        key. There is no way to discover the cause from inside a silent
        instrument, which is precisely why the instrument has to notice for you.

        Falls back to the system default and says so **on the new output**,
        which is the same reasoning as the routing confirmation: the proof that
        you are somewhere audible is that you can hear it.
        """
        while getattr(self, "running", False):
            time.sleep(3.0)
            try:
                present = {d.name for d in audio_out.list_output_devices()}
                for track, device in ((SPEECH, self.speech_device),
                                      (EARCON, self.earcon_device)):
                    if device.name in present:
                        continue
                    fallback = audio_out.default_output_device()
                    if fallback is None or fallback.name not in present:
                        continue
                    lost = device.name
                    self.route(track, fallback)
                    what = "Speech" if track == SPEECH else "Earcons"
                    self.earcons.route_confirm()
                    self.say(f"{lost} disconnected. {what} now on {fallback.name}.",
                             force=True)
            except Exception:
                # A watchdog that can crash is not a watchdog.
                pass

    def _accessibility_node(self):
        for mode in self.nav.modes:
            if mode.name == "Global":
                return mode.find("Accessibility")
        return None

    def _reconcile_spatial(self) -> str:
        """
        Keep the spatial-audio setting honest about what the output can do.

        On a single output there is no stereo field, so Stereo and Binaural are
        not merely ineffective — they are **not choices**. Offering them anyway
        costs navigation time and teaches the user that this instrument's menus
        do not mean what they say.

        So the options list collapses to Mono rather than the setting being
        left to lie. The setting itself stays in place, at the same position,
        because a menu that changes length under you is its own problem.

        Returns a sentence to append to the announcement, or "".
        """
        acc = self._accessibility_node()
        param = acc.find("Earcon Space") if acc else None
        if param is None:
            return ""
        mono_out = len(self.router.channels_for(EARCON)) == 1

        if mono_out:
            note = ""
            if self.earcons.spatial is not Spatial.MONO:
                self._spatial_before_mono = self.earcons.spatial
                self.earcons.spatial = Spatial.MONO
                note = " Spatial set to Mono; a single output has no stereo field."
            param.options = ["Mono"]
            param.index = 0
            return note

        param.options = list(SPATIAL_MODES)
        if self._spatial_before_mono is not None:
            # Give back what they had before mono took it away.
            self.earcons.spatial = self._spatial_before_mono
            self._spatial_before_mono = None
        param.index = param.options.index(self.earcons.spatial.label)
        return ""

    def _sync_settings(self) -> None:
        """
        Put every deferred setting back to what is actually happening.

        A settings screen showing something other than the truth is worse than
        one showing nothing: it invites you to "change" to what you already
        have, and to trust it about everything else.
        """
        acc = self._accessibility_node()
        if acc is None:
            return
        # The channel menus belong to whichever device is selected, so they are
        # rebuilt rather than left offering pairs that do not exist.
        for param_name, device, track in (
                ("Speech Channels", self.speech_device, SPEECH),
                ("Earcon Channels", self.earcon_device, EARCON)):
            param = acc.find(param_name)
            if param is not None:
                stereo = len(self.router.channels_for(track)) > 1
                param.options = audio_out.channel_options(device, stereo) or ["1"]
        self._reconcile_spatial()
        for param_name in DEFERRED:
            param = acc.find(param_name)
            live = self._live_value(param_name)
            if param is not None and live in param.options:
                param.index = param.options.index(live)
            elif param is not None:
                param.index = 0

    def refresh_buses(self) -> None:
        """
        Hand out fresh Bus objects after a level or routing change.

        A Bus is a lightweight view over the router's state, so anything
        holding one needs a new copy when that state moves. Cheap, and it keeps
        gain in one place instead of scattered across the things that play.
        """
        eng = self.engines.get("espeak")
        if eng is not None:
            eng.set_bus(self.router.bus(SPEECH))
        self.earcons.bus = self.router.bus(EARCON)

    def set_language(self, name: str) -> None:
        """
        Change the words AND the pronunciation. Both halves, always.

        Changing one without the other is the classic half-done
        internationalisation: a Spanish voice reading English strings, or
        Spanish strings read by English rules. Either is worse than staying in
        English.
        """
        self.strings = Strings(name)
        esp = self.engines.get("espeak")
        if esp is not None and hasattr(esp, "set_voice_spec"):
            esp.set_voice_spec(self.strings.voice)

    def set_rate(self, wpm: int) -> None:
        self.rate = max(80, min(450, int(wpm)))
        for eng in self.engines.values():
            eng.set_rate(self.rate)

    def route(self, track: str, device: OutputDevice) -> None:
        """Point one bus at a device and hand the new bus to whoever needs it."""
        self.router.set_targets(track, [device])
        if track == SPEECH:
            self.speech_device = device
            self.refresh_buses()
            say = self.engines.get("say")
            if say is not None:
                say.set_output_device(device)
        else:
            self.earcon_device = device
            self.refresh_buses()
        self._sync_settings()

    # ------------------------------------------------------------------ #
    def apply_accessibility(self, change: Change) -> None:
        """
        Make the Accessibility submenu real.

        A settings screen you can hear but that does nothing is exactly the
        half-built accessibility this prototype argues against, so every one of
        these takes effect on the spot.
        """
        after = change.after
        if after is None or "Accessibility" not in after.path:
            return
        item = self.nav.focused()
        name = after.name

        if name == "Language":
            self.set_language(item.display_value)
        elif name == "Learning Mode":
            self.learning.enabled = bool(item.value)
            self.learning.reset()
        elif name == "Speech":
            # The announcement for this change has already been queued by the
            # time we get here, so switching speech off still tells you it
            # worked. Getting back is what the "where am I" key is for.
            self.speech_enabled = bool(item.value)
        elif name == "Earcons":
            self.earcons.enabled = bool(item.value)
        elif name == "Verbosity":
            self.verbosity = Verbosity.from_name(item.display_value)
        elif name == "Speech Rate":
            self.set_rate(int(item.value))
        elif name == "Speech Volume":
            self.router.set_gain(SPEECH, item.value / 100.0)
            self.refresh_buses()
        elif name == "Earcon Volume":
            self.router.set_gain(EARCON, item.value / 100.0)
            self.refresh_buses()
        elif name == "Voice":
            # Applied before the announcement is spoken, so arrowing through
            # the list previews each voice IN that voice. Reading a voice menu
            # aloud in a *different* voice tells you nothing about it.
            self.engine.set_voice(item.display_value)
        elif name == "Speech Engine":
            wanted = {"espeak-ng": "espeak", "Piper": "piper",
                      "macOS say": "say"}.get(item.display_value, "espeak")
            if (wanted == "say"
                    and audio_out.resolve_say_device(self.speech_device.name) is None):
                # `say` addresses devices through its own ID space, which does
                # not contain every CoreAudio output — the StudioLive is absent
                # here. Switching anyway would send speech to the system default
                # while the menu claimed otherwise, and you would find out
                # during a show. Refuse, and say why.
                item.index = 0
                self.engine.set_rate(self.rate)
                self.pending_warning = (
                    f"macOS say cannot reach {self.speech_device.name}. "
                    f"Staying on {self.engine.name}"
                )
                return
            if wanted in self.engines and wanted != self.engine_key:
                self.engine.stop()
                self.engine_key = wanted
                self.engine.set_rate(self.rate)
                # The voice menu belongs to the engine, so it is rebuilt in
                # place rather than left listing voices that no longer exist.
                acc = self._accessibility_node()
                voice_param = acc.find("Voice") if acc else None
                if voice_param is not None:
                    voice_param.options = self.engine.available_voices() or ["Default"]
                    voice_param.index = 0
        elif name in DEFERRED:
            # Deliberately inert until Enter — see DEFERRED above.
            pass


    # ------------------------------------------------------------------ #
    def handle(self, k: Key, reader=None) -> None:
        # Silence first, and it says nothing back. A silence key that announces
        # itself is not a silence key.
        if k.name == keys.SILENCE:
            self.engine.stop()
            return
        if k.name == keys.INTERRUPT or k.char == "q":
            self.running = False
            return

        # A live routing confirmation owns Enter and Escape until it resolves.
        # Nothing else should be reachable while the instrument may be about to
        # go silent on you.
        if self.pending is not None and self.pending.active:
            if k.name == keys.ENTER:
                self.pending.confirm()
                return
            if k.name == keys.ESCAPE:
                self.pending.revert()
                return

        nav = self.nav
        on_leaf = not isinstance(nav.focused(), Node)
        step = COARSE if k.shift else 1
        change = None

        if k.name == keys.DOWN:
            change = nav.move(1)
        elif k.name == keys.UP:
            change = nav.move(-1)
        elif k.name == keys.RIGHT:
            # Right does double duty, resolved by what is under the cursor:
            # a submenu is entered, a value is raised.
            change = nav.adjust(step) if on_leaf else nav.descend()
        elif k.name == keys.LEFT:
            change = nav.adjust(-step) if on_leaf else nav.ascend()
        elif k.name == keys.ENTER:
            if self.apply_deferred():
                return
            focused = nav.focused()
            if not isinstance(focused, Node) and focused.kind == "text" and reader:
                if TextEditor(self, focused).run(reader):
                    self._sync_settings()
                return
            change = nav.descend()
        elif k.name == keys.ESCAPE:
            change = nav.ascend()          # always ascends, even on a leaf
        elif k.name == keys.TAB:
            change = nav.cycle_mode(-1 if k.shift else 1)
        elif k.name == keys.PAGE_DOWN:
            change = nav.sibling_container(1)
        elif k.name == keys.PAGE_UP:
            change = nav.sibling_container(-1)
        elif k.name == keys.HOME:
            change = nav.value_to_minimum() if on_leaf else nav.to_first()
        elif k.name == keys.END:
            change = nav.value_to_maximum() if on_leaf else nav.to_last()
        elif k.char in ("+", "="):
            change = nav.adjust(step)
        elif k.char in ("-", "_"):
            change = nav.adjust(-step)
        elif k.char == "w":
            self.announce(nav.here(), force=True)   # always speaks
            return
        elif k.char == "v":
            self.verbosity = Verbosity(self.verbosity % 3 + 1)
            self.say(f"{self.verbosity.label}.", force=True)
            return
        elif k.char == "s":
            self.earcons.spatial = Spatial(self.earcons.spatial % 3 + 1)
            self.say(f"{self.earcons.spatial.label}.", force=True)
            self.demo_space()
            return
        elif k.char == "p":
            names = PACK_NAMES
            nxt = names[(names.index(self.earcons.pack.name) + 1) % len(names)]
            self.earcons.set_pack(nxt)
            self.say(f"{nxt}. {PACKS[nxt].blurb}", force=True)
            self.demo_pack()
            return
        elif k.char == "l":
            self.learning.enabled = not self.learning.enabled
            self.learning.reset()
            self._sync_toggle("Learning Mode", self.learning.enabled)
            self.say(f"Learning mode {'on' if self.learning.enabled else 'off'}.",
                     force=True)
            return
        elif k.char == "k":
            self.learning.drill()
            return
        elif k.char == "m":
            # The latency demonstration. Start it, then hammer the arrow keys:
            # the click must stay dead steady while speech is being cancelled
            # and restarted underneath it.
            if self.metronome.running:
                self.metronome.stop()
                time.sleep(0.15)
                self.metronome.print_report()
                self.say(self.metronome.report(), force=True)
            else:
                self.metronome.start()
                self.say("Metronome running. Move around, then press M again.",
                         force=True)
            return
        elif k.char == "b":
            self.show_braille = not self.show_braille
            self.say(f"Braille line {'on' if self.show_braille else 'off'}.", force=True)
            return
        elif k.char in OPERATIONS:
            kind, gerund, past, secs = OPERATIONS[k.char]
            if not self.activity.start(kind, gerund, past, secs):
                self.say("Already busy.", force=True)
            return
        elif k.char == "x":
            if self.activity.running:
                self.activity.cancel()
            return
        elif k.char == "a":
            run_audition(self)
            return
        elif k.char == "?":
            self.say(
                "Arrows navigate. Right enters or raises, left leaves or lowers. "
                "Escape always leaves. Page keys jump to the same parameter in the "
                "next submenu. Tab changes mode. V changes verbosity. "
                "S changes earcon space. W says where you are. "
                "Keys one to four run a long operation. "
                "Control Space silences. Q quits.",
                force=True,
            )
            return

        if change is None:
            return
        if change.event is Event.VALUE:
            self.apply_accessibility(change)

        # Output settings are inert until Enter, so say so — but only when the
        # selection actually differs from what is playing, and only as part of
        # the same utterance.
        warning, self.pending_warning = self.pending_warning, ""
        if warning:
            # A refusal must not first announce the value it refused. Speak the
            # reason alone, over the limit tone — this IS a limit, just one
            # imposed by the hardware rather than by a range.
            self.earcons.limit(False)
            self.say(warning, force=True)
        else:
            self.announce(change, suffix=self._apply_hint(change))

        # Walking away from an unapplied selection would leave the menu showing
        # a device that is not live. Put it back to the truth.
        before = change.before
        after = change.after
        if (before is not None and after is not None
                and before.name in DEFERRED and after.name != before.name):
            self._sync_settings()

    # ------------------------------------------------------------------ #
    def power_on(self) -> None:
        """
        Startup. You need to know the instrument is ready from across a stage,
        before you have touched it — so this is longer and louder than
        anything else the prototype plays.
        """
        self.earcons.power(True)
        snap = self.nav.snapshot()
        self.say(f"Ready. {snap.mode}, {snap.name}.")

    def power_off(self) -> None:
        """
        Shutdown, and it waits for itself to finish. A shutdown tone that gets
        cut off by the process exiting tells you nothing about whether the
        instrument actually shut down or simply froze.
        """
        self.activity.cancel()
        self.engine.stop()
        self.earcons.power(False)
        self.say("Shutting down.")
        deadline = time.monotonic() + 3.0
        while self.engine.is_speaking() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.25)

    def _live_value(self, name: str) -> str:
        """What a deferred setting is *actually* doing right now."""
        def chans(track):
            return audio_out.label_from_channels(self.router.channels_for(track))

        def width(track):
            return "Stereo" if len(self.router.channels_for(track)) > 1 else "Mono"

        return {
            "Speech Output": self.speech_device.name,
            "Speech Width": width(SPEECH),
            "Speech Channels": chans(SPEECH),
            "Earcon Output": self.earcon_device.name,
            "Earcon Width": width(EARCON),
            "Earcon Channels": chans(EARCON),
            "Earcon Pack": self.earcons.pack.name,
            "Earcon Space": self.earcons.spatial.label,
        }.get(name, "")

    def _apply_hint(self, change: Change) -> str:
        """"Press Enter to apply", but only when there is something to apply."""
        after = change.after
        if after is None or after.name not in DEFERRED:
            return ""
        if change.event not in (Event.VALUE, Event.MOVED, Event.DESCENDED):
            return ""
        return "Press Enter to apply" if after.value != self._live_value(after.name) else ""

    def apply_deferred(self) -> bool:
        """
        Commit whatever deferred setting is focused. Returns False if there is
        nothing staged, so Enter falls through to its normal meaning.
        """
        snap = self.nav.snapshot()
        if snap.name not in DEFERRED or snap.value == self._live_value(snap.name):
            return False

        # The two harmless ones: apply, then demonstrate. Name first, sound
        # second — the order that was wrong before.
        if snap.name == "Earcon Pack":
            self.earcons.set_pack(snap.value)
            self.say(f"{snap.value}. {PACKS[snap.value].blurb}", force=True)
            self.demo_pack()
            return True
        if snap.name in ("Speech Channels", "Earcon Channels",
                         "Speech Width", "Earcon Width"):
            track = SPEECH if snap.name.startswith("Speech") else EARCON
            what = "Speech" if track == SPEECH else "Earcons"

            if snap.name.endswith("Width"):
                # Narrowing to mono keeps the same starting output; widening
                # takes the pair that output belongs to. Either way you stay
                # roughly where you were rather than being thrown back to 1-2.
                first = self.router.channels_for(track)[0]
                want = (first,) if snap.value == "Mono" else (first - first % 2,
                                                              first - first % 2 + 1)
            else:
                want = audio_out.channels_from_label(snap.value)

            self.router.set_channels(track, want)
            self.refresh_buses()
            # Reconcile BEFORE the general resync, because the explanation is
            # generated by the *transition* and the resync would consume it.
            note = self._reconcile_spatial() if track == EARCON else ""
            self._sync_settings()
            live = audio_out.label_from_channels(self.router.channels_for(track))
            self.say(f"{what} on output {live}.{note}", force=True)
            self.earcons.route_confirm()
            return True
        if snap.name == "Earcon Space":
            self.earcons.spatial = Spatial.from_name(snap.value)
            self.say(f"{snap.value}.", force=True)
            self.demo_space()
            return True
        return self.arm_route()

    def arm_route(self) -> bool:
        """
        Stage the focused output change, apply it provisionally, and start the
        revert countdown. Returns False if there is nothing to change.
        """
        snap = self.nav.snapshot()
        if snap.name not in ("Speech Output", "Earcon Output"):
            return False
        track = SPEECH if snap.name == "Speech Output" else EARCON
        target = audio_out.find_device(snap.value)
        current = self.speech_device if track == SPEECH else self.earcon_device
        if target is None or target.index == current.index:
            return False

        what = "Speech" if track == SPEECH else "Earcons"
        previous = current
        self.pending = PendingChange(
            self,
            label=f"{what} now on {target.name}",
            apply_fn=lambda: self.route(track, target),
            revert_fn=lambda: self.route(track, previous),
            seconds=10.0,
            back_label=f"{what} back on {previous.name}",
        )
        self.pending.arm()
        return True

    def _sync_toggle(self, name: str, value: bool) -> None:
        """Keep a tree toggle in step with a setting changed by a shortcut key."""
        acc = self._accessibility_node()
        param = acc.find(name) if acc else None
        if param is not None:
            param.value = value

    def demo_space(self) -> None:
        """A left-to-right sweep: the fastest way to judge a spatial mode."""
        for pos in (0.0, 0.25, 0.5, 0.75, 1.0):
            self.earcons.value(pos, Earcons.value_pan(pos, "pan"))
            time.sleep(0.09)

    def demo_pack(self) -> None:
        """
        Play the current pack's signature phrase.

        The name of a sound tells you nothing about the sound, so changing
        pack plays a value sweep, a limit and a toggle — enough to judge it
        without having to go and find each one.
        """
        for part in self.earcons.signature():
            part()
            time.sleep(0.35)

    def close(self) -> None:
        self.running = False
        self.metronome.stop()
        for eng in self.engines.values():
            eng.close()
        self.router.close()


# ===================================================================== #
def apply_setup(app: App, data: dict) -> None:
    """
    Re-apply a saved setup. Anything missing or stale is skipped, not fatal.

    Devices are matched **by name**: an index saved last week points at a
    different device today, and silently sending speech somewhere else is the
    one failure this whole design is built to avoid.
    """
    if not data:
        return
    if data.get("language") in LANGUAGES:
        app.set_language(data["language"])
    if data.get("engine") in app.engines:
        app.engine_key = data["engine"]
    if data.get("voice"):
        app.engine.set_voice(data["voice"])
    if isinstance(data.get("rate"), int):
        app.set_rate(data["rate"])
    if data.get("verbosity"):
        app.verbosity = Verbosity.from_name(data["verbosity"])
    if isinstance(data.get("earcons"), bool):
        app.earcons.enabled = data["earcons"]
    if data.get("pack") in PACK_NAMES:
        app.earcons.set_pack(data["pack"])
    if data.get("space"):
        app.earcons.spatial = Spatial.from_name(data["space"])
    for key, track in (("speech_output", SPEECH), ("earcon_output", EARCON)):
        name = data.get(key)
        if name:
            dev = audio_out.find_device(name)
            if dev is not None:
                app.route(track, dev)
    app._sync_settings()


def main() -> int:
    ap = argparse.ArgumentParser(description="Speech Interaction Prototype.")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--device", default=None,
                    help="output device: name or part of a name (preferred), or an index")
    ap.add_argument("--engine", default=None, choices=["espeak", "piper", "say"])
    ap.add_argument("--rate", type=int, default=300, help="words per minute")
    ap.add_argument("--verbosity", default="normal", choices=["terse", "normal", "verbose"])
    ap.add_argument("--space", default="stereo", choices=["mono", "stereo", "binaural"])
    ap.add_argument("--pack", default="Sine", choices=PACK_NAMES)
    ap.add_argument("--braille", action="store_true",
                    help="also print each announcement as a line of text")
    ap.add_argument("--audition", action="store_true",
                    help="play the hands-free speech audition and exit")
    ap.add_argument("--wizard", action="store_true",
                    help="run first-run setup again")
    ap.add_argument("--no-wizard", action="store_true",
                    help="skip setup even on a first run")
    args = ap.parse_args()

    devices = audio_out.list_output_devices()
    if args.list_devices:
        for d in devices:
            print(f"{d.index:3d}  {d.name}  ({d.channels}ch)")
        return 0

    if not available_engines():
        print("No speech engine available (need espeak-ng or macOS say).", file=sys.stderr)
        return 1

    if args.device is not None:
        device = audio_out.find_device(args.device)
        if device is None:
            print(f"No single output device matching {args.device!r}. Try --list-devices.",
                  file=sys.stderr)
            return 1
    else:
        device = audio_out.default_output_device()
        if device is None:
            print("No output devices found.", file=sys.stderr)
            return 1

    engine_key = args.engine or next(
        (k for k in ("espeak", "piper", "say") if k in available_engines()), "espeak")
    app = App(device, engine_key, args.rate)
    app.verbosity = Verbosity.from_name(args.verbosity)
    app.earcons.spatial = Spatial.from_name(args.space)
    app.earcons.set_pack(args.pack)
    app.show_braille = args.braille

    if args.audition:
        print("Warming the say process pool...", flush=True)
        time.sleep(3.0)
        try:
            run_audition(app)
        finally:
            app.close()
        return 0

    print(f"Speech : [{device.index}] {device.name}")
    print(f"Earcons: [{device.index}] {device.name}  "
          f"({app.earcons.pack.name}, {app.earcons.spatial.label})")
    print(f"Engine : {app.engine.name} at {app.rate} wpm, {app.verbosity.label}")
    print("Press ? to hear the keys, q to quit.\n", flush=True)

    # Restore whatever setup remembered, then decide whether to run it again.
    # First run means "we have never been told what works" — not "the file is
    # missing", but in practice those are the same thing.
    first_run = not wiz.has_run_before()
    apply_setup(app, wiz.load_setup())

    try:
        with KeyReader() as reader:
            if args.wizard or (first_run and not args.no_wizard):
                wiz.Wizard(app, reader).run()
            app.power_on()
            while app.running:
                k = reader.read()
                if k is None:
                    continue
                app.handle(k, reader)
            app.power_off()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
