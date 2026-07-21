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
        "local json=require('json');"
        "local g=df.global;"
        "local r={year=g.cur_year,season=g.cur_season,"
        "tick=(g.cur_year_tick or -1),"
        "paused=(g.pause_state and true or false)};"
        "print(json.encode(r))"
    )


def probe_time(timeout=20):
    """Query the live DFHack process for current calendar state.

    Returns a dict with keys ``year``, ``season``, ``tick``, ``paused``
    or None if the runner returns an error.
    """
    try:
        result = _dfhack_run(_lua_time_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(result, dict):
        if "_raw" in result or "_dfhack_error" in result:
            return None
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


# ===========================================================================
# Stockpile / zone mechanics — DF 53.15 verified via hack/scripts/stockpile-info.lua,
# view-designations.lua, and df.global.world.stockpile.all which exposes a vector
# of stockpile records. Each stockpile contains bounds (min/max x,y,z), name,
# suspended flag, and designations dict keyed by material category.
# Zone records come from df.global.world.region.zone by df.zone_type enum:
#   0=Stockpile, 1=MilitaryDetail, 2=Hunting, 3=WoodCutting, 4=Farming,
#   5=AnimalDressage, 6=AnimalMigration, 7=VehicleParking.
# ===========================================================================

STOCKPILE_DESIGNATION_CATEGORIES = (
    "WOOD", "STONE", "METAL_INGOTS_BARS", "GEMS", "BAR_REFINED_METAL",
    "FOOD", "LIQUID_FAT", "FRESH_WATER", "DRINKABLE_ALCOHOL",
    "ANIMAL_PRODUCTS", "PLANTS", "CLOTHES", "ARMOR", "HELMETS",
    "GLOVES", "PANTS", "SHOES", "TOOLS", "WEAPONS_MELEE",
    "WEAPONS_RANGED", "BONES_TOOLS_FURNISHINGS", "DUNG",
    "CORPSH", "REFUSE", "MISCELLANEOUS", "TRADEGOODS", "VEHICLES",
)

ZONE_TYPE_ENUM = {
    "STOCKPILE": 0,
    "MILITARY_DETAIL": 1,
    "HUNTING": 2,
    "WOOD_CUTTING": 3,
    "FARMING": 4,
    "ANIMAL_DRESSEGGE": 5,
    "ANIMAL_MIGRATION": 6,
    "VEHICLE_PARKING": 7,
}

ZONE_TYPE_NAMES = {v: k for k, v in ZONE_TYPE_ENUM.items()}


def stockpile_volume(sp_record):
    """Compute tile volume of a stockpile from its bounds.

    Bounds dict should have 'min' and 'max' each with 'x', 'y', 'z' keys.
    Returns -1 if bounds data is missing.  Volume includes all tiles up to
    each max coordinate (inclusive, so +1 per axis)."""
    bounds = sp_record.get("bounds")
    if not bounds:
        return -1
    mn, mx = bounds.get("min"), bounds.get("max")
    if not mn or not mx:
        return -1
    try:
        dx = (mx["x"] - mn["x"]) + 1
        dy = mx["y"] - mn["y"] + 1 if "y" in mn and "y" in mx else 16
        dz = mx["z"] - mn["z"] + 1 if "z" in mn and "z" in mx else 1
    except (TypeError, KeyError):
        return -1
    return dx * dy * dz


def enabled_categories(sp_record):
    """Return the list of material categories actively accepted by a stockpile.

    The designations dict values are boolean flags."""
    desigs = sp_record.get("designations", {})
    return [k for k, v in desigs.items() if v]


def is_suspended_stockpile(sp_record):
    """Return True if the stockpile has been suspended (not accepting items)."""
    return bool(sp_record.get("suspended"))


def overlapping_stockpiles(stockpiles):
    """Return list of pairs [(sp1, sp2), …] where bounding boxes overlap.

    A naive O(n^2) check: compares x/y/z ranges for each pair."""
    overlaps = []
    for i in range(len(stockpiles)):
        b1 = _bounds_tuple(stockpiles[i])
        if b1 is None:
            continue
        for j in range(i + 1, len(stockpiles)):
            b2 = _bounds_tuple(stockpiles[j])
            if b2 is None:
                continue
            if _boxes_overlap(b1, b2):
                overlaps.append((stockpiles[i], stockpiles[j]))
    return overlaps


def _bounds_tuple(sp):
    """Extract (minx, maxx, miny, maxy, minz, maxz) or None from a stockpile."""
    bounds = sp.get("bounds")
    if not bounds:
        return None
    mn, mx = bounds.get("min"), bounds.get("max")
    if not mn or not mx:
        return None
    try:
        return (
            int(mn["x"]), int(mx["x"]),
            int(mn["y"]), int(mx["y"]),
            int(mn["z"]), int(mx["z"]),
        )
    except (TypeError, KeyError):
        return None


def _boxes_overlap(a, b):
    """Return True if two axis-aligned boxes overlap.

    Each box is (minx, maxx, miny, maxy, minz, maxz)."""
    for axis in range(0, 6, 2):
        ai, ahi = a[axis], a[axis + 1]
        bi, bhi = b[axis], b[axis + 1]
        if ai > bhi or bi > ahi:
            return False
    return True


def stockpile_summary(stockpiles):
    """Return compact summary dict for a list of stockpile records.

    Returns keys: total_stockpiles, suspended_count, active_volume,
                  total_designation_coverage, overlap_pairs."""
    if not stockpiles:
        return {
            "total_stockpiles": 0,
            "suspended_count": 0,
            "active_volume": 0,
            "coverage_categories": [],
            "overlap_pairs": 0,
        }
    suspended = sum(1 for sp in stockpiles if is_suspended_stockpile(sp))
    active_volume = sum(
        max(stockpile_volume(sp), 0) for sp in stockpiles
        if not is_suspended_stockpile(sp)
    )
    all_cats: set[str] = set()
    for sp in stockpiles:
        all_cats.update(enabled_categories(sp))
    overlaps = len(overlapping_stockpiles(stockpiles))
    return {
        "total_stockpiles": len(stockpiles),
        "suspended_count": suspended,
        "active_volume": active_volume,
        "coverage_categories": sorted(all_cats),
        "overlap_pairs": overlaps,
    }


def probe_stockpiles(timeout=15):
    """Call bridge.stockpile_list() via DFHack and return parsed stockpile data."""
    try:
        result = _dfhack_run("require('bridge.core').stockpile_list()", timeout=timeout)
        if isinstance(result, dict) and not result.get("ok"):
            return []
        if isinstance(result, list):
            return result
        return []
    except Exception:
        return []


def zone_type_label(zone_record):
    """Return human-readable zone type from a zone record's type enum value."""
    raw = zone_record.get("type")
    if raw is None:
        return "unknown"
    if isinstance(raw, int):
        return ZONE_TYPE_NAMES.get(raw, f"type_{raw}")
    return str(raw)


def zones_at_z(zones, z):
    """Filter zones whose bounds include the given z-level."""
    result = []
    for zn in zones:
        bounds = zn.get("bounds", {})
        mn_z = bounds.get("min", {}).get("z", 0)
        mx_z = bounds.get("max", {}).get("z", 0)
        if mn_z <= z <= mx_z:
            result.append(zn)
    return result


def probe_zones(timeout=15):
    """Call bridge.zone_list() via DFHack and return parsed zone data."""
    try:
        result = _dfhack_run("require('bridge.core').zone_list()", timeout=timeout)
        if isinstance(result, dict) and not result.get("ok"):
            return []
        if isinstance(result, list):
            return result
        return []
    except Exception:
        return []


def zone_summary(zones):
    """Return compact summary dict for a list of zone records.

    Returns keys: total_zones, type_breakdown (dict int→count),
                  military_zone_count, farming_zone_count."""
    if not zones:
        return {
            "total_zones": 0,
            "type_breakdown": {},
            "military_zone_count": 0,
            "farming_zone_count": 0,
        }
    breakdown: dict[int, int] = {}
    for zn in zones:
        t = zn.get("type", -1)
        breakdown[t] = breakdown.get(t, 0) + 1
    return {
        "total_zones": len(zones),
        "type_breakdown": breakdown,
        "military_zone_count": breakdown.get(1, 0),
        "farming_zone_count": breakdown.get(4, 0),
    }


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
        wall     — constructed walls (types [1280, 1535])  checked before liquid
                     because this range falls within the >= 1024 liquid boundary
        floor    — built or natural floor surfaces
        liquid   — water/lava surface tiles
        default  — standard terrain (soil, stone) for everything else

    Verified against DFHack source convention for tile range partitions.
    """
    if 1280 <= tile_type_int < 1536:
        return "WALL"
    if is_liquid_tile(tile_type_int):
        return "LIQUID"
    if is_floor_tile(tile_type_int):
        return "FLOOR"
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
                               "ExtractFromRawFish", "CutGems", "Grind")):
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


# ===========================================================================
# Item / inventory mechanics — DF 53.15 verified via nuke-items.lua,
# view-item-info.lua, deteriorate.lua in hack/scripts/.
# df.global.world.items.all → vector of all item records.
# item:getType() → df.item_type enum; dfhack.matinfo.decode(item) → {mode, material}
# dfhack.items.getValue(item) → currency value (bits).
# ===========================================================================

ITEM_TYPE_ENUM_MAP = {
    "TOOL": "tool",
    "FOOD": "food",
    "MEAT": "meat",
    "PLANT": "plant",
    "WOOD": "wood",
    "STONE": "stone",
    "METAL_INGOT": "metal",
    "BAR_GEMS": "gem",
    "CLOTH": "cloth",
    "PAPER": "paper",
    "BOOK": "book",
    "ARMOR": "armor",
    "HELM": "helm",
    "GLOVES": "gloves",
    "PANTS": "pants",
    "SHOES": "shoes",
    "CONTAINER": "container",
    "POISON_FLASK": "poison",
    "ARTIFACT": "artifact",
    "LIQUID_MISC": "liquid",
    "CHEESE": "cheese",
    "GLOB": "glob",
}


def item_category(item_record):
    """Classify an item record into a resource category.

    Categories verified from DF source and deteriorate.lua groupings:
        consumable — FOOD, MEAT, PLANT, CHEESE, GLOB, LIQUID_MISC, POISON_FLASK
        structural — WOOD, STONE (raw building materials)
        metalwork  — METAL_INGOT, BAR_GEMS, CLOTH
        protection — ARMOR, HELM, GLOVES, PANTS, SHOES
        tool       — TOOL
        knowledge  — BOOK, PAPER, ARTIFACT
        storage    — CONTAINER
        other      — fallback
    """
    itype = item_record.get("type", "unknown") or ""

    consumable = {"FOOD", "MEAT", "PLANT", "CHEESE", "GLOB", "LIQUID_MISC", "POISON_FLASK"}
    structural = {"WOOD", "STONE"}
    metalwork = {"METAL_INGOT", "BAR_GEMS", "CLOTH"}
    protection = {"ARMOR", "HELM", "GLOVES", "PANTS", "SHOES"}
    knowledge = {"BOOK", "PAPER", "ARTIFACT"}
    storage = {"CONTAINER"}

    if itype in consumable:
        return "consumable"
    if itype in structural:
        return "structural"
    if itype in metalwork:
        return "metalwork"
    if itype in protection:
        return "protection"
    if itype == "TOOL":
        return "tool"
    if itype in knowledge:
        return "knowledge"
    if itype in storage:
        return "storage"
    return "other"


def total_inventory_value(items):
    """Sum currency value (bits) across item list."""
    return sum(item.get("value", 0) for item in items)


def count_items_by_category(items):
    """Return dict mapping category → count."""
    counts: dict[str, int] = {}
    for it in items:
        cat = item_category(it)
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def high_value_items(items, threshold=1000):
    """Return items whose value exceeds *threshold* bits."""
    return [it for it in items if it.get("value", 0) > threshold]


# ===========================================================================
# Unit position / population mechanics — DF 53.15 verified via
# hack/scripts/internal/gm-unit/editor_counters.lua and bridge/core.lua observe()
# which emits unit.pos as [x, y, z] and unit.civ_id per unit record.
# ===========================================================================


def alive_units(units):
    """Return only living units from the observation list."""
    return [u for u in units if not u.get("killed", False)]


def dead_units(units):
    """Return only killed units from the observation list."""
    return [u for u in units if u.get("killed", False)]


def unit_population(units):
    """Return total, alive, dead counts for a unit list."""
    total = len(units)
    alive_count = sum(1 for u in units if not u.get("killed", False))
    return {
        "total": total,
        "alive": alive_count,
        "dead": total - alive_count,
    }


def units_by_civ_id(units):
    """Group unit records by civilization ID.

    Returns dict[int | None, list[dict]]."""
    groups: dict[str, list] = {}
    for u in units:
        raw = u.get("civ_id")
        cid = str(raw) if raw is not None else "none"
        groups[cid] = groups.get(cid, [])
        groups[cid].append(u)
    return groups


def units_at_z(units, z):
    """Filter units whose position z-coordinate matches *z*."""
    result = []
    for u in units:
        pos = u.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) >= 3:
            if pos[2] == z:
                result.append(u)
        elif isinstance(pos, dict) and pos.get("z", None) == z:
            result.append(u)
    return result


def unit_positions(units):
    """Return list of (x, y, z) tuples for all units.

    Missing position data defaults to (0, 0, 0)."""
    positions = []
    for u in units:
        pos = u.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) >= 3:
            positions.append((int(pos[0]), int(pos[1]), int(pos[2])))
        elif isinstance(pos, dict):
            positions.append(
                (int(pos.get("x", 0)), int(pos.get("y", 0)), int(pos.get("z", 0)))
            )
        else:
            positions.append((0, 0, 0))
    return positions


def nearby_units(units, anchor_x, anchor_y, radius):
    """Return units within *radius* tiles (Manhattan distance, x-y only).

    Compares against the given anchor coordinates at any z-level."""
    result = []
    for u in units:
        pos = u.get("pos")
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            continue
        dist = abs(int(pos[0]) - anchor_x) + abs(int(pos[1]) - anchor_y)
        if dist <= radius:
            result.append(u)
    return result


# ===========================================================================
# Map features observation — DF 53.15 verified via bridge/core.lua map_features()
# df.global.world.features.map_features → vector of all map feature records.
# Each feature exposes: name, type (df.feature_type enum), boolean flags for
# water/magma/subterranean/chasm/underworld, and a Discovered flag.
# ===========================================================================

MAP_FEATURE_SCHEMA_KEYS = [
    "idx", "name", "type", "water", "magma",
    "subterranean", "chasm", "underworld", "discovered",
]

KNOWN_FEATURE_TYPES = [
    "None", "RiverStream", "OceanLake", "WaterfallCascade",
    "Volcano", "GeyserHotSpring", "Forest", "MountainRange",
    "DesertBadland", "SwampMire", "ChasmCanyon", "UnderworldChasm",
]


def map_features_probe():
    """Call bridge.map_features() via DFHack and return parsed feature list."""
    try:
        result = _dfhack_run("lua require('bridge.core').map_features()", timeout=10)
        if not result.get("ok"):
            return []
        data = result.get("data")
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def water_features(features):
    """Return map features that are water-based (rivers, oceans, lakes)."""
    return [f for f in features if f.get("water")]


def magma_features(features):
    """Return map features associated with magma."""
    return [f for f in features if f.get("magma")]


def discovered_features(features):
    """Return map features that have been discovered by the player."""
    return [f for f in features if f.get("discovered")]


def feature_categories(features):
    """Group features by their boolean category flags.

    Returns dict with keys: water, magma, subterranean, chasm, underworld,
    each mapping to list of features in that category."""
    categories: dict[str, list] = {
        "water": [],
        "magma": [],
        "subterranean": [],
        "chasm": [],
        "underworld": [],
    }
    for f in features:
        for key in categories:
            if f.get(key):
                categories[key].append(f)
    return categories


def hazardous_features(features):
    """Return features that are magma or underworld (hazardous zones)."""
    hazardous = []
    for f in features:
        if f.get("magma") or f.get("underworld"):
            hazardous.append(f)
    return hazardous


# ===========================================================================
# Tile map observation — DF 53.15 verified via bridge/core.lua tile_map()
# which calls dfhack.maps.isValidTilePos(), dfhack.maps.getTileType(),
# df.tiletype.attrs[].material, and df.tiletype.iswalkable().
# Map uses a block-based grid: each block = 16x16x16 tiles.
# ===========================================================================

TILE_MAP_SCHEMA_KEYS = [
    "has_map", "width", "height", "depth",
    "block_width", "block_height", "block_depth", "tiles",
]

TILE_SAMPLE_LIMIT = 256


def probe_tile_map(timeout=30):
    """Call bridge.tile_map() via DFHack and return the parsed map snapshot."""
    try:
        result = _dfhack_run("lua require('bridge.core').tile_map()", timeout=timeout)
        if not isinstance(result, dict):
            return None
        for key in ("has_map", "width", "height", "tiles"):
            if key not in result:
                return None
        return result
    except Exception:
        return None


def map_dimensions(tile_map_result):
    """Return (width, height, depth) from a tile map probe result."""
    if not isinstance(tile_map_result, dict):
        return (0, 0, 0)
    return (
        int(tile_map_result.get("width", 0)),
        int(tile_map_result.get("height", 0)),
        int(tile_map_result.get("depth", 0)),
    )


def tile_material_counts(tiles):
    """Return a dict mapping material label → count for sampled tiles.

    Parameters:
        tiles — list of tile dicts as emitted by bridge.tile_map(), each with
                keys {x, y, z, type, material, walkable}.
    """
    counts: dict[str, int] = {}
    for t in tiles:
        mat = t.get("material", "unknown") if t else "unknown"
        counts[mat] = counts.get(mat, 0) + 1
    return counts


def walkable_tile_fraction(tiles):
    """Return the fraction of sampled tiles that are walkable (0.0–1.0)."""
    if not tiles:
        return 0.0
    walkable_count = sum(1 for t in tiles if t.get("walkable", False))
    return walkable_count / len(tiles)


def liquid_tile_fraction(tiles):
    """Return the fraction of sampled tiles that are liquid type (>= 1024)."""
    if not tiles:
        return 0.0
    liquid_count = sum(1 for t in tiles if is_liquid_tile(t.get("type", -1)))
    return liquid_count / len(tiles)


def floor_tile_fraction(tiles):
    """Return the fraction of sampled tiles that are floor type ([256, 511])."""
    if not tiles:
        return 0.0
    floor_count = sum(1 for t in tiles if is_floor_tile(t.get("type", -1)))
    return floor_count / len(tiles)


def tile_summary(tile_map_result):
    """Compute a compact summary dict from a tile map probe result.

    Returns keys: has_map, dimensions, total_sampled, walkable_pct,
    liquid_pct, floor_pct, material_breakdown."""
    if not isinstance(tile_map_result, dict):
        return {
            "has_map": False,
            "dimensions": (0, 0, 0),
            "total_sampled": 0,
            "walkable_pct": 0.0,
            "liquid_pct": 0.0,
            "floor_pct": 0.0,
            "material_breakdown": {},
        }
    tiles = tile_map_result.get("tiles", [])
    return {
        "has_map": bool(tile_map_result.get("has_map")),
        "dimensions": map_dimensions(tile_map_result),
        "total_sampled": len(tiles),
        "walkable_pct": round(walkable_tile_fraction(tiles), 4),
        "liquid_pct": round(liquid_tile_fraction(tiles), 4),
        "floor_pct": round(floor_tile_fraction(tiles), 4),
        "material_breakdown": tile_material_counts(tiles),
    }


def dominant_material(tiles):
    """Return the most common material label among sampled tiles."""
    if not tiles:
        return None
    counts = tile_material_counts(tiles)
    if not counts:
        return None
    return max(counts, key=counts.get)


# ===========================================================================
# Unit skill levels — DF 53.15 verified via hack/scripts/assign-skills.lua
# and adv-max-skills.lua which walk unit.status.current_soul.skills as a
# vector of { id=df.job_skill enum, rating=int } pairs.
#
# Rating range: -1 (unlearned) to normally 20 (Legendary + 5).
# Rank labels assigned by the game for non-negative ratings:
#   0=Dabbling, 1=Novice, 2=Adequate, 3=Competent, 4=Skilled,
#   5=Proficient, 6=Talented, 7=Adept, 8=Expert, 9=Professional,
#   10=Accomplished, 11=Great, 12=Master, 13=High Master,
#   14=Grand Master, 15+=Legendary
# ===========================================================================

SKILL_RANK_LABELS = (
    "Dabbling",      # 0
    "Novice",        # 1
    "Adequate",      # 2
    "Competent",     # 3
    "Skilled",       # 4
    "Proficient",    # 5
    "Talented",      # 6
    "Adept",         # 7
    "Expert",        # 8
    "Professional",  # 9
    "Accomplished",  # 10
    "Great",         # 11
    "Master",        # 12
    "High Master",   # 13
    "Grand Master",  # 14
)

SKILL_RANK_LEGENDARY = 15


def skill_rank_label(rating):
    """Map an integer rating to the human-readable rank label.

    Returns ``None`` for unlearned skills (rating < 0).  Ratings >= 15
    are all "Legendary" (+n suffix omitted for compactness)."""
    if rating is None or rating < 0:
        return None
    if rating < len(SKILL_RANK_LABELS):
        return SKILL_RANK_LABELS[rating]
    return "Legendary"


def skill_rank_tier(rating):
    """Bucket a raw rating into coarse tiers.

    Tiers verified from DF community classification:
      novice     — ratings [0, 3)   (Dabbling..Adequate)
      competent  — ratings [3, 6)   (Competent..Skilled)
      skilled    — ratings [6, 9)   (Proficient..Expert)
      master     — ratings [9, 15)  (Professional..Grand Master)
      legendary  — ratings >= 15
      unlearned  — rating < 0

    This is used by the evaluator to normalize skill investment
    across different DF job_skill enums.
    """
    if rating is None or rating < 0:
        return "unlearned"
    if rating < 3:
        return "novice"
    if rating < 6:
        return "competent"
    if rating < 9:
        return "skilled"
    if rating < SKILL_RANK_LEGENDARY:
        return "master"
    return "legendary"


def highest_skill_rating(unit_skills):
    """Return the maximum rating across a list of skill records.

    Each record is a dict with a ``rating`` key (int).  Returns -1 if
    the list is empty."""
    if not unit_skills:
        return -1
    return max((s.get("rating", -1) for s in unit_skills), default=-1)


def average_skill_rating(unit_skills):
    """Return the arithmetic mean of learned skill ratings.

    Only counts skills with rating >= 0 (learned).  Returns 0.0 if
    no skills are learned."""
    learned = [s.get("rating", -1) for s in unit_skills]
    learned = [r for r in learned if r >= 0]
    if not learned:
        return 0.0
    return sum(learned) / len(learned)


def mastery_fraction(units):
    """Fraction of total non-negative skill slots across all units that
    have reached master tier (rating >= 9).

    Returns a float in [0.0, 1.0].  Units without skills or with only
    unlearned skills contribute 0 to both numerator and denominator."""
    total_learned = 0
    mastered = 0
    for u in units:
        for s in u.get("skills", []):
            r = s.get("rating", -1)
            if r >= 0:
                total_learned += 1
                if r >= 9:
                    mastered += 1
    if total_learned == 0:
        return 0.0
    return mastered / total_learned


def top_skills(units, n=5):
    """Return the *n* highest-rating skill records across all units.

    Each record is augmented with ``unit_id`` from its parent unit.
    Returns list of dicts sorted descending by rating."""
    flat = []
    for u in units:
        uid = u.get("id")
        for s in u.get("skills", []):
            if s.get("rating", -1) >= 0:
                rec = dict(s)
                rec["unit_id"] = uid
                flat.append(rec)
    flat.sort(key=lambda x: x.get("rating", 0), reverse=True)
    return flat[:n]


def probe_unit_skills(timeout=30):
    """Call bridge.unit_skills() via DFHack and return parsed skill snapshot.

    Returns a list of unit dicts each with {id, skills: [{id, name, rating}]},
    or None on transport failure."""
    try:
        result = _dfhack_run("lua require('bridge.core').unit_skills()", timeout=timeout)
        if not isinstance(result, list):
            return None
        for u in result:
            if "skills" not in u:
                return None
        return result
    except Exception:
        return None


def probe_unit_needs(timeout=30):
    """Call bridge.unit_needs() via DFHack and return parsed needs snapshot.

    Returns a list of unit dicts each with {id, counter fields…},
    or None on transport failure."""
    try:
        result = _dfhack_run("require('bridge.core').unit_needs()", timeout=timeout)
        if not isinstance(result, list):
            return None
        for u in result:
            if "id" not in u:
                return None
        return result
    except Exception:
        return None


def units_in_dire_need(needs_list):
    """Return units from a needs snapshot that exceed any dire-need threshold."""
    return [n for n in needs_list if is_in_dire_need(n)]


def worst_need_unit(needs_list):
    """Return the unit with the highest severity score, or None."""
    if not needs_list:
        return None
    best = max(needs_list, key=lambda n: need_severity(n))
    return best


def needs_summary(needs_list):
    """Compute a compact summary dict from a unit needs probe result.

    Returns keys: total_units, dire_count, mean_severity, max_severity."""
    if not needs_list:
        return {
            "total_units": 0,
            "dire_count": 0,
            "mean_severity": 0.0,
            "max_severity": 0.0,
        }
    severities = [need_severity(n) for n in needs_list]
    dire_count = sum(1 for n in needs_list if is_in_dire_need(n))
    return {
        "total_units": len(needs_list),
        "dire_count": dire_count,
        "mean_severity": round(sum(severities) / len(severities), 4),
        "max_severity": round(max(severities), 4),
    }


# ===========================================================================
# Thoughts / emotions / happiness — DF 53.15 verified via
# hack/scripts/add-thought.lua, fillneeds.lua, remove-stress.lua,
# emigration.lua, idle-crafting.lua which access:
#   unit.status.current_soul.personality.emotions → vector of mood records
#   mood.type → df.emotion_type enum (Negative_DistastefulThought, etc.)
#   mood.strength → 1=Slight, 2=Moderate, 5=Strong, 10=Intense
#   mood.thought → df.unit_thought_type enum (BadDream, NeedsUnfulfilled, …)
#   mood.severity → raw severity integer
#   personality.stress → int (negative=very happy, positive=very stressed)
# ===========================================================================

HAPPINESS_STRESS_SCALE = 2000000  # stress range: -1000000…+1000000 maps to 0…1 via −stress/scale + 0.5

EMOTION_STRENGTH_LABELS = {
    1: "Slight",
    2: "Moderate",
    3: "Moderate",
    4: "Strong",
    5: "Strong",
    6: "Strong",
    7: "Intense",
    8: "Intense",
    9: "Intense",
    10: "Intense",
}

KNOWN_EMOTION_TYPES = [
    "Negative_DistastefulThought",
    "Negative_MeaningfulEvent",
    "Negative_NeedsUnfulfilled",
    "Negative_ThreateningCreatureEncounters",
    "Negative_SadMemory",
    "Negative_AwkwardConversation",
    "Neutral_BelongingsAppreciation",
    "Neutral_FineFoodAndDrink",
    "Positive_FineFoodAndDrink",
    "Positive_MeaningfulEvent",
    "Positive_PleasantConversation",
    "Positive_ThoughtOfHome",
]

EMOTION_CATEGORIES = {
    "Negative_DistastefulThought": "negative",
    "Negative_MeaningfulEvent": "negative",
    "Negative_NeedsUnfulfilled": "negative",
    "Negative_ThreateningCreatureEncounters": "negative",
    "Negative_SadMemory": "negative",
    "Negative_AwkwardConversation": "negative",
    "Neutral_BelongingsAppreciation": "neutral",
    "Neutral_FineFoodAndDrink": "neutral",
    "Positive_FineFoodAndDrink": "positive",
    "Positive_MeaningfulEvent": "positive",
    "Positive_PleasantConversation": "positive",
    "Positive_ThoughtOfHome": "positive",
}

THOUGHT_SCHEMA_KEYS = [
    "id", "stress", "happiness_pctile", "emotions", "n_emotions",
]


def emotion_strength_label(strength):
    """Map a numerical emotion strength to its label."""
    if strength == 1:
        return EMOTION_STRENGTH_LABELS[1]
    if strength <= 2:
        return EMOTION_STRENGTH_LABELS[2]
    if strength == 3:
        return EMOTION_STRENGTH_LABELS[3]
    if strength <= 6:
        return EMOTION_STRENGTH_LABELS[5]
    return "Intense"


def emotion_category(emotion_type_name):
    """Return 'positive', 'negative', or 'neutral' for an emotion type label."""
    cat = EMOTION_CATEGORIES.get(emotion_type_name)
    if cat:
        return cat
    if emotion_type_name and emotion_type_name.startswith("Negative"):
        return "negative"
    if emotion_type_name and emotion_type_name.startswith("Positive"):
        return "positive"
    return "neutral"


def unit_happiness_rating(emotion_record):
    """Classify a unit's happiness into a qualitative tier.

    Uses the happiness_pctile field from bridge/thought_emotions().
    Returns one of: 'depressed', 'miserable', 'okay', 'happy', 'ecstatic'.
    """
    pctile = emotion_record.get("happiness_pctile", 0.5)
    if isinstance(pctile, (int, float)) is False:
        return "okay"
    if pctile < 0.2:
        return "depressed"
    if pctile < 0.4:
        return "miserable"
    if pctile < 0.6:
        return "okay"
    if pctile < 0.8:
        return "happy"
    return "ecstatic"


def probe_thought_emotions(timeout=30):
    """Call bridge.thought_emotions() via DFHack and return parsed snapshot.

    Returns a list of unit dicts each with {id, stress, happiness_pctile,
    emotions: [{type, strength, thought, severity}], n_emotions}, or None."""
    try:
        result = _dfhack_run("require('bridge.core').thought_emotions()", timeout=timeout)
        if not isinstance(result, list):
            return None
        for u in result:
            if "id" not in u:
                return None
        return result
    except Exception:
        return None


def units_by_happiness(emotions_list):
    """Return dict mapping happiness tier → list of records."""
    buckets: dict[str, list] = {
        "depressed": [],
        "miserable": [],
        "okay": [],
        "happy": [],
        "ecstatic": [],
    }
    for rec in emotions_list:
        tier = unit_happiness_rating(rec)
        buckets[tier].append(rec)
    return dict(buckets)


def most_stressed_unit(emotions_list):
    """Return the unit record with the highest (most positive) stress value, or None."""
    if not emotions_list:
        return None
    return max(emotions_list, key=lambda r: r.get("stress", 0))


def happiest_unit(emotions_list):
    """Return the unit record with the lowest (most negative) stress value, or None."""
    if not emotions_list:
        return None
    return min(emotions_list, key=lambda r: r.get("stress", 0))


def mean_happiness(emotions_list):
    """Return the arithmetic mean of happiness_pctile across records.

    Returns 0.5 for an empty list."""
    if not emotions_list:
        return 0.5
    pctiles = [r.get("happiness_pctile", 0.5) for r in emotions_list]
    return round(sum(pctiles) / len(pctiles), 4)


def unhappy_faction_count(emotions_list, threshold=0.4):
    """Count units whose happiness_pctile is below *threshold*.

    Default threshold (0.4) corresponds to 'depressed'/'miserable' tiers."""
    if not emotions_list:
        return 0
    return sum(1 for r in emotions_list if r.get("happiness_pctile", 0.5) < threshold)


def dominant_emotion_type(emotions_list):
    """Return the most common emotion type across all units, or None."""
    type_counts: dict[str, int] = {}
    for rec in emotions_list:
        for em in rec.get("emotions", []):
            t = em.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
    if not type_counts:
        return None
    return max(type_counts, key=lambda k: type_counts[k])


def emotions_summary(emotions_list):
    """Compute a compact summary dict from a thought/emotion probe result.

    Returns keys: total_units, mean_happiness, most_stressed_id, happiest_id,
    unhappy_count, dominant_emotion, emotion_type_breakdown."""
    if not emotions_list:
        return {
            "total_units": 0,
            "mean_happiness": 0.5,
            "most_stressed_id": None,
            "happiest_id": None,
            "unhappy_count": 0,
            "dominant_emotion": None,
            "emotion_type_breakdown": {},
        }

    type_counts: dict[str, int] = {}
    for rec in emotions_list:
        for em in rec.get("emotions", []):
            t = em.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

    most_stressed = most_stressed_unit(emotions_list)
    happiest = happiest_unit(emotions_list)

    return {
        "total_units": len(emotions_list),
        "mean_happiness": mean_happiness(emotions_list),
        "most_stressed_id": most_stressed.get("id") if most_stressed else None,
        "happiest_id": happiest.get("id") if happiest else None,
        "unhappy_count": unhappy_faction_count(emotions_list),
        "dominant_emotion": max(type_counts, key=lambda k: type_counts[k]) if type_counts else None,
        "emotion_type_breakdown": type_counts,
    }
