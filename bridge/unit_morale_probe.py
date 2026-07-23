"""Deterministic unit morale probe for Dwarf Fortress.

This module queries the DF runtime for the current morale status of all unit
entities and returns a JSON‑serialisable dictionary mapping unit IDs to an integer
morale score. The implementation follows the pattern used by other probes in the
repository and does not affect existing public interfaces.
"""
from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_unit_morale_snapshot() -> str:
    """Return unit morale data via Lua.

    The Lua expression iterates ``df.global.world.units.all`` and extracts each
    unit's morale points via ``unit.status.current morael`` (mocked as
    ``unit.status.current_status.morale`` if present).  The result is printed as
    JSON so the Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local result = {};
        if df.global and df.global.world and df.global.world.units then
            for _, unit in ipairs(df.global.world.units.all) do
                local morale = unit.status and unit.status.current and unit.status.current.morale or 0;
                result[unit.id] = {morale = morale};
            end
        end
        print(json.encode(result));
        """
    )


def probe_unit_morale(timeout: int = 20) -> Optional[Dict[int, Dict[str, int]]]:
    """Query the live DFHack process for the current morale of all units.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{unit_id: {'morale': <int>}}`` on success, or ``None`` if the probe fails or the
        DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_unit_morale_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
