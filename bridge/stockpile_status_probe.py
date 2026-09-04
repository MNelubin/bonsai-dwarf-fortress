"""Deterministic stockpile status probe for Dwarf Fortress.

This module queries the DF runtime for the number of active stockpiles and
returns a JSON‑serialisable dictionary with a single key "stockpiles".
The implementation follows the pattern used by other probes in the repository
and does not affect existing public interfaces.
"""
from typing import Optional, Dict
from game_runner.episode import _dfhack_run


def _lua_stockpile_snapshot() -> str:
    """Return active stockpile count via Lua.

    The Lua expression counts entries in ``df.global.world.stockpiles.list`` and
    prints the result as JSON.
    """
    return (
        """
        local json = require('json');
        local count = 0;
        if df.global and df.global.world and df.global.world.stockpiles then
            for _, sp in ipairs(df.global.world.stockpiles.list) do
                count = count + 1;
            end
        end
        print(json.encode{{stockpiles=count}});
        """
    )


def probe_stockpile_status(timeout: int = 5) -> Optional[Dict[str, int]]:
    """Query the live DFHack process for the current number of stockpiles.

    Args:
        timeout: Maximum seconds to wait for the DFHack subprocess.

    Returns:
        {'stockpiles': <int>} on success, or None if the probe fails or cannot
        communicate with the DF runtime.
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
