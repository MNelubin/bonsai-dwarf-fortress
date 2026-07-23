"""Deterministic designation probe for Dwarf Fortress.\n\nThis module queries the DF runtime for the number of tiles that have a\ndesignation (i.e. are scheduled for digging, building, etc.) and returns a JSON\nserialisable dictionary with a single key "designated_tiles".  The implementation\nfollow the pattern used by other probes in the repository and does not affect\nexisting public interfaces.\n"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_designation_snapshot() -> str:
    """Return the count of designated tiles via Lua.\n\nThe Lua expression iterates over ``df.global.map.designation.designations`` and\ncounts the entries that have a non‑zero ``tile`` reference.  The result is printed\nas JSON so the Python side can parse it safely.\n"""
    return ("""
        local json = require('json');
        local count = 0;
        if df.global and df.global.map and df.global.map.designation then
            for _, d in ipairs(df.global.map.designation.designations) do
                if d.tile then
                    count = count + 1;
                end
            end
        end
        print(json.encode{{designated_tiles=count}});
        """)


def probe_designated_tiles(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of designated tiles.\n\nArgs:\n    timeout: Maximum seconds to wait for the DFHack subprocess.\n\nReturns:\n    ``{'designated_tiles': <int>}`` on success, or ``None`` if the probe fails\nor the result cannot be parsed as JSON.\n"""
    try:
        raw = _dfhack_run(_lua_designation_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
