"""The offline room-design search: the model.

The owner's specification, and the reason none of this lives in the agent:

    сделать... небольшую систему, где каждый дизайн... потом мы сделаем так, чтобы дизайны
    генерировались с определёнными требованиями... потом мы смогли отследить, какой самый
    лучший... тем самым эволюционными методами... возможно прикрутить метод отжига

    отбор комнат уже вести ВНЕ обучения основного Агента

So designs are searched for here, offline, and the agent only ever asks for one by name.

EVERY NUMBER IN THIS FILE WAS MEASURED AGAINST THE GAME. That matters more than usual,
because a search optimises whatever you give it: an objective that is wrong by a constant
still returns the best design, an objective that is wrong in SHAPE returns an artefact and
looks just as confident.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- the measured tables

# What DF pays per tile of a room. NOT 1 per cell — that was the first version of
# bonsai-roomvalue and it undercounted every finished room by 3 per tile.
#
# Measured against DF's own `view_sheets.curroom` on an owned 2x2 bedroom at z=48, with
# the field poisoned to -777 before each read so a stale value could not pass as fresh:
#
#     4 rough soil tiles                      DF said 4
#     one rewritten to StoneFloorSmooth       DF said 7
#     restored to soil                        DF said 4
#
# and swept over 0,1,2,3,4 smoothed of 4, DF answered 4, 7, 10, 13, 16 — additive, per
# tile. Smoothing is the single biggest lever the search has, and quickfort can emit it
# (dig key 's'), which is why it is in the representation at all.
# An ENGRAVED cell is a smoothed one that also carries an engraving, so its 14 is 4 + 10.
#
# Engravings are not on the tile at all: an engraved floor is still StoneFloorSmooth with
# special = SMOOTH, which is why a tiletype-only scorer is structurally blind to them. They
# are records in `df.global.world.event.engravings` — NOT `world.engravings`, which does
# not exist on this build — matched to a tile by `pos` in all three axes.
#
# Measured with the same poison-and-reopen oracle that established smooth = 4, by adding
# one record to a 2x2 bedroom worth 4 and sweeping its quality. DF answered:
#
#     quality  0    1    2    3    4    5     6
#     curroom  14   24   34   44   54   124   74
#     adds     +10  +20  +30  +40  +50  +120  +70
#
# The ladder is NOT monotonic — Masterful adds 120 and Artifact 70. Surprising enough to
# write down rather than smooth over; it was read twice.
TILE_VALUE = {".": 1, "s": 4, "e": 14}

ENGRAVING_VALUE = {0: 10, 1: 20, 2: 30, 3: 40, 4: 50, 5: 120, 6: 70}

# The search banks the GUARANTEED 10, not the expected value. A real engraver routinely
# lands quality 2-5, worth 30 to 120, but a blueprint cannot request a quality — so
# counting on anything above Ordinary would make the offline score drift from DF in the
# optimistic direction, which is exactly what this guard was written to prevent.
# Underrating is safe; overrating is not.
ALLOW_ENGRAVE = True

# Base value of a piece of furniture, before material and quality.
BASE_ITEM_VALUE = {"s": 25}          # a statue; everything else is 10
DEFAULT_BASE = 10

# The quality ladder, as integer arithmetic. Cross-checked rather than taken on trust:
# `bonsai-roomvalue` had already measured, on four separate pieces and by a different
# route, ordinary 10, well-crafted 14 and superior 23. This law returns exactly those for
# V0 = 10 at q = 0, 1 and 3.
#
# df.item_quality: 0 Ordinary, 1 WellCrafted, 2 FinelyCrafted, 3 Superior, 4 Exceptional,
# 5 Masterful, 6 Artifact.
def item_value(key: str, material_value: int = 1, quality: int = 0) -> int:
    v0 = BASE_ITEM_VALUE.get(key, DEFAULT_BASE) * material_value
    if quality <= 0:
        return v0
    if quality == 1:
        return (11 * v0) // 10 + 3
    if quality == 2:
        return (12 * v0) // 10 + 6
    if quality == 3:
        return (4 * v0 + 29) // 3
    if quality == 4:
        return (3 * v0) // 2 + 15
    return 2 * v0 + 30


# quickfort's own build keys, read out of hack/scripts/internal/quickfort/build.lua.
# Single cells, every one of them, so no multi-tile extent arithmetic is needed.
PIECE_KEYS = {
    "a": "armor stand", "b": "bed", "c": "chair", "d": "door", "f": "cabinet",
    "h": "chest", "n": "coffin", "r": "weapon rack", "s": "statue", "t": "table",
}

# quickfort's zone keys, from zone.lua, mapped onto df.civzone_type names.
ZONE_KEY = {"Bedroom": "b", "Office": "o", "DiningHall": "h", "Tomb": "T"}

# What each kind of room is not a room without.
FUNCTIONAL = {
    "Bedroom": ("b",),
    "Office": ("c", "t"),
    "DiningHall": ("t", "c"),
    "Tomb": ("n",),
}

# DF's own demands, per position, read live from `entity_position`. The room VALUE is in
# bonsai-roomvalue.DEMANDS; these are the furniture counts, read the same way and on the
# same run.
REQUIRED_FURNITURE = {
    "monarch": {"h": 10, "f": 5, "r": 5, "a": 5},
    "duke": {"h": 5, "f": 3, "r": 3, "a": 3},
    "count": {"h": 3, "f": 2, "r": 2, "a": 2},
    "outpost liaison": {"h": 3, "f": 2, "r": 2, "a": 2},
    "diplomat": {"h": 3, "f": 2, "r": 2, "a": 2},
    "general": {"h": 2, "f": 1, "r": 3, "a": 3},
    "baron": {"h": 2, "f": 1, "r": 1, "a": 1},
    "mayor": {"h": 2, "f": 1, "r": 1, "a": 1},
    "lieutenant": {"h": 1, "f": 1, "r": 2, "a": 2},
    "captain": {"h": 1, "f": 1, "r": 1, "a": 1},
    "sheriff": {"h": 1, "f": 1, "r": 1, "a": 1},
    "captain of the guard": {"h": 1, "f": 1, "r": 1, "a": 1},
    "dungeon master": {"h": 1, "f": 1, "r": 1, "a": 1},
    "manager": {},
    "bookkeeper": {},
}

# The room value each position demands, from the same live read. Kept here so the search
# runs without DF; bonsai-roomvalue re-reads it from the world every battery run and fails
# on drift, which is what keeps this honest.
REQUIRED_VALUE = {
    "captain": {"Office": 1, "Bedroom": 1, "DiningHall": 1},
    "manager": {"Office": 1},
    "bookkeeper": {"Office": 1},
    "lieutenant": {"Office": 100, "Bedroom": 100, "DiningHall": 100},
    "sheriff": {"Office": 100, "Bedroom": 100, "DiningHall": 100},
    "captain of the guard": {"Office": 250, "Bedroom": 250, "DiningHall": 250},
    "dungeon master": {"Office": 250, "Bedroom": 250, "DiningHall": 250},
    "general": {"Office": 500, "Bedroom": 250, "DiningHall": 250, "Tomb": 1},
    "mayor": {"Office": 500, "Bedroom": 500, "DiningHall": 500},
    "baron": {"Office": 500, "Bedroom": 500, "DiningHall": 500, "Tomb": 500},
    "outpost liaison": {"Office": 1500, "Bedroom": 1500, "DiningHall": 1500},
    "diplomat": {"Office": 1500, "Bedroom": 1500, "DiningHall": 1500},
    "count": {"Office": 1500, "Bedroom": 1500, "DiningHall": 1500, "Tomb": 1500},
    "duke": {"Office": 2500, "Bedroom": 2500, "DiningHall": 2500, "Tomb": 2500},
    "monarch": {"Office": 10000, "Bedroom": 10000, "DiningHall": 10000, "Tomb": 10000},
}

# What the fort pays, in the units it actually pays them: one miner job per tile dug, one
# mason job per tile smoothed, and for a piece of furniture the item somebody had to make
# plus the haul plus the build.
DIG_COST = 1
SMOOTH_COST = 1
ENGRAVE_COST = 1        # an engraved cell is three jobs: mine it, smooth it, engrave it
BUILD_COST = 3

# How hard a shortfall against the demand hurts. Large enough that no amount of saved
# digging buys its way out of missing the target, small enough to be a gradient rather
# than a wall — an infeasible design can still tell the search which way is better.
SHORTFALL_WEIGHT = 100


class DesignError(ValueError):
    """A malformed design — a programming error, not search output."""


@dataclass(frozen=True)
class Requirement:
    """What the search is being asked for.

    The target is a DEMAND, in DF's own numbers, not a quality tier. v50's value-to-name
    cutoffs are not knowable on this build — `getRoomDescription` is the stub — so a tier
    is a number the game will never confirm. "Good enough for a baron" it will.
    """

    kind: str                       # df.civzone_type name: Bedroom / Office / ...
    position: str = "manager"       # whose demands to meet
    max_w: int = 9
    max_h: int = 9
    material_value: int = 1         # what the fort's commonest stone or wood is worth
    quality: int = 0                # what its craftsdwarves reliably produce
    allow_smooth: bool = True

    @property
    def demand(self) -> int:
        return REQUIRED_VALUE.get(self.position, {}).get(self.kind, 0)

    @property
    def furniture(self) -> dict:
        return REQUIRED_FURNITURE.get(self.position, {})


@dataclass(frozen=True)
class Design:
    """One room layout.

    Everything is tuples of str and int: hashable, orderable, JSON-able, and `repr()` is a
    total order, which is what deterministic tie-breaking needs. Nothing on the decision
    path may be a set or a dict — their iteration order is hash-dependent and would make
    the same seed give different answers between runs.

    The cell alphabet:
        '#'  undug rock: the wall ring, and any pillar
        '.'  dug interior, in the zone, rough
        's'  dug interior, in the zone, smoothed
        'e'  dug, smoothed AND engraved — DF will not engrave rough stone
        '+'  the doorway: dug, NOT in the zone
        ' '  the corridor tile outside the door
    """

    kind: str
    w: int
    h: int
    cells: tuple[str, ...]                        # h strings of length w
    pieces: tuple[tuple[int, int, str], ...] = ()  # (x, y, key), kept sorted
    seed_name: str = ""

    def __post_init__(self) -> None:
        if self.w <= 0 or self.h <= 0:
            raise DesignError(f"{self.w}x{self.h} is not an area")
        if len(self.cells) != self.h:
            raise DesignError(f"{len(self.cells)} rows for height {self.h}")
        for row in self.cells:
            if len(row) != self.w:
                raise DesignError(f"row {row!r} is not {self.w} wide")
        object.__setattr__(self, "pieces", tuple(sorted(self.pieces)))

    def at(self, x: int, y: int) -> str:
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.cells[y][x]
        return "#"

    @property
    def zone_cells(self) -> tuple[tuple[int, int], ...]:
        """The tiles the civzone covers. Walls are NOT among them.

        DF prices a wall inside the extent the same as a rough floor — measured — so
        painting a huge zone over bedrock is free value, and an unconstrained search WILL
        find that and return a 2x2 room with a 30x30 zone over solid rock. A room that is
        mostly rock is not a room. The exploit is real and this is where it is refused.
        """
        return tuple((x, y) for y in range(self.h) for x in range(self.w)
                     if self.cells[y][x] in TILE_VALUE)

    def value(self, material_value: int = 1, quality: int = 0) -> int:
        tiles = sum(TILE_VALUE[self.cells[y][x]] for x, y in self.zone_cells)
        furniture = sum(item_value(k, material_value, quality) for _, _, k in self.pieces)
        return tiles + furniture

    def cost(self) -> int:
        dug = sum(1 for row in self.cells for ch in row if ch in ".se+")
        smoothed = sum(1 for row in self.cells for ch in row if ch in "se")
        engraved = sum(1 for row in self.cells for ch in row if ch == "e")
        return (DIG_COST * dug + SMOOTH_COST * smoothed + ENGRAVE_COST * engraved
                + BUILD_COST * len(self.pieces))


def score(design: Design, req: Requirement) -> int:
    """Maximise. All integer, so the objective has no float in it anywhere.

    DO NOT MAXIMISE VALUE. Maximising value returns "dig out the level, smooth it, fill it
    with statues" — and worse, it pretends to rank designs above the target when
    `LADDER_CUTOFFS_KNOWN` is false and nothing here can tell a good room from a better
    one once both satisfy the noble. DF's own scale is a THRESHOLD scale, so the search
    minimises cost subject to MEETING the demand, and the shortfall term gives an
    infeasible design a direction to walk rather than a flat wall.
    """
    short = max(0, req.demand - design.value(req.material_value, req.quality))
    return -SHORTFALL_WEIGHT * short - design.cost()


def bare_room(req: Requirement) -> Design:
    """The seed: what the agent can already build today.

    `create_zone` paints a rectangle and `place_furniture` drops the required pieces into
    it, unsmoothed, and that is the whole of the fort's current ability. So "the best
    design beats the seed" means "the search beats what the agent does now", which is the
    claim worth making. Seeding from a shipped 28-bedroom blueprint would compare against
    something the agent cannot produce.
    """
    w, h = req.max_w, req.max_h
    rows = []
    for y in range(h):
        if y == 0 or y == h - 1:
            rows.append("#" * w)
        else:
            rows.append("#" + "." * (w - 2) + "#")
    # a door on the north wall, and the corridor tile outside it
    door_x = w // 2
    rows[0] = rows[0][:door_x] + "+" + rows[0][door_x + 1:]

    interior = [(x, y) for y in range(1, h - 1) for x in range(1, w - 1)]
    pieces: list[tuple[int, int, str]] = []
    wanted: list[str] = list(FUNCTIONAL.get(req.kind, ()))
    for key, n in sorted(req.furniture.items()):
        wanted.extend([key] * n)
    for (x, y), key in zip(interior, wanted):
        pieces.append((x, y, key))
    return Design(kind=req.kind, w=w, h=h, cells=tuple(rows),
                  pieces=tuple(pieces), seed_name="bare")
