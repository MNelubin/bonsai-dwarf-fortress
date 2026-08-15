"""Is this design a room, or only a shape?

`validate` returns REASONS, never a bare False. A search rejects thousands of candidates
and a bare False tells you nothing about which rule is doing the rejecting — and one of
these rules exists specifically because the search will otherwise find an exploit and
present it as a triumph.
"""

from __future__ import annotations

from .model import ALLOW_ENGRAVE, FUNCTIONAL, PIECE_KEYS, Design, Requirement, TILE_VALUE

# A statue is treated as blocking. Its passability was NOT settled: `df.building_type.attrs`
# carries only classname and name, and the vmethods that would answer it need an instance.
# The conservative reading is the one that cannot produce a room a dwarf gets stuck in, and
# the statue is the best value-per-piece in the game by a factor of two and a half, so an
# optimistic reading here would be an incentive to wall the room off with them.
BLOCKING = {"s"}


def validate(d: Design, req: Requirement) -> list[str]:
    reasons: list[str] = []

    if d.kind != req.kind:
        reasons.append(f"design is a {d.kind}, requirement is a {req.kind}")
    if d.w > req.max_w or d.h > req.max_h:
        reasons.append(f"{d.w}x{d.h} does not fit in {req.max_w}x{req.max_h}")

    # a) enclosed: the border is rock, except the one doorway
    doors = [(x, y) for y in range(d.h) for x in range(d.w) if d.cells[y][x] == "+"]
    for y in range(d.h):
        for x in range(d.w):
            edge = x in (0, d.w - 1) or y in (0, d.h - 1)
            if edge and d.cells[y][x] in TILE_VALUE:
                reasons.append(f"the room is open at {x},{y}")
                break

    # b) exactly one door, on a wall, not in a corner
    if len(doors) != 1:
        reasons.append(f"{len(doors)} doorways, want exactly 1")
    else:
        dx, dy = doors[0]
        on_edge = dx in (0, d.w - 1) or dy in (0, d.h - 1)
        corner = dx in (0, d.w - 1) and dy in (0, d.h - 1)
        if not on_edge:
            reasons.append("the doorway is not on a wall")
        if corner:
            reasons.append("the doorway is in a corner, which opens onto nothing")
        inside = [(dx + ox, dy + oy) for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                  if d.at(dx + ox, dy + oy) in TILE_VALUE]
        if len(inside) != 1:
            reasons.append(f"the doorway touches {len(inside)} room tiles, want 1")

    # c) the zone is one connected piece
    zone = set(d.zone_cells)
    if not zone:
        reasons.append("the room has no floor")
    else:
        start = min(zone)
        seen, stack = {start}, [start]
        while stack:
            x, y = stack.pop()
            for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + ox, y + oy)
                if n in zone and n not in seen:
                    seen.add(n)
                    stack.append(n)
        if len(seen) != len(zone):
            reasons.append(f"the room is in {len(zone) - len(seen)} disconnected pieces")

    # d) furniture: on the floor, one per tile, and nothing on the doorway
    occupied: dict[tuple[int, int], str] = {}
    for x, y, key in d.pieces:
        if key not in PIECE_KEYS:
            reasons.append(f"{key!r} is not a quickfort build key")
        if (x, y) in occupied:
            reasons.append(f"two pieces on {x},{y}")
        occupied[(x, y)] = key
        if (x, y) not in zone:
            reasons.append(f"a {PIECE_KEYS.get(key, key)} at {x},{y} is not in the room")

    # e) every piece can be walked to from inside the door
    if zone and len(doors) == 1:
        dx, dy = doors[0]
        entry = [(dx + ox, dy + oy) for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                 if (dx + ox, dy + oy) in zone]
        if entry:
            blocked = {p for p, k in occupied.items() if k in BLOCKING}
            walk = {c for c in zone if c not in blocked}
            if entry[0] in walk:
                seen, stack = {entry[0]}, [entry[0]]
                while stack:
                    x, y = stack.pop()
                    for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        n = (x + ox, y + oy)
                        if n in walk and n not in seen:
                            seen.add(n)
                            stack.append(n)
                for (px, py), key in sorted(occupied.items()):
                    if key in BLOCKING:
                        continue
                    if not any((px + ox, py + oy) in seen
                               for ox, oy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))):
                        reasons.append(
                            f"a {PIECE_KEYS.get(key, key)} at {px},{py} is walled off")

    # f) the furniture DF requires of this rank
    have: dict[str, int] = {}
    for _, _, key in d.pieces:
        have[key] = have.get(key, 0) + 1
    for key, n in sorted(req.furniture.items()):
        if have.get(key, 0) < n:
            reasons.append(f"{req.position} needs {n} x {PIECE_KEYS.get(key, key)}, "
                           f"has {have.get(key, 0)}")

    # g) the piece that makes it that kind of room at all
    for key in FUNCTIONAL.get(req.kind, ()):
        if have.get(key, 0) < 1:
            reasons.append(f"a {req.kind} needs a {PIECE_KEYS.get(key, key)}")

    # h) smoothing, when the requirement forbids it
    if not req.allow_smooth and any("s" in row for row in d.cells):
        reasons.append("the requirement forbids smoothing")
    if not ALLOW_ENGRAVE and any("e" in row for row in d.cells):
        reasons.append("engraving is not priced, so it may not be emitted")
    if any("e" in row for row in d.cells) and not req.allow_smooth:
        # DF will not engrave rough stone: the tile has to be smoothed first, and an
        # engraved cell is therefore a smoothed cell that also carries a record.
        reasons.append("an engraved tile must be smoothed first, and smoothing is off")

    return reasons
