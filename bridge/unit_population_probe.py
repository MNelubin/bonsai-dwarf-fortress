"""Deterministic unit population probe for Dwarf Fortress.

This module queries the DF runtime for the population distribution across
civilization IDs and returns a JSON‑serialisable dictionary mapping each civ_id
to an integer count of living units belonging to that civ. The implementation follows
the pattern used by other probes in the repository and does not affect existing public
interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_unit_population_snapshot() -> str:
    """Return unit population per civ via Lua.

    The Lua expression iterates ``df.global.world.units.all`` and builds a table
    mapping ``civ_id`` to the number of units. The result is printed as JSON so the
    Python side can parse it safely.
    """
    return ("""
    local json = require('json');
    local result = {};
    if df.global and df.global.world and df.global.world.units then
        for _,u in ipairs(df.global.world.units.all) do
            result[u.civ_id] = (result[u.civ_id] or 0) + 1;
        end
    end
    print(json.encode(result));
    """
    )


def probe_unit_population(timeout: int = 20) -> Optional[Dict[int, int]]:
    """Query the live DFHack process for unit population per civilization ID.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        A dictionary ``{civ_id: count}`` on success, or ``None`` if the probe fails
        or the DF runtime is not available.
    """
    try:
        raw = _dfhack_run(_lua_unit_population_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        # Ensure all keys are integers and values are counts.
        return {int(k): int(v) for k, v in raw.items()}
    return None
