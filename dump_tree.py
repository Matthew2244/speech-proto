#!/usr/bin/env python3
"""
Print the parameter tree — as an outline, or as JSON.

The JSON form is the point of this script. It is the whole instrument's state
with no speech vocabulary anywhere in it: names, values, ranges, options,
structure. That is the machine-readable representation a manufacturer has to
build once, and it is what speech, a Braille display, a remote editor and any
community tool would each consume independently.

    ./dump_tree.py                     outline, everything
    ./dump_tree.py --depth 2           just the top of each mode
    ./dump_tree.py --mode Global       one mode
    ./dump_tree.py --json --mode Global
    ./dump_tree.py --count             how big the tree actually is
"""

from __future__ import annotations

import argparse
import json

from speechproto.instrument import build_instrument
from speechproto.params import Node


def outline(node, depth: int = 0, max_depth: int | None = None) -> None:
    pad = "  " * depth
    if isinstance(node, Node):
        print(f"{pad}{node.name}  ({len(node)} items)")
        if max_depth is not None and depth >= max_depth:
            return
        for child in node:
            outline(child, depth + 1, max_depth)
    else:
        extra = ""
        if node.kind == "continuous":
            extra = f"  [{node.minimum}..{node.maximum}]"
        elif node.kind == "stepped":
            extra = f"  [{node.index + 1} of {len(node.options)}]"
        print(f"{pad}{node.name}: {node.display_value}{extra}")


def counts(node) -> tuple[int, int]:
    """(nodes, leaf parameters) under and including this node."""
    if isinstance(node, Node):
        n, p = 1, 0
        for c in node:
            cn, cp = counts(c)
            n += cn
            p += cp
        return n, p
    return 0, 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Print the parameter tree.")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of an outline")
    ap.add_argument("--depth", type=int, default=None, help="limit outline depth")
    ap.add_argument("--mode", default=None, help="only this mode (Program, Combi, Set List, Global)")
    ap.add_argument("--count", action="store_true", help="print sizes and exit")
    args = ap.parse_args()

    modes = build_instrument(["Mac Studio Speakers", "StudioLive 64S", "System Default"])
    if args.mode:
        wanted = args.mode.strip().lower()
        modes = [m for m in modes if m.name.lower() == wanted]
        if not modes:
            print(f"No mode named {args.mode!r}.")
            return 1

    if args.count:
        total_n = total_p = 0
        for m in modes:
            n, p = counts(m)
            total_n += n
            total_p += p
            print(f"{m.name}: {n} nodes, {p} parameters")
        print(f"total: {total_n} nodes, {total_p} parameters")
        return 0

    if args.json:
        print(json.dumps([m.to_dict() for m in modes], indent=2))
        return 0

    for m in modes:
        outline(m, max_depth=args.depth)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
