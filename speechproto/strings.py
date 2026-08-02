# SPDX-License-Identifier: Apache-2.0
"""
Layer 5d — the words, separated from the logic.

Why this file exists
--------------------
"Add Spanish" is usually taken to mean "ship a Spanish voice". It does not.
A Spanish voice reading English words gives you English mangled by Spanish
pronunciation rules — `Cutoff, sixty four, maximum` spoken as though it were
Spanish. That is worse than useless, and it is what shipping a voice without
localising the strings actually produces.

Real multilingual support is two separate things:

    1. **Pronunciation** — a voice for that language. espeak-ng ships over a
       hundred, so this part is nearly free.
    2. **The words themselves** — every framing word the announcement builder
       produces: maximum, minimum, item, of, submenu, parameters, and the
       prompts like "Press Enter to edit".
       This part is not free, and it is the part that gets skipped.

So the rule this file enforces is: **no literal user-facing string anywhere in
the announcement builder.** Every word comes from here, keyed by language. It
costs nothing to do on day one and is close to impossible to retrofit once a
hundred string literals are scattered through the logic.

Parameter names are a separate decision
----------------------------------------
`Cutoff`, `Resonance`, `IFX 1` stay as they are. Synth parameter names are
effectively international vocabulary among musicians, they are what is printed
on the panel, and translating them would leave a Spanish player unable to match
what they hear to any manual or forum post in existence. Only the *framing*
words translate. That is a deliberate line, and worth stating in DESIGN.md
because it is not the obvious choice.

On the translations below
--------------------------
**English is authoritative. The others need a native speaker before this is
shown to anyone.** They are here to prove the architecture works and to make the
point audible in a meeting — not because machine-chosen wording is good enough
to ship. Getting "of" or a plural wrong in a screen reader is the difference
between fluent and grating, and that judgement is not one to guess at.
"""

from __future__ import annotations

#: Every framing word the announcement builder can produce.
#: Adding a language means adding a block here and nothing else.
STRINGS: dict[str, dict[str, str]] = {
    "English": {
        "maximum": "maximum",
        "minimum": "minimum",
        "item": "item",
        "of": "of",
        "submenu": "submenu",
        "parameters": "parameters",
        "items": "items",
        "value": "value",
        "range": "range",
        "to": "to",
        "edit_hint": "Press Enter to edit",
        "on": "on",
        "off": "off",
        "ready": "Ready",
        "shutting_down": "Shutting down",
        "cancelled": "Cancelled",
        "half_way": "Half way",
        "percent": "percent",
        "press_enter_apply": "Press Enter to apply",
        "press_enter_keep": "Press Enter to keep",
        "kept": "Kept",
        "timed_out": "Timed out",
        "already_busy": "Already busy",
        "can_you_hear": "Can you hear this?",
    },
    # ---- Needs review by a native speaker before any demo ---------------- #
    "Español": {
        "maximum": "máximo",
        "minimum": "mínimo",
        "item": "elemento",
        "of": "de",
        "submenu": "submenú",
        "parameters": "parámetros",
        "items": "elementos",
        "value": "valor",
        "range": "rango",
        "to": "a",
        "edit_hint": "Pulsa Intro para editar",
        "on": "activado",
        "off": "desactivado",
        "ready": "Listo",
        "shutting_down": "Apagando",
        "cancelled": "Cancelado",
        "half_way": "A la mitad",
        "percent": "por ciento",
        "press_enter_apply": "Pulsa Intro para aplicar",
        "press_enter_keep": "Pulsa Intro para mantener",
        "kept": "Mantenido",
        "timed_out": "Tiempo agotado",
        "already_busy": "Ya está ocupado",
        "can_you_hear": "¿Puedes oír esto?",
    },
    "Français": {
        "maximum": "maximum",
        "minimum": "minimum",
        "item": "élément",
        "of": "sur",
        "submenu": "sous-menu",
        "parameters": "paramètres",
        "items": "éléments",
        "value": "valeur",
        "range": "plage",
        "to": "à",
        "edit_hint": "Appuyez sur Entrée pour modifier",
        "on": "activé",
        "off": "désactivé",
        "ready": "Prêt",
        "shutting_down": "Extinction",
        "cancelled": "Annulé",
        "half_way": "À la moitié",
        "percent": "pour cent",
        "press_enter_apply": "Appuyez sur Entrée pour appliquer",
        "press_enter_keep": "Appuyez sur Entrée pour conserver",
        "kept": "Conservé",
        "timed_out": "Délai dépassé",
        "already_busy": "Déjà occupé",
        "can_you_hear": "Entendez-vous ceci ?",
    },
    "Deutsch": {
        "maximum": "Maximum",
        "minimum": "Minimum",
        "item": "Element",
        "of": "von",
        "submenu": "Untermenü",
        "parameters": "Parameter",
        "items": "Elemente",
        "value": "Wert",
        "range": "Bereich",
        "to": "bis",
        "edit_hint": "Eingabetaste zum Bearbeiten",
        "on": "ein",
        "off": "aus",
        "ready": "Bereit",
        "shutting_down": "Herunterfahren",
        "cancelled": "Abgebrochen",
        "half_way": "Zur Hälfte",
        "percent": "Prozent",
        "press_enter_apply": "Eingabetaste zum Anwenden",
        "press_enter_keep": "Eingabetaste zum Behalten",
        "kept": "Behalten",
        "timed_out": "Zeit abgelaufen",
        "already_busy": "Bereits beschäftigt",
        "can_you_hear": "Können Sie das hören?",
    },
}

#: The espeak-ng base voice each language should speak with. Choosing a
#: language has to change **both** halves — the words and the pronunciation —
#: or you get one language's text read by another language's rules, which is
#: the exact failure this file exists to prevent.
LANGUAGE_VOICES: dict[str, str] = {
    "English": "en-us",
    "Español": "es",
    "Français": "fr-fr",
    "Deutsch": "de",
}

LANGUAGES = list(STRINGS)


class Strings:
    """
    Word lookup for one language, falling back to English for anything missing.

    Falling back rather than failing is deliberate: a half-translated language
    should degrade to a mixed announcement, not to a crash or an empty string.
    A blind user can work around one English word. They cannot work around
    silence.
    """

    def __init__(self, language: str = "English"):
        self.language = language if language in STRINGS else "English"
        self._table = STRINGS[self.language]
        self._fallback = STRINGS["English"]

    def __call__(self, key: str) -> str:
        return self._table.get(key) or self._fallback.get(key, key)

    @property
    def voice(self) -> str:
        return LANGUAGE_VOICES.get(self.language, "en-us")

    @property
    def needs_review(self) -> bool:
        """True for everything except English — see the module docstring."""
        return self.language != "English"
