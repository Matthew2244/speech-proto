# SPDX-License-Identifier: Apache-2.0
"""
Layer 5a — focus tracking.

This file answers one question: **what changed?**

That is the whole reason it exists as its own layer. A screen reader that
describes the current state on every keypress is the thing everyone builds
first and nobody keeps — it re-reads the submenu you never left, and the
parameter name you already knew, until you switch it off. Announcing what
*changed* requires knowing what was true a moment ago, so focus has to be a
tracked, snapshotted thing rather than a pointer you dereference on demand.

So navigation here always produces a `Change`: the focus before, the focus
after, and a tag saying what kind of movement it was. The announcement builder
in step 4 reads that triple and nothing else. It never touches the live tree.

`Focus` is a frozen snapshot with no references into the tree. That matters
because parameters are mutable — if `before` held a live reference to the
cutoff parameter, changing the value would retroactively change what "before"
said, and the diff would always come out empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .params import Node, Param


class Event(Enum):
    """What kind of change just happened. The builder branches on this."""

    MOVED = auto()        # up/down to a sibling
    DESCENDED = auto()    # into a submenu
    ASCENDED = auto()     # back out of one
    VALUE = auto()        # a parameter's value changed
    MODE = auto()         # switched Program/Combi/Set List/Global
    VALUE_LIMIT = auto()  # tried to push a value past its bound
    LIST_EDGE = auto()    # tried to move past the first or last sibling
    READ_ONLY = auto()    # arrows cannot change this; Enter opens an editor
    NONE = auto()         # nothing happened; say nothing


# Two kinds of "you cannot go further", kept apart because they deserve
# different answers:
#
#   VALUE_LIMIT  the value is pinned at 127 and you asked for more. Something
#                IS true and worth hearing — "127, maximum".
#
#   LIST_EDGE    you are on the first item and pressed Up. **Nothing changed.**
#                Under "announce what changed" the correct amount of speech is
#                none at all; the limit earcon carries it. Re-speaking the item
#                you never left is exactly the noise this design removes.
#
# Collapsing these into one event is the easy mistake, and it produces a screen
# reader that repeats itself at every list boundary.


@dataclass(frozen=True)
class Focus:
    """
    An immutable snapshot of where focus is and what is under it.

    Deliberately flat and free of object references: every field is a string,
    number or bool. It therefore serialises as-is, which is what lets the same
    snapshot feed speech, a Braille line, or a remote editor without any of
    them reaching into the model.
    """

    mode: str
    path: tuple[str, ...]        # container names, mode root first
    container: str               # immediate container's name
    index: int                   # position within that container, 0-based
    count: int                   # how many siblings, for "item 2 of 4"
    name: str                    # focused item's name
    kind: str                    # 'node' | 'continuous' | 'stepped' | 'toggle' | 'text'
    value: str                   # display value; '' for a node
    children: int                # child count if this is a node, else 0
    position: float | None       # 0..1 within range, for earcon pitch
    at_min: bool
    at_max: bool
    minimum: str = ""            # printable bounds, for verbose announcements
    maximum: str = ""
    #: What this node's children are, as a spoken word: "parameters" when they
    #: are all leaves, "items" when they are submenus. "Filter, 4 parameters"
    #: and "Timbres, 16 items" are both right; one word for both is not.
    child_label: str = ""
    #: The same word for the *container's* children — i.e. for the siblings
    #: this focus sits among, which is what `count` counts. Kept separate from
    #: `child_label` because they describe different levels and confusing them
    #: turns "Filter, 4 parameters" into "Filter, 4 items".
    container_label: str = ""
    #: Semantic tag from the parameter itself — "pan" means this value
    #: IS a stereo position, which changes where its earcon comes from.
    role: str = ""

    @property
    def is_node(self) -> bool:
        return self.kind == "node"

    def to_dict(self) -> dict:
        return dict(
            mode=self.mode, path=list(self.path), container=self.container,
            index=self.index, count=self.count, name=self.name, kind=self.kind,
            value=self.value, children=self.children, position=self.position,
            at_min=self.at_min, at_max=self.at_max,
        )


@dataclass(frozen=True)
class Change:
    """The before/after pair the announcement builder consumes."""

    event: Event
    before: Focus | None
    after: Focus | None
    #: True when the user asked to go further and the edge stopped them. Drives
    #: the limit earcon, and the word "maximum" at normal verbosity.
    hit_limit: bool = False


# --------------------------------------------------------------------- #
class Navigator:
    """
    Owns the cursor. Knows nothing about speech, earcons or verbosity.

    Every public method returns a `Change`, including when nothing happened —
    `Event.NONE` is a real answer, and it is how the interaction layer knows to
    stay silent rather than repeat itself.
    """

    def __init__(self, modes: list[Node]):
        if not modes:
            raise ValueError("Navigator needs at least one mode")
        self.modes = modes
        self.mode_index = 0
        # Focus is a path of indices from the mode root down. The last entry is
        # the focused item's index inside its container.
        self._path: list[int] = [0]
        # Each mode remembers where you were. Switching to Combi and back to
        # Program should land where you left, not at the top — a performer
        # flipping between modes mid-set is returning to work in progress, not
        # starting over.
        self._remembered: dict[int, list[int]] = {}
        # Where you were inside each submenu you have visited. Re-entering
        # Filter puts you back on Cutoff, not on Type.
        self._node_memory: dict[int, int] = {}
        # Where you were inside the *last* submenu of a given group. This is
        # what makes Timbre 4 open on Volume when you were on Volume in
        # Timbre 3 — the sixteen timbres share a shape, so position in one is
        # a good guess at intent in the next.
        self._sibling_hint: dict[int, int] = {}

    # -- resolving the path -------------------------------------------- #
    @property
    def mode(self) -> Node:
        return self.modes[self.mode_index]

    def _container(self) -> Node:
        """The Node whose children the cursor is sitting among."""
        node = self.mode
        for i in self._path[:-1]:
            node = node[i]
        return node

    def _item(self):
        container = self._container()
        idx = min(self._path[-1], len(container) - 1)
        return container[idx]

    def focused(self):
        """
        The live object under the cursor — a `Param` or a `Node`.

        Snapshots are what the announcement builder reads; this is for the
        interaction layer, which sometimes needs the real thing (to apply an
        Accessibility setting the moment it changes, for instance).
        """
        return self._item()

    def _container_path(self) -> tuple[str, ...]:
        names = [self.mode.name]
        node = self.mode
        for i in self._path[:-1]:
            node = node[i]
            names.append(node.name)
        return tuple(names)

    # -- snapshotting --------------------------------------------------- #
    def snapshot(self) -> Focus:
        container = self._container()
        item = self._item()
        is_node = isinstance(item, Node)

        minimum = maximum = ""
        if not is_node and item.kind == "continuous":
            # Bounds are rendered through the same formatter as the value, so
            # a verbose announcement says "range L64 to R63", not "range 0 to
            # 127" — the numbers the user never sees.
            minimum = item.format(item.minimum)
            maximum = item.format(item.maximum)

        def label_for(node: Node) -> str:
            if not len(node):
                return ""
            return "items" if any(isinstance(c, Node) for c in node) else "parameters"

        child_label = label_for(item) if is_node else ""
        container_label = label_for(container)

        return Focus(
            mode=self.mode.name,
            path=self._container_path(),
            container=container.name,
            index=self._path[-1],
            count=len(container),
            name=item.name,
            kind="node" if is_node else item.kind,
            value="" if is_node else item.display_value,
            children=len(item) if is_node else 0,
            position=None if is_node else item.position,
            at_min=False if is_node else item.at_minimum,
            at_max=False if is_node else item.at_maximum,
            minimum=minimum,
            maximum=maximum,
            child_label=child_label,
            container_label=container_label,
            role="" if is_node else getattr(item, "role", ""),
        )

    # -- moving --------------------------------------------------------- #
    def move(self, delta: int) -> Change:
        """
        Up or down among siblings. **Does not wrap.**

        Stopping at the edge is a deliberate choice: wrapping silently past the
        boundary of a sixteen-timbre list means you no longer know where you
        are, and finding that out by muting the wrong timbre is not an
        acceptable way to find out.
        """
        before = self.snapshot()
        container = self._container()
        target = self._path[-1] + delta
        if target < 0 or target >= len(container):
            return Change(Event.LIST_EDGE, before, before, hit_limit=True)
        self._path[-1] = target
        self._record_position()
        return Change(Event.MOVED, before, self.snapshot())

    def to_first(self) -> Change:
        before = self.snapshot()
        if self._path[-1] == 0:
            return Change(Event.LIST_EDGE, before, before, hit_limit=True)
        self._path[-1] = 0
        self._record_position()
        return Change(Event.MOVED, before, self.snapshot())

    def to_last(self) -> Change:
        before = self.snapshot()
        last = len(self._container()) - 1
        if self._path[-1] == last:
            return Change(Event.LIST_EDGE, before, before, hit_limit=True)
        self._path[-1] = last
        self._record_position()
        return Change(Event.MOVED, before, self.snapshot())

    # -- in and out ----------------------------------------------------- #
    def _node_at(self, depth: int) -> Node:
        """The node `depth` levels down the current path (0 = the mode root)."""
        node = self.mode
        for i in self._path[:depth]:
            node = node[i]
        return node

    def _record_position(self) -> None:
        """
        Remember where we are, for both kinds of return trip.

        Called after every successful move. Cheap, and it is what turns a
        16-timbre edit from a chore into something you can do at tempo.
        """
        container = self._container()
        self._node_memory[id(container)] = self._path[-1]
        if len(self._path) >= 2:
            group = self._node_at(len(self._path) - 2)
            self._sibling_hint[id(group)] = self._path[-1]

    def descend(self) -> Change:
        before = self.snapshot()
        container = self._container()
        item = self._item()
        if not isinstance(item, Node) or len(item) == 0:
            return Change(Event.NONE, before, before)

        # Where should the cursor land inside this submenu? In order of
        # preference: where you last were in *this* submenu; failing that,
        # where you last were in one of its siblings; failing that, the top.
        idx = self._node_memory.get(id(item))
        if idx is None:
            idx = self._sibling_hint.get(id(container), 0)
        self._path.append(max(0, min(idx, len(item) - 1)))
        self._record_position()
        return Change(Event.DESCENDED, before, self.snapshot())

    def sibling_container(self, delta: int) -> Change:
        """
        Jump to the next or previous sibling submenu, **staying on the same
        parameter**. Timbre 3's Volume to Timbre 4's Volume, in one keystroke.

        This is the move a musician actually makes: comparing one setting
        across sixteen timbres, or walking the same control through three
        effect slots. Doing it by hand is Escape, Down, Right, Down — four
        keystrokes and a lost place — repeated fifteen times.

        It is also the move that makes the container-change announcement rule
        earn its keep: the container changed and the parameter did not, so you
        hear `Timbre 4, 110` and nothing more.
        """
        before = self.snapshot()
        if len(self._path) < 2:
            # Nothing to page through — we are at the top level of a mode.
            return Change(Event.NONE, before, before)

        group = self._node_at(len(self._path) - 2)
        target = self._path[-2] + delta
        if target < 0 or target >= len(group):
            return Change(Event.LIST_EDGE, before, before, hit_limit=True)

        sibling = group[target]
        if not isinstance(sibling, Node) or len(sibling) == 0:
            return Change(Event.NONE, before, before)

        # Hold the parameter position across the jump; clamp if the sibling is
        # shorter, which is what makes this safe on ragged trees.
        keep = min(self._path[-1], len(sibling) - 1)
        self._path[-2] = target
        self._path[-1] = keep
        self._record_position()
        return Change(Event.MOVED, before, self.snapshot())

    def ascend(self) -> Change:
        before = self.snapshot()
        if len(self._path) <= 1:
            # Already at the top of the mode. Not a limit worth a tone — you
            # are somewhere valid, you simply cannot go further out.
            return Change(Event.NONE, before, before)
        self._path.pop()
        self._record_position()
        return Change(Event.ASCENDED, before, self.snapshot())

    # -- changing values ------------------------------------------------ #
    def adjust(self, steps: int) -> Change:
        """
        Change the focused parameter's value. `steps` is signed; ±10 is coarse.

        A node under the cursor is not an error — Left and Right mean
        ascend/descend there, and the interaction layer routes accordingly.
        """
        before = self.snapshot()
        item = self._item()
        if isinstance(item, Node):
            return Change(Event.NONE, before, before)
        if item.kind == "text":
            # Silence would be indistinguishable from a broken key. Point at
            # the key that does work instead — see textentry.py.
            return Change(Event.READ_ONLY, before, before)
        if not item.nudge(steps):
            # Already at the edge. The value did not move, but the user asked,
            # so this is a limit — earcon plus, at normal verbosity, the word.
            return Change(Event.VALUE_LIMIT, before, self.snapshot(), hit_limit=True)
        return Change(Event.VALUE, before, self.snapshot())

    def value_to_minimum(self) -> Change:
        return self._value_extreme(to_max=False)

    def value_to_maximum(self) -> Change:
        return self._value_extreme(to_max=True)

    def _value_extreme(self, to_max: bool) -> Change:
        before = self.snapshot()
        item = self._item()
        if isinstance(item, Node):
            return Change(Event.NONE, before, before)
        if item.kind == "text":
            return Change(Event.READ_ONLY, before, before)
        changed = item.to_maximum() if to_max else item.to_minimum()
        if not changed:
            return Change(Event.VALUE_LIMIT, before, self.snapshot(), hit_limit=True)
        return Change(Event.VALUE, before, self.snapshot())

    # -- modes ---------------------------------------------------------- #
    def cycle_mode(self, delta: int = 1) -> Change:
        before = self.snapshot()
        self._remembered[self.mode_index] = list(self._path)
        self.mode_index = (self.mode_index + delta) % len(self.modes)
        self._path = list(self._remembered.get(self.mode_index, [0]))
        self._clamp_path()
        return Change(Event.MODE, before, self.snapshot())

    def _clamp_path(self) -> None:
        """Keep a remembered path valid if the tree changed underneath it."""
        node = self.mode
        clean: list[int] = []
        for depth, i in enumerate(self._path):
            if not isinstance(node, Node) or len(node) == 0:
                break
            i = max(0, min(i, len(node) - 1))
            clean.append(i)
            if depth < len(self._path) - 1:
                node = node[i]
        self._path = clean or [0]

    # -- for the "where am I" key --------------------------------------- #
    def here(self) -> Change:
        """
        Report the current position without moving.

        Exists because speech and earcons switch off independently, and with
        both off there would otherwise be no way to find your way back to the
        setting that turned them off. This one always speaks.
        """
        snap = self.snapshot()
        return Change(Event.MOVED, None, snap)
