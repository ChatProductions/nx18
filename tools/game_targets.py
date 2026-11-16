#!/usr/bin/env python3
"""Switch title selection for the reusable nx18 native toolchain.

A catalog entry selects defaults, NOT compatibility: no catalog game is
implicitly asserted playable. Unlisted title IDs remain supported as
experimental custom targets.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class GameTarget:
    title_id: str
    name: str
    slug: str
    priority: str
    compatibility: str = "unverified"

    @property
    def bundle_id(self) -> str:
        return "org.nx18.game.t" + self.title_id.lower()


TARGETS = (
    GameTarget("0100B51020B68000", "Terminator 2D: NO FATE",
               "terminator2d", "first-test"),
    GameTarget("010029B0118E8000", "Need for Speed: Hot Pursuit Remastered",
               "nfshp", "fallback"),
    GameTarget("0100670014482000", "Assassin's Creed II (The Ezio Collection)",
               "ac2", "long-term"),
)
ALIASES = {
    "terminator": TARGETS[0],
    "t2": TARGETS[0],
    "t2d": TARGETS[0],
    "nfs": TARGETS[1],
    "hotpursuit": TARGETS[1],
    "hot-pursuit": TARGETS[1],
    "ac2": TARGETS[2],
    "ezio": TARGETS[2],
}
for target in TARGETS:
    ALIASES[target.slug] = target
    ALIASES[target.title_id.lower()] = target


def title_id(text: str) -> str:
    if not re.fullmatch(r"[0-9A-Fa-f]{16}", text):
        raise ValueError("Switch base title ID must be exactly 16 hexadecimal digits")
    return text.upper()


def resolve_target(name_or_id: str) -> GameTarget:
    term = name_or_id.strip().lower()
    if term in ALIASES:
        return ALIASES[term]
    tid = title_id(name_or_id.strip())
    return GameTarget(tid, "Custom Switch title " + tid,
                      "title-" + tid.lower(), "experimental")


def target_from_id(tid: str) -> GameTarget:
    return resolve_target(title_id(tid))


def main() -> None:
    p = argparse.ArgumentParser(description="List and resolve nx18 native game targets.")
    p.add_argument("target", nargs="?", default="terminator",
                   help="terminator, nfshp, ac2 or a 16-digit custom title ID")
    p.add_argument("--list", action="store_true", help="Show configured targets")
    a = p.parse_args()
    if a.list:
        for t in TARGETS:
            print(t.title_id + "\t" + t.slug + "\t" + t.priority + "\t" + t.name)
    else:
        t = resolve_target(a.target)
        print(t.title_id + "\t" + t.name + "\t" + t.priority)


if __name__ == "__main__":
    main()
