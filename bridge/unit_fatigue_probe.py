"""Deterministic unit fatigue probe for Dwarf Fortress.

Queries the DF runtime for the fatigue level of all active units and returns a JSON‑serialisable
dictionary mapping unit IDs to their fatigue enum value (0 = fresh, 1 = tired, 2 = exhausted, 3 = critical).
The implementation follows the pattern used by other probes in the repository and does not affect
existing public interfaces.
"""
from typing import Dict, Optional
from game_runner.episode import _dfhack_run


def _lua_fatigue_snapshot() -> str:
    """Return unit fatigue data via Lua.

    The Lua expression iterates ``df.global.units.all`` and builds a map from unit ID to the
    integer value of ``unit.status.energy.flags.fatigue``.  The result is printed as JSON so
    the Python side can parse it safely.
    """
    return (
        """
        local json = require('json');
        local result = {};
        if df.global and df.global.units then
            for _, unit in ipairs(df.global.units.all) do
                local fatigue = unit.status and unit.status.energy and unit.status.energy.flags and unit.status.energy.flags.fatigue or 0;
                result[unit.id] = {fatigue = fatigue};
            end
        end
        print(json.encode(result));
        """
    )


def probe_fatigue(timeout: int = 20) -> Optional[Dict[int, Dict[str, int]]]:
    """Query the live DFHack process for current unit fatigue levels.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{unit_id: {'fatigue': <int>}}`` on success, or ``None`` if the probe
        fails or the result cannot be parsed as JSON.
    """
    try:
        raw = _dfhack_run(_lua_fatigue_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
