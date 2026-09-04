"""Deterministic unit health probe for Dwarf Fortress.

This module queries the DF runtime for basic health metrics of all units
and returns a JSON‑serialisable list where each entry is a dictionary with
unit ID and a health score (0‑100).  The implementation follows the pattern
used by other probes in the repository and does not affect existing public
interfaces.
"""
from typing import List, Dict, Optional
from game_runner.episode import _dfhack_run

def _lua_unit_health_snapshot() -> str:
    """Return unit health data via Lua.
    The Lua expression iterates ``df.global.world.units.all`` and builds a JSON array
    where each element is ``{id=unit.id, health=score}``.  ``score`` is derived from
    ``unit.Attributes.health`` scaled to 0–100.
    """
    return ("""
        local json = require('json');
        local result = [];
        if df.global and df.global.world and df.global.world.units then
            for _,u in ipairs(df.global.world.units.all) do
                local h = u.Attributes.health or 0;
                local score = math.floor(h / 100);
                table.insert(result, {id=u.id, health=score});
            end
        end
        print(json.encode(result));
    """)

def probe_unit_health(timeout: int = 20) -> Optional[List[Dict[str, int]]]:
    """Query the live DFHack process for unit health.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A list of dictionaries ``{"id": <int>, "health": <int>}`` on success,
        or ``None`` if the probe fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_unit_health_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
    else:
        # raw should be a JSON string from the Lua script.
        import json
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        if not isinstance(parsed, list):
            return None
        for entry in parsed:
            if not isinstance(entry, dict) or "id" not in entry or "health" not in entry:
                return None
        return parsed
    return None
# deterministic edit marker
