#!/usr/bin/env python3
"""Re-roll the fork identity in branding.properties.

    python3 scripts/roll_branding.py              # new package name + label + codename + icon
    python3 scripts/roll_branding.py --icon-only  # new icon only, keep the identity
    python3 scripts/roll_branding.py --seed 1234  # pin the icon seed

Changing appId / codename changes the installed identity: a build with the new
values installs ALONGSIDE the old app instead of updating over it, and the old
Zygisk module is left behind. The current values (io.moonlit.quarry / quarry)
match release oss-173, so releases built with them update over oss-173.
"""

from __future__ import annotations

import argparse
import random
import secrets
import sys
from pathlib import Path

ADJECTIVES = [
    "moonlit", "quiet", "hidden", "silent", "amber", "velvet", "arctic", "cobalt",
    "dusky", "frozen", "gentle", "hollow", "iron", "jade", "lunar", "misty",
    "neon", "opal", "pale", "polar", "silver", "solar", "still", "sunken",
    "tidal", "umber", "violet", "wild", "winter", "woven",
]
NOUNS = [
    "quarry", "harbor", "ledger", "meadow", "anchor", "beacon", "canyon", "cipher",
    "cobalt", "comet", "delta", "ember", "fjord", "garnet", "glacier", "harbour",
    "island", "kernel", "lantern", "lattice", "lumen", "marble", "mesa", "nebula",
    "orchard", "pebble", "prairie", "ridge", "shard", "spindle", "summit", "thicket",
    "timber", "valley", "willow", "zenith",
]
RESERVED = {"com", "org", "net", "android", "google", "io", "app"}


def read_properties(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return lines, values


def write_properties(path: Path, lines: list[str], values: dict[str, str]) -> None:
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in values:
                out.append(f"{key}={values[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def new_identity(rnd: random.Random, taken: set[str]) -> tuple[str, str, str]:
    for _ in range(500):
        noun = rnd.choice(NOUNS)
        adjective = rnd.choice(ADJECTIVES)
        if noun in RESERVED or adjective in RESERVED:
            continue
        app_id = f"io.{adjective}.{noun}"
        if app_id in taken:
            continue
        label = noun.replace("_", " ").title()
        return app_id, label, noun
    raise SystemExit("error: could not generate a fresh identity")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--properties", default=Path(__file__).resolve().parent.parent / "branding.properties", type=Path)
    parser.add_argument("--icon-only", action="store_true", help="only reroll the icon seed")
    parser.add_argument("--seed", type=int, default=None, help="explicit icon seed")
    parser.add_argument("--app-id", default=None, help="explicit package name")
    args = parser.parse_args(argv)

    path: Path = args.properties.resolve()
    lines, values = read_properties(path)
    rnd = random.Random(secrets.randbits(128))

    if not args.icon_only:
        if args.app_id:
            app_id = args.app_id
            noun = app_id.rsplit(".", 1)[-1]
            label = noun.replace("_", " ").title()
        else:
            app_id, label, noun = new_identity(rnd, {values.get("appId", "")})
        values["appId"] = app_id
        values["appLabel"] = label
        values["codename"] = noun

    values["iconSeed"] = str(args.seed if args.seed is not None else rnd.randrange(1, 2**33))

    write_properties(path, lines, values)

    print(f"appId:    {values['appId']}")
    print(f"appLabel: {values['appLabel']}")
    print(f"codename: {values['codename']}")
    print(f"iconSeed: {values['iconSeed']}")
    if not args.icon_only:
        print()
        print("NOTE: builds with this identity install as a NEW app; they do not")
        print("      update an installation of the previous identity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
