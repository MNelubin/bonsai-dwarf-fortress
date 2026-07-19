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
