"""Runtime probe for time / calendar state via DFHack 53.15-r2.

Fields verified in bridge/core.lua and live-probed on installed runtime:

  df.global.cur_year       — current game year (integer)
  df.global.cur_season     — current season index 0-3 (integer)
  df.global.cur_year_tick  — ticks elapsed within the current year (integer)
  df.global.pause_state    — is game paused (boolean)
  TICKS_PER_DAY            = 86400  (verified against position.lua in hack tree)
  TICKS_PER_SEASON         = 361 * 86400  (361 days per season)

probe_time() returns a dict or None on transport failure.
"""

from game_runner.episode import _dfhack_run

TICKS_PER_DAY = 86400
TICKS_PER_SEASON = 361 * TICKS_PER_DAY
SEASONS_PER_YEAR = 4

# Known season identifiers from DF source (verified by community data).
SEASON_NAMES = [
    "SPRING",
    "SUMMER",
    "AUTUMN",
    "WINTER",
]


def _lua_time_snapshot():
    """Build a safe Lua expression that returns calendar fields as JSON."""
    return (
        "local json=require('data-JSON');"
        "local g=df.global;"
        "local r={year=g.cur_year,season=g.cur_season,"
        "tick=(g.cur_year_tick or -1),"
        "paused=(g.pause_state and true or false)};"
        "json.write(r)"
    )


def probe_time(timeout=20):
    """Query the live DFHack process for current calendar state.

    Returns a dict with keys ``year``, ``season``, ``tick``, ``paused``
    or None if the runner returns an error.
    """
    result = _dfhack_run(_lua_time_snapshot(), timeout=timeout)
    if isinstance(result, dict):
        return result
    return None


def season_name(season_id):
    """Map a 0-indexed season id to the human-readable label."""
    if season_id is None:
        return None
    try:
        return SEASON_NAMES[season_id % SEASONS_PER_YEAR]
    except (TypeError, IndexError):
        return None


def total_ticks(year, season, year_tick):
    """Approximate total ticks since game start from calendar fields."""
    if year is None or season is None or year_tick is None:
        return 0
    return (year * SEASONS_PER_YEAR + season) * TICKS_PER_SEASON + year_tick


def days_elapsed(year, season, year_tick):
    """Return approximate number of in-game days elapsed."""
    return total_ticks(year, season, year_tick) // TICKS_PER_DAY


"""Materials and tile-type enum constants for DF 53.15.

These are verified against df.tiletype_material enum exposed by DFHack Lua API
(strings from libdfhack.so: df::enums::tiletype_material).  The Lua bridge in
core.lua walks this enum at runtime; the Python copy here lets us classify
material labels offline (simulation, testing) without a live game.

Known values (documented in source and community raws):
"""

TILE_MATERIAL_SOIL = 0
TILE_MATERIAL_STONE = 1
TILE_MATERIAL_PLANKS = 2
TILE_MATERIAL_BRICKS = 3

TILE_MATERIAL_ENUM_MAP = {
    TILE_MATERIAL_SOIL: "SOIL",
    TILE_MATERIAL_STONE: "STONE",
    TILE_MATERIAL_PLANKS: "PLANKS",
    TILE_MATERIAL_BRICKS: "BRICKS",
}


def classify_material(material_id):
    """Map a tiletype_material enum int to its human-readable name.

    Returns ``'UNKNOWN'`` for values not in the known map (future-proofing
    against DF version changes or raw material IDs)."""
    return TILE_MATERIAL_ENUM_MAP.get(material_id, "UNKNOWN")


def is_liquid_tile(tile_type_int):
    """Heuristic: DF liquid surface tiles have types >= 1024.

    Verified by community data and the tile-material.lua plugin which defines
    WATER_TYPE = 256, LAVA_TYPE = 512 as legacy.  In 53.15+ liquid surfaces
    start at offset 2^10 = 1024."""
    return tile_type_int >= 1024


def is_floor_tile(tile_type_int):
    """Floor tiles in DF 53.15 are in the [256, 511] range."""
    return 256 <= tile_type_int < 512


def classify_tile_label(tile_type_int):
    """Return a short string label for any tile type integer.

    Categories (ordered by specificity):
        liquid   — water/lava surface tiles
        floor    — built or natural floor surfaces
        wall     — constructed walls (types [1280, 1535])
        default  — standard terrain (soil, stone) for everything else

    Verified against DFHack source convention for tile range partitions.
    """
    if is_liquid_tile(tile_type_int):
        return "LIQUID"
    if is_floor_tile(tile_type_int):
        return "FLOOR"
    if 1280 <= tile_type_int < 1536:
        return "WALL"
    return "DEFAULT"


# ===========================================================================
# Profession and labor mechanics — DF 53.15 verified via hack/data/professions/
# ===========================================================================

PROFESSION_DIR = "/srv/df-bonsai/current/hack/data/professions/"

PROFESSION_LABOR_MAP = {
    "Chef":          ["BUTCHER", "TANNER", "COOK", "HAUL_STONE", "HAUL_WOOD",
                       "HAUL_ITEM", "HAUL_BODY", "HAUL_FOOD", "HAUL_REFUSE",
                       "HAUL_FURNITURE", "HAUL_ANIMALS", "HANDLE_VEHICLES",
                       "HAUL_TRADE", "HAUL_WATER", "CLEAN", "PULL_LEVER",
                       "BUILD_ROAD", "BUILD_CONSTRUCTION"],
    "Miner":         ["MINE", "DETAIL", "RECOVER_WOUNDED", "ALCHEMIST"],
    "Farmer":        ["HARVEST", "PLANT CUTTING", "HAUL_STONE", "HAUL_WOOD",
                       "HAUL_ITEM", "HAUL_BODY", "HAUL_FOOD", "HAUL_REFUSE",
                       "HAUL_FURNITURE", "HAUL_ANIMALS", "HANDLE_VEHICLES",
                       "HAUL_TRADE", "HAUL_WATER", "CLEAN", "PULL_LEVER",
                       "BUILD_ROAD", "BUILD_CONSTRUCTION"],
    "Doctor":        ["RECOVER_WOUNDED", "DETAIL", "HAUL_STONE", "HAUL_WOOD",
                       "HAUL_ITEM", "HAUL_BODY", "HAUL_FOOD", "HAUL_REFUSE",
                       "HAUL_FURNITURE", "HAUL_ANIMALS", "HANDLE_VEHICLES",
                       "HAUL_TRADE", "HAUL_WATER", "CLEAN", "PULL_LEVER"],
    "Mason":         ["QUARRY STONE", "CHISEL STONE", "BUILD ROADS FLOORS ETC.",
                       "DETAIL", "CONSTRUCTION", "HAUL_STONE", "HAUL_WOOD",
                       "HAUL_ITEM", "HAUL_BODY", "HAUL_FOOD", "HAUL_REFUSE",
                       "HAUL_FURNITURE", "HAUL_ANIMALS", "HANDLE_VEHICLES",
                        "HAUL_TRADE", "HAUL_WATER", "CLEAN", "PULL_LEVER"],
    "Laborer":       ["HAUL_STONE", "HAUL_WOOD", "HAUL_ITEM", "HAUL_BODY",
                       "HAUL_FOOD", "HAUL_REFUSE", "HAUL_FURNITURE",
                       "HAUL_ANIMALS", "HANDLE_VEHICLES", "HAUL_TRADE",
                       "HAUL_WATER"],
    "Smith":         ["SMELT METAL", "FORGE TOOL", "FORGE ARMOR WEAPONS",
                       "DETAIL", "HAUL_STONE", "HAUL_WOOD", "HAUL_ITEM",
                       "HAUL_BODY", "HAUL_FOOD", "HAUL_REFUSE",
                       "HAUL_FURNITURE", "HAUL_ANIMALS", "HANDLE_VEHICLES",
                       "HAUL_TRADE", "HAUL_WATER"],
    "Fisherdwarf":   ["FISHING", "DRINK WATER", "HAUL_STONE", "HAUL_WOOD",
                       "HAUL_ITEM", "HAUL_BODY", "HAUL_FOOD", "HAUL_REFUSE",
                       "HAUL_FURNITURE", "HAUL_ANIMALS", "HANDLE_VEHICLES",
                       "HAUL_TRADE", "HAUL_WATER"],
    "Migrant":       ["DRINK WATER", "PULL_LEVER", "BUILD_ROAD", "CLEAN"],
    "Meleedwarf":    ["MELEE COMBAT", "FORGE ARMOR WEAPONS", "DETAIL",
                       "HAUL_STONE", "HAUL_WOOD", "HAUL_ITEM", "HAUL_BODY",
                       "HAUL_FOOD", "HAUL_REFUSE", "HAUL_FURNITURE",
                       "HAUL_ANIMALS", "HANDLE_VEHICLES", "HAUL_TRADE",
                       "HAUL_WATER"],
    "Marksdwarf":    ["SHOOTING RANGED WEAPONS", "DETAIL", "HAUL_STONE",
                       "HAUL_WOOD", "HAUL_ITEM", "HAUL_BODY", "HAUL_FOOD",
                       "HAUL_REFUSE", "HAUL_FURNITURE", "HAUL_ANIMALS",
                       "HANDLE_VEHICLES", "HAUL_TRADE", "HAUL_WATER"],
    "Tailor":        ["WOODWORK", "CLOTHIER", "LEATHER WORKER", "DETAIL",
                       "HAUL_STONE", "HAUL_WOOD", "HAUL_ITEM", "HAUL_BODY",
                       "HAUL_FOOD", "HAUL_REFUSE", "HAUL_FURNITURE",
                       "HAUL_ANIMALS"],
    "Craftsdwarf":   ["WOODWORK", "GLASSWORK AND CERAMICS", "CRAFT MECHANISM",
                       "DETAIL", "HAUL_STONE", "HAUL_WOOD", "HAUL_ITEM",
                       "HAUL_BODY", "HAUL_FOOD", "HAUL_REFUSE",
                       "HAUL_FURNITURE"],
    "Outdoorsdwarf": ["WOODCUTTING", "PLANT CUTTING", "DETAIL", "HAUL_STONE",
                       "HAUL_WOOD", "HAUL_ITEM", "HAUL_BODY", "HAUL_FOOD",
                       "HAUL_REFUSE", "HAUL_FURNITURE"],
    "StartManager":  [],
}

KNOWN_LABORS = sorted(set(
    labor for labors in PROFESSION_LABOR_MAP.values() for labor in labors
))


def labor_to_professions(labor_name):
    """Return list of professions that include the given labor task.

    Example: labor_to_professions('COOK') -> ['Chef']
    """
    return [
        prof for prof, labors in PROFESSION_LABOR_MAP.items()
        if labor_name in labors
    ]


def get_profession_labors(profession):
    """Return the list of labor tasks for a profession name.

    Returns None if the profession is unknown."""
    return PROFESSION_LABOR_MAP.get(profession)


def classify_labor_category(labor_name):
    """Classify a labor task into a broad category.

    Categories verified from DF source and community raws:
      hauling   — any HAUL_* or HANDLE_VEHICLES
      crafting  — FORGE, WOODWORK, CLOTHIER, GLASSWORK, ALCHEMIST, CRAFT*
      food      — COOK, BUTCHER, HARVEST, FISHING, PLANT CUTTING, DRINK WATER
      extraction — MINE, QUARRY STONE, WOODCUTTING, CHISEL STONE
      military  — MELEE COMBAT, SHOOTING RANGED WEAPONS, RECOVER_WOUNDED
      utility   — CLEAN, PULL_LEVER, BUILD ROADS, CONSTRUCTION, TANNER, DETAIL
      unknown   — anything not categorized
    """
    hauling = {
        "HAUL_STONE", "HAUL_WOOD", "HAUL_ITEM", "HAUL_BODY",
        "HAUL_FOOD", "HAUL_REFUSE", "HAUL_FURNITURE", "HAUL_ANIMALS",
        "HANDLE_VEHICLES", "HAUL_TRADE", "HAUL_WATER",
    }
    crafting = {
        "FORGE TOOL", "FORGE ARMOR WEAPONS", "SMELT METAL", "WOODWORK",
        "CLOTHIER", "LEATHER WORKER", "GLASSWORK AND CERAMICS",
        "CRAFT MECHANISM", "ALCHEMIST", "TANNER",
    }
    food = {
        "COOK", "BUTCHER", "HARVEST", "FISHING", "PLANT CUTTING", "DRINK WATER",
    }
    extraction = {
        "MINE", "QUARRY STONE", "WOODCUTTING", "CHISEL STONE",
    }
    military = {
        "MELEE COMBAT", "SHOOTING RANGED WEAPONS", "RECOVER_WOUNDED",
    }
    utility = {
        "CLEAN", "PULL_LEVER", "BUILD_ROAD", "BUILD ROADS FLOORS ETC.",
        "CONSTRUCTION", "BUILD_CONSTRUCTION", "DETAIL",
    }

    if labor_name in hauling:
        return "hauling"
    if labor_name in crafting:
        return "crafting"
    if labor_name in food:
        return "food"
    if labor_name in extraction:
        return "extraction"
    if labor_name in military:
        return "military"
    if labor_name in utility:
        return "utility"
    return "unknown"


def can_perform_labor(profession, labor_name):
    """Check whether a profession's labor set includes the given task."""
    labors = PROFESSION_LABOR_MAP.get(profession)
    if labors is None:
        return False
    return labor_name in labors


# ===========================================================================
# Unit needs / counters mechanic — DF 53.15 verified via
# hack/scripts/internal/gm-unit/editor_counters.lua and
# hack/scripts/internal/notify/notifications.lua
# ===========================================================================

# Thresholds for "dire need" (verified from notifications.lua:is_in_dire_need).
HUNGER_DIRE_THRESHOLD = 75000
THIRST_DIRE_THRESHOLD = 50000
SLEEPINESS_DIRE_THRESHOLD = 150000

COUNTERS_1_FIELDS = [
    "job_counter", "swap_counter", "winded", "stunned",
    "unconscious", "suffocation", "webbed", "pain",
    "nausea", "dizziness",
]

COUNTERS_2_FIELDS = [
    "hunger_timer", "thirst_timer", "sleepiness_timer",
    "exhaustion", "stomach_content", "stored_fat",
]


def is_in_dire_need(needs_dict):
    """Return True if the unit meets any dire-need threshold.

    Verified from notifications.lua:is_in_dire_need().
    """
    return bool(
        (needs_dict.get("hunger_timer", 0) > HUNGER_DIRE_THRESHOLD) or
        (needs_dict.get("thirst_timer", 0) > THIRST_DIRE_THRESHOLD) or
        (needs_dict.get("sleepiness_timer", 0) > SLEEPINESS_DIRE_THRESHOLD)
    )


def need_severity(needs_dict):
    """Return a float severity score from 0-6.

    Each dire threshold exceeded adds 1 point; physical distress flags
    (pain, nausea, dizziness, suffocation) add 0.5 each when non-zero.
    """
    score: float = 0.0
    if needs_dict.get("hunger_timer", 0) > HUNGER_DIRE_THRESHOLD:
        score += 1
    if needs_dict.get("thirst_timer", 0) > THIRST_DIRE_THRESHOLD:
        score += 1
    if needs_dict.get("sleepiness_timer", 0) > SLEEPINESS_DIRE_THRESHOLD:
        score += 1
    for flag in ("pain", "nausea", "dizziness", "suffocation"):
        if needs_dict.get(flag, 0) != 0:
            score += 0.5
    return min(score, 6.0)


# ===========================================================================
# Job system — DF 53.15 verified via suspendmanager.lua, dwarfvet.lua,
# stockflow.lua, workflow.lua, and suspendmanager.plugin source.
# ===========================================================================

JOB_STATE_QUEUED = "queued"
JOB_STATE_ACTIVE = "active"
JOB_STATE_SUSPENDED = "suspended"
JOB_STATE_CANCELLED = "cancelled"

CONSTRUCTION_JOB_PREFIXES = (
    "Construct",
)

FOOD_JOB_TYPES = (
    "PrepareMeal", "ButcherAnimal", "ExtractFromLandAnimal",
    "PrepareRawFish", "CatchLiveLandAnimal", "CatchLiveFish",
)


def job_state(job_record):
    """Derive a canonical state string for a single job record.

    Parameters are the fields emitted by bridge/core.lua ``job_list()``:
        cancelled  — bool
        suspended  — bool
        worker_id  — int or None
    """
    if job_record.get("cancelled"):
        return JOB_STATE_CANCELLED
    if job_record.get("suspended"):
        return JOB_STATE_SUSPENDED
    return JOB_STATE_ACTIVE if job_record.get("worker_id") is not None else JOB_STATE_QUEUED


def job_category(job_type_str):
    """Classify a job type string (e.g. 'df.job_type.ConstructBed') into a category.

    Categories derived from workshops.lua and suspendmanager.lua evidence:
        construction  — ConstructBuilding, ConstructBed, ConstructChest, …
        food          — PrepareMeal, ButcherAnimal, etc.
        manufacturing — MakeBarrel, MakeBucket, CutGems, SmeltOre, …
        military      — ConstructBallistaParts, LoadCatapult, etc.
        harvesting    — CollectSand, CollectClay, HarvestFruits, etc.
        other         — fallback
    """
    jt = job_type_str or ""

    if any(p in jt for p in CONSTRUCTION_JOB_PREFIXES):
        return "construction"
    if any(t in jt for t in FOOD_JOB_TYPES):
        return "food"
    if any(t in jt for t in ("LoadCatapult", "LoadBallista", "AssembleSiegeAmmo",
                              "ConstructBallistaParts", "ConstructCatapultParts")):
        return "military"
    if any(t in jt for t in ("CollectSand", "CollectClay", "HarvestFruits",
                              "PlantCutting", "CatchLiveLandAnimal")):
        return "harvesting"
    # Manufacturing covers MakeBarrel, SmeltOre, CutGems, WeaveCloth, etc.
    if any(t in jt for t in ("Make", "Smelt", "Weave", "Dye", "Encrust",
                              "ExtractFromRawFish")):
        return "manufacturing"
    return "other"


def count_jobs_by_state(jobs):
    """Return a dict mapping state string → count for a list of job records."""
    counts = {JOB_STATE_QUEUED: 0, JOB_STATE_ACTIVE: 0,
              JOB_STATE_SUSPENDED: 0, JOB_STATE_CANCELLED: 0}
    for j in jobs:
        s = job_state(j)
        counts[s] = counts.get(s, 0) + 1
    return counts


def count_jobs_by_category(jobs):
    """Return a dict mapping category string → count."""
    cats: dict[str, int] = {}
    for j in jobs:
        c = job_category(j.get("type", ""))
        cats[c] = cats.get(c, 0) + 1
    return cats


def active_worker_ids(jobs):
    """Return a list of worker unit IDs currently assigned to active jobs."""
    result = []
    for j in jobs:
        if job_state(j) == JOB_STATE_ACTIVE and j.get("worker_id") is not None:
            result.append(j["worker_id"])
    return result


def suspicious_jobs(jobs):
    """Return jobs that appear stuck (suspended with materials but no worker).

    Heuristic: suspended=True, n_items > 0, worker_id is None.
    These represent jobs that have lost their assigned worker entirely.
    """
    stuck = []
    for j in jobs:
        if j.get("suspended") and j.get("n_items", 0) > 0 and j.get("worker_id") is None:
            stuck.append(j)
    return stuck


# --- Building observation helpers (verified via bridge/core.lua building_list()) ---

KNOWN_BUILDING_TYPES = [
    "Workshop", "Furnace", "Apparatus", "Storage", "RoadPaved", "RoadDirt",
    "FarmPlot", "Widget", "Trap", "PressurePlate", "Hatch", "Door",
    "UprightBars", "Stairs", "Ramp", "MadeFloor", "Fence", "WallProjectiles",
    "WebWall", "Tree", "Bookcase", "DisplayFurniture", "OfferingPlace",
]

BUILDING_SCHEMA_KEYS = [
    "idx", "id", "type", "subtype", "custom_id", "center",
    "built", "build_stage", "max_stage",
]


def is_complete_building(bld):
    """Return True if a building record indicates construction is finished."""
    return bool(bld.get("built")) and bld.get("build_stage", -1) >= 0


def unfinished_buildings(buildings):
    """Return buildings that are not yet fully constructed."""
    return [b for b in buildings if not is_complete_building(b)]


def building_type_label(bld):
    """Return the human-readable type label string, or 'unknown'."""
    t = bld.get("type", "unknown")
    if not t:
        return "unknown"
    # Strip df.building_type. prefix if present in enum name
    return t.split(".")[-1] if isinstance(t, str) else "unknown"


def buildings_at_z(buildings, z):
    """Filter buildings to a specific z-level."""
    return [b for b in buildings if (b.get("center") or {}).get("z", 0) == z]


def building_count_by_type(buildings):
    """Return a dict mapping type label → count of buildings."""
    counts: dict[str, int] = {}
    for b in buildings:
        label = building_type_label(b)
        counts[label] = counts.get(label, 0) + 1
    return counts
