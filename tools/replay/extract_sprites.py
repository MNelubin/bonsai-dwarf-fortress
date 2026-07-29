#!/usr/bin/env python3
"""Parse Dwarf Fortress v50 graphics raws into a compact sprite index for the replay
viewer, and pack the sheets it needs into one atlas.

The whole game-state -> sprite mapping in v50 is declarative, so nothing here is
reverse-engineered:

    [TILE_PAGE:NAME] [FILE:images/x.png] [TILE_DIM:32:32] [PAGE_DIM_PIXELS:w:h]
    [TILE_GRAPHICS:PAGE:col:row:TOKEN:variant]

Tokens are systematic, and wall connectivity is encoded in the token NAME
(STONE_WALL_N_S, SOIL_WALL_NE, ...), which is why an external renderer can reproduce
DF's own wall joining without touching the binary.

    python extract_sprites.py <df_raws_dir> <images_dir> <out_dir>

Writes:
    atlas.png        every sprite the viewer needs, packed into one sheet
    sprites.json     token -> [atlas_col, atlas_row], plus tile size and metadata
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

# Which pages to pack. Start from every page whose sheet is on disk: the atlas is
# small enough (sub-megabyte) that completeness beats a size micro-optimisation, and
# an over-narrow filter silently drops terrain — the first pass excluded brooks,
# shrubs and saplings purely because their page names did not match a prefix list.
# Portraits and world-map art are the only things worth skipping: they are large and
# a fort replay never draws them.
SKIP_PAGE_SUBSTRINGS = ("PORTRAIT", "WORLD_MAP", "TITLE", "LOGO")


# A few sprites DF assembles from parts rather than shipping whole. Each entry is
# (page, col, row) cells composited bottom-up into one atlas tile.
#
# Dwarves are the case that matters: dwarf_body.png holds body PARTS (a row of heads,
# a torso, arms, legs) and the game stacks them with per-part palette rows for skin
# tone, hair and clothing — 763 layers in the adult LAYER_SET. Taking "the first
# non-shadow layer" picked a CAPE and drew every dwarf as a dark hood. Reproducing the
# full composite needs palettes, tissue conditions and worn equipment; a fort replay at
# 12-32 px a tile only needs a recognisable figure, so we stack legs + torso + head
# from the game's own art. The default palette row is already the painted skin tone,
# so no substitution is required for this.
COMPOSITES = {
    "CREATURE_DWARF": [("DWARF_BODY", 4, 5), ("DWARF_BODY", 4, 2), ("DWARF_BODY", 0, 0)],
}


def wanted(page: str) -> bool:
    return not any(s in page.upper() for s in SKIP_PAGE_SUBSTRINGS)

TAG = re.compile(r"\[([A-Z_0-9]+)((?::[^\]]*)?)\]")
PLANT_BLOCK = re.compile(r"\[PLANT_GRAPHICS:([^\]]+)\]((?:(?!\[PLANT_GRAPHICS)[\s\S])*)")
PLANT_TILE = re.compile(r"\[(GRASS_[1-4]|SHRUB|SHRUB_DEAD|SAPLING|CROP|CROP_SPROUT)"
                        r":([A-Z_0-9]+):(\d+):(\d+)\]")


def parse_plants(raws_dir: pathlib.Path) -> dict[str, tuple[str, int, int]]:
    """Vegetation is NOT declared with [TILE_GRAPHICS] — it hangs off each plant species:

        [PLANT_GRAPHICS:MEADOW-GRASS]
            [GRASS_1:GRASS:0:0] [GRASS_2:GRASS:1:0] ...
        [PLANT_GRAPHICS:LONGLAND GRASS]
            [SHRUB:PLANT_CROPS:0:0] [SAPLING:TREE_SAPLINGS:5:0]

    Missing this is why the first build drew grass from the FLOORS page (entirely the
    wrong sprites) and left every shrub and sapling as a hole in the map.

    A recording stores no plant species, so we take the sprite set the surface species
    agree on — 32 of them share GRASS cells (0..3, 0), and only cavern grasses differ.
    Emitted as synthetic PLANT_* tokens so the rest of the pipeline is unchanged.
    """
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for f in sorted(raws_dir.rglob("*.txt")):
        text = f.read_text(encoding="utf-8", errors="replace")
        for pm in PLANT_BLOCK.finditer(text):
            for kind, page, col, row in PLANT_TILE.findall(pm.group(2)):
                counts[kind][(page, int(col), int(row))] += 1
    out: dict[str, tuple[str, int, int]] = {}
    for kind, c in counts.items():
        out["PLANT_" + kind] = c.most_common(1)[0][0]      # the consensus sprite
    return out


CREATURE_BLOCK = re.compile(
    r"\[CREATURE_GRAPHICS:([^\]]+)\]((?:(?!\[CREATURE_GRAPHICS)[\s\S])*)")
LAYER_SET = re.compile(r"\[LAYER_SET:([^\]]+)\]")
LAYER_LINE = re.compile(r"\[LAYER:([A-Z_0-9]+):([A-Z_0-9]+):(\d+):(\d+)\]")
DEFAULT_LINE = re.compile(r"\[DEFAULT:([A-Z_0-9]+):(\d+):(\d+)")


def parse_creatures(raws_dir: pathlib.Path) -> dict[str, tuple[str, int, int]]:
    """One representative sprite per creature, as CREATURE_<ID>.

    Simple creatures declare [DEFAULT:<page>:<x>:<y>]. Dwarves, elves, humans and
    goblins instead build themselves from [LAYER_SET]/[LAYER_GROUP]/[LAYER] — the dwarf
    file alone runs past 400 layer declarations, and its 91 base-body layers ALL point
    at the same sprite cell, differing only in the palette row applied for skin colour
    and undead state. So a viewer that wants one recognisable sprite per creature can
    take the first non-shadow body layer of the adult LAYER_SET and ignore the rest;
    reproducing the full composite would mean palettes, tissue conditions and worn
    equipment, none of which a fort replay needs.
    """
    out: dict[str, tuple[str, int, int]] = {}
    for f in sorted(raws_dir.rglob("*.txt")):
        text = f.read_text(encoding="utf-8", errors="replace")
        for cm in CREATURE_BLOCK.finditer(text):
            cid = cm.group(1).split(":")[0].strip().replace(" ", "_")
            body = cm.group(2)
            key = "CREATURE_" + cid
            if key in out:
                continue
            d = DEFAULT_LINE.search(body)
            if d:
                out[key] = (d.group(1), int(d.group(2)), int(d.group(3)))
                continue
            # layered: skip BABY/CHILD/CORPSE/PORTRAIT sets, then skip SHADOW layers
            adult = body
            sets = list(LAYER_SET.finditer(body))
            for i, sm in enumerate(sets):
                if sm.group(1).strip() == "DEFAULT":
                    end = sets[i + 1].start() if i + 1 < len(sets) else len(body)
                    adult = body[sm.end():end]
                    break
            for lm in LAYER_LINE.finditer(adult):
                if "SHADOW" in lm.group(1):
                    continue
                out[key] = (lm.group(2), int(lm.group(3)), int(lm.group(4)))
                break
    return out


def parse_raws(raws_dir: pathlib.Path) -> tuple[dict, dict]:
    """Return (pages, token->(page, col, row))."""
    pages: dict[str, dict] = {}
    tokens: dict[str, tuple[str, int, int]] = {}
    for f in sorted(raws_dir.rglob("*.txt")):
        text = f.read_text(encoding="utf-8", errors="replace")
        cur = None
        for m in TAG.finditer(text):
            tag = m.group(1)
            rest = m.group(2)[1:] if m.group(2) else ""
            if tag == "TILE_PAGE":
                cur = rest
                pages.setdefault(cur, {})
            elif cur and tag == "FILE":
                pages[cur]["file"] = rest
            elif cur and tag == "TILE_DIM":
                pages[cur]["dim"] = [int(x) for x in rest.split(":")[:2]]
            elif cur and tag == "PAGE_DIM_PIXELS":
                pages[cur]["px"] = [int(x) for x in rest.split(":")[:2]]
            elif tag == "TILE_GRAPHICS":
                p = rest.split(":")
                if len(p) >= 4 and p[1].isdigit() and p[2].isdigit():
                    name = p[3]
                    # Multi-tile buildings carry stage + footprint coordinates AFTER the
                    # token: [WORKSHOP_3X3:0:4:WORKSHOP_CARPENTER:3:0:0]. Keying on the
                    # bare token collapses every cell of a 3x3 workshop onto its first
                    # one, so fold the footprint into the token name.
                    tail = p[4:]
                    if tail and not tail[0].isdigit():        # WORKSHOP_CUSTOM:<id>:...
                        name = f"{name}_{tail[0]}"
                        tail = tail[1:]
                    if len(tail) >= 3 and all(t.isdigit() for t in tail[:3]):
                        name = f"{name}_S{tail[0]}_{tail[1]}_{tail[2]}"
                    # first definition wins, matching the raws' own precedence order
                    tokens.setdefault(name, (p[0], int(p[1]), int(p[2])))
    return pages, tokens


def load_sheet(images_dir: pathlib.Path, filename: str):
    """Load a sprite sheet exactly as the raws name it.

    Two traps here, both of which produced silently-blank sprites the first time:

    * ONE page (ALT_FLOORS) points at a .bmp, not a .png. Substituting the
      similarly-named .png loads a real image at the wrong coordinates, so the crop
      succeeds and yields empty or wrong cells. Always try the exact name first.
    * That .bmp has no alpha channel — it keys transparency on magenta (255,0,255),
      113k pixels of it. Without keying, every 'transparent' pixel is opaque magenta.
    """
    from PIL import Image

    exact = images_dir / pathlib.PurePath(filename).name
    src = exact if exact.exists() else None
    if src is None:
        alt = exact.with_suffix(".png")
        src = alt if alt.exists() else None
    if src is None:
        return None
    im = Image.open(src)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
        if src.suffix.lower() != ".png":
            px = im.load()
            for y in range(im.height):
                for x in range(im.width):
                    r, g, b, _ = px[x, y]
                    if r > 240 and g < 15 and b > 240:
                        px[x, y] = (0, 0, 0, 0)
    return im


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    raws_dir, images_dir, out_dir = (pathlib.Path(p) for p in sys.argv[1:4])
    out_dir.mkdir(parents=True, exist_ok=True)

    pages, tokens = parse_raws(raws_dir)
    plants = parse_plants(raws_dir)
    creatures = parse_creatures(raws_dir)
    tokens.update(plants)
    tokens.update(creatures)
    keep = {t: v for t, v in tokens.items() if wanted(v[0])}
    print(f"parsed {len(pages)} pages, {len(tokens)} tokens "
          f"(incl. {len(plants)} vegetation, {len(creatures)} creatures); "
          f"{len(keep)} on wanted pages")

    try:
        from PIL import Image
    except ImportError:
        print("error: Pillow is required to pack the atlas (pip install pillow)",
              file=sys.stderr)
        return 1

    sheets: dict[str, "Image.Image"] = {}
    missing_pages = set()
    # COMPOSITES reference pages that no token points at on its own (a dwarf's body
    # parts are only ever named by LAYER lines we deliberately skip), so ask for them
    # explicitly or the composite silently finds no art.
    needed = {v[0] for v in keep.values()} | {pg for parts in COMPOSITES.values()
                                              for pg, _, _ in parts}
    for page in sorted(needed):
        fn = (pages.get(page) or {}).get("file")
        im = load_sheet(images_dir, fn) if fn else None
        if im is None:
            missing_pages.add(page)
        else:
            sheets[page] = im

    usable = {t: v for t, v in keep.items() if v[0] in sheets}
    print(f"loaded {len(sheets)} sheets; {len(usable)} tokens usable; "
          f"{len(missing_pages)} pages unavailable")

    TILE = 32
    cols = 64
    rows = (len(usable) + cols - 1) // cols
    atlas = Image.new("RGBA", (cols * TILE, rows * TILE), (0, 0, 0, 0))
    index: dict[str, list[int]] = {}
    oversized, blank, out_of_range, opaque = [], [], [], []
    COMPOSED = {}

    def cell_of(page, col, row):
        """Crop one sheet cell to TILE x TILE, or None if the sheet has no art there."""
        sheet = sheets.get(page)
        if sheet is None:
            return None
        dim = (pages.get(page) or {}).get("dim") or [TILE, TILE]
        w, h = dim[0], dim[1]
        box = (col * w, row * h, col * w + w, row * h + h)
        if box[2] > sheet.width or box[3] > sheet.height:
            return None
        c = sheet.crop(box)
        return c if (w, h) == (TILE, TILE) else c.resize((TILE, TILE), Image.NEAREST)

    for tok, parts in COMPOSITES.items():
        stack = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        got = 0
        for page, col, row in parts:
            c = cell_of(page, col, row)
            if c is not None:
                stack.alpha_composite(c)
                got += 1
        if got:
            usable[tok] = ("__composite__", 0, 0)
            sheets.setdefault("__composite__", Image.new("RGBA", (TILE, TILE)))
            COMPOSED[tok] = stack

    slot = 0
    for tok, (page, col, row) in sorted(usable.items()):
        if tok in COMPOSED:
            cell = COMPOSED[tok]
        else:
            sheet = sheets[page]
            dim = (pages.get(page) or {}).get("dim") or [TILE, TILE]
            w, h = dim[0], dim[1]
            box = (col * w, row * h, col * w + w, row * h + h)
            if box[2] > sheet.width or box[3] > sheet.height:
                out_of_range.append(tok)
                continue
            cell = sheet.crop(box)
            if (w, h) != (TILE, TILE):
                oversized.append(tok)
                cell = cell.resize((TILE, TILE), Image.NEAREST)
        # A fully transparent cell means the raws point somewhere this sheet has no
        # art. Indexing it anyway paints nothing and leaves a hole in the map — which
        # is exactly how half the grass went missing on the first build. Drop it, so
        # the viewer's candidate list falls through to a token that renders.
        if not cell.getbbox():
            blank.append(tok)
            continue
        ax, ay = slot % cols, slot // cols
        atlas.paste(cell, (ax * TILE, ay * TILE))
        index[tok] = [ax, ay]
        # DF composites a tile: an opaque floor sprite, then features on top.
        # Shrubs are 634/1024 opaque, saplings 319, boulders 743 - drawn alone they
        # sit on the page background instead of on the ground. Recording which
        # sprites are full-coverage lets the renderer know which need a base under
        # them.
        if cell.getchannel('A').getextrema()[0] > 250:
            opaque.append(tok)
        slot += 1

    atlas = atlas.crop((0, 0, cols * TILE, max(1, (slot + cols - 1) // cols) * TILE))
    atlas.save(out_dir / "atlas.png", optimize=True)
    meta = {
        "tile": TILE, "cols": cols, "rows": (slot + cols - 1) // cols,
        "tokens": index,
        "opaque": opaque,
        "note": "token -> [atlas_col, atlas_row]; sprites are TILE x TILE px",
    }
    (out_dir / "sprites.json").write_text(json.dumps(meta, separators=(",", ":")),
                                          encoding="utf-8")
    size = (out_dir / "atlas.png").stat().st_size
    print(f"wrote atlas.png {atlas.width}x{atlas.height} ({size:,} bytes) "
          f"with {len(index):,} sprites")
    print(f"  {len(opaque):,} sprites are full-coverage (usable as a base layer)")
    if blank:
        print(f"  dropped {len(blank)} EMPTY sprites (raws point at art-free cells): "
              f"{blank[:6]}{'...' if len(blank) > 6 else ''}")
    if out_of_range:
        print(f"  dropped {len(out_of_range)} cells past their sheet edge")
    if oversized:
        print(f"  rescaled {len(oversized)} non-32px sprites (e.g. {oversized[:3]})")
    if missing_pages:
        print(f"  skipped pages with no image on disk: "
              f"{sorted(missing_pages)[:5]}{'...' if len(missing_pages) > 5 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
