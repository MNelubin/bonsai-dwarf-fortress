#!/usr/bin/env python3
"""Work out which sprites DF recolours, and build the swap table for them.

    python build_palette.py [build_dir] [palettes.png]

DF v50 does not ship one sprite per stone. Natural rock, soil, boulders and stairs are
drawn ONCE in a fixed set of key colours, and the game swaps those colours at draw time
for the row belonging to the tile's material. Drawing the key art as-is is why soil walls
rendered grey: the art is grey, the game is what makes it brown.

The mechanism, confirmed against the raws and measured against our own atlas:

    data/vanilla/vanilla_descriptors_graphics/graphics/images/palettes.png is 18 x 137.
    Row 0 is the key row — "this is the one used in the images themselves"
    (palette_default.txt:9). Rows 1..136 are named palettes, declared as
    [PALETTE_COLOR:AMBER:1], [PALETTE_COLOR:AMETHYST:2], ... 136 of them.
    world.raws.descriptors.colors also has exactly 136 entries, in the same order
    (colors[0].id == "AMBER"), so a material's palette row is state_color.Solid + 1.
    Row 0 therefore means "leave this alone".

Which sprites take part is MEASURED, not guessed from token names — a name-based rule
would silently miss a family the next DF version adds. The separation is stark:

    SOIL_WALL_N_S_W_E_1          100.0% of visible pixels are key colours
    STONE_WALL_N_S_W_E_1         100.0%
    SMOOTHED_STONE_WALL_N_S_W_E  100.0%
    PALETTE_STAIR_UPDOWN          97.2%
    BOULDER                       84.7%   (the rest is anti-aliasing near a key colour)
    STONE_FLOOR_5 / DIRT_FLOOR_5 / PLANT_GRASS_1 / PLANT_SHRUB   0.0%

Floors, grass and plants carry their own colour and must NOT be touched.
"""
from __future__ import annotations

import json
import pathlib
import sys

# Key colours are matched with a small tolerance: PNG re-encoding and anti-aliasing move
# a pixel by a unit or two, and BOULDER's misses were all (46,48,56) against a key of
# (47,48,56). Too wide a tolerance would start eating real art, so keep it tight.
TOL = 6

# A sprite counts as palette art when nearly all of it is key colours. The score
# distribution across the whole atlas is strongly bimodal — 1,284 sprites land in 0-5%
# and 3,055 in 95-100%, with a thin middle — so the threshold sits in a real gap rather
# than next to either population. Terrain splits cleanly at this line:
#
#   1.000  SOIL_WALL STONE_WALL SMOOTHED/WORN1/WORN2/WORN3_STONE_WALL ROOT_WALL
#          WOODEN_WALL ROCK_BLOCKS_WALL BOULDER PALETTE_STAIR FLOOR_STONE_BLOCK
#          TREE_BASE_TRUNK TREE_LEAFLESS_TWIGS
#   0.984  TREE_BRANCH
#   0.908  PEBBLES_FLOOR
#   ------ threshold ------
#   0.501  ORE_VEIN_WALL      full-colour ore over palette rock; see NOTE below
#   0.000  DIRT_FLOOR PLANT_GRASS GRASS_RAMP ICE_WALL MAGMA_WALL BROOK_BED
#
# The swap only ever rewrites pixels that ARE key colours, so a mistakenly included
# sprite loses only its incidental matches — but that is still visible damage, and the
# gap is wide enough that there is no reason to gamble.
PALETTE_FRAC = 0.90


def near(c, key_index):
    """Nearest key colour within TOL, or None. Chebyshev distance — cheap and enough."""
    best, bd = None, TOL + 1
    for i, k in enumerate(key_index):
        d = max(abs(c[0] - k[0]), abs(c[1] - k[1]), abs(c[2] - k[2]))
        if d < bd:
            best, bd = i, d
    return best if bd <= TOL else None


def main() -> int:
    from PIL import Image

    build = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("build")
    pal_path = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else build / "palettes.png"
    if not pal_path.is_file():
        print(f"{pal_path} not found — copy it from the DF install:\n"
              "  data/vanilla/vanilla_descriptors_graphics/graphics/images/palettes.png",
              file=sys.stderr)
        return 2

    pal = Image.open(pal_path).convert("RGB")
    ncol, nrow = pal.size
    rows = [[list(pal.getpixel((c, r))) for c in range(ncol)] for r in range(nrow)]
    key = rows[0]

    sprites = json.loads((build / "sprites.json").read_text(encoding="utf-8"))
    atlas = Image.open(build / "atlas.png").convert("RGBA")
    T, toks = sprites["tile"], sprites["tokens"]

    palette_tokens, scores = [], {}
    for name, (ax, ay) in toks.items():
        cell = atlas.crop((ax * T, ay * T, ax * T + T, ay * T + T))
        vis = [p for p in cell.getdata() if p[3] > 8]
        if not vis:
            continue
        hit = sum(1 for p in vis if near(p[:3], key) is not None)
        frac = hit / len(vis)
        scores[name] = round(frac, 4)
        if frac >= PALETTE_FRAC:
            palette_tokens.append(name)
    palette_tokens.sort()

    out = {"cols": ncol, "rows": nrow, "key": key, "table": rows,
           "tokens": palette_tokens}
    (build / "palette.json").write_text(json.dumps(out), encoding="utf-8")

    borderline = sorted(((v, k) for k, v in scores.items() if 0.5 <= v < PALETTE_FRAC),
                        reverse=True)[:10]
    print(f"wrote {build / 'palette.json'}  {ncol} colours x {nrow} rows")
    print(f"  {len(palette_tokens):,} of {len(scores):,} sprites are palette art "
          f"({100 * len(palette_tokens) / max(1, len(scores)):.1f}%)")
    print("  families taking part: " + ", ".join(sorted({
        t.rsplit("_", 1)[0] for t in palette_tokens})[:12]) + " ...")
    if borderline:
        # Anything sitting between the two populations is worth a human look — it is
        # either art we are about to wrongly recolour or art we are about to leave grey.
        print("  BORDERLINE (neither clearly palette art nor clearly full-colour):")
        for v, k in borderline:
            print(f"    {k:40} {v:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
