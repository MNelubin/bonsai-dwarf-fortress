#!/usr/bin/env python3
"""Render one frame of a recording to a PNG, independently of the browser viewer.

    python render_frame.py <rec.jsonl.gz> <z> <out.png> [frame_index] [build_dir]

This exists to be LOOKED AT. The viewer's own statistics (percentage of canvas
painted, distinct colour count) are perfectly consistent with a broken render — the
first sprite build scored 53.9%/398 colours while half the grass was invisible,
because the raws pointed at art-free cells and nobody opened the picture.

It re-implements the same token rules against the same atlas, so agreement between
this and the viewer is real evidence, and disagreement localises the bug.
"""
from __future__ import annotations

import gzip
import json
import os
import pathlib
import sys

DIRS = [("N", 0, -1), ("S", 0, 1), ("W", -1, 0), ("E", 1, 0)]

# A cell painted less than this is reported as thin. Half is the "obviously broken"
# line; raise it (BONSAI_THIN_AT=0.9) to hunt features that render on a black box
# because nothing was laid underneath them.
THIN_AT = float(os.environ.get("BONSAI_THIN_AT", "0.5"))

# How many levels down to look for something to show through open air or under a
# see-through feature. Three was not enough: on the surface level 577 cells of open air
# over a valley and 162 tree parts had nothing within reach and rendered as black boxes
# scattered across the grass.
DEPTH = int(os.environ.get("BONSAI_DEPTH", "8"))


def vhash(x: int, y: int, z: int) -> int:
    h = (x * 73856093) ^ (y * 19349663) ^ (z * 83492791)
    return (h ^ (h >> 13)) & 0xFFFFFFFF


def load_frames(path: pathlib.Path):
    events = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    break
    frames, grid, origin, dims = [], None, None, None
    for m in (e for e in events if e.get("kind") == "map"):
        if m.get("keyframe") and "rle" in m:
            origin, dims = m["origin"], m["dims"]
            grid = [0] * (dims[0] * dims[1] * dims[2])
            p = 0
            rle = m["rle"]
            for i in range(0, len(rle), 2):
                v, n = rle[i], rle[i + 1]
                grid[p:p + n] = [v] * n
                p += n
        elif grid is not None and "set" in m:
            s = m["set"]
            for i in range(0, len(s), 2):
                grid[s[i]] = s[i + 1]
        if grid is not None:
            frames.append({"tick": m["tick"], "grid": list(grid), "origin": origin,
                           "dims": dims, "units": m.get("units", []),
                           "blds": m.get("blds", [])})
    return events, frames


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    from PIL import Image

    rec_path = pathlib.Path(sys.argv[1])
    z = int(sys.argv[2])
    out = pathlib.Path(sys.argv[3])
    idx = int(sys.argv[4]) if len(sys.argv) > 4 else -1
    build = pathlib.Path(sys.argv[5]) if len(sys.argv) > 5 else pathlib.Path("build")

    sprites = json.loads((build / "sprites.json").read_text(encoding="utf-8"))
    tilemap = json.loads((build / "tilemap.json").read_text(encoding="utf-8"))["tiles"]
    enums = json.loads(pathlib.Path("enums_compact.json").read_text(encoding="utf-8"))
    tt_info = {int(k): v for k, v in enums["tt"].items()}
    atlas = Image.open(build / "atlas.png").convert("RGBA")
    T, toks = sprites["tile"], sprites["tokens"]
    OPAQUE = set(sprites.get("opaque") or toks)

    events, frames = load_frames(rec_path)
    if not frames:
        print("no map track in this recording", file=sys.stderr)
        return 1
    f = frames[idx]
    W, H, _ = f["dims"]
    zi = z - f["origin"][2]

    def solid(nx, ny):
        if nx < 0 or ny < 0 or nx >= W or ny >= H:
            return True
        m = tilemap.get(str(f["grid"][zi * W * H + ny * W + nx]))
        return bool(m) and m["k"] in ("wall", "tree")

    def pick(*cands):
        return next((c for c in cands if c and c in toks), None)

    def variant_of(tt):
        v = tt_info.get(tt, [None, None, None, -1])
        return v[3] if len(v) > 3 and isinstance(v[3], int) and v[3] >= 0 else None

    def token(tt, x, y):
        m = tilemap.get(str(tt))
        if not m:
            return None
        fam, kind = m["f"], m["k"]
        gx, gy = x + f["origin"][0], y + f["origin"][1]
        var = variant_of(tt)
        if kind == "plain":
            return pick(fam)
        if kind == "var4":
            # DF's own variant index, not a hash: eight grass tiletypes are four
            # sprites x two shades, and hashing them collapsed the game's pattern
            # into uniform noise.
            i = var if var is not None else (vhash(gx, gy, z) & 3)
            return pick(f"{fam}_{i + 1}", fam + "_1")
        if kind == "floor9":
            # _1.._9 is a 3x3 EDGE-BLEND patch on the sheet, not nine variants: the
            # centre (_5) is the solid floor and the eight around it are mostly-empty
            # feathers meant to be composited ON TOP of it where a different material
            # abuts. Returning a feather INSTEAD of the centre drew a one-tile-wide
            # mined corridor as DIRT_FLOOR_4 — 47 opaque pixels out of 1024 — so a year
            # of digging rendered as black lines through the rock. The centre is the
            # tile; edges are added by edge_tokens().
            alts = ["_5", "_5B", "_5C", "_5D"]
            i = var if var is not None else (vhash(gx, gy, z) & 3)
            return pick(fam + alts[i & 3], fam + "_5", fam + "_1")
        if kind == "stair":
            shape = tt_info.get(tt, ["", ""])[0]
            suf = "_UP" if shape == "STAIR_UP" else "_DOWN" if shape == "STAIR_DOWN" else "_UPDOWN"
            return pick(fam + suf, fam + "_UPDOWN")
        on = [d for d, dx, dy in DIRS if solid(x + dx, y + dy)]
        if kind == "wall":
            key, v = "_".join(on), (vhash(gx, gy, z) % 4) + 1
            return pick(f"{fam}_{key}_{v}", f"{fam}_{key}", fam + "_N_S_W_E_1", fam + "_N_S_W_E")
        if kind == "tree":
            return pick(f"{fam}_{''.join(on)}", fam, fam + "_NSWE")
        if kind == "ramp":
            c = [n for n, (dx, dy) in
                 (("NW", (-1, -1)), ("NE", (1, -1)), ("SW", (-1, 1)), ("SE", (1, 1)))
                 if solid(x + dx, y + dy)]
            return pick(f"{fam}_{'_'.join(c)}", fam + "_OTHER",
                        fam.replace("_WITH_WALL", "_OTHER"))
        return None

    def at(x, y):
        """Chosen token at a cell, resolving ramp tops to the ramp they cap."""
        if x < 0 or y < 0 or x >= W or y >= H:
            return None
        tt = f["grid"][zi * W * H + y * W + x]
        if tt_info.get(tt, ["", ""])[0] == "RAMP_TOP" and zi > 0:
            tt = f["grid"][(zi - 1) * W * H + y * W + x]
        return token(tt, x, y)

    def base_under(x, y):
        """A ground sprite to sit a transparent feature on.

        The tiletype of a shrub or boulder says nothing about the floor beneath it, and
        the recording does not carry per-tile floor material, so take the ground the
        neighbours agree on. Better than a black hole and never invents a material the
        surrounding fort does not already have.
        """
        votes = {}
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
            t = at(x + dx, y + dy)
            if t and t in OPAQUE:
                votes[t] = votes.get(t, 0) + 1
        return max(votes, key=votes.get) if votes else None

    def edge_tokens(x, y):
        """Feathers to composite over a floor9 tile where a different material abuts.

        DF's 3x3 blend set is an overlay: _2 softens the north edge, _4 the west, _1 the
        north-west corner, and so on around the solid _5 centre. Sides are drawn before
        corners so a corner sits on top of the two sides it joins.
        """
        tt = f["grid"][zi * W * H + y * W + x]
        m = tilemap.get(str(tt))
        if not m or m["k"] != "floor9":
            return []
        fam = m["f"]

        def other(dx, dy):
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= W or ny >= H:
                return False
            m2 = tilemap.get(str(f["grid"][zi * W * H + ny * W + nx]))
            return (m2 or {}).get("f") != fam

        n, s, w, e = other(0, -1), other(0, 1), other(-1, 0), other(1, 0)
        want = []
        for flag, idx in ((n, 2), (s, 8), (w, 4), (e, 6)):
            if flag:
                want.append(idx)
        for flag, idx in ((n and w, 1), (n and e, 3), (s and w, 7), (s and e, 9)):
            if flag:
                want.append(idx)
        return [t for t in (f"{fam}_{i}" for i in want) if t in toks]

    def blit(tok, x, y):
        ax, ay = toks[tok]
        img.alpha_composite(atlas.crop((ax * T, ay * T, ax * T + T, ay * T + T)),
                            (x * T, y * T))

    def token_at_z(x, y, zoff):
        """Token at a cell on a level `zoff` below the one being viewed."""
        zj = zi - zoff
        if zj < 0 or x < 0 or y < 0 or x >= W or y >= H:
            return None
        tt = f["grid"][zj * W * H + y * W + x]
        if tt_info.get(tt, ["", ""])[0] in ("EMPTY", "NONE", "ENDLESS_PIT", "RAMP_TOP"):
            return None
        return token(tt, x, y)

    def blit_below(x, y):
        """Draw the nearest level below this cell, dimmed with distance. Returns True if
        anything was found."""
        for zoff in range(1, DEPTH + 1):
            below = token_at_z(x, y, zoff)
            if below:
                ax, ay = toks[below]
                cell = atlas.crop((ax * T, ay * T, ax * T + T, ay * T + T))
                # 0.45*zoff reached full black at three levels down, so the deepest
                # visible layer was painted pure black and still counted as painted.
                # Cap it: distance should read as depth, not as a hole.
                cell.alpha_composite(Image.new("RGBA", (T, T),
                                               (0, 0, 0, int(255 * min(0.78, 0.22 * zoff)))))
                img.alpha_composite(cell, (x * T, y * T))
                return True
        return False

    img = Image.new("RGBA", (W * T, H * T), (0, 0, 0, 0))
    drawn, holes, layered, depth = 0, {}, 0, 0
    # What tiletype ended up in each cell, so coverage can be blamed on a tiletype rather
    # than on a pixel. "Drawn" is not the same as "visible": a one-tile corridor picked
    # DIRT_FLOOR_4, a 47/1024-opaque edge feather, and counted as drawn while rendering
    # as a black line. Only measuring the composited alpha catches that class of bug.
    cell_tt = [0] * (W * H)
    for y in range(H):
        for x in range(W):
            cell_tt[y * W + x] = f["grid"][zi * W * H + y * W + x]
            tk = at(x, y)
            if not tk:
                # Open space: DF shows the levels below, dimmed with distance. Without
                # this an open tile is a black void and the fort reads as full of holes.
                if blit_below(x, y):
                    depth += 1
                else:
                    tt = f["grid"][zi * W * H + y * W + x]
                    info = tt_info.get(tt, ["?", "?", "?"])
                    if info[0] not in ("EMPTY", "NONE", "ENDLESS_PIT"):
                        holes[f"{info[0]}/{info[1]}"] = holes.get(f"{info[0]}/{info[1]}", 0) + 1
                continue
            if tk not in OPAQUE:
                # A see-through sprite needs something behind it. Neighbours first — a
                # shrub belongs on the grass around it — but a tree branch 4 levels up
                # has only other branches beside it, so it falls through to the ground
                # below, which is what DF actually shows through a canopy. Without the
                # fallback a third of the canopy levels rendered at 22-34% coverage:
                # branches and twigs floating on black.
                base = base_under(x, y)
                if base:
                    blit(base, x, y)
                    layered += 1
                elif blit_below(x, y):
                    layered += 1
            blit(tk, x, y)
            for edge in edge_tokens(x, y):
                blit(edge, x, y)
            drawn += 1

    dwarf = "CREATURE_DWARF" if "CREATURE_DWARF" in toks else None
    # Recordings made before the capture carried an explicit citizen flag fall back to
    # the pinned T0 cohort id-set - which is also exactly the set the score counts.
    meta = next((e for e in events if e.get("kind") == "meta"), {})
    cohort = {int(c) for c in
              ((meta.get("t0_raw") or {}).get("cids") or "").split(",") if c.strip()}
    for u in f["units"]:
        if u[3] != z:
            continue
        ux, uy = u[1] - f["origin"][0], u[2] - f["origin"][1]
        # A creature can wander outside the recorded bbox — the region is pinned at T0
        # and wildlife is not. Drawing it threw IndexError and killed the whole render.
        if not (0 <= ux < W and 0 <= uy < H):
            continue
        citizen = bool(u[7]) if len(u) > 7 else (u[0] in cohort)
        if citizen and dwarf:
            blit(dwarf, ux, uy)
        else:
            # wildlife: the recording carries no creature race yet, so mark it rather
            # than guess a species
            for dx in range(12, 20):
                for dy in range(12, 20):
                    img.putpixel((ux * T + dx, uy * T + dy),
                                 (180, 90, 70, 255) if not citizen else (232, 220, 192, 255))

    # Coverage is measured BEFORE the background goes on — once the dark backdrop is
    # composited every cell is opaque and an unpainted tile is indistinguishable from a
    # deliberately dark one.
    thin = coverage_report(img, cell_tt, W, H, T, tt_info, tilemap)
    backdrop = Image.new("RGBA", img.size, (13, 12, 11, 255))
    backdrop.alpha_composite(img)
    backdrop.convert("RGB").save(out, optimize=True)
    print(f"{out}  {img.width}x{img.height}  tick {f['tick']}  z={z}")
    print(f"  drew {drawn} of {W*H} tiles ({100*drawn/(W*H):.1f}%), "
          f"{layered} needed a ground layer, {depth} showed the level below")
    if holes:
        print("  UNDRAWN (would be holes in the map):")
        for k, v in sorted(holes.items(), key=lambda kv: -kv[1]):
            print(f"    {k:24} {v}")
    return 1 if thin else 0


def coverage_report(img, cell_tt, W, H, T, tt_info, tilemap) -> int:
    """Blame near-empty cells on the tiletype that produced them.

    Counting tiles "drawn" cannot see this class of bug: the renderer picks a token, the
    token exists in the atlas, and the cell still comes out black because the sprite is
    an edge feather with 5% coverage and nothing was laid under it. Alpha is the only
    thing that knows the difference between a rendered tile and a visible one.
    """
    alpha = img.getchannel("A")
    worst: dict[str, list] = {}
    for y in range(H):
        for x in range(W):
            box = alpha.crop((x * T, y * T, x * T + T, y * T + T))
            lit = sum(1 for a in box.getdata() if a > 8)
            if lit >= T * T * THIN_AT:
                continue
            tt = cell_tt[y * W + x]
            info = tt_info.get(tt, ["?", "?"])
            m = tilemap.get(str(tt)) or {}
            key = f"{info[0]}/{info[1]}" + (f" -> {m.get('f')}({m.get('k')})" if m else " -> UNMAPPED")
            e = worst.setdefault(key, [0, 0])
            e[0] += 1
            e[1] += lit
    if not worst:
        print(f"  coverage: every tile at least {THIN_AT:.0%} painted")
        return 0
    total = sum(v[0] for v in worst.values())
    print(f"  THIN CELLS: {total} of {W*H} ({100*total/(W*H):.1f}%) painted under {THIN_AT:.0%}")
    for k, (n, lit) in sorted(worst.items(), key=lambda kv: -kv[1][0])[:12]:
        print(f"    {k:52} {n:6}  avg {lit/n/(T*T)*100:5.1f}% painted")
    return total


if __name__ == "__main__":
    raise SystemExit(main())
