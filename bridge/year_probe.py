"""Deterministic year probe for Dwarf Fortress.

This module queries the DF runtime for the current year and season, and returns a JSON‑serialisable
dictionary with keys "year" (int) and "season" (int).  The implementation follows the pattern used by
other probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_year_snapshot() -> str:
    """Return the current year and season via Lua.

    The Lua code reads ``df.global.cur_year`` and ``df.global.cur_season`` and prints a JSON object.
    """
    return (
        """
        local json = require('json');
        local year = df.global.cur_year or 0;
        local season = df.global.cur_season or 0;
        print(json.encode{{year=year, season=season}});
        """
    )


def probe_advancement_commands(timeout: int = 5) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current year/season.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        {'year': <int>, 'season': <int>} on success or ``None`` if the probe fails.
    """
    try:
        raw = _dfhack_run(_lua_year_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
# end of module
