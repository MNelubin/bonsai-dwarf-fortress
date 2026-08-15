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
import re
from dataclasses import dataclass, field


class LibraryError(ValueError):
    """A library entry is malformed — a programming error, not agent input."""


# quickfort's own key tables. Kept here so a cluster can be declared in the same
# vocabulary the blueprints use, and so a typo is a KeyError at import rather than a
# blueprint that silently builds the wrong thing.
WORKSHOP_KEYS = {
    "wc": "Carpenters",
    "wm": "Masons",
    "wr": "Craftsdwarfs",
    "wt": "Mechanics",
    "wl": "Still",
    "wk": "Clothiers",
    "wb": "Bowyers",
    "ws": "Siege",
}

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

    plus several SIZES per cluster. `cost` is in plain building materials because that is
    what the owner asked for — "можно просто в каких-то числах" — and because it is the
    number the fort actually pays.
    """

    name: str
    size: int                       # 1..4, several variants of the same cluster
    workshops: tuple[str, ...]      # quickfort keys, e.g. ("wc", "wm")
    stockpiles: tuple[str, ...]     # quickfort keys, e.g. ("w", "s")
    replenishes: tuple[str, ...]    # what the fort can make more of once it stands
    blueprint: str = ""             # a shipped blueprint, when one already does this
    capabilities: int = 0           # how many distinct jobs it unlocks; measured, not guessed

    def __post_init__(self) -> None:
        for key in self.workshops:
            if key not in WORKSHOP_KEYS:
                raise LibraryError(f"{self.name}: unknown workshop key {key!r}")
        for key in self.stockpiles:
            if key not in STOCKPILE_KEYS:
                raise LibraryError(f"{self.name}: unknown stockpile key {key!r}")
        if not 1 <= self.size <= 4:
            raise LibraryError(f"{self.name}: size {self.size} outside 1..4")

    @property
    def cost(self) -> int:
        """Build material the cluster costs, in items.

        One per workshop is DF's own rule for the basic shops in this library, and
        stockpiles cost nothing to place. Declared as a property rather than a stored
        number so it cannot drift from the workshop list.
        """
        return len(self.workshops)


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
    Cluster(
        name="embark", size=2, blueprint="embark.csv",
        workshops=("wc", "wt", "wm", "wr"),
        stockpiles=("w", "s", "g", "p", "d", "f", "u"),
        replenishes=("furniture", "mechanisms", "blocks", "crafts"),
    ),
    Cluster(
        name="woodworking", size=1,
        workshops=("wc",), stockpiles=("w", "u"),
        replenishes=("beds", "tables", "chairs", "doors", "barrels", "bins"),
    ),
    Cluster(
        name="woodworking", size=2,
        workshops=("wc", "wc"), stockpiles=("w", "u"),
        replenishes=("beds", "tables", "chairs", "doors", "barrels", "bins"),
    ),
    Cluster(
        name="stoneworking", size=1,
        workshops=("wm",), stockpiles=("s", "u"),
        replenishes=("blocks", "stone furniture", "coffins"),
    ),
    Cluster(
        name="stoneworking", size=2,
        workshops=("wm", "wr"), stockpiles=("s", "u", "g"),
        replenishes=("blocks", "stone furniture", "coffins", "crafts"),
    ),
    Cluster(
        name="brewing", size=1,
        workshops=("wl",), stockpiles=("f",),
        replenishes=("drink",),
    ),
)

TEMPLATES_BY_NAME = {t.name: t for t in TEMPLATES}
TEMPLATE_NAMES = tuple(t.name for t in TEMPLATES)
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
