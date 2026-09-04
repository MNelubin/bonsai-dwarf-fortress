"""Deterministic season probe for Dwarf Fortress.

This module queries the DF runtime for the current season name and returns a JSON‑serialisable
dictionary with a single key "season".  The implementation follows the pattern used by other
probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_season_snapshot() -> str:
    """Return the current season name via Lua.

    The Lua code prints a JSON object containing the season string.  Seasons in DF are given by
    ``df.global.world.season`` which yields a string such as "spring".
    """
    return (
        """
        local json = require('json');
        print(json.encode{{season = tostring(df.global.world.season) }});
        """
    )


def probe_season(timeout: int = 5) -> Optional[Dict[str, str]]:
    """Query the live DFHack process for the current season.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        {'season': <str>} on success, or None if the probe cannot communicate with the DF runtime.
    """
    try:
        raw = _dfhack_run(_lua_season_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if '_dfhack_error' in raw or '_raw' in raw:
            return None
        return raw
    return None

# deterministic edit marker
# end of module
