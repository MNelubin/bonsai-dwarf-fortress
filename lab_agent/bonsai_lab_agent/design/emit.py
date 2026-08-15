"""Turn a Design into a quickfort blueprint the fort can actually stamp.

The format is copied from DFHack's own shipped `bedrooms/28-3-Modified_Windmill_Villas.csv`
rather than invented: a `#dig` grid, then a `#meta` that chains the rest, then `#zone`,
then `#build`. That two-pass shape is the game's own answer to "you cannot build in rock
you have not dug yet".

`#dig` MUST come first. `quickfort run <file>` with no label runs the FIRST blueprint in
the file, and `library/pump_stack.csv` opens with a `#notes` help section — running it
printed a walkthrough and stamped nothing.
"""

from __future__ import annotations

from .model import Design, ZONE_KEY


def to_quickfort(d: Design, name: str = "bonsai") -> str:
    """One csv with four sections, all anchored at 1;1 so the cursor IS the corner.

    Anchoring at start(1;1) is deliberate: quickfort's CLI lands the cursor on the
    blueprint's own start() cell, so any other anchor makes the caller subtract an offset
    it has to know about. `library.cursor_for` then returns the position unchanged.
    """
    rows: list[str] = []

    # ---- dig: everything that has to become open floor, INCLUDING what will be smoothed
    #
    # You cannot smooth rock nobody has mined. The first version put `s` where a tile was
    # to be smoothed, which REPLACED its `d`, and the game said so on the first dry run:
    # "Tiles that could not be designated for digging: 11" against exactly the 11 smooth
    # cells. Smoothing is a second pass over a finished floor, the same way building is.
    rows.append(f'"#dig label(dig) start(1;1) {name}"')
    for y in range(d.h):
        line = []
        for x in range(d.w):
            line.append("d" if d.cells[y][x] in ".se+" else "")
        rows.append(",".join(line) + ",#")
    rows.append(",".join(["#"] * (d.w + 1)))

    # ---- smooth: the second pass, run once the digging has finished
    rows.append(f'"#dig label(smooth) start(1;1) hidden() {name} smoothing"')
    for y in range(d.h):
        line = []
        for x in range(d.w):
            line.append("s" if d.cells[y][x] in "se" else "")
        rows.append(",".join(line) + ",#")
    rows.append(",".join(["#"] * (d.w + 1)))

    # ---- engrave: the third pass. DF will not engrave rough stone, so an engraved cell
    # is dug in pass one and smoothed in pass two before it gets here.
    rows.append(f'"#dig label(engrave) start(1;1) hidden() {name} engraving"')
    for y in range(d.h):
        line = []
        for x in range(d.w):
            line.append("e" if d.cells[y][x] == "e" else "")
        rows.append(",".join(line) + ",#")
    rows.append(",".join(["#"] * (d.w + 1)))

    # ---- meta: smoothing, engraving, the zone and the build, once the digging is done
    rows.append(f'"#meta label(rooms) start(1;1) {name} rooms"')
    rows.append("smooth/smooth,#")
    rows.append("engrave/engrave,#")
    rows.append("zone/zone,#")
    rows.append("build/build,#")
    rows.append(",".join(["#"] * (d.w + 1)))

    # ---- zone: one rectangle stamp over the interior
    rows.append(f'"#zone label(zone) start(1;1) hidden() {name}"')
    zone = d.zone_cells
    key = ZONE_KEY.get(d.kind, "b")
    if zone:
        xs = [x for x, _ in zone]
        ys = [y for _, y in zone]
        x0, y0 = min(xs), min(ys)
        zw, zh = max(xs) - x0 + 1, max(ys) - y0 + 1
        for y in range(d.h):
            line = []
            for x in range(d.w):
                line.append(f"{key}({zw}x{zh})" if (x, y) == (x0, y0) else "")
            rows.append(",".join(line) + ",#")
    rows.append(",".join(["#"] * (d.w + 1)))

    # ---- build: the furniture, plus a door in the doorway
    rows.append(f'"#build label(build) start(1;1) hidden() {name}"')
    at = {(x, y): k for x, y, k in d.pieces}
    for y in range(d.h):
        line = []
        for x in range(d.w):
            if d.cells[y][x] == "+":
                line.append("d")
            else:
                line.append(at.get((x, y), ""))
        rows.append(",".join(line) + ",#")
    rows.append(",".join(["#"] * (d.w + 1)))

    return "\n".join(rows) + "\n"
