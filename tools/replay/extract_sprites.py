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


def wanted(page: str) -> bool:
    return not any(s in page.upper() for s in SKIP_PAGE_SUBSTRINGS)

TAG = re.compile(r"\[([A-Z_0-9]+)((?::[^\]]*)?)\]")


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
                    # first definition wins, matching the raws' own precedence order
                    tokens.setdefault(p[3], (p[0], int(p[1]), int(p[2])))
    return pages, tokens


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    raws_dir, images_dir, out_dir = (pathlib.Path(p) for p in sys.argv[1:4])
    out_dir.mkdir(parents=True, exist_ok=True)

    pages, tokens = parse_raws(raws_dir)
    keep = {t: v for t, v in tokens.items() if wanted(v[0])}
    print(f"parsed {len(pages)} pages, {len(tokens)} tokens; {len(keep)} on wanted pages")

    try:
        from PIL import Image
    except ImportError:
        print("error: Pillow is required to pack the atlas (pip install pillow)",
              file=sys.stderr)
        return 1

    # Load every sheet we still need, once.
    sheets: dict[str, "Image.Image"] = {}
    missing_pages = set()
    for page in sorted({v[0] for v in keep.values()}):
        info = pages.get(page) or {}
        fn = info.get("file")
        if not fn:
            missing_pages.add(page)
            continue
        # raws say images/foo.png but some pages point at .bmp siblings
        cands = [images_dir / pathlib.PurePath(fn).name]
        cands.append(cands[0].with_suffix(".png"))
        src = next((c for c in cands if c.exists()), None)
        if src is None:
            missing_pages.add(page)
            continue
        try:
            sheets[page] = Image.open(src).convert("RGBA")
        except OSError:
            missing_pages.add(page)

    usable = {t: v for t, v in keep.items() if v[0] in sheets}
    print(f"loaded {len(sheets)} sheets; {len(usable)} tokens usable; "
          f"{len(missing_pages)} pages unavailable")

    TILE = 32
    cols = 64
    rows = (len(usable) + cols - 1) // cols
    atlas = Image.new("RGBA", (cols * TILE, rows * TILE), (0, 0, 0, 0))
    index: dict[str, list[int]] = {}
    oversized = []

    for i, (tok, (page, col, row)) in enumerate(sorted(usable.items())):
        sheet = sheets[page]
        dim = (pages.get(page) or {}).get("dim") or [TILE, TILE]
        w, h = dim[0], dim[1]
        box = (col * w, row * h, col * w + w, row * h + h)
        if box[2] > sheet.width or box[3] > sheet.height:
            continue                       # raws reference a cell past the sheet edge
        cell = sheet.crop(box)
        if (w, h) != (TILE, TILE):
            oversized.append(tok)
            cell = cell.resize((TILE, TILE), Image.NEAREST)
        ax, ay = i % cols, i // cols
        atlas.paste(cell, (ax * TILE, ay * TILE))
        index[tok] = [ax, ay]

    atlas.save(out_dir / "atlas.png", optimize=True)
    meta = {
        "tile": TILE, "cols": cols, "rows": rows,
        "tokens": index,
        "note": "token -> [atlas_col, atlas_row]; sprites are TILE x TILE px",
    }
    (out_dir / "sprites.json").write_text(json.dumps(meta, separators=(",", ":")),
                                          encoding="utf-8")
    size = (out_dir / "atlas.png").stat().st_size
    print(f"wrote atlas.png {atlas.width}x{atlas.height} ({size:,} bytes) "
          f"with {len(index):,} sprites")
    if oversized:
        print(f"  note: {len(oversized)} non-32px sprites were rescaled "
              f"(e.g. {oversized[:3]})")
    if missing_pages:
        print(f"  note: skipped pages with no image on disk: "
              f"{sorted(missing_pages)[:5]}{'...' if len(missing_pages) > 5 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
