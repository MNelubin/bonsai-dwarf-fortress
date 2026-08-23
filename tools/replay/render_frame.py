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
import re
import sys
from array import array

from entity_sprites import building_cells, creature_token, item_token, liquid_token

DIRS = [("N", 0, -1), ("S", 0, 1), ("W", -1, 0), ("E", 1, 0)]


def canonical_ramp_suffix(parts) -> str:
    """Return the spelling used by the premium raws for a ramp wall mask.

    The all-cardinal token is the sole irregular spelling: N_S_E_W. Every other
    cardinal combination follows N,S,W,E order.
    """
    parts = set(parts)
    card = [d for d in ("N", "S", "W", "E") if d in parts]
    if len(card) == 4:
        card = ["N", "S", "E", "W"]
    return "_".join(card + [d for d in ("NW", "NE", "SW", "SE") if d in parts])


def decode_floor_flag(flag: int) -> dict[str, int]:
    """Decode VIEWPORT_FLOOR_FLAG bytes in the order published by DFHack."""
    flag = int(flag or 0)
    out = {}
    for name in ("S", "W", "E", "N"):
        out[name], flag = flag & 0xFF, flag >> 8
    out["special"] = flag & 0x7
    return out


def ramp_suffix_from_flag(flag: int) -> str:
    """Decode the eight wall bits of VIEWPORT_RAMP_FLAG into a raw token suffix."""
    bits = int(flag or 0) >> 8  # low byte is ramp type
    order = ("N", "W", "E", "S", "NW", "NE", "SW", "SE")
    return canonical_ramp_suffix(d for i, d in enumerate(order) if bits & (1 << i))


def grass_edge_fragments(is_grass_neighbor) -> list[str]:
    """Return DF's transparent grass fragments for one foreign floor cell.

    ``GRASS_5*`` are opaque turf centres. The other eight cells on the same sheet
    belong in neighbouring cells; they are not alternate textures for the foreign
    floor. Keeping this source-centric prevents stone-on-stone double drawing.
    """
    neighbours = (
        (0, -1, "GRASS_8"), (0, 1, "GRASS_2"),
        (-1, 0, "GRASS_6"), (1, 0, "GRASS_4"),
        (-1, -1, "GRASS_9"), (1, -1, "GRASS_7"),
        (-1, 1, "GRASS_3"), (1, 1, "GRASS_1"),
    )
    return [token for dx, dy, token in neighbours if is_grass_neighbor(dx, dy)]

# A cell painted less than this is reported as thin. Half is the "obviously broken"
# line; raise it (BONSAI_THIN_AT=0.9) to hunt features that render on a black box
# because nothing was laid underneath them.
THIN_AT = float(os.environ.get("BONSAI_THIN_AT", "0.5"))
WALL_INTERIOR = "__WALL_INTERIOR__"

# How many levels down to look for something to show through open air or under a
# see-through feature. Three was not enough: on the surface level 577 cells of open air
# over a valley and 162 tree parts had nothing within reach and rendered as black boxes
# scattered across the grass.
DEPTH = int(os.environ.get("BONSAI_DEPTH", "8"))

# Palette row used for wood when the recording does not say which tree it is. DF colours
# a trunk by its species; the geology dump knows the rock under the tree, not the tree,
# and painting a branch mudstone-grey is worse than painting every tree brown.
WOOD_ROW = 13                                        # PALETTE_COLOR:BROWN:13
WOODY = {"TREE", "MUSHROOM", "PLANT"}                # tiletype material classes

# Shapes that STAND ON something and therefore need ground drawn under them. Everything
# else fills its own tile and DF draws it over black.
#
# This used to be decided by sprite opacity, which is wrong for exactly the tiles that
# matter most. A wall sprite is deliberately semi-transparent — SOIL_WALL_N_S_W_E_1 has
# eight alpha levels (mean 170), STONE_WALL_N_S_W_E_1 has four (mean 127) — because the
# ALPHA IS THE TEXTURE: over black it reads as dark rock with pale mineral flecks, which
# is what the game shows. Filling those gaps with the level below washed the rock out
# into a bright field, the inverse of the real thing.
FEATURE_SHAPES = {"SHRUB", "SAPLING", "BOULDER", "PEBBLES",
                  "TWIG", "BRANCH", "TRUNK_BRANCH"}
# A grass tile in the game is SOIL with blades on top (verified against a paused
# in-game frame): a dark earth base showing through sparse green blades. The
# plant page's turf cells are a species overlay, not the floor.


def load_palette(build):
    """Key colours, the 137-row swap table, and which tokens take part. None if absent."""
    p = build / "palette.json"
    if not p.is_file():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    d["key"] = [tuple(c) for c in d["key"]]
    d["tokens"] = set(d["tokens"])
    return d


def load_geology(build):
    """Per-tile palette row for the save, expanded from the RLE dump. None if absent."""
    for name in ("geology.json.gz", "geology.json"):
        p = build / name
        if not p.is_file():
            continue
        opener = gzip.open if name.endswith(".gz") else open
        with opener(p, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        w, h, dep = d["dims"]
        grid = [0] * (w * h * dep)
        i, rle = 0, d["prle"]
        for k in range(0, len(rle), 2):
            v, n = rle[k], rle[k + 1]
            grid[i:i + n] = [v] * n
            i += n
        d["grid"] = grid
        return d
    return None


def vhash(x: int, y: int, z: int) -> int:
    h = (x * 73856093) ^ (y * 19349663) ^ (z * 83492791)
    return (h ^ (h >> 13)) & 0xFFFFFFFF


def ramp_connection_suffix(solid_at, x: int, y: int) -> str:
    """Premium ramp token suffix for the walls around one ramp cell."""
    card = {d: solid_at(x + dx, y + dy) for d, dx, dy in DIRS}
    out = [d for d, _, _ in DIRS if card[d]]
    for d, dx, dy, a, b in (("NW", -1, -1, "N", "W"),
                            ("NE", 1, -1, "N", "E"),
                            ("SW", -1, 1, "S", "W"),
                            ("SE", 1, 1, "S", "E")):
        if not card[a] and not card[b] and solid_at(x + dx, y + dy):
            out.append(d)
    return canonical_ramp_suffix(out)


def exposed_wall_suffix(solid_at, x: int, y: int) -> str:
    """Premium wall suffix for the borders that are not joined to solid terrain."""
    return "_".join(d for d, dx, dy in DIRS if not solid_at(x + dx, y + dy))


def hidden_detail_variant(x: int, y: int, z: int) -> int:
    """0 for plain hidden background, otherwise one of DF's five detail frames."""
    hv = vhash(x, y, z)
    return ((hv >> 5) % 5) + 1 if (hv & 31) == 0 else 0


def tile_wall_suffix(tile_info: list) -> str | None:
    """Return the directional wall token encoded by DF's tiletype itself.

    Smooth and constructed walls retain an explicit L/R/U/D graphical form. Recomputing
    it from nearby solid cells changes the sprite at room boundaries and produces a box
    around each cell. The digit-bearing corner forms need a separate mapping and remain
    on the neighbour fallback until we have captured each form from the live viewport.
    """
    description = str(tile_info[2]) if len(tile_info) > 2 else ""
    match = re.search(r"\b([LRUD]+)$", description)
    if not match:
        return None
    # L/R/U/D are connected neighbours; premium wall tokens name the exposed
    # borders, so the sprite mask is their complement.
    letters = set(match.group(1))
    return "_".join(direction for direction, letter in
                    (("N", "U"), ("S", "D"), ("W", "L"), ("E", "R"))
                    if letter not in letters)


def load_frames(path: pathlib.Path):
    events = []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    break
    frames, grid, palette_grid, origin, dims = [], None, None, None, None
    for m in (e for e in events if e.get("kind") in ("map", "kf", "d")):
        if (m.get("keyframe") or m.get("kind") == "kf") and "rle" in m:
            origin, dims = m["origin"], m["dims"]
            grid = array("H", [0]) * (dims[0] * dims[1] * dims[2])
            p = 0
            rle = m["rle"]
            for i in range(0, len(rle), 2):
                v, n = rle[i], rle[i + 1]
                grid[p:p + n] = array("H", [v]) * n
                p += n
        elif grid is not None and "set" in m:
            s = m["set"]
            for i in range(0, len(s), 2):
                grid[s[i]] = s[i + 1]
        if grid is not None:
            # Fog of war. Absent in recordings made before the capture carried it; those
            # render with everything revealed, which is what the game would NOT show.
            fog = None
            if "hrle" in m:
                fog = bytearray(len(grid))
                p, h = 0, m["hrle"]
                for i in range(0, len(h), 2):
                    v, n = h[i], h[i + 1]
                    fog[p:p + n] = bytes([v]) * n
                    p += n
            liquid = None
            if "lrle" in m:
                liquid = bytearray(len(grid))
                p, h = 0, m["lrle"]
                for i in range(0, len(h), 2):
                    v, n = h[i], h[i + 1]
                    liquid[p:p + n] = bytes([v]) * n
                    p += n
            if "prle" in m:
                palette_grid = bytearray(len(grid))
                p, h = 0, m["prle"]
                for i in range(0, len(h), 2):
                    v, n = h[i], h[i + 1]
                    palette_grid[p:p + n] = bytes([v]) * n
                    p += n
            elif palette_grid is not None and "pset" in m:
                h = m["pset"]
                for i in range(0, len(h), 2):
                    palette_grid[h[i]] = h[i + 1]
            viewport = m.get("viewport")
            if viewport:
                viewport = dict(viewport)
                viewport["texrefs"] = {int(row[0]): f"{row[1]}:{row[2]}:{row[3]}"
                                       for row in viewport.get("tex", [])}
                for src, dst in (("bgrle", "bg"), ("bg2rle", "bg2"),
                                 ("frle", "floor"), ("rrle", "ramp"),
                                 ("srle", "shadow"), ("trle", "top")):
                    if src not in viewport:
                        continue
                    values = []
                    runs = viewport[src]
                    for i in range(0, len(runs), 2):
                        values.extend([runs[i]] * runs[i + 1])
                    viewport[dst] = values
            frames.append({"tick": m["tick"], "grid": array("H", grid), "origin": origin,
                           "dims": dims, "units": m.get("units", []),
                           "blds": m.get("blds", []), "items": m.get("items", []),
                           "fog": fog, "liquid": liquid,
                           "palette": bytes(palette_grid) if palette_grid is not None else None,
                           "dfv": m.get("dfv"), "viewport": viewport})
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
    sprite_tokens = set(toks)
    OPAQUE = set(sprites.get("opaque") or toks)
    PAL = load_palette(build)
    GEO = load_geology(build)

    events, frames = load_frames(rec_path)
    if not frames:
        print("no map track in this recording", file=sys.stderr)
        return 1
    f = frames[idx]
    if f.get("dfv") and f["dfv"] not in enums.get("df", ""):
        print(f"version mismatch: recording DF {f['dfv']} vs enums {enums.get('df')}",
              file=sys.stderr)
        return 2
    W, H, _ = f["dims"]
    zi = z - f["origin"][2]

    def solid(nx, ny, zj=zi):
        if nx < 0 or ny < 0 or nx >= W or ny >= H:
            return True
        if zj < 0 or zj >= f["dims"][2]:
            return True
        m = tilemap.get(str(f["grid"][zj * W * H + ny * W + nx]))
        return bool(m) and m["k"] in ("wall", "tree")

    def pick(*cands):
        return next((c for c in cands if c and c in toks), None)

    # Generic soil floor, used as the underlay under sparse surface sprites when
    # no opaque neighbour can be voted on. DIRT_FLOOR_5 is a full 32x32 opaque cell.
    GROUND = pick("DIRT_FLOOR_5", "PEBBLES_FLOOR_5")

    def variant_of(tt):
        v = tt_info.get(tt, [None, None, None, -1])
        return v[3] if len(v) > 3 and isinstance(v[3], int) and v[3] >= 0 else None

    def ramp_suffix(x, y, zj):
        """DF's ramp connectivity: cardinals, then exposed diagonal corners."""
        exact = viewport_value("ramp", x, y, zj)
        if exact is not None:
            return ramp_suffix_from_flag(exact)
        return ramp_connection_suffix(lambda nx, ny: solid(nx, ny, zj), x, y)

    def viewport_value(field, x, y, zj=zi):
        """Engine-selected value for this cell, or None outside the captured viewport."""
        if os.environ.get("BONSAI_IGNORE_VIEWPORT") == "1":
            return None
        vp = f.get("viewport")
        if not vp or zj + f["origin"][2] != vp["origin"][2]:
            return None
        wx, wy = x + f["origin"][0], y + f["origin"][1]
        vx, vy, _ = vp["origin"]
        vw, vh = vp["dims"]
        sx, sy = wx - vx, wy - vy
        values = vp.get(field)
        if values is None or sx < 0 or sy < 0 or sx >= vw or sy >= vh:
            return None
        return values[sy * vw + sx]

    def viewport_token(field, x, y, zj=zi):
        """Resolve an unstable runtime texpos through its stable raw page/cell."""
        texpos = viewport_value(field, x, y, zj)
        vp = f.get("viewport") or {}
        source = (vp.get("texrefs") or {}).get(texpos)
        return (sprites.get("source_tokens") or {}).get(source)

    def ramp_family(prefix, x, y, zj):
        suffix = ramp_suffix(x, y, zj)
        return pick(f"{prefix}_WITH_WALL_{suffix}" if suffix else None,
                    prefix + "_OTHER")

    def token(tt, x, y, zj=zi):
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
        on = [d for d, dx, dy in DIRS if solid(x + dx, y + dy, zj)]
        if kind == "wall":
            encoded = tile_wall_suffix(tt_info.get(tt, []))
            # Premium wall token names are exposed borders, not connected wall
            # neighbours. Direction-bearing smooth/construction tiletypes already
            # arrive complemented through tile_wall_suffix(); natural walls need the
            # same complement applied to the neighbour-derived fallback.
            exposed = exposed_wall_suffix(lambda nx, ny: solid(nx, ny, zj), x, y)
            key = encoded if encoded is not None else exposed
            if key == "":
                return WALL_INTERIOR
            v = (vhash(gx, gy, z) % 4) + 1
            return pick(f"{fam}_{key}_{v}", f"{fam}_{key}", fam + "_N_S_W_E_1", fam + "_N_S_W_E")
        if kind == "tree":
            return pick(f"{fam}_{''.join(on)}", fam, fam + "_NSWE")
        if kind == "ramp":
            base = fam.removesuffix("_WITH_WALL")
            return ramp_family(base + "_RAMP" if not base.endswith("_RAMP") else base,
                               x, y, zj)
        return None

    def at(x, y):
        """Chosen token at a cell, including the distinct multilevel ramp-top art."""
        if x < 0 or y < 0 or x >= W or y >= H:
            return None
        tt = f["grid"][zi * W * H + y * W + x]
        shape = tt_info.get(tt, ["", ""])[0]
        # Renderer-selected backgrounds give us the exact family and variant. Feature
        # tiletypes (plants/trees) use later viewport layers that are not all captured
        # yet, so retain their semantic reconstruction for now.
        exact = viewport_token("bg", x, y)
        terrain = tilemap.get(str(tt))
        if (exact and (terrain or {}).get("k") != "tree"
                and shape not in FEATURE_SHAPES):
            return exact
        if shape == "RAMP_TOP" and zi > 0:
            below = f["grid"][(zi - 1) * W * H + y * W + x]
            if tt_info.get(below, ["", ""])[0] == "RAMP":
                return ramp_family("MULTILEVEL_RAMP", x, y, zi - 1)
        return token(tt, x, y, zi)

    def base_under(x, y):
        """A ground sprite to sit a transparent feature on.

        Prefer DF's captured background at the feature cell. Older/outside-viewport
        captures do not have it, so search outward for the nearest actual floor. The
        bounded rings also repair orphan RAMP_TOP cells at the padded edge of a
        one-z-level capture without turning arbitrary open space into terrain.
        """
        exact = viewport_token("bg", x, y)
        if exact and exact in OPAQUE:
            return exact, 0

        def floor_at(nx, ny):
            if nx < 0 or ny < 0 or nx >= W or ny >= H:
                return None
            ntt = f["grid"][zi * W * H + ny * W + nx]
            nm = tilemap.get(str(ntt)) or {}
            family, kind = nm.get("f", ""), nm.get("k")
            ground = (kind in ("floor9", "var4") or
                      (kind == "plain" and (family.startswith("FLOOR_") or
                                            family in ("SMOOTH_ICE_FLOOR", "BROOK_BED"))))
            if not ground:
                return None
            t = at(nx, ny)
            return (t, palette_row(nx, ny, z)) if t and t in OPAQUE else None

        for radius in range(1, 5):
            votes = {}
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    candidate = floor_at(x + dx, y + dy)
                    if candidate:
                        votes[candidate] = votes.get(candidate, 0) + 1
            if votes:
                return max(votes, key=votes.get)
        return None

    def edge_tokens(x, y):
        """Transparent grass from neighbouring cells, over one foreign floor.

        The ZCode crops establish grass crossing tile borders via the eight
        non-centre cells of DF's GRASS sheet. They do not justify drawing this
        cell's stone/soil texture a second time, so other material transitions stay
        disabled until they are confirmed from a real frame.
        """
        tt = f["grid"][zi * W * H + y * W + x]
        m = tilemap.get(str(tt))
        if not m or m["k"] != "floor9":
            return []

        def grass(dx, dy):
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= W or ny >= H:
                return False
            m2 = tilemap.get(str(f["grid"][zi * W * H + ny * W + nx]))
            return (m2 or {}).get("f") == "PLANT_GRASS"

        # GRASS art already carries its final greens. Applying this stone cell's
        # palette row would recreate the material-on-material overlay in the old shots.
        return [(t, 0) for t in grass_edge_fragments(grass) if t in toks]

    # ---------------------------------------------------------------- palette recolour
    # DF draws natural rock, soil and wood from GREYSCALE key art and swaps the key
    # colours for the row belonging to the tile's material. Drawing the key art unswapped
    # is why soil walls came out grey when the soil FLOOR beside them was brown.
    nearest = {}

    def key_index(c):
        i = nearest.get(c)
        if i is not None:
            return i if i >= 0 else None
        best, bd = -1, 7
        for j, k in enumerate(PAL["key"]):
            d = max(abs(c[0] - k[0]), abs(c[1] - k[1]), abs(c[2] - k[2]))
            if d < bd:
                best, bd = j, d
        nearest[c] = best if bd <= 6 else -1
        return best if bd <= 6 else None

    swapped = {}

    def sprite(tok, row):
        """The atlas cell for a token, recoloured to a palette row. Cached per pair."""
        if tok == WALL_INTERIOR:
            return Image.new("RGBA", (T, T), (0, 0, 0, 0))
        ax, ay = toks[tok]
        if not PAL or row <= 0 or tok not in PAL["tokens"]:
            return atlas.crop((ax * T, ay * T, ax * T + T, ay * T + T))
        hit = swapped.get((tok, row))
        if hit is not None:
            return hit
        cell = atlas.crop((ax * T, ay * T, ax * T + T, ay * T + T)).copy()
        table, px = PAL["table"][row], cell.load()
        for yy in range(T):
            for xx in range(T):
                r, g, b, a = px[xx, yy]
                if a > 8:
                    i = key_index((r, g, b))
                    if i is not None:
                        nr, ng, nb = table[i]
                        px[xx, yy] = (nr, ng, nb, a)
        swapped[(tok, row)] = cell
        return cell

    def palette_row(x, y, zz):
        """Which palette row this cell's material calls for. 0 means leave the art alone."""
        if f.get("palette") is not None:
            return f["palette"][(zz - f["origin"][2]) * W * H + y * W + x]
        if not GEO:
            return 0
        tt = f["grid"][(zz - f["origin"][2]) * W * H + y * W + x]
        # Wood is not geology: a trunk is coloured by its species, and the dump knows the
        # rock under the tree. One brown for every tree beats mudstone-coloured branches.
        if (tt_info.get(tt, ["", ""])[1] or "") in WOODY:
            return WOOD_ROW
        gx, gy, gz = x + f["origin"][0], y + f["origin"][1], zz
        ox, oy, oz = GEO["origin"]
        gw, gh, gd = GEO["dims"]
        ix, iy, iz = gx - ox, gy - oy, gz - oz
        if not (0 <= ix < gw and 0 <= iy < gh and 0 <= iz < gd):
            return 0
        return GEO["grid"][iz * gw * gh + iy * gw + ix]

    def blit(tok, x, y, row=0):
        img.alpha_composite(sprite(tok, row), (x * T, y * T))

    def wall_backdrop(x, y, row):
        """Opaque material-colour backing required by translucent wall key art."""
        if PAL and 0 < row < len(PAL["table"]):
            r, g, b = PAL["table"][row][9]
        else:
            r, g, b = (47, 48, 56)
        img.alpha_composite(Image.new("RGBA", (T, T), (r, g, b, 255)), (x * T, y * T))


    def token_at_z(x, y, zoff):
        """Token at a cell on a level `zoff` below the one being viewed."""
        zj = zi - zoff
        if zj < 0 or x < 0 or y < 0 or x >= W or y >= H:
            return None
        tt = f["grid"][zj * W * H + y * W + x]
        if tt_info.get(tt, ["", ""])[0] in ("EMPTY", "NONE", "ENDLESS_PIT", "RAMP_TOP"):
            return None
        return token(tt, x, y, zj)

    def blit_below(x, y):
        """Draw the nearest level below this cell, dimmed with distance. Returns True if
        anything was found."""
        for zoff in range(1, DEPTH + 1):
            below = token_at_z(x, y, zoff)
            if below:
                cell = sprite(below, palette_row(x, y, z - zoff)).copy()
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
    FOG = f.get("fog")
    unseen = 0
    for y in range(H):
        for x in range(W):
            cell_tt[y * W + x] = f["grid"][zi * W * H + y * W + x]
            # Premium DF has dedicated unrevealed-rock art. Pure black made a revealed
            # corridor look like a wall and let entities appear to stand "inside" it.
            if FOG is not None and FOG[zi * W * H + y * W + x]:
                unseen += 1
                gx, gy = x + f["origin"][0], y + f["origin"][1]
                # The real frame is mostly the HIDDEN_ROCK background colour. Its five
                # rock-detail cells are a sparse animated variation, not a tile pattern
                # stamped over every unrevealed cell. A second hash avoids a regular
                # grid and pins the roughly 1/32 density measured in the reference shot.
                img.alpha_composite(Image.new("RGBA", (T, T), (49, 44, 52, 255)),
                                    (x * T, y * T))
                variant = hidden_detail_variant(gx, gy, z)
                if variant:
                    hidden = pick(f"HIDDEN_ROCK_{variant}", "HIDDEN_ROCK_1")
                    if hidden:
                        blit(hidden, x, y)
                continue
            tk = at(x, y)
            if not tk:
                # Open space: DF shows the levels below, dimmed with distance. Without
                # this an open tile is a black void and the fort reads as full of holes.
                tt = f["grid"][zi * W * H + y * W + x]
                info = tt_info.get(tt, ["?", "?", "?"])
                base = base_under(x, y) if info[0] == "RAMP_TOP" else None
                if base:
                    blit(base[0], x, y, base[1])
                    layered += 1
                elif blit_below(x, y):
                    depth += 1
                else:
                    if info[0] not in ("EMPTY", "NONE", "ENDLESS_PIT"):
                        holes[f"{info[0]}/{info[1]}"] = holes.get(f"{info[0]}/{info[1]}", 0) + 1
                continue
            row = palette_row(x, y, z)
            m = tilemap.get(str(cell_tt[y * W + x]))
            shape = tt_info.get(cell_tt[y * W + x], ["", ""])[0]
            if shape == "RAMP_TOP" and zi > 0:
                below_tt = f["grid"][(zi - 1) * W * H + y * W + x]
                if tt_info.get(below_tt, ["", ""])[0] == "RAMP":
                    # MULTILEVEL_RAMP is translucent transition/shadow art. It is not
                    # a terrain base: on an empty canvas it becomes the black/cyan
                    # wedges seen in the old upper-level render. DF first exposes the
                    # material ramp from z-1 and composites the multilevel pass above.
                    below_base = token(below_tt, x, y, zi - 1)
                    if below_base:
                        blit(below_base, x, y, palette_row(x, y, z - 1))
            if m and m["k"] == "wall":
                # Wall sprites are intentionally translucent key art. DF composites
                # them over an opaque material-colour cell; compositing straight over
                # our transparent canvas is what produced the half-black walls.
                wall_backdrop(x, y, row)
                if tk == WALL_INTERIOR:
                    drawn += 1
                    continue
            if (shape in FEATURE_SHAPES or (m or {}).get("k") == "tree"):
                # A shrub belongs on the grass around it; a tree branch four levels up has
                # only other branches beside it, so it falls through to the ground below,
                # which is what DF shows through a canopy.
                base = base_under(x, y)
                if base:
                    blit(base[0], x, y, base[1])
                    layered += 1
                elif blit_below(x, y):
                    layered += 1
            blit(tk, x, y, row)
            if shape == "RAMP":
                if overlay := ramp_family("OVERLAY_RAMP", x, y, zi):
                    blit(overlay, x, y)
                # Ramp lighting is another raw pass, separate from both the material
                # slope and its outline. Compose the straight side pieces for every
                # cardinal wall touching the ramp.
                for d, dx, dy in DIRS:
                    if solid(x + dx, y + dy, zi):
                        if shadow := pick("RAMP_SHADOW_ON_RAMP_" + d):
                            blit(shadow, x, y)
            for edge, edge_row in edge_tokens(x, y):
                blit(edge, x, y, edge_row)
            drawn += 1

    # The wall texture is only the base layer. DF adds a separate shadow onto each
    # neighbouring revealed walkable tile; omitting it flattened rooms into a grid of
    # unrelated squares. Straight pieces are safe to compose and cover all four sides.
    for y in range(H):
        for x in range(W):
            p = zi * W * H + y * W + x
            if FOG is not None and FOG[p]:
                continue
            here = tilemap.get(str(f["grid"][p]))
            if here and here["k"] in ("wall", "tree"):
                continue
            for d, dx, dy in DIRS:
                nx, ny = x + dx, y + dy
                near = (tilemap.get(str(f["grid"][zi * W * H + ny * W + nx]))
                        if 0 <= nx < W and 0 <= ny < H else None)
                if near and near["k"] == "wall":
                    shadow = pick("WALL_SHADOW_STRAIGHT_" + d)
                    if shadow:
                        blit(shadow, x, y)

    # Liquids are a surface layer in DF. The recorder preserves depth and water/magma;
    # both are rendered from the game's own WATER/MAGMA tokens over the terrain.
    liquid = f.get("liquid")
    if liquid is not None:
        for y in range(H):
            for x in range(W):
                p = zi * W * H + y * W + x
                if FOG is not None and FOG[p]:
                    continue
                if tok := liquid_token(liquid[p], sprite_tokens):
                    blit(tok, x, y)

    # Furniture and workshops are buildings in DF, not terrain. Only render a building
    # when we have its real graphical token. Invented footprint rectangles made unknown
    # buildings and old Construction records look like boxed wall sprites.
    building_footprints = set()
    for b in f["blds"]:
        if len(b) < 7 or b[6] != z:
            continue
        cells = building_cells(b, enums, sprite_tokens)
        if cells:
            for gx, gy, tok in cells:
                building_footprints.add((gx, gy, b[6]))
                x, y = gx - f["origin"][0], gy - f["origin"][1]
                p = zi * W * H + y * W + x if 0 <= x < W and 0 <= y < H else -1
                if p >= 0 and not (FOG is not None and FOG[p]):
                    # Workshop/furnace art already contains its own base and overlay
                    # passes. Applying the construction material palette here painted
                    # a second full-footprint material sheet over the building.
                    blit(tok, x, y, 0)

    # On-ground items use their real item family and material. Inventory/building
    # components were filtered by the capture, so a workshop no longer becomes a pile
    # of duplicate dots.
    visible_items = {}
    for it in f["items"]:
        if len(it) >= 5:
            key = (it[2], it[3], it[4])
            # Recordings made before the explicit on-ground marker contain workshop
            # inventory collapsed onto the building centre. Never turn that legacy
            # capture bug into a random object painted over a valid workshop sprite.
            if len(it) <= 13:
                gx, gy, gz = key
                lx, ly = gx - f["origin"][0], gy - f["origin"][1]
                lz = gz - f["origin"][2]
                construction_tile = False
                if 0 <= lx < W and 0 <= ly < H and 0 <= lz < f["dims"][2]:
                    terrain_tt = f["grid"][lz * W * H + ly * W + lx]
                    construction_tile = tt_info.get(terrain_tt, ["", ""])[1] == "CONSTRUCTION"
                if key in building_footprints or construction_tile:
                    continue
            visible_items[key] = it
    for it in visible_items.values():
        if len(it) < 5 or it[4] != z:
            continue
        tok = item_token(it, enums, sprite_tokens)
        x, y = it[2] - f["origin"][0], it[3] - f["origin"][1]
        p = zi * W * H + y * W + x if 0 <= x < W and 0 <= y < H else -1
        if tok and p >= 0 and not (FOG is not None and FOG[p]):
            blit(tok, x, y, it[11] if len(it) > 11 else 0)

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
        if FOG is not None and FOG[zi * W * H + uy * W + ux]:
            continue
        citizen = bool(u[7]) if len(u) > 7 else (u[0] in cohort)
        ctok = creature_token(u, sprite_tokens)
        if ctok:
            blit(ctok, ux, uy)
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
    thin = coverage_report(img, cell_tt, W, H, T, tt_info, tilemap,
                           FOG, zi)
    backdrop = Image.new("RGBA", img.size, (13, 12, 11, 255))
    backdrop.alpha_composite(img)
    crop = os.environ.get("BONSAI_CROP")
    if crop:
        try:
            cx1, cy1, cx2, cy2 = (int(v) for v in crop.split(","))
            lx1, ly1 = cx1 - f["origin"][0], cy1 - f["origin"][1]
            lx2, ly2 = cx2 - f["origin"][0] + 1, cy2 - f["origin"][1] + 1
            box = (max(0, lx1) * T, max(0, ly1) * T,
                   min(W, lx2) * T, min(H, ly2) * T)
            if box[2] > box[0] and box[3] > box[1]:
                backdrop = backdrop.crop(box)
            else:
                raise ValueError("viewport is outside the capture")
        except (TypeError, ValueError) as exc:
            print(f"invalid BONSAI_CROP={crop!r}: {exc}", file=sys.stderr)
            return 2
    backdrop.convert("RGB").save(out, optimize=True)
    print(f"{out}  {backdrop.width}x{backdrop.height}  tick {f['tick']}  z={z}")
    print(f"  drew {drawn} of {W*H} tiles ({100*drawn/(W*H):.1f}%), "
          f"{layered} needed a ground layer, {depth} showed the level below")
    if FOG is None:
        print("  NO FOG TRACK - recording predates it, so undiscovered rock is "
              "shown as if the player had seen it")
    else:
        print(f"  fog of war: {unseen} of {W*H} cells undiscovered "
              f"({100*unseen/(W*H):.1f}%) using DF's hidden-rock sprites")
    if holes:
        print("  UNDRAWN (would be holes in the map):")
        for k, v in sorted(holes.items(), key=lambda kv: -kv[1]):
            print(f"    {k:24} {v}")
    return 1 if thin else 0


def coverage_report(img, cell_tt, W, H, T, tt_info, tilemap, fog=None, zi=0) -> int:
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
            if fog is not None and fog[zi * W * H + y * W + x]:
                continue                      # black on purpose, not a hole
            tt = cell_tt[y * W + x]
            info = tt_info.get(tt, ["?", "?"])
            # These sprites intentionally use alpha as texture/silhouette. The real game
            # draws stone walls over black (dark rock with pale flecks) and branches as
            # sparse canopy. Treating their designed transparency as a missing render
            # made the verifier reject the frame that visually matches Steam.
            if info[0] in ("WALL", "FORTIFICATION", "TREE", "BRANCH",
                           "TRUNK_BRANCH", "TWIG"):
                continue
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
