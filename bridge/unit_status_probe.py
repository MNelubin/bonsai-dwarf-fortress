"""
Deterministic unit status probe for Dwarf Fortress.

This module queries the DF runtime for the status of the first active unit
and returns a JSON‑serialisable dictionary with a single key "status"
containing the unit's "idle", "working", "dead", or "injured" state.
The implementation follows the pattern used by other probes in the repository
and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_unit_status_snapshot() -> str:
    """Return the status of the first active unit via Lua.

    The Lua expression iterates over ``df.global.world.units.active`` and
    encodes the first unit's ``status`` field (an enum) as a JSON string.
    """
    return (
        """
        local json = require('json');
        local unit = nil;
        if df.global and df.global.world and df.global.world.units then
            for _, u in ipairs(df.global.world.units.active) do
                unit = u;
                break;
            end
        end
        local status = unit and tostring(df.unit_status[unit.status]) or "unknown";
        print(json.encode{{status=status}});
        """
    )


def probe_unit_status(timeout: int = 20) -> Optional[Dict[str, str]]:
    """Query the live DFHack process for the status of the first active unit.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        ``{'status': <str>}`` on success, or ``None`` if the probe fails or the
        DF runtime is unavailable.
    """
    try:
        raw = _dfhack_run(_lua_unit_status_snapshot(), timeout=timeout)
    except Exception:
        return None
    if isinstance(raw, dict):
        if "_dfhack_error" in raw or "_raw" in raw:
            return None
        return raw
    return None

# deterministic edit marker
