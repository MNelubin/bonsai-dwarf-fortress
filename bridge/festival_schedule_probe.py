"""Deterministic festival schedule probe for Dwarf Fortress.

This module queries the DF runtime for the list of festivals and returns a JSON‑serialisable
dictionary with a single key "festival_schedule" containing a list of festival dictionaries, each
with "name" and "start" keys of type string. The implementation follows the pattern used by other
probes in the repository and does not affect existing public interfaces.
"""
from typing import List, Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_festival_snapshot() -> str:
    """Return festival schedule via Lua.

    The Lua code iterates ``df.global.world.festivals.list`` and builds a list of maps with ``name``
    and ``start`` exported as JSON. The result is printed as lower‑case JSON so the Python side can
    parse it safely.
    """
    return (
        """
        local json = require('json');
        local schedule = [];
        if df.global and df.global.world and df.global.world.festivals then
            for _, fest in ipairs(df.global.world.festivals.list) do
                local entry = {name = fest.name or "", start = tostring(fest.start) or ""};
                table.insert(schedule, entry);
            end
        end
        print(json.encode{{festival_schedule = schedule}});
        """
    )


def probe_festival_schedule(timeout: int = 5) -> Optional[List[Dict[str, str]]]:
    """Query the live DFHack process for the current festival schedule.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A list of festival dictionaries on success, or ``None`` if the probe cannot communicate
        with the DF runtime or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_festival_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "festival_schedule" in raw:
            # Ensure the schedule is a list of dicts with string fields.
            return raw["festival_schedule"]
        # Any other structure is considered an error.
        return None
    return None

# deterministic edit marker
# end of module
