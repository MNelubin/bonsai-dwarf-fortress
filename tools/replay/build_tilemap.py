#!/usr/bin/env python3
"""Build the tiletype -> sprite-token mapping the replay viewer renders with.

    python build_tilemap.py <enums.json> <sprites.json> <out tilemap.json>

Every rule here is validated against the sprites actually present in the atlas: a
candidate family is only accepted if its tokens exist. Coverage is reported per
tiletype weighted by nothing, and unmapped shapes are listed — so a DF upgrade that
renames a family shows up as a coverage drop rather than as silently missing terrain.

Direction conventions differ between families and are NOT guessable, so they are
encoded per-kind and verified:

    wall      STONE_WALL_N_S_W_E      cardinal subset, underscore-separated,
                                      plus corner-only forms (STONE_WALL_NE)
    tree      TREE_BRANCH_NSWE        cardinal subset, CONCATENATED
    ramp      STONE_RAMP_WITH_WALL_NW_NE   corner names, underscore-separated
    floor9    STONE_FLOOR_5 (+5B/5C/5D)    a 3x3 blend set; 5 is the interior tile
    stair     DIRT_STAIR_UP / _DOWN / _UPDOWN

`tint` marks sprites DF draws greyscale and colours by the tile's material (the raws
call these PALETTE sprites). The viewer multiplies them by the material colour.
"""
from __future__ import annotations

import json
import pathlib
import sys

# (shape, material-predicate) -> (family, kind, tint)
# Order matters: the first matching rule whose tokens exist in the atlas wins.
RULES: list[tuple[str, tuple[str, ...] | None, str, str, bool]] = [
    # shape,        materials (None = any),                family,               kind,     tint
    ("WALL",  ("SOIL",),                                   "SOIL_WALL",          "wall",   False),
    ("WALL",  ("STONE", "LAVA_STONE"),                     "STONE_WALL",         "wall",   False),
    ("WALL",  ("MINERAL",),                                "ORE_VEIN_WALL",      "wall",   False),
    ("WALL",  ("ROOT",),                                   "ROOT_WALL",          "wall",   False),
    ("WALL",  ("TREE",),                                   "TREE_BASE_TRUNK",    "tree",   False),
    ("WALL",  ("FROZEN_LIQUID",),                          "ICE_WALL",           "wall",   False),
    ("WALL",  ("CONSTRUCTION",),                           "ROCK_BLOCKS_WALL",   "wall",   True),
    ("WALL",  ("MAGMA",),                                  "MAGMA_WALL",         "wall",   False),
    ("WALL",  ("MUSHROOM", "PLANT"),                       "WOODEN_WALL",        "wall",   False),
    ("WALL",  None,                                        "STONE_WALL",         "wall",   False),

    ("FORTIFICATION", None,                                "FORTIFICATION",      "plain",  False),

    # Grass is drawn from the GRASS page via [PLANT_GRAPHICS], not from the FLOORS
    # page. Using the TILE_GRAPHICS "GRASS_*" tokens picked entirely wrong sprites.
    ("FLOOR", ("GRASS_LIGHT", "GRASS_DARK", "GRASS_DRY", "GRASS_DEAD"),
                                                           "PLANT_GRASS",        "var4",   False),
    ("FLOOR", ("SOIL",),                                   "DIRT_FLOOR",         "floor9", False),
    ("FLOOR", ("STONE", "LAVA_STONE", "MINERAL"),          "STONE_FLOOR",        "floor9", False),
    ("FLOOR", ("CONSTRUCTION",),                           "FLOOR_STONE_BLOCK",  "plain",  True),
    ("FLOOR", ("ASHES",),                                  "FLOOR_ASHES",        "plain",  False),
    ("FLOOR", ("FROZEN_LIQUID",),                          "SMOOTH_ICE_FLOOR",   "plain",  False),
    ("FLOOR", ("TREE",),                                   "WOOD_FLOOR",         "plain",  False),
    ("FLOOR", None,                                        "STONE_FLOOR",        "floor9", False),

    ("PEBBLES", None,                                      "PEBBLES_FLOOR",      "floor9", False),
    ("BOULDER", None,                                      "BOULDER",            "plain",  False),

    ("RAMP",  ("GRASS_LIGHT", "GRASS_DARK", "GRASS_DRY", "GRASS_DEAD"),
                                                           "GRASS_RAMP_WITH_WALL", "ramp", False),
    ("RAMP",  ("SOIL",),                                   "SOIL_RAMP_WITH_WALL",  "ramp", False),
    ("RAMP",  ("TREE",),                                   "TREE_BASE_TRUNK",      "tree", False),
    ("RAMP",  None,                                        "STONE_RAMP_WITH_WALL", "ramp", False),

    ("STAIR_UP",     ("SOIL",),                            "DIRT_STAIR",         "stair",  False),
    ("STAIR_DOWN",   ("SOIL",),                            "DIRT_STAIR",         "stair",  False),
    ("STAIR_UPDOWN", ("SOIL",),                            "DIRT_STAIR",         "stair",  False),
    ("STAIR_UP",     ("GRASS_LIGHT", "GRASS_DARK"),        "GRASS_STAIR",        "stair",  False),
    ("STAIR_DOWN",   ("GRASS_LIGHT", "GRASS_DARK"),        "GRASS_STAIR",        "stair",  False),
    ("STAIR_UPDOWN", ("GRASS_LIGHT", "GRASS_DARK"),        "GRASS_STAIR",        "stair",  False),
    ("STAIR_UP",     None,                                 "PALETTE_STAIR",      "stair",  True),
    ("STAIR_DOWN",   None,                                 "PALETTE_STAIR",      "stair",  True),
    ("STAIR_UPDOWN", None,                                 "PALETTE_STAIR",      "stair",  True),

    ("BRANCH",       None,                                 "TREE_BRANCH",        "tree",   False),
    ("TRUNK_BRANCH", None,                                 "TREE_BRANCH",        "tree",   False),
    ("TWIG",         None,                                 "TREE_LEAFLESS_TWIGS", "tree",  False),
    ("SAPLING",      None,                                 "PLANT_SAPLING",      "plain",  False),
    ("SHRUB",        None,                                 "PLANT_SHRUB",        "plain",  False),

    ("BROOK_TOP",    None,                                 "BROOK_TOP",          "plain",  False),
    ("BROOK_BED",    None,                                 "BROOK_BED",          "plain",  False),
]

# `special` overrides the family for stone walls and floors.
SPECIAL_WALL = {"SMOOTH": "SMOOTHED_STONE_WALL", "WORN_1": "WORN1_STONE_WALL",
                "WORN_2": "WORN2_STONE_WALL", "WORN_3": "WORN3_STONE_WALL"}

KIND_PROBES = {                      # a token that must exist for the family to be usable
    "wall": ("_N_S_1", "_N_S", "_N"),
    "tree": ("_NS", "_N", ""),
    "ramp": ("_NW_NE", "_NW", "_N"),
    "floor9": ("_5", "_1"),
    "var4": ("_1", "_2"),
    "stair": ("_UP",),
    "plain": ("",),
}


def usable(tokens: dict, family: str, kind: str) -> bool:
    return any((family + suffix) in tokens for suffix in KIND_PROBES[kind])


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    enums = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    sprites = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
    out = pathlib.Path(sys.argv[3])
    tokens = sprites["tokens"]

    full = enums.get("tt") or {}
    specials = enums.get("special") or {}

    mapping: dict[str, dict] = {}
    unmapped: dict[str, int] = {}
    for tid_s, info in full.items():
        shape, material = info[0], info[1]
        special = specials.get(tid_s, "NONE")
        if shape in ("EMPTY", "NONE", "ENDLESS_PIT", "RAMP_TOP"):
            continue                                  # nothing to draw
        chosen = None
        for rshape, rmats, fam, kind, tint in RULES:
            if rshape != shape:
                continue
            if rmats is not None and material not in rmats:
                continue
            f = fam
            if kind == "wall" and fam == "STONE_WALL" and special in SPECIAL_WALL:
                cand = SPECIAL_WALL[special]
                if usable(tokens, cand, kind):
                    f = cand
            if usable(tokens, f, kind):
                chosen = {"f": f, "k": kind}
                if tint:
                    chosen["t"] = 1
                break
        if chosen:
            mapping[tid_s] = chosen
        else:
            unmapped[f"{shape}/{material}"] = unmapped.get(f"{shape}/{material}", 0) + 1

    out.write_text(json.dumps({"tiles": mapping}, separators=(",", ":")), encoding="utf-8")
    print(f"mapped {len(mapping)} of {len(full)} tiletypes -> {out}")
    if unmapped:
        print(f"unmapped shape/material combinations ({sum(unmapped.values())} tiletypes):")
        for k, v in sorted(unmapped.items(), key=lambda kv: -kv[1])[:15]:
            print(f"    {k:32} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
