"""The library: room templates and workshop clusters.

The owner's design, and the reason this file exists rather than a floor-plan generator:

    использование именно шаблонов внутри игры внутри двхака
    ...
    отбор комнат уже вести вне обучения основного Агента

So designs are DATA, not behaviour. The agent asks for "bedroom, tier 3" or "woodworking,
size 2"; it never learns a layout. Improving the layouts is an offline search that writes
new entries here, outside the agent's training loop.

Everything below is decoded from DFHack's own blueprint library and its own key tables
(`hack/data/blueprints/`, `hack/scripts/internal/quickfort/{build,place}.lua`), not
written from memory. That distinction has already cost this project three invented enum
names, each of which failed silently.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import re
from pathlib import Path
from dataclasses import dataclass, field


class LibraryError(ValueError):
    """A library entry is malformed — a programming error, not agent input."""


# quickfort's own key tables. Kept here so a cluster can be declared in the same
# vocabulary the blueprints use, and so a typo is a KeyError at import rather than a
# blueprint that silently builds the wrong thing.
# quickfort's own key table, read out of hack/scripts/internal/quickfort/build.lua, and
# every entry checked against a live `df.workshop_type` / `df.furnace_type` enumeration.
#
# Two of quickfort's keys are deliberately ABSENT. `wS` (Soap Maker) and `wp` (Screw
# Press) are `workshop_type.Custom` with custom=0/1 — real buildings, but not members of
# df.workshop_type, so `build_workshop` cannot name them. Transcribing them here as though
# they were workshop types is exactly how three invented DF names have shipped before;
# enumerating the enum live is what caught them.
WORKSHOP_KEYS = {
    "wc": "Carpenters", "ww": "Farmers", "wm": "Masons", "wr": "Craftsdwarfs",
    "wj": "Jewelers", "wf": "MetalsmithsForge", "wv": "MagmaForge", "wb": "Bowyers",
    "wt": "Mechanics", "ws": "Siege", "wu": "Butchers", "we": "Leatherworks",
    "wn": "Tanners", "wk": "Clothiers", "wh": "Fishery", "wl": "Still", "wo": "Loom",
    "wq": "Quern", "k": "Kennels", "wz": "Kitchen", "wy": "Ashery", "wd": "Dyers",
    "wM": "Millstone",
}

FURNACE_KEYS = {
    "ew": "WoodFurnace", "es": "Smelter", "el": "MagmaSmelter", "eg": "GlassFurnace",
    "ea": "MagmaGlassFurnace", "ek": "Kiln", "en": "MagmaKiln",
}

BUILDING_KEYS = {**WORKSHOP_KEYS, **FURNACE_KEYS}

# What DF charges to put one up, read live from its own table with
# `dfhack.buildings.getFiltersByType`. Fifteen of these are "any one building material"
# and the rest are not, which is the whole reason this table exists: the verb used to hand
# every workshop a log, and a Quern took it. Cost is the SUM of the filter quantities.
BUILD_COST = {
    "wc": 1, "ww": 1, "wm": 1, "wr": 1, "wj": 1, "wb": 1, "wt": 1, "wu": 1, "we": 1,
    "wn": 1, "wk": 1, "wh": 1, "wl": 1, "wo": 1, "wq": 1, "k": 1, "wz": 1,
    "wf": 2, "wv": 2, "wd": 2, "wM": 2, "ws": 3, "wy": 3,
    "ew": 1, "es": 1, "el": 1, "eg": 1, "ea": 1, "ek": 1, "en": 1,
}

# The demands that are NOT "any building material". A fort with a hundred logs still
# cannot build any of these.
BUILD_NEEDS = {
    "wq": ("a manufactured QUERN item",),
    "wM": ("a MILLSTONE item", "TRAPPARTS"),
    "wy": ("BLOCKS", "an EMPTY barrel", "a bucket"),
    "wd": ("an EMPTY barrel", "a bucket"),
    "wf": ("an ANVIL", "a fire-safe building material"),
    "wv": ("an ANVIL", "a magma-safe building material"),
    "ws": ("three building materials, not one",),
    "ew": ("a fire-safe building material",),
    "es": ("a fire-safe building material",),
    "eg": ("a fire-safe building material",),
    "ek": ("a fire-safe building material",),
    "el": ("a magma-safe building material",),
    "ea": ("a magma-safe building material",),
    "en": ("a magma-safe building material",),
}

# Which buildings must exist BEFORE these can be built, straight off the demands above: a
# quern and a millstone are made at a Mason's, trap parts at a Mechanic's, and the barrels
# and buckets at a Carpenter's. This is a build ORDER, not a preference.
PREREQ = {
    "wq": ("wm",), "wM": ("wm", "wt"), "wy": ("wm", "wc"), "wd": ("wc",),
}

# How many distinct jobs DFHack offers at each, measured with its own
# `require('dfhack.workshops').getJobs(type, subtype, -1)`.
#
# THESE NUMBERS ARE WORLD-SPECIFIC and must not be read as a property of the building.
# getJobs appends one SmeltOre per ore-bearing inorganic in the world — 16 in this one —
# and the Craftsdwarf's 631 is almost entirely one job kind repeated per instrument and
# per material. A scorer that ranks clusters on this number alone will pick the
# Craftsdwarf's every time for the wrong reason, so `Cluster.capabilities` takes the union
# over DISTINCT workshop kinds and the raw figure is kept here, labelled, for reference.
JOBS_OFFERED = {
    "wc": 55, "ww": 2, "wm": 28, "wr": 631, "wj": 4, "wf": 92, "wv": 92, "wb": 0,
    "wt": 2, "ws": 4, "wu": 3, "we": 65, "wn": 2, "wk": 0, "wh": 3, "wl": 3, "wo": 5,
    "wq": 2, "k": 0, "wz": 4, "wy": 1, "wd": 70, "wM": 2,
    "ew": 2, "es": 40, "el": 40, "eg": 84, "ea": 83, "ek": 79, "en": 78,
}

# Tiles on the ground, from quickfort's own min/max width and height.
FOOTPRINT_BY_KEY = {"ws": (5, 5), "k": (5, 5), "wq": (1, 1), "wM": (1, 1)}

STOCKPILE_KEYS = {
    "a": "animals", "f": "food", "u": "furniture", "n": "coins", "y": "corpses",
    "r": "refuse", "s": "stone", "w": "wood", "e": "gems", "b": "bars_blocks",
    "h": "cloth", "l": "leather", "z": "ammo", "g": "finished_goods",
    "p": "weapons", "d": "armor", "c": "custom",
}

# The section markers a blueprint file can open with. `#query` and `#config` are dead in
# this DFHack — silently downgraded to `ignore` — but they still open a section, so the
# parser has to know them or it reads their grid as part of the previous blueprint.
SECTION_MODES = frozenset({
    "dig", "build", "place", "zone", "burrow", "meta", "notes", "ignore", "aliases",
    "query", "config",
})


def _rows(text: str) -> list[list[str]]:
    """Blueprint rows, CSV-quoting respected.

    Splitting on commas is not enough: a header that carries a comma is quoted, so
    `"#dig label(dig) start(12; 12) 28 bedrooms, 3 tiles each"` splits into two cells and
    the first no longer starts with `#`. Every bedrooms/ blueprint is written that way,
    and a naive split read all three of them as having no dig section at all.
    """
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]


def blueprint_extents(text: str) -> dict[str, tuple[int, int, int]]:
    """Map extent of each section in a blueprint file: mode -> (width, height, levels).

    This measures the GROUND, which is not what the file's shape says. A .csv holds
    several independent blueprints one after another, each grid fenced by a trailing `#`
    column and closed by an all-`#` row, and `#>` / `#<` rows step down and up z-levels.
    Mini_Saracen is 26 lines of up to 12 comma-fields and stamps an 11x11 room — measured
    on the map at 95,85..105,95 after a live `quickfort run`, and this function returns
    11x11 for it.

    Counting lines and commas instead, which is what this library did at first, gives a
    number that cannot answer the only question a footprint is for: does it fit.
    """
    out: dict[str, tuple[int, int, int]] = {}
    mode: str | None = None
    width = height = levels = 0
    best_w = best_h = 0

    def close() -> None:
        nonlocal mode, width, height, levels, best_w, best_h
        if mode is not None:
            w = max(best_w, width)
            h = max(best_h, height)
            if w and h:
                prev = out.get(mode)
                # a file may repeat a mode (dreamfort has many #dig sections); keep the
                # largest, because that is the one that has to fit
                if prev is None or w * h > prev[0] * prev[1]:
                    out[mode] = (w, h, max(1, levels))
        mode, width, height, levels, best_w, best_h = None, 0, 0, 0, 0, 0

    for cells in _rows(text):
        head = cells[0] if cells else ""
        if head.startswith("#"):
            token = head[1:].split("(")[0].split()[0].lower() if len(head) > 1 else ""
            if token in SECTION_MODES:
                close()
                mode = token
                levels = 1
                continue
            if head.startswith("#>") or head.startswith("#<"):
                # a z-level step: the widest and tallest level is what must fit
                best_w, best_h = max(best_w, width), max(best_h, height)
                width, height = 0, 0
                levels += 1
                continue
            # an all-# row, or a stray comment, closes the grid
            if mode is not None and {c for c in cells if c} <= {"#"}:
                best_w, best_h = max(best_w, width), max(best_h, height)
                width, height = 0, 0
            continue
        if mode is None:
            continue
        # a data row: everything up to the fence, ignoring trailing blanks
        row = 0
        for i, c in enumerate(cells):
            if c == "#":
                break
            if c:
                row = i + 1
        if row == 0 and height == 0:
            continue                            # leading blank rows are not extent
        width = max(width, row)
        height += 1

    close()
    return out


def blueprint_labels(text: str) -> list[tuple[str, str]]:
    """(mode, label) for every section, in file order.

    A .csv holds several blueprints and `quickfort run <file>` runs the FIRST one. That is
    a trap dressed as a default: `library/pump_stack.csv` begins with a `#notes` help
    section, so running the file printed the walkthrough and stamped nothing, while
    `library/tombs/Mini_Saracen.csv` worked only because its first section happens to be
    `#dig`. Anything else has to be addressed as `-n /<label>`.
    """
    out: list[tuple[str, str]] = []
    for cells in _rows(text):
        head = cells[0] if cells else ""
        if not head.startswith("#"):
            continue
        token = head[1:].split("(")[0].split()[0].lower() if len(head) > 1 else ""
        if token not in SECTION_MODES:
            continue
        m = re.search(r"label\(\s*([^)]*?)\s*\)", head)
        out.append((token, m.group(1) if m else ""))
    return out


# Sections that put something on the ground. `notes`, `meta`, `aliases` and `ignore` are
# text or indirection — dreamfort's notes section is 60 rows of walkthrough prose, and
# counting it as extent would say the fort needs a 60-tile-tall hole.
GROUND_MODES = frozenset({"dig", "build", "place", "zone", "burrow"})


def template_extent(text: str) -> tuple[tuple[int, int, int], tuple[str, ...]]:
    """(width, height, levels) a blueprint needs on the map, and its ground modes.

    Sections share one anchor, so what must fit is the union: the widest and the tallest
    of them, over the deepest.
    """
    ext = blueprint_extents(text)
    modes = tuple(sorted(m for m in ext if m in GROUND_MODES))
    if not modes:
        return (0, 0, 0), ()
    return (max(ext[m][0] for m in modes),
            max(ext[m][1] for m in modes),
            max(ext[m][2] for m in modes)), modes



@dataclass(frozen=True)
class Template:
    """One room design the agent can stamp.

    `footprint` is the extent the blueprint needs ON THE MAP, so a caller can ask whether
    it fits before trying — the same discipline as `build_farm_plot` refusing rather than
    building somewhere useless.

    It used to be the shape of the FILE: comma-fields wide by lines tall. That number
    cannot answer the fit question and was wrong for every entry — Mini_Saracen read
    12x26 and stamps 11x11, dreamfort read 42x3238 and stamps 34x35 over two levels.
    Every value here now comes from `template_extent` over the shipped file, and the
    11x11 was confirmed on the live map after a real `quickfort run`.
    """

    name: str
    path: str                       # relative to DFHack's blueprints directory
    modes: tuple[str, ...]          # ground sections it contains: dig/build/place/zone
    footprint: tuple[int, int]      # width, height in tiles, on the map
    makes: str                      # what a player gets out of it
    levels: int = 1                 # z-levels it spans
    label: str = ""                 # which blueprint IN the file to run; "" = the first
    label_mode: str = "dig"         # what that blueprint DOES: decides the fit test
    start: str = ""                 # the blueprint's declared anchor
    shipped: bool = True            # ships with DFHack, versus generated by our search
    tier: int = 0                   # 0 = not aimed at a quality tier

    def __post_init__(self) -> None:
        if not self.modes:
            raise LibraryError(f"{self.name}: a template must declare its modes")
        w, h = self.footprint
        if w <= 0 or h <= 0:
            raise LibraryError(f"{self.name}: footprint {self.footprint} is not an area")
        if self.levels < 1:
            raise LibraryError(f"{self.name}: levels {self.levels} is not a depth")

    @property
    def qf_name(self) -> str:
        """What `quickfort run` wants to be handed.

        The shipped blueprints live at `hack/data/blueprints/<path>` on disk but quickfort
        addresses them as `library/<path>`. Passing the disk-relative path gets
        `failed to open "dfhack-config/blueprints/<path>"`, which is a real refusal and
        easy to mistake for a missing file.
        """
        return self.path if not self.shipped else f"library/{self.path}"


@dataclass(frozen=True)
class Cluster:
    """A group of workshops and the stockpiles that feed them.

    The four properties the owner asked the agent to choose on:

        среди чего должен агент выбирать — это их цена создания... и количество их
        возможностей, и... что можно восполнить, если их построить

    plus several SIZES per cluster. Every number here is derived from a measured table
    rather than stored, so none of them can drift from the membership.
    """

    name: str
    size: int                       # 1..4, several variants of the same cluster
    workshops: tuple[str, ...]      # quickfort keys, e.g. ("wc", "wm"); repeats allowed
    stockpiles: tuple[str, ...]     # quickfort keys, e.g. ("w", "s")
    replenishes: tuple[str, ...]    # what the fort can make more of once it stands
    blueprint: str = ""             # a shipped blueprint, when one already does this

    def __post_init__(self) -> None:
        for key in self.workshops:
            if key not in BUILDING_KEYS:
                raise LibraryError(f"{self.name}: unknown building key {key!r}")
        for key in self.stockpiles:
            if key not in STOCKPILE_KEYS:
                raise LibraryError(f"{self.name}: unknown stockpile key {key!r}")
        if not 1 <= self.size <= 4:
            raise LibraryError(f"{self.name}: size {self.size} outside 1..4")
        if not self.replenishes:
            raise LibraryError(f"{self.name}: must say what it replenishes")

    @property
    def cost(self) -> int:
        """Items the fort pays to put the cluster up.

        NOT one per workshop, which is what this returned first. DF's own filter table
        charges Siege and the Ashery three, and the forges, the Dyer's, the Millstone two.
        Derived rather than stored so it cannot drift from the membership.
        """
        return sum(BUILD_COST[k] for k in self.workshops)

    @property
    def needs(self) -> tuple[str, ...]:
        """The demands that are not simply "a building material", in DF's own terms.

        "three items" and "an anvil plus a fire-safe boulder" are not the same thing to a
        fort, and a cluster the fort cannot supply is worse than one it cannot afford —
        it will sit there unbuilt looking like progress.
        """
        out: list[str] = []
        for k in dict.fromkeys(self.workshops):
            out.extend(BUILD_NEEDS.get(k, ()))
        return tuple(dict.fromkeys(out))

    @property
    def prereq(self) -> tuple[str, ...]:
        """Buildings that must already exist, and are not in this cluster.

        A quern is made at a Mason's; a millstone needs trap parts from a Mechanic's. A
        cluster that carries its own prerequisite is self-sufficient and this is empty.
        """
        mine = set(self.workshops)
        out: list[str] = []
        for k in dict.fromkeys(self.workshops):
            out.extend(p for p in PREREQ.get(k, ()) if p not in mine)
        return tuple(dict.fromkeys(out))

    @property
    def capabilities(self) -> int:
        """Distinct jobs the cluster unlocks — the union over DISTINCT member kinds.

        Two Carpenter's workshops unlock no new job; they buy throughput. Counting the
        list rather than the set would make "size" and "capability" the same number and
        the agent would be choosing on one thing twice.

        The per-building figures are DFHack's own `getJobs`, and they are WORLD-SPECIFIC:
        see JOBS_OFFERED. Treat this as an ordering, not a physical constant.
        """
        return sum(JOBS_OFFERED[k] for k in dict.fromkeys(self.workshops))

    @property
    def throughput(self) -> int:
        """How many buildings can be working at once. This is what size buys."""
        return len(self.workshops)

    @property
    def footprint(self) -> tuple[int, int]:
        """Ground the cluster needs, packed edge to edge in one row.

        Most workshops are 3x3; Siege and Kennels are 5x5 and Quern and Millstone are
        1x1, from quickfort's own min/max width and height.
        """
        width = height = 0
        for k in self.workshops:
            w, h = FOOTPRINT_BY_KEY.get(k, (3, 3))
            width += w
            height = max(height, h)
        return width, height


# ---------------------------------------------------------------- shipped templates
# Headers and extents read off the files themselves; `modes` from the section markers
# each file actually contains.
TEMPLATES: tuple[Template, ...] = (
    Template(
        name="embark", path="embark.csv", modes=("build", "place"),
        footprint=(15, 10), start="8;2;center of wagon",
        label_mode="build", label="workshops",
        makes="the four post-embark workshops and the seven stockpiles that feed them",
    ),
    Template(
        name="bedrooms28", path="bedrooms/28-3-Modified_Windmill_Villas.csv",
        modes=("build", "dig", "zone"), footprint=(22, 23), start="12;12",
        label="dig",
        makes="28 bedrooms, 3 tiles each",
    ),
    Template(
        name="bedrooms48", path="bedrooms/48-4-Raynard_Whirlpool_Housing.csv",
        modes=("build", "dig", "zone"), footprint=(33, 33), start="17;17",
        label="dig",
        makes="48 bedrooms, 4 tiles each",
    ),
    Template(
        name="bedrooms95", path="bedrooms/95-9-Hactar1_3_Branch_Tree.csv",
        modes=("build", "dig", "zone"), footprint=(70, 74), start="36;73",
        label="dig",
        makes="95 bedrooms including 14 suites, and 190 tombs",
    ),
    Template(
        name="tombs24", path="tombs/Mini_Saracen.csv", modes=("build", "dig"),
        footprint=(11, 11), start="6;6", makes="a crypt for 24 corpses",
    ),
    Template(
        name="tombs513", path="tombs/The_Saracen_Crypts.csv", modes=("build", "dig"),
        footprint=(47, 47), start="24;25", makes="a crypt for 513 corpses",
    ),
    Template(
        name="dreamfort", path="dreamfort.csv",
        modes=("build", "burrow", "dig", "place", "zone"),
        footprint=(34, 35), levels=2, start="",
        label="dig_all",
        makes="a complete self-sustaining fortress, in stages",
    ),
    Template(
        name="aquifer_tap", path="aquifer_tap.csv", modes=("dig",),
        footprint=(18, 18), levels=2, start="",
        label="dig",
        makes="a safe tap into an aquifer for water",
    ),
    Template(
        name="pump_stack", path="pump_stack.csv", modes=("build", "dig"),
        footprint=(4, 5), start="", label="dig",
        makes="a powered pump stack",
    ),
    Template(
        name="mineshafts", path="exploratory-mining/vertical-mineshafts.csv",
        modes=("dig",), footprint=(40, 40), start="",
        makes="exploratory mineshafts as stairs every third tile",
    ),
    Template(
        name="tunnels", path="exploratory-mining/tunnels.csv", modes=("dig",),
        footprint=(101, 51), start="", makes="exploratory tunnels every ten units",
    ),
)


# ---------------------------------------------------------------- clusters
# `embark` is decoded from DFHack's own file: wc/wt/wm/wr are the Carpenter's,
# Mechanic's, Mason's and Craftsdwarf's workshops, and it places wood, stone, finished
# goods, weapons, armor, food and furniture piles alongside them. That file IS the
# owner's cluster idea, already shipped, which is why the first entry quotes it rather
# than reinventing it.
CLUSTERS: tuple[Cluster, ...] = (
    # `survival` first, and ahead of `embark`, because of what the measured year showed:
    # drink went 12 -> 0 with nothing brewed and two of seven dwarves dead. Brewing needs
    # an EMPTY BARREL the fort owns, and the Carpenter's is the only measured source of
    # one — 14 of the test fort's 15 barrels belonged to another civilisation. So
    # Carpenter's + Still is the smallest cluster that can actually put beer in a mug,
    # and it is what an agent should build first.
    Cluster(
        name="survival", size=1,
        workshops=("wc", "wl"), stockpiles=("w", "f", "u"),
        replenishes=("barrels", "buckets", "beds", "doors", "bins", "DRINK"),
    ),
    Cluster(
        name="survival", size=2,
        workshops=("wc", "wl", "wz", "ww"), stockpiles=("w", "f", "u"),
        replenishes=("barrels", "buckets", "beds", "DRINK", "prepared meals",
                     "rendered fat", "seed bags", "plant fibre"),
    ),
    Cluster(
        name="survival", size=3,
        workshops=("wc", "wc", "wl", "wl", "wz", "ww"),
        stockpiles=("w", "f", "u", "s"),
        replenishes=("barrels", "buckets", "beds", "DRINK", "prepared meals",
                     "rendered fat", "seed bags", "plant fibre"),
    ),

    # Decoded from DFHack's own embark.csv rather than invented; the test asserts every
    # key we claim appears in the shipped file.
    Cluster(
        name="embark", size=2, blueprint="embark.csv",
        workshops=("wc", "wt", "wm", "wr"),
        stockpiles=("w", "s", "g", "p", "d", "f", "u"),
        replenishes=("furniture", "mechanisms", "blocks", "crafts"),
    ),

    Cluster(
        name="woodworking", size=1,
        workshops=("wc",), stockpiles=("w", "u"),
        replenishes=("beds", "tables", "chairs", "doors", "barrels", "bins", "buckets"),
    ),
    Cluster(
        name="woodworking", size=2,
        workshops=("wc", "wc"), stockpiles=("w", "u"),
        replenishes=("beds", "tables", "chairs", "doors", "barrels", "bins", "buckets"),
    ),
    Cluster(
        name="woodworking", size=3,
        workshops=("wc", "wc", "wc", "ew"), stockpiles=("w", "u", "b"),
        replenishes=("beds", "tables", "chairs", "doors", "barrels", "bins", "buckets",
                     "charcoal", "ash"),
    ),

    Cluster(
        name="stoneworking", size=1,
        workshops=("wm",), stockpiles=("s", "u"),
        replenishes=("blocks", "stone furniture", "coffins", "querns", "millstones"),
    ),
    Cluster(
        name="stoneworking", size=2,
        workshops=("wm", "wt"), stockpiles=("s", "u", "g"),
        replenishes=("blocks", "stone furniture", "coffins", "querns", "millstones",
                     "mechanisms"),
    ),
    Cluster(
        name="stoneworking", size=3,
        workshops=("wm", "wm", "wt", "wr"), stockpiles=("s", "u", "g"),
        replenishes=("blocks", "stone furniture", "coffins", "mechanisms", "crafts"),
    ),

    Cluster(
        name="craft_trade", size=1,
        workshops=("wr",), stockpiles=("s", "g"),
        replenishes=("crafts", "scrolls", "bound books", "totems"),
    ),
    Cluster(
        name="craft_trade", size=2,
        workshops=("wr", "wm", "wj"), stockpiles=("s", "g", "e", "u"),
        replenishes=("crafts", "scrolls", "blocks", "stone furniture", "cut gems",
                     "encrusted goods"),
    ),

    # The cluster that proves `prereq` is needed: three of these four cost items no fort
    # has at embark, and two of them are made by a Mason's that is not in the cluster.
    Cluster(
        name="milling", size=1,
        workshops=("wm", "wq"), stockpiles=("s", "f"),
        replenishes=("flour", "plant paste", "blocks", "stone furniture"),
    ),
    Cluster(
        name="milling", size=2,
        workshops=("wm", "wt", "wq", "wM"), stockpiles=("s", "f", "b"),
        replenishes=("flour", "plant paste", "mechanisms", "blocks", "powered milling"),
    ),

    Cluster(
        name="butchery", size=1,
        workshops=("wu", "wn"), stockpiles=("a", "r", "f", "l"),
        replenishes=("meat", "fat", "bone", "skin", "tanned hides"),
    ),
    Cluster(
        name="butchery", size=2,
        workshops=("wu", "wn", "we", "wh"), stockpiles=("a", "r", "f", "l", "u"),
        replenishes=("meat", "fat", "bone", "tanned hides", "bags", "waterskins",
                     "backpacks", "quivers", "prepared fish"),
    ),

    Cluster(
        name="textiles", size=1,
        workshops=("wo", "wk"), stockpiles=("h", "l"),
        replenishes=("cloth", "clothing"),
    ),
    Cluster(
        name="textiles", size=2,
        workshops=("wo", "wk", "wd", "ww"), stockpiles=("h", "l", "f"),
        replenishes=("cloth", "clothing", "dyes", "dyed cloth", "plant fibre"),
    ),

    Cluster(
        name="metal", size=1,
        workshops=("es", "wf"), stockpiles=("s", "b", "p", "d"),
        replenishes=("metal bars", "steel", "forged goods"),
    ),
    Cluster(
        name="metal", size=2,
        workshops=("es", "es", "wf", "wt"), stockpiles=("s", "b", "p", "d"),
        replenishes=("metal bars", "steel", "forged goods", "mechanisms"),
    ),
    Cluster(
        name="metal_magma", size=1,
        workshops=("el", "wv"), stockpiles=("s", "b", "p", "d"),
        replenishes=("metal bars", "steel", "forged goods"),
    ),

    Cluster(
        name="ceramics", size=1,
        workshops=("ek",), stockpiles=("s", "u", "g"),
        replenishes=("pearlash", "quicklime", "clay jugs", "bricks", "glazes"),
    ),
    Cluster(
        name="glass", size=1,
        workshops=("eg",), stockpiles=("s", "g", "u"),
        replenishes=("raw glass", "glass goods"),
    ),
)

# ---------------------------------------------------------------- generated templates
# Designs the offline search found, read from the archive it writes.
#
# The archive is JSON rather than python source on purpose. It is DATA the search produces,
# and appending a generated entry to a hand-written tuple is a merge conflict waiting to
# happen and a thing somebody eventually edits by hand. Reading it here rather than
# importing the design package also keeps `actions` independent of `design`: the agent's
# action surface must not depend on the search that fills it.
#
# Without this the loop was OPEN. The search ran, beat its seed, emitted a blueprint the
# game accepted — and nothing could ask for the result, because `apply_template` only knew
# DFHack's eleven shipped files.
ARCHIVE = Path(__file__).resolve().parents[1] / "design" / "archive.json"


def _generated() -> tuple[Template, ...]:
    # Returning an empty tuple silently is how a missing archive turned into
    # SchemaError("template: enum needs choices") thrown from a dataclass three modules
    # away, with nothing naming the file that was absent. Say which file, once.
    if not ARCHIVE.is_file():
        print(f"bonsai: no generated-room archive at {ARCHIVE}; "
              f"build_room will be unavailable", file=sys.stderr)
        return ()
    try:
        rows = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    out = []
    for r in rows:
        out.append(Template(
            name=r["name"],
            path=f"bonsai/{r['name']}.csv",
            modes=("build", "dig", "zone"),
            footprint=(r["w"], r["h"]),
            makes=f"a {r['kind']} good enough for a {r['position']} "
                  f"(value {r['value']} against a demand of {r['demand']})",
            levels=1,
            label="dig",
            label_mode="dig",
            start="1;1",
            shipped=False,
        ))
    return tuple(out)


GENERATED: tuple[Template, ...] = _generated()
ALL_TEMPLATES: tuple[Template, ...] = TEMPLATES + GENERATED

TEMPLATES_BY_NAME = {t.name: t for t in ALL_TEMPLATES}
TEMPLATE_NAMES = tuple(t.name for t in ALL_TEMPLATES)
ROOM_TEMPLATE_NAMES = tuple(t.name for t in GENERATED)
CLUSTER_NAMES = tuple(dict.fromkeys(c.name for c in CLUSTERS))


def start_offset(t: Template) -> tuple[int, int]:
    """The blueprint's anchor cell, 1-indexed, as quickfort's CLI uses it.

    This is the whole of the position trap. `quickfort run -c X,Y,Z` lands the cursor on
    the blueprint's own `start()` cell, NOT on its top-left — so `start(6;6)` run at
    100,90 puts the corner at 95,85, which is exactly where the live run put it. The
    `apply_blueprint` API does the opposite: it adds the position to the data indices and
    ignores `start()` entirely. A caller that wants a known corner has to subtract this.

    A blueprint with no `start()` anchors at 1;1, which is its top-left.
    """
    nums = [int(n) for n in re.findall(r"\d+", t.start.split(";cent")[0])][:2]
    if len(nums) < 2:
        return 1, 1
    return nums[0], nums[1]


def cursor_for(t: Template, x0: int, y0: int) -> tuple[int, int]:
    """Where to put the cursor so the template's top-left corner lands on (x0, y0)."""
    sx, sy = start_offset(t)
    return x0 + sx - 1, y0 + sy - 1


def cluster(name: str, size: int = 1) -> Cluster | None:
    """The named cluster at the requested size, or the largest that is no bigger."""
    candidates = [c for c in CLUSTERS if c.name == name and c.size <= size]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.size)
