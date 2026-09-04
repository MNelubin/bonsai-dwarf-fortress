"""Deterministic stockpile query probe for Dwarf Fortress.

This module queries the DF runtime for the number of active general stockpiles and returns a JSON‑serialisable dictionary with a single key "general_stockpiles".  The implementation follows the pattern used by other probes in the repository and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_stockpile_snapshot() -> str:
    """Return active general stockpile count via Lua.

    The Lua expression iterates ``df.global.world.buildings.list`` and counts buildings
    whose building type code is ``df.building_type.GeneralStockpile``.  The result is printed
    as JSON so the Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local count = 0;
        if df.global and df.global.world and df.global.world.buildings then
            for _, bld in ipairs(df.global.world.buildings.list) do
                if bld.building_type == df.building_type.GeneralStockpile then
                    count = count + 1;
                end
            end
        end
        print(json.encode{{general_stockpiles=count}});
        """
    )


def probe_general_stockpiles(timeout: int = 20) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the number of active general stockpiles.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'general_stockpiles': <int>}`` on success, or ``None`` if the probe
        fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_stockpile_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
