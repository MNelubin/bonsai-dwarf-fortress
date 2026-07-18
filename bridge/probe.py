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
